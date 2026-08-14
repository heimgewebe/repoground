"""Race-safe plan/apply effects for manual query-artifact GC."""
from __future__ import annotations

import copy
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ..core.rooted_filesystem import (
    RootedFilesystemError,
    atomic_write_bytes,
    exclusive_file_lock,
    exclusive_write_bytes,
    lstat_path,
    make_directories,
    path_exists,
    read_regular_bytes,
)
from .runtime_artifact_gc import (
    RuntimeArtifactGCError,
    build_retention_plan,
    canonical_json,
    sha256_bytes,
    sha256_json,
    verify_retention_plan,
)
from .runtime_artifact_retention import (
    MANUAL_GC_DEFAULT_PROFILE,
    runtime_artifact_gc_profile,
)

_STORE_FILENAME = "query_artifacts.json"
_LOCK_FILENAME = ".query_artifacts.lock"
_RECEIPT_DIRNAME = "retention-receipts"
_TRANSACTION_DIRNAME = "retention-transactions"
_RECEIPT_KIND = "lenskit.runtime_artifact_gc_receipt"
_TRANSACTION_KIND = "lenskit.runtime_artifact_gc_transaction"
_SCHEMA_VERSION = 1


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _plan_stem(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeArtifactGCError("invalid_plan", "plan_sha256 must be lowercase SHA-256")
    return value


class RuntimeArtifactGCStore:
    """Manual GC bound to one store directory and one inter-process lock."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.store_file = self.storage_dir / _STORE_FILENAME
        self.lock_file = self.storage_dir / _LOCK_FILENAME
        self.receipt_dir = self.storage_dir / _RECEIPT_DIRNAME
        self.transaction_dir = self.storage_dir / _TRANSACTION_DIRNAME
        try:
            make_directories(self.storage_dir, mode=0o700)
        except RootedFilesystemError as exc:
            raise RuntimeArtifactGCError(
                "unsafe_store_directory", f"unsafe artifact storage directory: {self.storage_dir}"
            ) from exc
        self._assert_owned(
            self.storage_dir,
            label="artifact storage directory",
            directory=True,
        )

    def _assert_owned(self, path: Path, *, label: str, directory: bool = False) -> None:
        try:
            if not path_exists(path):
                return
            metadata = lstat_path(path)
        except RootedFilesystemError as exc:
            raise RuntimeArtifactGCError("unsafe_store_entry", f"cannot safely inspect {label}") from exc
        predicate = stat.S_ISDIR if directory else stat.S_ISREG
        if not predicate(metadata.st_mode):
            raise RuntimeArtifactGCError(
                "unsafe_store_entry", f"{label} is not a {'directory' if directory else 'regular file'}"
            )
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise RuntimeArtifactGCError("foreign_store_owner", f"{label} has a foreign owner")

    def _ensure_audit_dirs(self) -> None:
        try:
            make_directories(self.receipt_dir, mode=0o700)
            make_directories(self.transaction_dir, mode=0o700)
        except RootedFilesystemError as exc:
            raise RuntimeArtifactGCError(
                "unsafe_audit_directory", "retention audit directories are unsafe"
            ) from exc
        self._assert_owned(self.receipt_dir, label="receipt directory", directory=True)
        self._assert_owned(self.transaction_dir, label="transaction directory", directory=True)

    def _read_store(self) -> tuple[list[dict[str, Any]], bytes]:
        try:
            if not path_exists(self.store_file):
                return [], b"[]"
            self._assert_owned(self.store_file, label="query artifact store")
            payload = read_regular_bytes(self.store_file)
            data = json.loads(payload.decode("utf-8"))
        except (RootedFilesystemError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeArtifactGCError(
                "unsafe_store_entry", "query artifact store cannot be read safely"
            ) from exc
        if not isinstance(data, list):
            raise RuntimeArtifactGCError("invalid_store_json", "query artifact store root must be a list")
        seen: set[str] = set()
        rendered: list[dict[str, Any]] = []
        for index, entry in enumerate(data):
            if not isinstance(entry, dict):
                raise RuntimeArtifactGCError(
                    "invalid_store_entry", f"query artifact entry {index} is not an object"
                )
            artifact_id = entry.get("id")
            if not isinstance(artifact_id, str) or not artifact_id or artifact_id in seen:
                raise RuntimeArtifactGCError(
                    "invalid_store_entry", f"query artifact entry {index} has an invalid/duplicate id"
                )
            seen.add(artifact_id)
            rendered.append(entry)
        return rendered, payload

    def _receipt_path(self, plan_sha256: str) -> Path:
        return self.receipt_dir / f"{_plan_stem(plan_sha256)}.json"

    def _transaction_path(self, plan_sha256: str) -> Path:
        return self.transaction_dir / f"{_plan_stem(plan_sha256)}.json"

    def _read_json(self, path: Path, *, label: str) -> Dict[str, Any]:
        self._assert_owned(path, label=label)
        try:
            parsed = json.loads(read_regular_bytes(path).decode("utf-8"))
        except (RootedFilesystemError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeArtifactGCError("invalid_audit_record", f"invalid {label}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeArtifactGCError("invalid_audit_record", f"{label} must be an object")
        return parsed

    def _verify_receipt(self, receipt: Dict[str, Any], plan_sha256: str) -> Dict[str, Any]:
        digest = receipt.get("receipt_sha256")
        body = copy.deepcopy(receipt)
        body.pop("receipt_sha256", None)
        if (
            not isinstance(digest, str)
            or sha256_json(body) != digest
            or body.get("kind") != _RECEIPT_KIND
            or body.get("plan_sha256") != plan_sha256
        ):
            raise RuntimeArtifactGCError("invalid_receipt", "retention receipt binding is invalid")
        return receipt

    def _verify_transaction(self, transaction: Dict[str, Any], plan_sha256: str) -> Dict[str, Any]:
        digest = transaction.get("transaction_sha256")
        body = copy.deepcopy(transaction)
        body.pop("transaction_sha256", None)
        if (
            not isinstance(digest, str)
            or sha256_json(body) != digest
            or body.get("kind") != _TRANSACTION_KIND
            or body.get("plan_sha256") != plan_sha256
        ):
            raise RuntimeArtifactGCError("invalid_transaction", "retention transaction binding is invalid")
        return transaction

    def assert_no_pending(self, *, allow_plan_sha256: Optional[str] = None) -> None:
        """Block normal writes while an effect may lack its final receipt."""
        self._ensure_audit_dirs()
        try:
            entries = sorted(self.transaction_dir.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise RuntimeArtifactGCError(
                "unsafe_audit_directory", "transaction directory cannot be enumerated"
            ) from exc
        for path in entries:
            stem = path.stem
            if (
                path.suffix != ".json"
                or len(stem) != 64
                or any(character not in "0123456789abcdef" for character in stem)
            ):
                raise RuntimeArtifactGCError(
                    "unsafe_audit_entry", f"unexpected transaction entry {path.name!r}"
                )
            receipt_path = self._receipt_path(stem)
            if path_exists(receipt_path):
                self._verify_receipt(
                    self._read_json(receipt_path, label="retention receipt"), stem
                )
                continue
            if stem == allow_plan_sha256:
                continue
            raise RuntimeArtifactGCError(
                "retention_transaction_pending",
                f"unfinished retention transaction {stem} must be recovered first",
            )

    def plan(
        self,
        *,
        protection: Mapping[str, Any],
        as_of: Optional[str] = None,
        profile_id: str = MANUAL_GC_DEFAULT_PROFILE,
    ) -> Dict[str, Any]:
        try:
            budgets = runtime_artifact_gc_profile(profile_id)
        except ValueError as exc:
            raise RuntimeArtifactGCError("unknown_profile", str(exc)) from exc
        with exclusive_file_lock(self.lock_file, mode=0o600):
            self.assert_no_pending()
            entries, payload = self._read_store()
            return build_retention_plan(
                entries=entries,
                store_sha256=sha256_bytes(payload),
                protection=protection,
                as_of=as_of or _utc_now_iso(),
                profile_id=profile_id,
                budgets=budgets,
            )

    def _receipt_response(
        self,
        receipt: Dict[str, Any],
        *,
        idempotent_replay: bool,
        recovered_after_effect: bool,
    ) -> Dict[str, Any]:
        response = copy.deepcopy(receipt)
        response["idempotent_replay"] = idempotent_replay
        response["recovered_after_effect"] = recovered_after_effect
        return response

    def _finalize_receipt(
        self,
        transaction: Dict[str, Any],
        *,
        recovered_after_effect: bool,
    ) -> Dict[str, Any]:
        plan_sha256 = transaction["plan_sha256"]
        path = self._receipt_path(plan_sha256)
        if path_exists(path):
            receipt = self._verify_receipt(self._read_json(path, label="retention receipt"), plan_sha256)
            return self._receipt_response(
                receipt, idempotent_replay=True, recovered_after_effect=recovered_after_effect
            )
        body = copy.deepcopy(transaction["receipt_body"])
        receipt = {**body, "receipt_sha256": sha256_json(body)}
        try:
            exclusive_write_bytes(path, (canonical_json(receipt) + "\n").encode(), mode=0o600)
        except RootedFilesystemError as exc:
            if path_exists(path):
                receipt = self._verify_receipt(
                    self._read_json(path, label="retention receipt"), plan_sha256
                )
                return self._receipt_response(
                    receipt, idempotent_replay=True, recovered_after_effect=recovered_after_effect
                )
            raise RuntimeArtifactGCError("receipt_write_failed", "retention receipt write failed") from exc
        return self._receipt_response(
            receipt,
            idempotent_replay=recovered_after_effect,
            recovered_after_effect=recovered_after_effect,
        )

    def _existing_receipt(self, plan_sha256: str) -> Optional[Dict[str, Any]]:
        path = self._receipt_path(plan_sha256)
        if not path_exists(path):
            return None
        receipt = self._verify_receipt(
            self._read_json(path, label="retention receipt"), plan_sha256
        )
        return self._receipt_response(
            receipt, idempotent_replay=True, recovered_after_effect=False
        )

    def _recover_transaction(
        self, plan_sha256: str, current_sha256: str
    ) -> Optional[Dict[str, Any]]:
        path = self._transaction_path(plan_sha256)
        if not path_exists(path):
            return None
        transaction = self._verify_transaction(
            self._read_json(path, label="retention transaction"), plan_sha256
        )
        if current_sha256 == transaction["post_store_sha256"]:
            return self._finalize_receipt(transaction, recovered_after_effect=True)
        if current_sha256 != transaction["pre_store_sha256"]:
            raise RuntimeArtifactGCError(
                "transaction_state_ambiguous",
                "store matches neither transaction pre-image nor post-image",
            )
        return None

    def _current_protection(
        self,
        *,
        verified: Mapping[str, Any],
        entries: list[dict[str, Any]],
        current_sha256: str,
        protection: Mapping[str, Any],
    ) -> tuple[Dict[str, Any], set[str]]:
        current_plan = build_retention_plan(
            entries=entries,
            store_sha256=current_sha256,
            protection=protection,
            as_of=verified["as_of"],
            profile_id=verified["profile_id"],
            budgets=verified["budgets"],
        )
        planned = {row["artifact_id"] for row in verified.get("protected", [])}
        current = {row["artifact_id"] for row in current_plan.get("protected", [])}
        if not planned.issubset(current):
            raise RuntimeArtifactGCError(
                "protection_weakened",
                f"apply removed protected artifacts: {sorted(planned-current)}",
            )
        return current_plan, current

    def _validated_candidates(
        self,
        *,
        verified: Mapping[str, Any],
        entries: list[dict[str, Any]],
    ) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        candidates = {row["artifact_id"]: row for row in verified.get("candidates", [])}
        index = {entry["id"]: entry for entry in entries}
        for artifact_id, candidate in candidates.items():
            current = index.get(artifact_id)
            if current is None or sha256_json(current) != candidate.get("entry_sha256"):
                raise RuntimeArtifactGCError(
                    "candidate_identity_changed", f"candidate {artifact_id!r} changed"
                )
        return candidates, index

    def _prepared_transaction(
        self,
        *,
        verified: Mapping[str, Any],
        plan_sha256: str,
        entries: list[dict[str, Any]],
        current_bytes: bytes,
        current_sha256: str,
        current_plan: Mapping[str, Any],
        current_protected: set[str],
        candidates: Mapping[str, Mapping[str, Any]],
        index: Mapping[str, Mapping[str, Any]],
    ) -> tuple[Dict[str, Any], bytes, str, list[str], list[str]]:
        delete_ids = sorted(set(candidates) - current_protected)
        skipped = sorted(set(candidates) & current_protected)
        post_entries = [
            entry for entry in entries if entry["id"] not in set(delete_ids)
        ]
        post_bytes = (
            json.dumps(post_entries, indent=2).encode() if delete_ids else current_bytes
        )
        post_sha256 = sha256_bytes(post_bytes)
        protected_readback = sorted(current_protected & set(index))
        receipt_body = {
            "kind": _RECEIPT_KIND,
            "schema_version": _SCHEMA_VERSION,
            "status": "applied",
            "plan_sha256": plan_sha256,
            "profile_id": verified["profile_id"],
            "applied_at": _utc_now_iso(),
            "pre_store_sha256": current_sha256,
            "post_store_sha256": post_sha256,
            "protection_sha256": current_plan["protection_sha256"],
            "deleted": {
                "objects": len(delete_ids),
                "bytes": max(0, len(current_bytes) - len(post_bytes)),
            },
            "skipped_newly_protected": skipped,
            "effects": [
                {
                    "artifact_id": artifact_id,
                    "artifact_type": candidates[artifact_id]["artifact_type"],
                    "entry_sha256": candidates[artifact_id]["entry_sha256"],
                    "reasons": list(candidates[artifact_id]["reasons"]),
                }
                for artifact_id in delete_ids
            ],
            "protected_readback": protected_readback,
            "integrity_readback": {
                "store_json_valid": True,
                "post_store_sha256": post_sha256,
                "protected_artifacts_readable": protected_readback,
            },
        }
        transaction_body = {
            "kind": _TRANSACTION_KIND,
            "schema_version": _SCHEMA_VERSION,
            "plan_sha256": plan_sha256,
            "prepared_at": _utc_now_iso(),
            "pre_store_sha256": current_sha256,
            "post_store_sha256": post_sha256,
            "delete_ids": delete_ids,
            "receipt_body": receipt_body,
        }
        transaction = {
            **transaction_body,
            "transaction_sha256": sha256_json(transaction_body),
        }
        return transaction, post_bytes, post_sha256, delete_ids, protected_readback

    def _write_effect(
        self,
        *,
        plan_sha256: str,
        transaction: Mapping[str, Any],
        post_bytes: bytes,
        delete_ids: list[str],
    ) -> None:
        try:
            atomic_write_bytes(
                self._transaction_path(plan_sha256),
                (canonical_json(transaction) + "\n").encode(),
                mode=0o600,
            )
            if delete_ids:
                self._assert_owned(self.store_file, label="query artifact store")
                atomic_write_bytes(self.store_file, post_bytes, mode=0o600)
        except RootedFilesystemError as exc:
            raise RuntimeArtifactGCError(
                "gc_effect_failed", "manual GC effect write failed"
            ) from exc

    def _verify_effect_readback(
        self, *, post_sha256: str, protected_readback: list[str]
    ) -> None:
        readback_entries, readback_bytes = self._read_store()
        if sha256_bytes(readback_bytes) != post_sha256:
            raise RuntimeArtifactGCError(
                "post_apply_integrity_failed",
                "store readback differs from expected post-image",
            )
        readback_ids = {entry["id"] for entry in readback_entries}
        missing = sorted(set(protected_readback) - readback_ids)
        if missing:
            raise RuntimeArtifactGCError(
                "post_apply_protection_failed",
                f"protected artifacts disappeared: {missing}",
            )

    def apply(
        self,
        *,
        plan: Mapping[str, Any],
        protection: Mapping[str, Any],
    ) -> Dict[str, Any]:
        verified = verify_retention_plan(plan)
        plan_sha256 = verified["plan_sha256"]
        with exclusive_file_lock(self.lock_file, mode=0o600):
            self.assert_no_pending(allow_plan_sha256=plan_sha256)
            existing = self._existing_receipt(plan_sha256)
            if existing is not None:
                return existing
            entries, current_bytes = self._read_store()
            current_sha256 = sha256_bytes(current_bytes)
            recovered = self._recover_transaction(plan_sha256, current_sha256)
            if recovered is not None:
                return recovered
            if current_sha256 != verified["store_sha256"]:
                raise RuntimeArtifactGCError(
                    "store_snapshot_changed",
                    "store changed after dry-run; create a fresh plan",
                )
            current_plan, current_protected = self._current_protection(
                verified=verified,
                entries=entries,
                current_sha256=current_sha256,
                protection=protection,
            )
            candidates, index = self._validated_candidates(
                verified=verified, entries=entries
            )
            transaction, post_bytes, post_sha256, delete_ids, protected_readback = (
                self._prepared_transaction(
                    verified=verified,
                    plan_sha256=plan_sha256,
                    entries=entries,
                    current_bytes=current_bytes,
                    current_sha256=current_sha256,
                    current_plan=current_plan,
                    current_protected=current_protected,
                    candidates=candidates,
                    index=index,
                )
            )
            self._write_effect(
                plan_sha256=plan_sha256,
                transaction=transaction,
                post_bytes=post_bytes,
                delete_ids=delete_ids,
            )
            self._verify_effect_readback(
                post_sha256=post_sha256,
                protected_readback=protected_readback,
            )
            return self._finalize_receipt(
                transaction, recovered_after_effect=False
            )
