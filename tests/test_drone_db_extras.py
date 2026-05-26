"""Tests for the drone_db additions: classify(), seed/import, and migration."""

import sqlite3

import pytest

import drone_tools.drone_db as db


@pytest.fixture()
def dbpath(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(db_path=path)
    return path


# -- manufacturer_code column ----------------------------------------------


def test_add_and_get_manufacturer_code(dbpath):
    row_id = db.add_drone(manufacturer="DJI", model="Mini 4 Pro", manufacturer_code="1581", db_path=dbpath)
    d = db.get_drone(row_id, db_path=dbpath)
    assert d["manufacturer_code"] == "1581"


def test_migration_adds_column_to_legacy_db(tmp_path):
    """An old DB created without manufacturer_code gains it on next connect."""
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE drones (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "manufacturer TEXT NOT NULL, model TEXT NOT NULL, UNIQUE(manufacturer, model))"
    )
    conn.execute("INSERT INTO drones (manufacturer, model) VALUES ('DJI', 'Air 3')")
    conn.commit()
    conn.close()

    # Any public call routes through _connect -> _migrate.
    drones = db.list_drones(db_path=path)
    assert drones[0]["manufacturer_code"] is None
    # And the column now exists for writes.
    assert db.update_drone(drones[0]["id"], db_path=path, manufacturer_code="WXYZ")
    assert db.get_drone(drones[0]["id"], db_path=path)["manufacturer_code"] == "WXYZ"


# -- classify() -------------------------------------------------------------


def test_classify_by_manufacturer_code(dbpath):
    db.add_drone(manufacturer="DJI", model="Mavic 3", manufacturer_code="1581", db_path=dbpath)
    match = db.classify("1581F4F2C8A1", db_path=dbpath)
    assert match is not None
    assert match["model"] == "Mavic 3"


def test_classify_code_is_case_insensitive(dbpath):
    db.add_drone(manufacturer="DJI", model="Mavic 3", manufacturer_code="abcd", db_path=dbpath)
    assert db.classify("ABCD-123", db_path=dbpath)["model"] == "Mavic 3"


def test_classify_by_model_name_substring(dbpath):
    db.add_drone(manufacturer="DJI", model="Avata", db_path=dbpath)
    match = db.classify("operator-Avata-42", db_path=dbpath)
    assert match is not None
    assert match["model"] == "Avata"


def test_classify_prefers_model_over_manufacturer(dbpath):
    db.add_drone(manufacturer="DJI", model="Phantom", db_path=dbpath)
    db.add_drone(manufacturer="Skydio", model="X10", db_path=dbpath)
    # Serial contains both "dji" and "phantom"; the model match wins.
    match = db.classify("dji-phantom-001", db_path=dbpath)
    assert match["model"] == "Phantom"


def test_classify_short_model_does_not_match_digits(dbpath):
    # A 1-char model must not match a stray digit in an unrelated serial.
    db.add_drone(manufacturer="Skydio", model="2", db_path=dbpath)
    assert db.classify("autel-evo-123", db_path=dbpath) is None


def test_classify_none_and_no_match(dbpath):
    db.add_drone(manufacturer="DJI", model="Avata", db_path=dbpath)
    assert db.classify(None, db_path=dbpath) is None
    assert db.classify("", db_path=dbpath) is None
    assert db.classify("ZZZ-9999", db_path=dbpath) is None


# -- seed / import ----------------------------------------------------------


def test_seed_populates_and_is_idempotent(dbpath):
    imported, skipped = db.seed(db_path=dbpath)
    assert imported > 0
    assert skipped == 0
    again_imported, again_skipped = db.seed(db_path=dbpath)
    assert again_imported == 0
    assert again_skipped == imported
    assert len(db.list_drones(db_path=dbpath)) == imported


def test_seed_replace_updates_existing(dbpath):
    db.seed(db_path=dbpath)
    count = len(db.list_drones(db_path=dbpath))
    imported, skipped = db.seed(db_path=dbpath, replace=True)
    assert imported == count
    assert skipped == 0


def test_import_json_file(tmp_path, dbpath):
    src = tmp_path / "drones.json"
    src.write_text('[{"manufacturer": "XAG", "model": "P100", "num_rotors": 4, "remote_id_default": true}]')
    imported, skipped = db.import_drones(src, db_path=dbpath)
    assert (imported, skipped) == (1, 0)
    d = db.search_drones("XAG", db_path=dbpath)[0]
    assert d["num_rotors"] == 4
    assert d["remote_id_default"] == 1


def test_import_csv_coerces_types(tmp_path, dbpath):
    src = tmp_path / "drones.csv"
    src.write_text("manufacturer,model,weight_g,num_rotors,remote_id_wifi\nDJI,Neo,135,4,yes\n")
    imported, _ = db.import_drones(src, db_path=dbpath)
    assert imported == 1
    d = db.search_drones("Neo", db_path=dbpath)[0]
    assert d["weight_g"] == 135.0
    assert d["num_rotors"] == 4
    assert d["remote_id_wifi"] == 1


def test_import_skips_duplicates_without_replace(tmp_path, dbpath):
    db.add_drone(manufacturer="DJI", model="Avata", db_path=dbpath)
    src = tmp_path / "d.json"
    src.write_text('[{"manufacturer": "DJI", "model": "Avata", "weight_g": 410}]')
    imported, skipped = db.import_drones(src, db_path=dbpath)
    assert (imported, skipped) == (0, 1)
    assert db.get_drone(1, db_path=dbpath)["weight_g"] is None  # unchanged


def test_import_replace_updates_duplicate(tmp_path, dbpath):
    db.add_drone(manufacturer="DJI", model="Avata", db_path=dbpath)
    src = tmp_path / "d.json"
    src.write_text('[{"manufacturer": "DJI", "model": "Avata", "weight_g": 410}]')
    imported, skipped = db.import_drones(src, db_path=dbpath, replace=True)
    assert (imported, skipped) == (1, 0)
    assert db.get_drone(1, db_path=dbpath)["weight_g"] == 410.0


def test_import_skips_records_missing_required_fields(tmp_path, dbpath):
    src = tmp_path / "d.json"
    src.write_text('[{"manufacturer": "DJI"}, {"model": "X"}, {"manufacturer": "Autel", "model": "EVO"}]')
    imported, skipped = db.import_drones(src, db_path=dbpath)
    assert (imported, skipped) == (1, 2)


def test_import_rejects_non_list_json(tmp_path, dbpath):
    src = tmp_path / "d.json"
    src.write_text('{"manufacturer": "DJI", "model": "X"}')
    with pytest.raises(ValueError, match="list"):
        db.import_drones(src, db_path=dbpath)


# -- CLI: seed / import / identify ------------------------------------------


def test_main_seed(tmp_path, capsys):
    path = tmp_path / "cli.db"
    ret = db.main(["--db", str(path), "seed"])
    assert ret == 0
    assert "Seeded" in capsys.readouterr().out
    assert len(db.list_drones(db_path=path)) > 0


def test_main_import(tmp_path, capsys):
    path = tmp_path / "cli.db"
    src = tmp_path / "x.json"
    src.write_text('[{"manufacturer": "Parrot", "model": "Anafi"}]')
    ret = db.main(["--db", str(path), "import", str(src)])
    assert ret == 0
    assert "Imported 1 drone" in capsys.readouterr().out


def test_main_identify_hit(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "seed"])
    capsys.readouterr()
    ret = db.main(["--db", str(path), "identify", "operator-Avata-1"])
    assert ret == 0
    assert "Avata" in capsys.readouterr().out


def test_main_identify_miss(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "seed"])
    capsys.readouterr()
    ret = db.main(["--db", str(path), "identify", "ZZZ-9999", "--json"])
    assert ret == 1
    assert capsys.readouterr().out.strip() == "null"
