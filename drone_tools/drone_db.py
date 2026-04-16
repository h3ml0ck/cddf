"""CDDF drone reference database.

A SQLite-backed catalog of known drone makes and models with detection-relevant
attributes such as Remote ID support, RF frequencies, and audio signatures.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("~/.cddf/drones.db").expanduser()

_COLUMNS = [
    "id",
    "manufacturer",
    "model",
    "drone_type",
    "weight_g",
    "max_speed_ms",
    "max_range_m",
    "num_rotors",
    "remote_id_default",
    "remote_id_wifi",
    "remote_id_ble",
    "rf_frequency_mhz",
    "rf_protocol",
    "audio_freq_min_hz",
    "audio_freq_max_hz",
    "notes",
]

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS drones (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    manufacturer      TEXT    NOT NULL,
    model             TEXT    NOT NULL,
    drone_type        TEXT,
    weight_g          REAL,
    max_speed_ms      REAL,
    max_range_m       REAL,
    num_rotors        INTEGER,
    remote_id_default INTEGER DEFAULT 0,
    remote_id_wifi    INTEGER DEFAULT 0,
    remote_id_ble     INTEGER DEFAULT 0,
    rf_frequency_mhz  TEXT,
    rf_protocol       TEXT,
    audio_freq_min_hz REAL,
    audio_freq_max_hz REAL,
    notes             TEXT,
    UNIQUE(manufacturer, model)
);
"""


def _resolve(db_path: str | Path | None) -> Path:
    return Path(db_path) if db_path is not None else DEFAULT_DB_PATH


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _resolve(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db(db_path: str | Path | None = None) -> Path:
    """Create the database file and schema if they don't exist."""
    path = _resolve(db_path)
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
    return path


def add_drone(
    *,
    manufacturer: str,
    model: str,
    drone_type: str | None = None,
    weight_g: float | None = None,
    max_speed_ms: float | None = None,
    max_range_m: float | None = None,
    num_rotors: int | None = None,
    remote_id_default: bool = False,
    remote_id_wifi: bool = False,
    remote_id_ble: bool = False,
    rf_frequency_mhz: str | None = None,
    rf_protocol: str | None = None,
    audio_freq_min_hz: float | None = None,
    audio_freq_max_hz: float | None = None,
    notes: str | None = None,
    db_path: str | Path | None = None,
) -> int:
    """Insert a drone into the catalog. Returns the new row id."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            """\
            INSERT INTO drones (
                manufacturer, model, drone_type, weight_g, max_speed_ms,
                max_range_m, num_rotors, remote_id_default, remote_id_wifi,
                remote_id_ble, rf_frequency_mhz, rf_protocol,
                audio_freq_min_hz, audio_freq_max_hz, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                manufacturer,
                model,
                drone_type,
                weight_g,
                max_speed_ms,
                max_range_m,
                num_rotors,
                int(remote_id_default),
                int(remote_id_wifi),
                int(remote_id_ble),
                rf_frequency_mhz,
                rf_protocol,
                audio_freq_min_hz,
                audio_freq_max_hz,
                notes,
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]


def get_drone(drone_id: int, *, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Fetch a single drone by id."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM drones WHERE id = ?", (drone_id,)).fetchone()
    return _row_to_dict(row)


def update_drone(drone_id: int, *, db_path: str | Path | None = None, **fields: Any) -> bool:
    """Update fields on an existing drone. Returns True if the row existed."""
    valid = {k: v for k, v in fields.items() if k in _COLUMNS and k != "id"}
    if not valid:
        return False
    # Convert booleans to int for the three Remote ID flags
    for flag in ("remote_id_default", "remote_id_wifi", "remote_id_ble"):
        if flag in valid:
            valid[flag] = int(valid[flag])
    set_clause = ", ".join(f"{col} = ?" for col in valid)
    values = list(valid.values()) + [drone_id]
    with _connect(db_path) as conn:
        cur = conn.execute(f"UPDATE drones SET {set_clause} WHERE id = ?", values)
        return cur.rowcount > 0


def remove_drone(drone_id: int, *, db_path: str | Path | None = None) -> bool:
    """Delete a drone by id. Returns True if the row existed."""
    with _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM drones WHERE id = ?", (drone_id,))
        return cur.rowcount > 0


def list_drones(
    *,
    manufacturer: str | None = None,
    drone_type: str | None = None,
    remote_id_only: bool = False,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """List drones with optional filters."""
    clauses: list[str] = []
    params: list[Any] = []
    if manufacturer is not None:
        clauses.append("manufacturer = ?")
        params.append(manufacturer)
    if drone_type is not None:
        clauses.append("drone_type = ?")
        params.append(drone_type)
    if remote_id_only:
        clauses.append("remote_id_default = 1")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connect(db_path) as conn:
        rows = conn.execute(f"SELECT * FROM drones{where}", params).fetchall()
    return [dict(r) for r in rows]


def search_drones(query: str, *, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Search across manufacturer, model, drone_type, rf_protocol, and notes."""
    pattern = f"%{query}%"
    with _connect(db_path) as conn:
        rows = conn.execute(
            """\
            SELECT * FROM drones
            WHERE manufacturer LIKE ? OR model LIKE ? OR drone_type LIKE ?
                  OR rf_protocol LIKE ? OR notes LIKE ?
            """,
            (pattern, pattern, pattern, pattern, pattern),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _print_drone(d: dict[str, Any], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(d))
        return
    print(f"[{d['id']}] {d['manufacturer']} {d['model']}")
    for key in _COLUMNS:
        if key in ("id", "manufacturer", "model"):
            continue
        val = d.get(key)
        if val is not None:
            label = key.replace("_", " ").title()
            if key.startswith("remote_id"):
                val = "Yes" if val else "No"
            print(f"  {label}: {val}")


def _print_table(drones: list[dict[str, Any]], as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(drones))
        return
    if not drones:
        print("No drones found.")
        return
    for d in drones:
        rid = []
        if d.get("remote_id_wifi"):
            rid.append("WiFi")
        if d.get("remote_id_ble"):
            rid.append("BLE")
        rid_str = ",".join(rid) if rid else "-"
        rid_default = "Yes" if d.get("remote_id_default") else "No"
        print(f"  {d['id']:>4}  {d['manufacturer']:<16} {d['model']:<24} RID: {rid_default:<4} ({rid_str})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the CDDF drone reference database")
    parser.add_argument("--db", default=None, help="Path to database file")
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Create/verify the database")

    # add
    p_add = sub.add_parser("add", help="Add a drone to the catalog")
    p_add.add_argument("--manufacturer", required=True)
    p_add.add_argument("--model", required=True)
    p_add.add_argument("--type", dest="drone_type")
    p_add.add_argument("--weight-g", type=float)
    p_add.add_argument("--max-speed-ms", type=float)
    p_add.add_argument("--max-range-m", type=float)
    p_add.add_argument("--num-rotors", type=int)
    p_add.add_argument("--remote-id-default", action="store_true")
    p_add.add_argument("--remote-id-wifi", action="store_true")
    p_add.add_argument("--remote-id-ble", action="store_true")
    p_add.add_argument("--rf-frequency-mhz")
    p_add.add_argument("--rf-protocol")
    p_add.add_argument("--audio-freq-min-hz", type=float)
    p_add.add_argument("--audio-freq-max-hz", type=float)
    p_add.add_argument("--notes")

    # list
    p_list = sub.add_parser("list", help="List drones")
    p_list.add_argument("--manufacturer")
    p_list.add_argument("--type", dest="drone_type")
    p_list.add_argument("--remote-id-only", action="store_true")
    p_list.add_argument("--json", action="store_true")

    # search
    p_search = sub.add_parser("search", help="Search drones")
    p_search.add_argument("query")
    p_search.add_argument("--json", action="store_true")

    # show
    p_show = sub.add_parser("show", help="Show a drone by ID")
    p_show.add_argument("id", type=int)
    p_show.add_argument("--json", action="store_true")

    # update
    p_upd = sub.add_parser("update", help="Update a drone")
    p_upd.add_argument("id", type=int)
    p_upd.add_argument("--manufacturer")
    p_upd.add_argument("--model")
    p_upd.add_argument("--type", dest="drone_type")
    p_upd.add_argument("--weight-g", type=float)
    p_upd.add_argument("--max-speed-ms", type=float)
    p_upd.add_argument("--max-range-m", type=float)
    p_upd.add_argument("--num-rotors", type=int)
    p_upd.add_argument("--remote-id-default", action="store_true", default=None)
    p_upd.add_argument("--remote-id-wifi", action="store_true", default=None)
    p_upd.add_argument("--remote-id-ble", action="store_true", default=None)
    p_upd.add_argument("--rf-frequency-mhz")
    p_upd.add_argument("--rf-protocol")
    p_upd.add_argument("--audio-freq-min-hz", type=float)
    p_upd.add_argument("--audio-freq-max-hz", type=float)
    p_upd.add_argument("--notes")

    # remove
    p_rm = sub.add_parser("remove", help="Remove a drone by ID")
    p_rm.add_argument("id", type=int)
    p_rm.add_argument("--force", action="store_true", help="Skip confirmation")

    args = parser.parse_args(argv)
    db = args.db

    if args.command is None:
        parser.print_help()
        return 1

    try:
        if args.command == "init":
            path = init_db(db_path=db)
            print(f"Database ready at {path}")

        elif args.command == "add":
            init_db(db_path=db)
            row_id = add_drone(
                manufacturer=args.manufacturer,
                model=args.model,
                drone_type=args.drone_type,
                weight_g=args.weight_g,
                max_speed_ms=args.max_speed_ms,
                max_range_m=args.max_range_m,
                num_rotors=args.num_rotors,
                remote_id_default=args.remote_id_default,
                remote_id_wifi=args.remote_id_wifi,
                remote_id_ble=args.remote_id_ble,
                rf_frequency_mhz=args.rf_frequency_mhz,
                rf_protocol=args.rf_protocol,
                audio_freq_min_hz=args.audio_freq_min_hz,
                audio_freq_max_hz=args.audio_freq_max_hz,
                notes=args.notes,
                db_path=db,
            )
            print(f"Added drone #{row_id}: {args.manufacturer} {args.model}")

        elif args.command == "list":
            init_db(db_path=db)
            drones = list_drones(
                manufacturer=args.manufacturer,
                drone_type=args.drone_type,
                remote_id_only=args.remote_id_only,
                db_path=db,
            )
            _print_table(drones, as_json=args.json)

        elif args.command == "search":
            init_db(db_path=db)
            drones = search_drones(args.query, db_path=db)
            _print_table(drones, as_json=args.json)

        elif args.command == "show":
            init_db(db_path=db)
            d = get_drone(args.id, db_path=db)
            if d is None:
                print(f"Drone #{args.id} not found.", file=sys.stderr)
                return 1
            _print_drone(d, as_json=args.json)

        elif args.command == "update":
            init_db(db_path=db)
            fields: dict[str, Any] = {}
            for key in (
                "manufacturer",
                "model",
                "drone_type",
                "weight_g",
                "max_speed_ms",
                "max_range_m",
                "num_rotors",
                "remote_id_default",
                "remote_id_wifi",
                "remote_id_ble",
                "rf_frequency_mhz",
                "rf_protocol",
                "audio_freq_min_hz",
                "audio_freq_max_hz",
                "notes",
            ):
                val = getattr(args, key, None)
                if val is not None:
                    fields[key] = val
            if not fields:
                print("No fields to update.", file=sys.stderr)
                return 1
            if update_drone(args.id, db_path=db, **fields):
                print(f"Updated drone #{args.id}.")
            else:
                print(f"Drone #{args.id} not found.", file=sys.stderr)
                return 1

        elif args.command == "remove":
            init_db(db_path=db)
            if not args.force:
                d = get_drone(args.id, db_path=db)
                if d is None:
                    print(f"Drone #{args.id} not found.", file=sys.stderr)
                    return 1
                answer = input(f"Remove {d['manufacturer']} {d['model']} (#{args.id})? [y/N] ")
                if answer.lower() != "y":
                    print("Cancelled.")
                    return 0
            if remove_drone(args.id, db_path=db):
                print(f"Removed drone #{args.id}.")
            else:
                print(f"Drone #{args.id} not found.", file=sys.stderr)
                return 1

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
