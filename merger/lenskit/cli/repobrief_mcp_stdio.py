"""Minimal newline-delimited MCP stdio transport for RepoBrief."""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

from merger.lenskit.core import repobrief_mcp_resources, repobrief_mcp_tools
from merger.lenskit.core.repobrief_live_freshness import (
    DOES_NOT_ESTABLISH as FRESHNESS_DOES_NOT_ESTABLISH,
)
from merger.lenskit.core.repobrief_live_freshness import evaluate_live_freshness

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = (PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
SERVER_NAME = "repobrief"
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


def _tool_definitions(enable_snapshot_create: bool) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "name": "ask_context",
            "title": "RepoBrief context pack",
            "description": "Build a cited context pack from one existing RepoBrief bundle.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "bundle_manifest": {"type": "string"},
                    "query": {"type": "string"},
                    "task_profile": {"type": "string", "default": "basic_repo_question"},
                    "max_context_tokens": {"type": "integer", "minimum": 1, "default": 8000},
                    "max_answer_tokens": {"type": "integer", "minimum": 1, "default": 1200},
                    "k": {"type": "integer", "minimum": 1, "maximum": 100, "default": 5},
                },
                "required": ["bundle_manifest", "query"],
                "additionalProperties": False,
            },
            "annotations": _read_annotations(),
        },
        {
            "name": "grounding_verify",
            "title": "RepoBrief grounding verifier",
            "description": "Verify declared citations and ranges against an existing RepoBrief bundle.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "declaration": {"type": "object"},
                    "bundle_manifest": {"type": "string"},
                    "citation_map": {"type": ["string", "null"]},
                    "task_profile": {"type": ["string", "null"]},
                },
                "required": ["declaration", "bundle_manifest"],
                "additionalProperties": False,
            },
            "annotations": _read_annotations(),
        },
        {
            "name": "live_freshness",
            "title": "RepoBrief live freshness",
            "description": (
                "Compare snapshot Git provenance with the configured local checkout "
                "without refreshing it."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {"bundle_manifest": {"type": "string"}},
                "required": ["bundle_manifest"],
                "additionalProperties": False,
            },
            "annotations": _read_annotations(),
        },
        {
            "name": "find_symbol",
            "title": "RepoBrief symbol locator",
            "description": (
                "Locate Python symbol definitions (function/class/async_function) by name "
                "in an existing RepoBrief bundle. Answers 'where is X defined?' with an "
                "exact path and line range."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "bundle_manifest": {"type": "string"},
                    "name": {"type": "string", "minLength": 1},
                    "kind": {
                        "type": ["string", "null"],
                        "enum": [None, "class", "function", "async_function"],
                    },
                    "path": {"type": ["string", "null"]},
                    "k": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
                },
                "required": ["bundle_manifest", "name"],
                "additionalProperties": False,
            },
            "annotations": _read_annotations(),
        },
    ]
    if enable_snapshot_create:
        tools.append(
            {
                "name": "snapshot_create",
                "title": "RepoBrief snapshot create",
                "description": (
                    "Create RepoBrief bundle artifacts for the startup-bound repository "
                    "inside the startup-bound bundle root."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "profile": {"type": "string"},
                        "output_subdir": {"type": ["string", "null"]},
                        "output_mode": {"type": ["string", "null"]},
                        "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 1800},
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


class RepoBriefMcpStdioServer:
    """Bind existing RepoBrief handlers to the MCP JSON-RPC lifecycle."""

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
        if self.bundle_root.is_file() and not self.bundle_root.name.endswith(MANIFEST_SUFFIX):
            raise ValueError("file-valued bundle root must be a *.bundle.manifest.json file")
        self.repo_root = Path(repo_root).expanduser().resolve() if repo_root is not None else None
        if self.repo_root is not None and not self.repo_root.is_dir():
            raise ValueError(f"repo root is not a directory: {self.repo_root}")
        if enable_snapshot_create and self.repo_root is None:
            raise ValueError("--enable-snapshot-create requires an explicit --repo-root")
        self.enable_snapshot_create = enable_snapshot_create
        self.snapshot_output_root = (
            self.bundle_root if self.bundle_root.is_dir() else self.bundle_root.parent
        )
        self._negotiated = False

    def _initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        negotiated = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        self._negotiated = True
        return {
            "protocolVersion": negotiated,
            "capabilities": {
                "resources": {"subscribe": False, "listChanged": False},
                "tools": {"listChanged": False},
            },
            "serverInfo": {"name": SERVER_NAME, "title": "RepoBrief", "version": SERVER_VERSION},
            "instructions": (
                "RepoBrief reads existing deterministic bundles. Reads never refresh snapshots. "
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
            raise McpProtocolError(-32602, "bundle_manifest must name a RepoBrief bundle manifest")
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
            raise McpProtocolError(-32602, "bundle_manifest is outside the configured bundle root")
        if not manifest.is_file():
            raise McpProtocolError(-32602, "bundle_manifest does not exist")
        return manifest

    @staticmethod
    def _guard_bundle_path(raw_path: Any, manifest: Path, *, label: str) -> str | None:
        if raw_path is None:
            return None
        if not isinstance(raw_path, str) or not raw_path:
            raise McpProtocolError(-32602, f"{label} must be null or a non-empty string")
        path = Path(raw_path).expanduser().resolve()
        try:
            path.relative_to(manifest.parent.resolve())
        except ValueError as exc:
            raise McpProtocolError(-32602, f"{label} is outside the bundle directory") from exc
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
        listed = repobrief_mcp_resources.list_mcp_resources(self.bundle_root)
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
                    "description": "Existing RepoBrief bundle resource; no implicit refresh.",
                    "mimeType": mime_type,
                }
            )
        return {"resources": resources}

    def _resource_templates(self) -> dict[str, Any]:
        return {
            "resourceTemplates": [
                {
                    "uriTemplate": uri_template,
                    "name": uri_template,
                    "description": "Read-only RepoBrief snapshot resource template.",
                    "mimeType": "application/json",
                }
                for uri_template in repobrief_mcp_resources.resource_templates().get(
                    "templates", []
                )
            ]
        }

    def _resource_read(self, params: Mapping[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri:
            raise McpProtocolError(-32602, "resources/read requires a non-empty uri")
        result = repobrief_mcp_resources.read_mcp_resource(uri, bundle_root=self.bundle_root)
        manifest = result.get("bundle_manifest")
        live = None
        if isinstance(manifest, str) and manifest:
            live = self._safe_live_freshness(self._guard_manifest(manifest))
        text = result.get("content_text")
        if not isinstance(text, str):
            text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        content_type = result.get("content_type")
        mime_type = content_type if isinstance(content_type, str) else "application/json"
        return {
            "contents": [{"uri": uri, "mimeType": mime_type, "text": text}],
            "_meta": {
                "repobrief": {
                    "status": result.get("status"),
                    "snapshotContext": result.get("snapshot_context"),
                    "liveFreshness": live,
                    "implicitRefresh": False,
                }
            },
        }

    def _call_ask_context(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args = dict(arguments)
        manifest = self._guard_manifest(call_args.get("bundle_manifest"))
        call_args["bundle_manifest"] = str(manifest)
        payload = repobrief_mcp_tools.ask_context(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_grounding_verify(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args = dict(arguments)
        manifest = self._guard_manifest(call_args.get("bundle_manifest"))
        call_args["bundle_manifest"] = str(manifest)
        call_args["citation_map"] = self._guard_bundle_path(
            call_args.get("citation_map"),
            manifest,
            label="citation_map",
        )
        payload = repobrief_mcp_tools.grounding_verify(**call_args)
        payload["live_freshness"] = self._safe_live_freshness(manifest)
        return payload

    def _call_find_symbol(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        call_args = dict(arguments)
        # Fail closed at the transport boundary: reject an empty name (which would
        # otherwise list the first k symbols) or an unknown kind, independent of
        # any client-side inputSchema enforcement.
        name = call_args.get("name")
        if not isinstance(name, str) or not name.strip():
            raise McpProtocolError(-32602, "find_symbol requires a non-empty name")
        kind = call_args.get("kind")
        if kind is not None and kind not in repobrief_mcp_tools.FIND_SYMBOL_KINDS:
            raise McpProtocolError(
                -32602,
                "find_symbol kind must be one of class, function, async_function, or null",
                {"allowed_kinds": list(repobrief_mcp_tools.FIND_SYMBOL_KINDS)},
            )
        manifest = self._guard_manifest(call_args.get("bundle_manifest"))
        call_args["bundle_manifest"] = str(manifest)
        payload = repobrief_mcp_tools.find_symbol(**call_args)
        # Nav results reflect the snapshot; surface freshness so the agent knows
        # whether the index may lag the live working tree.
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
        return repobrief_mcp_tools.snapshot_create(**call_args)

    def _tool_payload(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        if name == "ask_context":
            return self._call_ask_context(arguments)
        if name == "grounding_verify":
            return self._call_grounding_verify(arguments)
        if name == "live_freshness":
            manifest = self._guard_manifest(arguments.get("bundle_manifest"))
            return self._safe_live_freshness(manifest)
        if name == "find_symbol":
            return self._call_find_symbol(arguments)
        if name == "snapshot_create":
            return self._call_snapshot_create(arguments)
        raise McpProtocolError(-32602, f"unknown or disabled tool: {name}")

    def _tool_call(self, params: Mapping[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise McpProtocolError(-32602, "tools/call requires name and object arguments")
        try:
            payload = self._tool_payload(name, arguments)
        except McpProtocolError:
            raise
        except Exception as exc:
            error_payload = {"status": "error", "tool": name, "error": str(exc)}
            return {
                "content": [
                    {"type": "text", "text": json.dumps(error_payload, ensure_ascii=False)}
                ],
                "structuredContent": error_payload,
                "isError": True,
            }
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
                }
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
            return _error_response(message.get("id"), -32600, "request method is required")
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
            return _error_response(request_id, -32603, "internal error", {"detail": str(exc)})
        return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def serve_stdio(
    server: RepoBriefMcpStdioServer,
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
    parser = argparse.ArgumentParser(description="Serve RepoBrief over MCP stdio.")
    parser.add_argument(
        "--bundle-root",
        required=True,
        help="Directory or exact RepoBrief bundle manifest.",
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
        server = RepoBriefMcpStdioServer(
            bundle_root=args.bundle_root,
            repo_root=args.repo_root,
            enable_snapshot_create=args.enable_snapshot_create,
        )
    except ValueError as exc:
        print(f"repobrief mcp stdio: {exc}", file=sys.stderr)
        return 2
    return serve_stdio(server)


if __name__ == "__main__":
    raise SystemExit(main())
