import json
import sqlite3

import pytest

import drone_tools.drone_db as db


@pytest.fixture()
def dbpath(tmp_path):
    """Return a fresh DB path and initialize the schema."""
    path = tmp_path / "test.db"
    db.init_db(db_path=path)
    return path


# -- Schema / init ----------------------------------------------------------


def test_init_db_creates_file(tmp_path):
    path = tmp_path / "new.db"
    result = db.init_db(db_path=path)
    assert result == path
    assert path.exists()


def test_init_db_idempotent(tmp_path):
    path = tmp_path / "new.db"
    db.init_db(db_path=path)
    db.init_db(db_path=path)  # second call should not raise
    assert path.exists()


# -- CRUD -------------------------------------------------------------------


def test_add_drone_returns_id(dbpath):
    row_id = db.add_drone(manufacturer="DJI", model="Mavic 3", db_path=dbpath)
    assert row_id >= 1


def test_add_drone_duplicate_raises(dbpath):
    db.add_drone(manufacturer="DJI", model="Mavic 3", db_path=dbpath)
    with pytest.raises(sqlite3.IntegrityError):
        db.add_drone(manufacturer="DJI", model="Mavic 3", db_path=dbpath)


def test_get_drone_returns_dict(dbpath):
    row_id = db.add_drone(
        manufacturer="DJI",
        model="Mini 4 Pro",
        drone_type="quadcopter",
        weight_g=249.0,
        num_rotors=4,
        remote_id_default=True,
        remote_id_wifi=True,
        remote_id_ble=True,
        rf_frequency_mhz="2400,5800",
        rf_protocol="OcuSync",
        notes="Sub-250g",
        db_path=dbpath,
    )
    d = db.get_drone(row_id, db_path=dbpath)
    assert d is not None
    assert d["manufacturer"] == "DJI"
    assert d["model"] == "Mini 4 Pro"
    assert d["drone_type"] == "quadcopter"
    assert d["weight_g"] == 249.0
    assert d["num_rotors"] == 4
    assert d["remote_id_default"] == 1
    assert d["remote_id_wifi"] == 1
    assert d["remote_id_ble"] == 1
    assert d["rf_frequency_mhz"] == "2400,5800"
    assert d["rf_protocol"] == "OcuSync"
    assert d["notes"] == "Sub-250g"


def test_get_drone_missing_returns_none(dbpath):
    assert db.get_drone(9999, db_path=dbpath) is None


def test_update_drone_changes_fields(dbpath):
    row_id = db.add_drone(manufacturer="DJI", model="Air 3", db_path=dbpath)
    assert db.update_drone(row_id, db_path=dbpath, weight_g=720.0, num_rotors=4)
    d = db.get_drone(row_id, db_path=dbpath)
    assert d["weight_g"] == 720.0
    assert d["num_rotors"] == 4


def test_update_drone_missing_returns_false(dbpath):
    assert db.update_drone(9999, db_path=dbpath, weight_g=100.0) is False


def test_update_drone_no_valid_fields(dbpath):
    row_id = db.add_drone(manufacturer="DJI", model="FPV", db_path=dbpath)
    assert db.update_drone(row_id, db_path=dbpath, bogus="nope") is False


def test_remove_drone_deletes(dbpath):
    row_id = db.add_drone(manufacturer="Skydio", model="X10", db_path=dbpath)
    assert db.remove_drone(row_id, db_path=dbpath) is True
    assert db.get_drone(row_id, db_path=dbpath) is None


def test_remove_drone_missing_returns_false(dbpath):
    assert db.remove_drone(9999, db_path=dbpath) is False


# -- Query ------------------------------------------------------------------


def _seed(dbpath):
    db.add_drone(
        manufacturer="DJI", model="Mavic 3", drone_type="quadcopter",
        remote_id_default=True, remote_id_wifi=True, db_path=dbpath,
    )
    db.add_drone(
        manufacturer="DJI", model="Mini 4 Pro", drone_type="quadcopter",
        remote_id_default=True, remote_id_wifi=True, remote_id_ble=True,
        db_path=dbpath,
    )
    db.add_drone(
        manufacturer="Skydio", model="X10", drone_type="quadcopter",
        remote_id_default=False, db_path=dbpath,
    )


def test_list_drones_returns_all(dbpath):
    _seed(dbpath)
    assert len(db.list_drones(db_path=dbpath)) == 3


def test_list_drones_filter_manufacturer(dbpath):
    _seed(dbpath)
    result = db.list_drones(manufacturer="DJI", db_path=dbpath)
    assert len(result) == 2
    assert all(d["manufacturer"] == "DJI" for d in result)


def test_list_drones_filter_type(dbpath):
    _seed(dbpath)
    db.add_drone(
        manufacturer="WingCopter", model="198", drone_type="vtol", db_path=dbpath,
    )
    result = db.list_drones(drone_type="vtol", db_path=dbpath)
    assert len(result) == 1


def test_list_drones_remote_id_only(dbpath):
    _seed(dbpath)
    result = db.list_drones(remote_id_only=True, db_path=dbpath)
    assert len(result) == 2
    assert all(d["remote_id_default"] == 1 for d in result)


def test_search_drones_matches_model(dbpath):
    _seed(dbpath)
    result = db.search_drones("Mini", db_path=dbpath)
    assert len(result) == 1
    assert result[0]["model"] == "Mini 4 Pro"


def test_search_drones_matches_notes(dbpath):
    db.add_drone(
        manufacturer="Autel", model="Evo II", notes="thermal camera",
        db_path=dbpath,
    )
    result = db.search_drones("thermal", db_path=dbpath)
    assert len(result) == 1


def test_search_drones_no_results(dbpath):
    _seed(dbpath)
    assert db.search_drones("nonexistent", db_path=dbpath) == []


# -- CLI --------------------------------------------------------------------


def test_main_init_creates_db(tmp_path, capsys):
    path = tmp_path / "cli.db"
    ret = db.main(["--db", str(path), "init"])
    assert ret == 0
    assert path.exists()
    assert "Database ready" in capsys.readouterr().out


def test_main_add_and_list(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "init"])
    ret = db.main([
        "--db", str(path), "add",
        "--manufacturer", "DJI", "--model", "Mavic 3",
        "--remote-id-default", "--remote-id-wifi",
    ])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Added drone #1" in out

    ret = db.main(["--db", str(path), "list"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "DJI" in out
    assert "Mavic 3" in out


def test_main_show_json(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "init"])
    db.main([
        "--db", str(path), "add",
        "--manufacturer", "Skydio", "--model", "X10",
    ])
    capsys.readouterr()  # discard prior output
    ret = db.main(["--db", str(path), "show", "1", "--json"])
    assert ret == 0
    data = json.loads(capsys.readouterr().out)
    assert data["manufacturer"] == "Skydio"


def test_main_show_not_found(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "init"])
    ret = db.main(["--db", str(path), "show", "999"])
    assert ret == 1
    assert "not found" in capsys.readouterr().err


def test_main_search(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "init"])
    db.main(["--db", str(path), "add", "--manufacturer", "DJI", "--model", "Air 3"])
    ret = db.main(["--db", str(path), "search", "Air"])
    assert ret == 0
    assert "Air 3" in capsys.readouterr().out


def test_main_update(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "init"])
    db.main(["--db", str(path), "add", "--manufacturer", "DJI", "--model", "FPV"])
    ret = db.main(["--db", str(path), "update", "1", "--weight-g", "795"])
    assert ret == 0
    assert "Updated" in capsys.readouterr().out
    d = db.get_drone(1, db_path=path)
    assert d["weight_g"] == 795.0


def test_main_remove_with_force(tmp_path, capsys):
    path = tmp_path / "cli.db"
    db.main(["--db", str(path), "init"])
    db.main(["--db", str(path), "add", "--manufacturer", "DJI", "--model", "Avata"])
    ret = db.main(["--db", str(path), "remove", "1", "--force"])
    assert ret == 0
    assert "Removed" in capsys.readouterr().out
    assert db.get_drone(1, db_path=path) is None


def test_main_no_command_returns_1(capsys):
    ret = db.main([])
    assert ret == 1
