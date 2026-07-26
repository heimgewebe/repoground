"""Minimal newline-delimited MCP stdio transport for RepoGround."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

from merger.repoground.core.live_freshness import (
    DOES_NOT_ESTABLISH as FRESHNESS_DOES_NOT_ESTABLISH,
)
from merger.repoground.core.live_freshness import evaluate_live_freshness

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = (PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
SERVER_NAME = "repoground"
SERVER_VERSION = "1.0"
MANIFEST_SUFFIX = ".bundle.manifest.json"


class McpProtocolError(ValueError):
    """JSON-RPC error that can be returned without leaking a traceback."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _read_annotations() -> dict[str, bool]:
    return {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    }


def _selector_properties() -> dict[str, Any]:
    return {
        "bundle_manifest": {
            "type": ["string", "null"],
            "description": "Optional exact manifest path inside the startup bundle root.",
        },
        "repo": {
            "type": ["string", "null"],
            "description": "Repository identity such as owner/repository or repository name.",
        },
        "stem": {
            "type": ["string", "null"],
            "description": "Optional exact snapshot stem.",
        },
    }


def _tool_definitions(enable_snapshot_create: bool) -> list[dict[str, Any]]:
    selector = _selector_properties()

    def schema(
        properties: dict[str, Any], required: list[str] | None = None
    ) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {**selector, **properties},
            "required": required or [],
            "additionalProperties": False,
        }

    tools: list[dict[str, Any]] = [
        {
            "name": "bundle_discover",
            "title": "RepoGround bundle discovery",
            "description": "List healthy existing bundles or select one by repository identity/stem.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "repo": selector["repo"],
                    "stem": selector["stem"],
                },
                "required": [],
                "additionalProperties": False,
            },
            "annotations": _read_annotations(),
        },
        {
            "name": "snapshot_status",
            "title": "RepoGround snapshot status",
            "description": "Read health, availability and freshness for one selected existing bundle.",
            "inputSchema": schema({"verbose": {"type": "boolean", "default": False}}),
            "annotations": _read_annotations(),
        },
        {
            "name": "ask_context",
            "title": "RepoGround context pack",
            "description": "Build a cited context pack from one existing RepoGround bundle.",
            "inputSchema": schema(
                {
                    "query": {"type": "string"},
                    "task_profile": {
                        "type": "string",
                        "default": "basic_repo_question",
                    },
                    "max_context_tokens": {
                        "type": "integer",
                        "minimum": 1,
                        "default": 8000,
                    },
                    "max_answer_tokens": {
                        "type": "integer",
                        "minimum": 1,
                        "default": 1200,
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 5,
                    },
                    "verbose": {"type": "boolean", "default": False},
                },
                ["query"],
            ),
            "annotations": _read_annotations(),
        },
        {
            "name": "query_existing_index",
            "title": "RepoGround bounded query",
            "description": "Route exact symbol-definition questions to the symbol index; otherwise use exact AND and labelled OR fallback with bounded cited ranges.",
            "inputSchema": schema(
                {
                    "query": {"type": "string"},
                    "task_profile": {
                        "type": "string",
                        "default": "basic_repo_question",
                    },
                    "max_context_tokens": {
                        "type": "integer",
                        "minimum": 1,
                        "default": 2000,
                    },
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 5,
                    },
                    "verbose": {"type": "boolean", "default": False},
                },
                ["query"],
            ),
            "annotations": _read_annotations(),
        },
        {
            "name": "range_get",
            "title": "RepoGround range reader",
            "description": "Resolve one exact bundle range reference without reading a live workspace.",
            "inputSchema": schema(
                {
                    "range_ref": {"type": "object"},
                    "verbose": {"type": "boolean", "default": False},
                },
                ["range_ref"],
            ),
            "annotations": _read_annotations(),
        },
        {
            "name": "grounding_verify",
            "title": "RepoGround grounding verifier",
            "description": "Verify declared citations and ranges against an existing RepoGround bundle.",
            "inputSchema": schema(
                {
                    "declaration": {"type": "object"},
                    "citation_map": {"type": ["string", "null"]},
                    "task_profile": {"type": ["string", "null"]},
                    "verbose": {"type": "boolean", "default": False},
                },
                ["declaration"],
            ),
            "annotations": _read_annotations(),
        },
        {
            "name": "live_freshness",
            "title": "RepoGround live freshness",
            "description": "Compare snapshot Git provenance with the configured local checkout without refreshing it.",
            "inputSchema": schema({}),
            "annotations": _read_annotations(),
        },
        {
            "name": "find_symbol",
            "title": "RepoGround symbol locator",
            "description": "Locate Python symbol definitions by name with exact path and line range.",
            "inputSchema": schema(
                {
                    "name": {"type": "string", "minLength": 1},
                    "kind": {
                        "type": ["string", "null"],
                        "enum": [None, "class", "function", "async_function"],
                    },
                    "path": {"type": ["string", "null"]},
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 25,
                    },
                    "verbose": {"type": "boolean", "default": False},
                },
                ["name"],
            ),
            "annotations": _read_annotations(),
        },
    ]
    for name, title, description in (
        (
            "find_references",
            "RepoGround call reference locator",
            "List bounded static call sites for a callee name.",
        ),
        (
            "get_callers",
            "RepoGround caller locator",
            "Group uniquely resolved callers for one exact target symbol.",
        ),
        (
            "get_callees",
            "RepoGround callee locator",
            "Group uniquely resolved outgoing calls for one exact caller symbol.",
        ),
    ):
        tools.append(
            {
                "name": name,
                "title": title,
                "description": description,
                "inputSchema": schema(
                    {
                        "name": {"type": "string", "minLength": 1},
                        "path": {"type": ["string", "null"]},
                        "k": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 200,
                            "default": 25,
                        },
                        "verbose": {"type": "boolean", "default": False},
                    },
                    ["name"],
                ),
                "annotations": _read_annotations(),
            }
        )
    if enable_snapshot_create:
        tools.append(
            {
                "name": "snapshot_create",
                "title": "RepoGround snapshot create",
                "description": "Create bundle artifacts for the startup-bound repository and output root.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string"},
                        "output_subdir": {"type": ["string", "null"]},
                        "output_mode": {"type": ["string", "null"]},
                        "timeout_seconds": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 1800,
                        },
                        "max_file_bytes": {"type": "string"},
                        "max_total_bytes": {"type": "string"},
                        "split_size": {"type": "string"},
                        "include_hidden": {"type": "boolean"},
                        "path_filter": {"type": ["string", "null"]},
                        "ext": {"type": ["array", "null"], "items": {"type": "string"}},
                        "redact_secrets": {"type": "boolean"},
                    },
                    "required": ["profile"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                },
            }
        )
    return tools


def tool_registry(enable_snapshot_create: bool = False) -> tuple[dict[str, Any], ...]:
    """Public immutable-length registry projection for docs and drift checks."""
    return tuple(_tool_definitions(enable_snapshot_create))


def tool_names(enable_snapshot_create: bool = False) -> tuple[str, ...]:
    """Public name projection used by documentation drift checks."""
    return tuple(tool["name"] for tool in tool_registry(enable_snapshot_create))


class RepoGroundMcpStdioServer:
    """Bind existing RepoGround handlers to the MCP JSON-RPC lifecycle."""

    def __init__(
        self,
        *,
        bundle_root: str | Path,
        repo_root: str | Path | None = None,
        enable_snapshot_create: bool = False,
    ) -> None:
        self.bundle_root = Path(bundle_root).expanduser().resolve()
        if not self.bundle_root.exists():
            raise ValueError(f"bundle root does not exist: {self.bundle_root}")
        if self.bundle_root.is_file() and not self.bundle_root.name.endswith(
            MANIFEST_SUFFIX
        ):
            raise ValueError(
                "file-valued bundle root must be a *.bundle.manifest.json file"
            )
        self.repo_root = (
            Path(repo_root).expanduser().resolve() if repo_root is not None else None
        )
        if self.repo_root is not None and not self.repo_root.is_dir():
            raise ValueError(f"repo root is not a directory: {self.repo_root}")
        if enable_snapshot_create and self.repo_root is None:
            raise ValueError(
                "--enable-snapshot-create requires an explicit --repo-root"
            )
        self.enable_snapshot_create = enable_snapshot_create
        self.snapshot_output_root = (
            self.bundle_root if self.bundle_root.is_dir() else self.bundle_root.parent
        )
        self._negotiated = False

    def _initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        negotiated = (
            requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        )
        self._negotiated = True
        return {
            "protocolVersion": negotiated,
            "capabilities": {
                "resources": {"subscribe": False, "listChanged": False},
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "title": "RepoGround",
                "version": SERVER_VERSION,
            },
            "instructions": (
                "RepoGround reads existing deterministic bundles, including documented legacy identities. Reads never refresh snapshots. "
                "Use live_freshness before relying on a snapshot. snapshot_create is exposed only "
                "when the operator starts the server with --enable-snapshot-create."
            ),
        }

    def _require_operation(self) -> None:
        if not self._negotiated:
            raise McpProtocolError(-32002, "server is not initialized")

    def _guard_manifest(self, raw_path: Any) -> Path:
        if not isinstance(raw_path, str) or not raw_path:
            raise McpProtocolError(-32602, "bundle_manifest must be a non-empty string")
        manifest = Path(raw_path).expanduser().resolve()
        if not manifest.name.endswith(MANIFEST_SUFFIX):
            raise McpProtocolError(
                -32602, "bundle_manifest must name a RepoGround bundle manifest"
            )
        if self.bundle_root.is_file():
            allowed = manifest == self.bundle_root
        else:
            try:
                manifest.relative_to(self.bundle_root)
            except ValueError:
                allowed = False
            else:
                allowed = True
        if not allowed:
            raise McpProtocolError(
                -32602, "bundle_manifest is outside the configured bundle root"
            )
        if not manifest.is_file():
            raise McpProtocolError(-32602, "bundle_manifest does not exist")
        return manifest

    def _resolve_manifest(self, arguments: Mapping[str, Any]) -> Path:
        raw_manifest = arguments.get("bundle_manifest")
        repo = arguments.get("repo")
        stem = arguments.get("stem")
        if raw_manifest is not None:
            if repo is not None or stem is not None:
                raise McpProtocolError(
                    -32602,
                    "bundle_manifest cannot be combined with repo or stem selectors",
                )
            return self._guard_manifest(raw_manifest)
        from merger.repoground.core.bundle_catalog import select_bundle_manifest

        selection = select_bundle_manifest(
            self.bundle_root,
            repo=repo,
            stem=stem,
            require_healthy=True,
        )
        selected = selection.get("selected")
        manifest = selected.get("manifest_path") if isinstance(selected, dict) else None
        if selection.get("status") != "available" or not isinstance(manifest, str):
            raise McpProtocolError(
                -32602,
                "no unique healthy RepoGround bundle matched the selector",
                {
                    "status": selection.get("status"),
                    "reason": selection.get("reason"),
                    "requested_repo": selection.get("requested_repo"),
                    "requested_stem": selection.get("requested_stem"),
                },
            )
        return self._guard_manifest(manifest)

    def _selected_call_args(
        self, arguments: Mapping[str, Any]
    ) -> tuple[dict[str, Any], Path]:
        manifest = self._resolve_manifest(arguments)
        call_args = {
            key: value
            for key, value in arguments.items()
            if key not in {"bundle_manifest", "repo", "stem"}
        }
        call_args["bundle_manifest"] = str(manifest)
        return call_args, manifest

    @staticmethod
    def _guard_bundle_path(raw_path: Any, manifest: Path, *, label: str) -> str | None:
        if raw_path is None:
            return None
        if not isinstance(raw_path, str) or not raw_path:
            raise McpProtocolError(
                -32602, f"{label} must be null or a non-empty string"
            )
        path = Path(raw_path).expanduser().resolve()
        try:
            path.relative_to(manifest.parent.resolve())
        except ValueError as exc:
            raise McpProtocolError(
                -32602, f"{label} is outside the bundle directory"
            ) from exc
        if not path.is_file():
            raise McpProtocolError(-32602, f"{label} does not exist")
        return str(path)

    def _safe_live_freshness(
        self,
        manifest: str | Path,
        repo_root: str | Path | None = None,
    ) -> dict[str, Any]:
        selected_root = self.repo_root if repo_root is None else repo_root
        if selected_root is None:
            return {
                "kind": "repobrief.live_freshness",
                "version": "v1",
                "status": "not_comparable",
                "reason": "repo_root_not_configured",
                "bundle_manifest": str(manifest),
                "repo_root": None,
                "read_only_git_probe": False,
                "implicit_refresh": False,
                "does_not_establish": list(FRESHNESS_DOES_NOT_ESTABLISH),
            }
        try:
            return evaluate_live_freshness(manifest, repo_root=selected_root)
        except Exception as exc:
            return {
                "kind": "repobrief.live_freshness",
                "version": "v1",
                "status": "unknown",
                "reason": str(exc),
                "bundle_manifest": str(manifest),
                "repo_root": str(selected_root),
                "read_only_git_probe": True,
                "implicit_refresh": False,
                "does_not_establish": list(FRESHNESS_DOES_NOT_ESTABLISH),
            }

    def _resource_list(self) -> dict[str, Any]:
        from merger.repoground.core import mcp_resources

        listed = mcp_resources.list_mcp_resources(self.bundle_root)
        resources = []
        for item in listed.get("resources", []):
            if not isinstance(item, dict) or not isinstance(item.get("uri"), str):
                continue
            resource_name = item.get("resource")
            mime_type = (
                "text/markdown"
                if resource_name in {"canonical", "reading-pack"}
                else "application/json"
            )
            resources.append(
                {
                    "uri": item["uri"],
                    "name": item["uri"],
                    "description": "Existing RepoGround bundle resource; no implicit refresh.",
                    "mimeType": mime_type,
                }
            )
        return {"resources": resources}

    def _resource_templates(self) -> dict[str, Any]:
        from merger.repoground.core import mcp_resources

        return {
            "resourceTemplates": [
                {
                    "uriTemplate": uri_template,
                    "name": uri_template,
                    "description": "Read-only RepoGround snapshot resource template.",
                    "mimeType": "application/json",
                }
                for uri_template in mcp_resources.resource_templates().get(
                    "templates", []
                )
            ]
        }

    def _resource_read(self, params: Mapping[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri:
            raise McpProtocolError(-32602, "resources/read requires a non-empty uri")
        from merger.repoground.core import mcp_resources

        result = mcp_resources.read_mcp_resource(uri, bundle_root=self.bundle_root)
        manifest = result.get("bundle_manifest")
        live = None
        if isinstance(manifest, str) and manifest:
            live = self._safe_live_freshness(self._guard_manifest(manifest))
        text = result.get("content_text")
        if not isinstance(text, str):
            text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        content_type = result.get("content_type")
        mime_type = (
            content_type if isinstance(content_type, str) else "application/json"
        )
        resource_meta = {
            "status": result.get("status"),
            "snapshotContext": result.get("snapshot_context"),
            "liveFreshness": live,
            "implicitRefresh": False,
            "identity": result.get("identity"),
        }
        return {
            "contents": [{"uri": uri, "mimeType": mime_type, "text": text}],
            "_meta": {
                "repoground": resource_meta,
            },
        }

    def _call_bundle_discover(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        from merger.repoground.core.bundle_catalog import (
            discover_bundle_catalog,
            select_bundle_manifest,
        )

        repo = arguments.get("repo")
        stem = arguments.get("stem")
        if repo is not None or stem is not None:
            return select_bundle_manifest(
                self.bundle_root,
                repo=repo,
                stem=stem,
                require_healthy=True,
            )
        return discover_bundle_catalog(self.bundle_root)

    def _call_snapshot_status(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args, manifest = self._selected_call_args(arguments)
        from merger.repoground.core import mcp_tools

        payload = mcp_tools.snapshot_status(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_ask_context(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args, manifest = self._selected_call_args(arguments)
        query = call_args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise McpProtocolError(-32602, "ask_context requires a non-empty query")
        from merger.repoground.core import mcp_tools

        payload = mcp_tools.ask_context(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_query_existing_index(
        self, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        call_args, manifest = self._selected_call_args(arguments)
        query = call_args.get("query")
        if not isinstance(query, str) or not query.strip():
            raise McpProtocolError(
                -32602, "query_existing_index requires a non-empty query"
            )
        k = call_args.get("k", 5)
        if not isinstance(k, int) or isinstance(k, bool) or not 1 <= k <= 100:
            raise McpProtocolError(
                -32602,
                "query_existing_index k must be an integer between 1 and 100",
            )
        budget = call_args.get("max_context_tokens", 2000)
        if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
            raise McpProtocolError(
                -32602,
                "query_existing_index max_context_tokens must be a positive integer",
            )
        from merger.repoground.core import mcp_tools

        payload = mcp_tools.query_existing_index(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_range_get(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args, manifest = self._selected_call_args(arguments)
        if not isinstance(call_args.get("range_ref"), dict):
            raise McpProtocolError(-32602, "range_get requires an object range_ref")
        from merger.repoground.core import mcp_tools

        payload = mcp_tools.range_get(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_grounding_verify(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args, manifest = self._selected_call_args(arguments)
        if not isinstance(call_args.get("declaration"), dict):
            raise McpProtocolError(
                -32602, "grounding_verify requires an object declaration"
            )
        call_args["citation_map"] = self._guard_bundle_path(
            call_args.get("citation_map"),
            manifest,
            label="citation_map",
        )
        from merger.repoground.core import mcp_tools

        payload = mcp_tools.grounding_verify(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_find_symbol(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args, manifest = self._selected_call_args(arguments)
        name = call_args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise McpProtocolError(-32602, "find_symbol requires a non-empty name")
        from merger.repoground.core import mcp_tools

        kind = call_args.get("kind")
        if kind is not None and kind not in mcp_tools.FIND_SYMBOL_KINDS:
            raise McpProtocolError(
                -32602,
                "find_symbol kind must be one of class, function, async_function, or null",
                {"allowed_kinds": list(mcp_tools.FIND_SYMBOL_KINDS)},
            )
        payload = mcp_tools.find_symbol(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_call_navigation(
        self, tool: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        call_args, manifest = self._selected_call_args(arguments)
        name = call_args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise McpProtocolError(-32602, f"{tool} requires a non-empty name")
        k = call_args.get("k", 25)
        if not isinstance(k, int) or isinstance(k, bool) or k < 1 or k > 200:
            raise McpProtocolError(
                -32602,
                f"{tool} k must be an integer between 1 and 200",
                {"k": k},
            )
        from merger.repoground.core import mcp_tools

        handlers = {
            "find_references": mcp_tools.find_references,
            "get_callers": mcp_tools.get_callers,
            "get_callees": mcp_tools.get_callees,
        }
        payload = handlers[tool](**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_snapshot_create(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not self.enable_snapshot_create or self.repo_root is None:
            raise McpProtocolError(-32602, "snapshot_create is disabled")
        forbidden = sorted({"repo", "output_root"}.intersection(arguments))
        if forbidden:
            raise McpProtocolError(
                -32602,
                "snapshot_create repository and output roots are fixed at server startup",
                {"forbidden_arguments": forbidden},
            )
        call_args = dict(arguments)
        call_args["repo"] = str(self.repo_root)
        call_args["output_root"] = str(self.snapshot_output_root)
        from merger.repoground.core import mcp_tools

        return mcp_tools.snapshot_create(**call_args)

    def _tool_payload(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name == "bundle_discover":
            return self._call_bundle_discover(arguments)
        if name == "snapshot_status":
            return self._call_snapshot_status(arguments)
        if name == "ask_context":
            return self._call_ask_context(arguments)
        if name == "query_existing_index":
            return self._call_query_existing_index(arguments)
        if name == "range_get":
            return self._call_range_get(arguments)
        if name == "grounding_verify":
            return self._call_grounding_verify(arguments)
        if name == "live_freshness":
            return self._safe_live_freshness(self._resolve_manifest(arguments))
        if name == "find_symbol":
            return self._call_find_symbol(arguments)
        if name in ("find_references", "get_callers", "get_callees"):
            return self._call_call_navigation(name, arguments)
        if name == "snapshot_create":
            return self._call_snapshot_create(arguments)
        raise McpProtocolError(-32602, f"unknown or disabled tool: {name}")

    @staticmethod
    def _tool_text_summary(name: str, payload: Mapping[str, Any]) -> str:
        summary: dict[str, Any] = {
            "tool": name,
            "status": payload.get("status", "unknown"),
            "details": "Use structuredContent for the complete typed result.",
        }
        retrieval = payload.get("retrieval")
        if isinstance(retrieval, Mapping):
            summary["strategy"] = retrieval.get("strategy")
            summary["match_count"] = retrieval.get("match_count")
        result = payload.get("result")
        if isinstance(result, Mapping):
            hit_count = result.get("hit_count")
            if isinstance(hit_count, int):
                summary["hit_count"] = hit_count
        selected = payload.get("selected")
        if isinstance(selected, Mapping):
            summary["stem"] = selected.get("stem")
        return json.dumps(summary, ensure_ascii=False, separators=(",", ":"))

    def _tool_call(self, params: Mapping[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise McpProtocolError(
                -32602, "tools/call requires name and object arguments"
            )
        try:
            payload = self._tool_payload(name, arguments)
        except McpProtocolError:
            raise
        except Exception as exc:
            error_payload = {"status": "error", "tool": name, "error": str(exc)}
            return {
                "content": [
                    {
                        "type": "text",
                        "text": self._tool_text_summary(name, error_payload),
                    }
                ],
                "structuredContent": error_payload,
                "isError": True,
            }
        return {
            "content": [
                {"type": "text", "text": self._tool_text_summary(name, payload)}
            ],
            "structuredContent": payload,
            "isError": False,
        }

    def dispatch(self, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return self._initialize(params)
        if method == "ping":
            return {}
        self._require_operation()
        if method == "tools/list":
            return {"tools": _tool_definitions(self.enable_snapshot_create)}
        if method == "tools/call":
            return self._tool_call(params)
        if method == "resources/list":
            return self._resource_list()
        if method == "resources/templates/list":
            return self._resource_templates()
        if method == "resources/read":
            return self._resource_read(params)
        raise McpProtocolError(-32601, f"method not found: {method}")

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error_response(None, -32600, "invalid JSON-RPC request")
        method = message.get("method")
        if not isinstance(method, str):
            return _error_response(
                message.get("id"), -32600, "request method is required"
            )
        if "id" not in message:
            return None
        request_id = message.get("id")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return _error_response(request_id, -32602, "params must be an object")
        try:
            result = self.dispatch(method, params)
        except McpProtocolError as exc:
            return _error_response(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:
            return _error_response(
                request_id, -32603, "internal error", {"detail": str(exc)}
            )
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(
    request_id: Any, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def serve_stdio(
    server: RepoGroundMcpStdioServer,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    for raw_line in input_stream:
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError:
            response = _error_response(None, -32700, "parse error")
        else:
            response = server.handle_message(message)
        if response is not None:
            output_stream.write(
                json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            output_stream.flush()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve RepoGround over MCP stdio.")
    parser.add_argument(
        "--bundle-root",
        required=True,
        help="Directory or exact RepoGround bundle manifest.",
    )
    parser.add_argument(
        "--repo-root",
        help="Optional explicit local checkout for live freshness comparison.",
    )
    parser.add_argument(
        "--enable-snapshot-create",
        action="store_true",
        help=(
            "Expose snapshot_create bound to --repo-root and --bundle-root. "
            "Requires --repo-root and is disabled by default."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        server = RepoGroundMcpStdioServer(
            bundle_root=args.bundle_root,
            repo_root=args.repo_root,
            enable_snapshot_create=args.enable_snapshot_create,
        )
    except ValueError as exc:
        print(f"repoground mcp stdio: {exc}", file=sys.stderr)
        return 2
    return serve_stdio(server)


if __name__ == "__main__":
    raise SystemExit(main())
