"""CDDF drone reference database.

A SQLite-backed catalog of known drone makes and models with detection-relevant
attributes such as Remote ID support, RF frequencies, and audio signatures.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from importlib import resources
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("~/.cddf/drones.db").expanduser()

_COLUMNS = [
    "id",
    "manufacturer",
    "model",
    "manufacturer_code",
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
    manufacturer_code TEXT,
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


# Columns added after the original schema, applied to pre-existing databases on
# connect so an old ~/.cddf/drones.db keeps working without a manual rebuild.
_MIGRATIONS: dict[str, str] = {
    "manufacturer_code": "TEXT",
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Add any columns missing from an existing drones table (no-op if absent)."""
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='drones'").fetchone()
    if tables is None:
        return  # fresh DB; init_db's CREATE TABLE already has every column
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(drones)")}
    for column, decl in _MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE drones ADD COLUMN {column} {decl}")


def _connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _resolve(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    _migrate(conn)
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
    manufacturer_code: str | None = None,
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
                manufacturer, model, manufacturer_code, drone_type, weight_g, max_speed_ms,
                max_range_m, num_rotors, remote_id_default, remote_id_wifi,
                remote_id_ble, rf_frequency_mhz, rf_protocol,
                audio_freq_min_hz, audio_freq_max_hz, notes
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                manufacturer,
                model,
                manufacturer_code,
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


# Shortest normalized manufacturer/model name eligible for substring matching,
# so trivially short names (e.g. "2+") don't match stray digits in a serial.
_MIN_NAME_MATCH = 3


def _normalize(text: str) -> str:
    """Lowercase and strip non-alphanumerics for forgiving substring matching."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def classify(serial: str | None, *, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Best-effort match of a Remote ID serial number to a catalog drone.

    Two strategies are tried in order:

    1. **CTA-2063-A manufacturer code** - a compliant Remote ID serial begins
       with a four-character assigned manufacturer code; it is matched against
       the ``manufacturer_code`` column (case-insensitive).
    2. **Name embedding** - some serials embed the model or manufacturer name;
       a catalog model/manufacturer that appears within the serial matches,
       preferring the more specific model match.

    Returns the matched drone row (dict) or ``None``. This is a heuristic aid
    for enriching detections, not an authoritative identification.
    """
    if not serial:
        return None

    with _connect(db_path) as conn:
        if len(serial) >= 4:
            row = conn.execute(
                "SELECT * FROM drones WHERE manufacturer_code IS NOT NULL AND UPPER(manufacturer_code) = UPPER(?)",
                (serial[:4],),
            ).fetchone()
            if row is not None:
                return dict(row)

        norm = _normalize(serial)
        if not norm:
            return None
        rows = conn.execute("SELECT * FROM drones").fetchall()
        # Prefer a model-name hit (more specific) over a manufacturer-only hit.
        # Require >= 3 chars so short names like "2+" don't match stray digits.
        for r in rows:
            model_n = _normalize(r["model"] or "")
            if len(model_n) >= _MIN_NAME_MATCH and model_n in norm:
                return dict(r)
        for r in rows:
            man_n = _normalize(r["manufacturer"] or "")
            if len(man_n) >= _MIN_NAME_MATCH and man_n in norm:
                return dict(r)
    return None


# ---------------------------------------------------------------------------
# Bulk import / seed
# ---------------------------------------------------------------------------

# Name of the curated dataset bundled inside the package (drone_tools/data/).
_BUNDLED_DATASET = "known_drones.json"

_FLOAT_COLS = {"weight_g", "max_speed_ms", "max_range_m", "audio_freq_min_hz", "audio_freq_max_hz"}
_INT_COLS = {"num_rotors"}
_BOOL_COLS = {"remote_id_default", "remote_id_wifi", "remote_id_ble"}
_TRUE = {"1", "true", "yes", "y", "t"}


def _coerce_record(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only known columns and coerce values to their SQL types.

    Works for both JSON (already typed) and CSV (all strings). Empty strings and
    None are dropped so add_drone falls back to its defaults.
    """
    allowed = set(_COLUMNS) - {"id"}
    out: dict[str, Any] = {}
    for key, value in record.items():
        if key not in allowed or value is None or value == "":
            continue
        if key in _BOOL_COLS:
            out[key] = value if isinstance(value, bool) else str(value).strip().lower() in _TRUE
        elif key in _FLOAT_COLS:
            out[key] = float(value)
        elif key in _INT_COLS:
            out[key] = int(value)
        else:
            out[key] = value
    return out


def _load_records(source: str | Path) -> list[dict[str, Any]]:
    """Read drone records from a .json (list of objects) or .csv (header row) file."""
    path = Path(source)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        return list(csv.DictReader(text.splitlines()))
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON import file must contain a list of drone objects")
    return data


def import_records(
    records: list[dict[str, Any]],
    *,
    db_path: str | Path | None = None,
    replace: bool = False,
) -> tuple[int, int]:
    """Insert drone records. Returns ``(imported, skipped)``.

    A record duplicating an existing (manufacturer, model) is skipped unless
    ``replace`` is set, in which case its row is updated in place. Records
    missing manufacturer or model are skipped.
    """
    imported = skipped = 0
    init_db(db_path=db_path)
    for raw in records:
        fields = _coerce_record(raw)
        if not fields.get("manufacturer") or not fields.get("model"):
            skipped += 1
            continue
        try:
            add_drone(db_path=db_path, **fields)
            imported += 1
        except sqlite3.IntegrityError:
            if not replace:
                skipped += 1
                continue
            with _connect(db_path) as conn:
                row = conn.execute(
                    "SELECT id FROM drones WHERE manufacturer = ? AND model = ?",
                    (fields["manufacturer"], fields["model"]),
                ).fetchone()
            if row is not None and update_drone(int(row["id"]), db_path=db_path, **fields):
                imported += 1
            else:
                skipped += 1
    return imported, skipped


def import_drones(source: str | Path, *, db_path: str | Path | None = None, replace: bool = False) -> tuple[int, int]:
    """Import drones from a JSON or CSV file. Returns ``(imported, skipped)``."""
    return import_records(_load_records(source), db_path=db_path, replace=replace)


def seed(*, db_path: str | Path | None = None, replace: bool = False) -> tuple[int, int]:
    """Populate the catalog from the dataset bundled with the package."""
    text = resources.files("drone_tools").joinpath("data").joinpath(_BUNDLED_DATASET).read_text(encoding="utf-8")
    return import_records(json.loads(text), db_path=db_path, replace=replace)


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

    # seed
    p_seed = sub.add_parser("seed", help="Populate the catalog from the bundled dataset")
    p_seed.add_argument("--replace", action="store_true", help="Update existing rows instead of skipping them")

    # import
    p_import = sub.add_parser("import", help="Import drones from a JSON or CSV file")
    p_import.add_argument("file", help="Path to a .json (list of objects) or .csv (header row) file")
    p_import.add_argument("--replace", action="store_true", help="Update existing rows instead of skipping them")

    # add
    p_add = sub.add_parser("add", help="Add a drone to the catalog")
    p_add.add_argument("--manufacturer", required=True)
    p_add.add_argument("--model", required=True)
    p_add.add_argument("--manufacturer-code", help="CTA-2063-A 4-char Remote ID manufacturer code")
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

    # identify
    p_ident = sub.add_parser("identify", help="Match a Remote ID serial to a catalog drone")
    p_ident.add_argument("serial", help="Remote ID serial / UAS ID to classify")
    p_ident.add_argument("--json", action="store_true")

    # show
    p_show = sub.add_parser("show", help="Show a drone by ID")
    p_show.add_argument("id", type=int)
    p_show.add_argument("--json", action="store_true")

    # update
    p_upd = sub.add_parser("update", help="Update a drone")
    p_upd.add_argument("id", type=int)
    p_upd.add_argument("--manufacturer")
    p_upd.add_argument("--model")
    p_upd.add_argument("--manufacturer-code")
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

        elif args.command == "seed":
            imported, skipped = seed(db_path=db, replace=args.replace)
            print(f"Seeded {imported} drone(s) from the bundled dataset ({skipped} skipped).")

        elif args.command == "import":
            imported, skipped = import_drones(args.file, db_path=db, replace=args.replace)
            print(f"Imported {imported} drone(s) from {args.file} ({skipped} skipped).")

        elif args.command == "add":
            init_db(db_path=db)
            row_id = add_drone(
                manufacturer=args.manufacturer,
                model=args.model,
                manufacturer_code=args.manufacturer_code,
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

        elif args.command == "identify":
            init_db(db_path=db)
            match = classify(args.serial, db_path=db)
            if match is None:
                if args.json:
                    print("null")
                else:
                    print(f"No catalog match for serial {args.serial!r}.")
                return 1
            _print_drone(match, as_json=args.json)

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
                "manufacturer_code",
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
