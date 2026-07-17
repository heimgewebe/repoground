import re
import sqlite3
import datetime
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

class AtlasRegistry:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _init_db(self) -> None:
        with self.conn:
            self.conn.execute("PRAGMA foreign_keys = ON;")
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS machines (
                    machine_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    labels TEXT,
                    last_seen_at TEXT
                );
                CREATE TABLE IF NOT EXISTS roots (
                    root_id TEXT PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    root_kind TEXT NOT NULL,
                    root_value TEXT NOT NULL,
                    label TEXT,
                    FOREIGN KEY(machine_id) REFERENCES machines(machine_id)
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    machine_id TEXT NOT NULL,
                    root_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    scan_config_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    inventory_ref TEXT,
                    dirs_ref TEXT,
                    summary_ref TEXT,
                    content_ref TEXT,
                    topology_ref TEXT,
                    hotspots_ref TEXT,
                    workspaces_ref TEXT,
                    duplicates_ref TEXT,
                    orphans_ref TEXT,
                    disk_ref TEXT,
                    FOREIGN KEY(machine_id) REFERENCES machines(machine_id),
                    FOREIGN KEY(root_id) REFERENCES roots(root_id)
                );
                CREATE TABLE IF NOT EXISTS deltas (
                    delta_id TEXT PRIMARY KEY,
                    from_snapshot_id TEXT NOT NULL,
                    to_snapshot_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    delta_ref TEXT NOT NULL,
                    FOREIGN KEY(from_snapshot_id) REFERENCES snapshots(snapshot_id),
                    FOREIGN KEY(to_snapshot_id) REFERENCES snapshots(snapshot_id)
                );
            """)

            # Migration: Ensure duplicates_ref, orphans_ref, and disk_ref exist if table was created in earlier version
            cur = self.conn.execute("PRAGMA table_info(snapshots)")
            cols = [row["name"] for row in cur.fetchall()]
            if "duplicates_ref" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN duplicates_ref TEXT")
            if "orphans_ref" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN orphans_ref TEXT")
            if "disk_ref" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN disk_ref TEXT")

            # Migration: progress tracking columns for live scan observability.
            # files_seen / dirs_seen / bytes_seen = in-progress counters
            # (distinct from total_files / total_dirs / total_bytes in the
            #  final snapshot_meta.json result artifact).
            # last_progress_at = liveness/diagnostic timestamp.
            # error_message = failure reason text.
            if "files_seen" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN files_seen INTEGER")
            if "dirs_seen" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN dirs_seen INTEGER")
            if "bytes_seen" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN bytes_seen INTEGER")
            if "last_progress_at" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN last_progress_at TEXT")
            if "error_message" not in cols:
                self.conn.execute("ALTER TABLE snapshots ADD COLUMN error_message TEXT")

    def register_machine(self, machine_id: str, hostname: str, labels: Optional[List[str]] = None) -> str:
        machine_id = machine_id.strip().lower()
        hostname = hostname.strip().lower()

        if not hostname:
            raise ValueError("Hostname cannot be empty")

        if not re.match(r"^[a-z0-9_.-]+$", machine_id):
            raise ValueError(f"Invalid machine_id format: '{machine_id}'. Must match ^[a-z0-9_.-]+$. Please provide a valid explicit identity via the --machine-id CLI flag or the ATLAS_MACHINE_ID environment variable.")

        cur = self.conn.cursor()
        cur.execute("SELECT * FROM machines WHERE lower(machine_id) = ?", (machine_id,))
        legacy_matches = [dict(row) for row in cur.fetchall()]

        if len(legacy_matches) > 1:
            raise ValueError(f"Ambiguous legacy machine IDs found for '{machine_id}'. Multiple case variations exist in the registry. Please resolve this inconsistency manually.")

        if len(legacy_matches) == 1:
            existing_machine = legacy_matches[0]
            existing_machine['labels'] = json.loads(existing_machine['labels']) if existing_machine['labels'] else None

            # Use the canonical stored machine_id to preserve snapshot history and foreign keys
            machine_id = existing_machine["machine_id"]

            existing_canonical_hostname = existing_machine["hostname"].strip().lower()
            if existing_canonical_hostname != hostname:
                raise ValueError(f"Machine ID '{machine_id}' is already registered with a different hostname '{existing_machine['hostname']}'. Cannot re-register with hostname '{hostname}'.")

            # Optionally sync canonical hostname back to DB
            hostname = existing_canonical_hostname

        labels_json = json.dumps(labels) if labels else None
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Concurrency race check is consciously left out of this PR scope
        with self.conn:
            self.conn.execute("""
                INSERT INTO machines (machine_id, hostname, labels, last_seen_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(machine_id) DO UPDATE SET
                    labels=excluded.labels,
                    last_seen_at=excluded.last_seen_at
            """, (machine_id, hostname, labels_json, now))

        return machine_id

    def get_machine(self, machine_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM machines WHERE machine_id = ?", (machine_id,))
        row = cur.fetchone()
        if not row:
            return None
        res = dict(row)
        res['labels'] = json.loads(res['labels']) if res['labels'] else None
        return res

    def list_machines(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM machines")
        machines = []
        for row in cur.fetchall():
            res = dict(row)
            res['labels'] = json.loads(res['labels']) if res['labels'] else None
            machines.append(res)
        return machines

    def get_machine_health(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT m.machine_id, m.hostname, m.labels, m.last_seen_at,
                   COUNT(s.snapshot_id) as total_complete_snapshots,
                   MAX(s.created_at) as last_snapshot_at
            FROM machines m
            LEFT JOIN snapshots s ON m.machine_id = s.machine_id AND s.status = 'complete'
            GROUP BY m.machine_id, m.hostname, m.labels, m.last_seen_at
            ORDER BY m.machine_id
        """)
        health_reports = []
        for row in cur.fetchall():
            res = dict(row)
            res['labels'] = json.loads(res['labels']) if res['labels'] else None

            # Note: This is a diagnostic read-only view and not a comprehensive "Health Score".
            # It provides raw metrics (last seen, snapshot counts) for the UI/Agent to interpret.
            res['has_snapshots'] = res['total_complete_snapshots'] > 0

            health_reports.append(res)
        return health_reports

    def register_root(self, root_id: str, machine_id: str, root_kind: str, root_value: str, label: Optional[str] = None) -> None:
        root_id = root_id.strip()

        if label is not None:
            label = label.strip()
            if not label:
                raise ValueError("Root label cannot be empty.")

        if not root_id:
            raise ValueError("Root ID cannot be empty.")
        if not re.match(r"^[A-Za-z0-9._-]+$", root_id) or root_id in [".", ".."]:
            raise ValueError(f"Root ID '{root_id}' is invalid. It must be filesystem-safe, matching ^[A-Za-z0-9._-]+$ and cannot be '.' or '..'.")

        with self.conn:
            cur = self.conn.cursor()
            cur.execute("SELECT machine_id, root_value FROM roots WHERE root_id = ?", (root_id,))
            existing = cur.fetchone()
            if existing:
                if existing["machine_id"] != machine_id:
                    raise ValueError(f"Root ID '{root_id}' is already registered to a different machine ('{existing['machine_id']}'). Cannot silently overwrite to machine '{machine_id}'.")
                if existing["root_value"] != root_value:
                    raise ValueError(f"Root ID '{root_id}' is already bound to path '{existing['root_value']}' on machine '{machine_id}'. Cannot silently rebind to '{root_value}'.")

            self.conn.execute("""
                INSERT INTO roots (root_id, machine_id, root_kind, root_value, label)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(root_id) DO UPDATE SET
                    machine_id=excluded.machine_id,
                    root_kind=excluded.root_kind,
                    root_value=excluded.root_value,
                    label=excluded.label
            """, (root_id, machine_id, root_kind, root_value, label))

    def get_root(self, root_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM roots WHERE root_id = ?", (root_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_roots(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM roots")
        return [dict(row) for row in cur.fetchall()]

    def create_snapshot(self, snapshot_id: str, machine_id: str, root_id: str, scan_config_hash: str, status: str) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        with self.conn:
            self.conn.execute("""
                INSERT INTO snapshots (snapshot_id, machine_id, root_id, created_at, scan_config_hash, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (snapshot_id, machine_id, root_id, now, scan_config_hash, status))

    def update_snapshot_status(self, snapshot_id: str, status: str, error_message: Optional[str] = None) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        with self.conn:
            self.conn.execute("""
                UPDATE snapshots SET status = ?, error_message = COALESCE(?, error_message), last_progress_at = ?
                WHERE snapshot_id = ?
            """, (status, error_message, now, snapshot_id))

    def update_snapshot_progress(self, snapshot_id: str, files_seen: int, dirs_seen: int, bytes_seen: int) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        with self.conn:
            self.conn.execute("""
                UPDATE snapshots SET files_seen = ?, dirs_seen = ?, bytes_seen = ?, last_progress_at = ?
                WHERE snapshot_id = ?
            """, (files_seen, dirs_seen, bytes_seen, now, snapshot_id))

    def update_snapshot_artifacts(self, snapshot_id: str, artifacts: Dict[str, str]) -> None:
        set_clauses = []
        params = []
        for key in ["inventory", "dirs", "summary", "content", "topology", "hotspots", "workspaces", "duplicates", "orphans", "disk"]:
            if key in artifacts:
                set_clauses.append(f"{key}_ref = ?")
                params.append(artifacts[key])

        if not set_clauses:
            return

        params.append(snapshot_id)
        query = f"UPDATE snapshots SET {', '.join(set_clauses)} WHERE snapshot_id = ?"
        with self.conn:
            self.conn.execute(query, params)

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_snapshots(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM snapshots ORDER BY created_at DESC, snapshot_id DESC")
        return [dict(row) for row in cur.fetchall()]

    def list_complete_snapshots(self, machine_id: Optional[str] = None, root_id: Optional[str] = None, snapshot_id: Optional[str] = None) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        query = "SELECT * FROM snapshots WHERE status = 'complete'"
        params = []

        if machine_id:
            query += " AND machine_id = ?"
            params.append(machine_id)
        if root_id:
            query += " AND root_id = ?"
            params.append(root_id)
        if snapshot_id:
            query += " AND snapshot_id = ?"
            params.append(snapshot_id)

        query += " ORDER BY created_at DESC, snapshot_id DESC"

        cur.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

    def register_delta(self, delta_id: str, from_snapshot_id: str, to_snapshot_id: str, delta_ref: str, created_at: Optional[str] = None):
        if not created_at:
            created_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
        with self.conn:
            self.conn.execute("""
                INSERT INTO deltas (delta_id, from_snapshot_id, to_snapshot_id, created_at, delta_ref)
                VALUES (?, ?, ?, ?, ?)
            """, (delta_id, from_snapshot_id, to_snapshot_id, created_at, delta_ref))

    def get_delta(self, delta_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM deltas WHERE delta_id = ?", (delta_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_deltas(self) -> List[Dict[str, Any]]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM deltas ORDER BY created_at DESC, delta_id DESC")
        return [dict(row) for row in cur.fetchall()]
