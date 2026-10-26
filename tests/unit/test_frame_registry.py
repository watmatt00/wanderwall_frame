"""
Unit tests: the frame album registry (PL-147 follow-up) — each frame's list of
the albums it owns, kept locally and in the cloud (.picframe/frames/<serial>.yaml),
through deletes, reinstalls, SD card moves and takeovers. The cloud is faked.
"""

import asyncio
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from src.api.app import app
from src.services import frame_registry as reg
from src.services import source_manager as sm
from src.services.source_manager import PhotoSource, SourceManager
from src.utils.rclone import RcloneResult

LAN = ("192.168.1.50", 50000)
TK = "1000000002343a2b"     # tkframe's board
NEW = "10000000abcd1234"    # a replacement board
KF = "10000000aaaa0001"     # kframe


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    """A fake Koofr account (remote "kfr"), a temp registry and albums, on board TK."""
    state = SimpleNamespace(files={}, dirs=["Documents"], board=TK, upload_ok=True, user="me@example.com")

    async def list_files(remote):
        prefix = remote.rstrip("/") + "/"
        return [p[len(prefix):] for p in state.files if p.startswith(prefix)]

    async def cat(remote_file, max_bytes=1024 * 1024):
        return state.files.get(remote_file)

    async def copyto(local_file, remote_dest):
        if not state.upload_ok:
            return RcloneResult(success=False, error="network down")
        state.files[remote_dest] = local_file.read_bytes()
        return RcloneResult(success=True)

    async def list_dirs(remote):
        return list(state.dirs)

    async def koofr():
        return "kfr"

    async def koofr_user(remote):
        return state.user

    monkeypatch.setattr(reg, "rclone_list_files", list_files)
    monkeypatch.setattr(reg, "rclone_cat", cat)
    monkeypatch.setattr(reg, "rclone_copyto", copyto)
    monkeypatch.setattr(reg, "rclone_list_dirs", list_dirs)
    monkeypatch.setattr(reg, "_koofr_remote", koofr)
    monkeypatch.setattr(reg, "_koofr_user", koofr_user)
    monkeypatch.setattr(reg, "board_serial", lambda: state.board)
    monkeypatch.setattr(reg, "get_settings", lambda: SimpleNamespace(frame=SimpleNamespace(name="tkframe")))
    monkeypatch.setattr(reg, "LOCAL_PATH", tmp_path / "frame_albums.yaml")
    monkeypatch.setattr(reg, "LEGACY_DELETED_PATH", tmp_path / "deleted_albums.yaml")
    monkeypatch.setattr(reg, "_loop", None)
    monkeypatch.setattr(reg, "_schedule", lambda coro: coro.close())  # push explicitly in tests

    manager = SourceManager(tmp_path / "sources.yaml")
    manager.add_listener(reg.note_change)
    monkeypatch.setattr(sm, "source_manager", manager)
    state.manager = manager
    state.tmp = tmp_path
    return state


def _add(cloud, sid, name=None):
    cloud.manager._save_sources(cloud.manager.list_sources() + [
        PhotoSource(id=sid, name=name or sid.title(), local_path=str(cloud.tmp / sid), rclone_remote=f"kfr:KFR_{sid}"),
    ])
    if f"KFR_{sid}" not in cloud.dirs:
        cloud.dirs.append(f"KFR_{sid}")


def _remove(cloud, sid):
    cloud.manager._save_sources([s for s in cloud.manager.list_sources() if s.id != sid])


def _cloud_doc(cloud, serial):
    return yaml.safe_load(cloud.files[f"kfr:.picframe/frames/{serial}.yaml"])


def _put_frame(cloud, serial, name, albums, last_seen="2020-01-01T00:00:00+00:00", **extra):
    doc = {"serial": serial, "frame_name": name, "last_seen": last_seen, "albums": albums, **extra}
    cloud.files[f"kfr:.picframe/frames/{serial}.yaml"] = yaml.safe_dump(doc).encode()
    for a in albums:
        if a["folder"] not in cloud.dirs:
            cloud.dirs.append(a["folder"])


def _statuses(doc):
    return {a["folder"]: a["status"] for a in doc["albums"]}


def _start():
    async def run():
        reg.start()
    asyncio.run(run())


# --- Local list ----------------------------------------------------------------

def test_albums_are_marked_deleted_never_removed(cloud):
    _add(cloud, "trip")
    _add(cloud, "kids")
    _remove(cloud, "trip")
    assert _statuses(reg.local_doc()) == {"KFR_trip": "deleted", "KFR_kids": "active"}
    assert reg.local_doc()["albums"][0]["deleted_at"]
    _add(cloud, "trip")
    assert _statuses(reg.local_doc()) == {"KFR_trip": "active", "KFR_kids": "active"}
    assert (reg.LOCAL_PATH.stat().st_mode & 0o777) == 0o600


def test_legacy_deletions_are_folded_in(cloud):
    reg.LEGACY_DELETED_PATH.write_text(yaml.safe_dump({"albums": [
        {"id": "old", "name": "Old", "rclone_remote": "koofr:KFR_old", "deleted_at": "2026-10-18T10:00:00+00:00"},
        {"id": "bad", "name": "Bad", "rclone_remote": "koofr:Documents"},
    ]}))
    doc = reg.local_doc()
    assert doc["serial"] == TK
    assert doc["albums"] == [{"folder": "KFR_old", "name": "Old", "status": "deleted",
                              "deleted_at": "2026-10-18T10:00:00+00:00"}]


def test_board_serial_from_cpuinfo(tmp_path, monkeypatch):
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text("processor\t: 0\nSerial\t\t: 1000000002343A2B\nModel\t: Raspberry Pi\n")
    monkeypatch.setattr(reg, "SERIAL_SOURCES", (tmp_path / "missing", cpuinfo))
    assert reg.board_serial() == TK


# --- Cloud copy and account --------------------------------------------------------

def test_first_push_on_shared_account(cloud):
    cloud.dirs.append("KFR_kframe")  # another frame's folder, from before the registry
    _add(cloud, "trip")
    assert asyncio.run(reg.push()) is True
    doc = _cloud_doc(cloud, TK)
    assert doc["account"] == "shared" and doc["frame_name"] == "tkframe" and doc["last_seen"]
    assert doc["albums"] == [{"folder": "KFR_trip", "name": "Trip", "status": "active"}]
    assert "pending_swap" not in doc and "last_pushed" not in doc  # local-only fields stay local
    assert reg.local_doc()["last_pushed"]


def test_first_push_on_fresh_account_is_dedicated(cloud):
    _add(cloud, "trip")
    asyncio.run(reg.push())
    assert _cloud_doc(cloud, TK)["account"] == "dedicated"
    # Stays dedicated once decided, even with folders appearing later
    cloud.dirs.append("KFR_stray")
    asyncio.run(reg.push())
    assert _cloud_doc(cloud, TK)["account"] == "dedicated"


def test_dedicated_counts_as_shared_once_another_frame_appears(cloud):
    _add(cloud, "trip")
    asyncio.run(reg.push())
    cloud.dirs.append("KFR_stray")
    assert asyncio.run(reg.cloud_view())["dedicated"] is True
    _put_frame(cloud, KF, "kframe", [{"folder": "KFR_kframe", "name": "Home", "status": "active"}])
    view = asyncio.run(reg.cloud_view())
    assert view["dedicated"] is False
    assert [u["folder"] for u in view["unclaimed"]] == ["KFR_stray"]  # KFR_kframe is claimed


def test_reinstall_gets_albums_back_from_cloud(cloud):
    _put_frame(cloud, TK, "tkframe", [
        {"folder": "KFR_tkf1", "name": "tkf1", "status": "active"},
        {"folder": "KFR_heic", "name": "Heic1", "status": "deleted", "deleted_at": "2026-10-01T00:00:00+00:00"},
    ], account="shared")
    # Fresh SD card: no local list, no albums
    assert asyncio.run(reg.push()) is True
    view = asyncio.run(reg.cloud_view())
    assert [(m["folder"], m["name"]) for m in view["mine"]] == [("KFR_heic", "Heic1"), ("KFR_tkf1", "tkf1")]
    assert _statuses(_cloud_doc(cloud, TK)) == {"KFR_tkf1": "deleted", "KFR_heic": "deleted"}
    assert reg.local_doc()["account"] == "shared"


def test_upload_failure_is_retried_later(cloud):
    cloud.upload_ok = False
    _add(cloud, "trip")
    assert asyncio.run(reg.push()) is False
    assert reg.local_doc()["last_pushed"] is None
    cloud.upload_ok = True
    assert asyncio.run(reg.push()) is True


# --- SD card moved to another Pi -------------------------------------------------------

def _tkframe_with_history(cloud):
    _add(cloud, "tkf1")
    _add(cloud, "heic", "Heic1")
    _remove(cloud, "heic")
    asyncio.run(reg.push())
    cloud.board = NEW


def test_card_moved_asks_then_keeps_albums(cloud):
    _tkframe_with_history(cloud)
    _start()
    assert reg.banner()["pending_swap"] == "…343a2b"
    assert asyncio.run(reg.push()) is False  # nothing written until answered

    result = asyncio.run(reg.resolve_swap(moved=True))
    assert result["cloud_updated"] is True
    assert reg.banner()["pending_swap"] is None
    assert _statuses(_cloud_doc(cloud, NEW)) == {"KFR_tkf1": "active", "KFR_heic": "deleted"}
    old = _cloud_doc(cloud, TK)
    assert old["replaced_by"] == NEW and old["replaced_at"]
    assert reg.local_doc()["pending_replace"] == []
    # The old board's file no longer counts as another frame
    view = asyncio.run(reg.cloud_view())
    assert view["frames"] == [] and [m["folder"] for m in view["mine"]] == ["KFR_heic"]


def test_card_copied_starts_a_new_frame(cloud):
    _tkframe_with_history(cloud)
    _start()
    asyncio.run(reg.resolve_swap(moved=False))
    assert _statuses(_cloud_doc(cloud, NEW)) == {"KFR_tkf1": "active"}  # the original keeps Heic1
    assert _cloud_doc(cloud, NEW)["account"] == "shared"
    assert _cloud_doc(cloud, TK).get("replaced_by") is None
    view = asyncio.run(reg.cloud_view())
    assert view["mine"] == [] and view["unclaimed"] == []  # KFR_heic is the original's
    assert [f["frame_name"] for f in view["frames"]] == ["tkframe"]


def test_card_back_on_its_board_clears_the_question(cloud):
    _tkframe_with_history(cloud)
    _start()
    cloud.board = TK
    _start()
    assert reg.banner()["pending_swap"] is None


def test_swap_answer_without_a_move_is_refused(cloud):
    with pytest.raises(reg.RegistryError):
        asyncio.run(reg.resolve_swap(moved=True))


# --- Takeover (new board, fresh SD card) ---------------------------------------------------

def test_takeover_of_recent_frame_needs_its_name(cloud):
    now = reg._now()
    _put_frame(cloud, KF, "kframe", [{"folder": "KFR_home", "name": "Home", "status": "deleted"}], last_seen=now)
    with pytest.raises(reg.RegistryError, match="Type its name"):
        asyncio.run(reg.take_over(KF, ""))
    assert _cloud_doc(cloud, KF).get("replaced_by") is None
    result = asyncio.run(reg.take_over(KF, " KFrame "))
    assert result == {"frame_name": "kframe", "albums_added": 1, "cloud_updated": True}
    assert _cloud_doc(cloud, KF)["replaced_by"] == TK
    assert [m["folder"] for m in asyncio.run(reg.cloud_view())["mine"]] == ["KFR_home"]


def test_takeover_of_old_frame_needs_no_name(cloud):
    _put_frame(cloud, KF, "kframe", [{"folder": "KFR_home", "name": "Home", "status": "active"}])
    assert asyncio.run(reg.take_over(KF))["albums_added"] == 1
    with pytest.raises(reg.RegistryError, match="already taken over"):
        asyncio.run(reg.take_over(KF))


@pytest.mark.parametrize("serial", [TK, "../etc", "ffff0000ffff0000"])
def test_takeover_refuses_self_invalid_or_unknown(cloud, serial):
    with pytest.raises(reg.RegistryError):
        asyncio.run(reg.take_over(serial, "x"))


def test_taken_over_frame_sees_banner_and_can_undo(cloud):
    _add(cloud, "trip")
    asyncio.run(reg.push())
    doc = _cloud_doc(cloud, TK)
    doc.update(replaced_by=NEW, replaced_at="2026-10-19T12:00:00+00:00")
    cloud.files[f"kfr:.picframe/frames/{TK}.yaml"] = yaml.safe_dump(doc).encode()

    asyncio.run(reg.push())
    assert reg.banner() == {"pending_swap": None, "replaced_by": "…" + NEW[-6:],
                            "replaced_at": "2026-10-19T12:00:00+00:00"}
    assert asyncio.run(reg.undo_takeover()) == {"undone": "…" + NEW[-6:]}
    assert _cloud_doc(cloud, TK)["replaced_by"] is None
    asyncio.run(reg.push())  # not re-adopted from the cloud
    assert reg.banner()["replaced_by"] is None


# --- Dashboard routes ------------------------------------------------------------------

def test_routes(cloud):
    client = TestClient(app, client=LAN)
    assert client.post("/api/albums/frame-swap", json={"moved": True}).json()["ok"] is False
    _put_frame(cloud, KF, "kframe", [{"folder": "KFR_home", "name": "Home", "status": "deleted"}])
    r = client.post("/api/albums/take-over", json={"serial": KF})
    assert r.json()["ok"] is True
    assert client.post("/api/albums/undo-takeover").json() == {"ok": False, "error": "This frame hasn't been taken over."}
    assert client.get("/dashboard/status").json()["registry"]["pending_swap"] is None


@pytest.mark.parametrize("path", ["/api/albums/frame-swap", "/api/albums/take-over", "/api/albums/undo-takeover"])
def test_routes_are_lan_only(cloud, path):
    r = TestClient(app, client=("8.8.8.8", 50000)).post(path, json={"moved": True, "serial": KF})
    assert r.status_code == 403


# --- Koofr account change ------------------------------------------------------------

def _new_account(cloud, user="apple@example.com"):
    """Point the frame at an empty Koofr account."""
    cloud.files.clear()
    cloud.dirs[:] = ["My documents"]
    cloud.user = user


def test_new_account_starts_a_fresh_list(cloud):
    _add(cloud, "trip")
    _add(cloud, "kids")
    _remove(cloud, "trip")
    assert asyncio.run(reg.push()) is True
    assert reg.local_doc()["koofr_user"] == "me@example.com"

    _new_account(cloud)
    _add(cloud, "demo")  # the push from this change is dropped in tests; push below
    assert asyncio.run(reg.push()) is True
    doc = reg.local_doc()
    assert _statuses(doc) == {"KFR_kids": "active", "KFR_demo": "active"}
    assert doc["koofr_user"] == "apple@example.com"
    assert doc["account"] == "dedicated"  # decided again: every KFR_* on the new account is this frame's
    cloud_doc = _cloud_doc(cloud, TK)
    assert cloud_doc["koofr_user"] == "apple@example.com"
    assert "KFR_trip" not in _statuses(cloud_doc)


def test_old_list_copied_to_the_new_account_is_replaced(cloud):
    """tkframe 2026-10-26: switched account before koofr_user existed; its old list was pushed to the new account."""
    reg.LOCAL_PATH.write_text(yaml.safe_dump({
        "serial": TK, "frame_name": "tkframe", "account": "shared",
        "albums": [{"folder": "KFR_tkf1", "name": "tkf1", "status": "deleted"},
                   {"folder": "KFR_heic", "name": "Heic1", "status": "deleted"}],
    }))
    _new_account(cloud)
    _put_frame(cloud, TK, "tkframe", [{"folder": "KFR_tkf1", "name": "tkf1", "status": "deleted"}],
               account="shared")
    cloud.dirs.remove("KFR_tkf1")  # _put_frame adds the folder; it's on the old account only
    _add(cloud, "tester")
    assert asyncio.run(reg.push()) is True
    doc = reg.local_doc()
    assert _statuses(doc) == {"KFR_tester": "active"}
    assert doc["account"] == "dedicated"
    assert doc["koofr_user"] == "apple@example.com"
    assert _statuses(_cloud_doc(cloud, TK)) == {"KFR_tester": "active"}


def test_old_list_on_the_same_account_is_kept(cloud):
    """A frame from before koofr_user (kframe): deleted albums' folders are still there, so keep the list."""
    reg.LOCAL_PATH.write_text(yaml.safe_dump({
        "serial": TK, "frame_name": "tkframe", "account": "shared",
        "albums": [{"folder": "KFR_old", "name": "Old", "status": "deleted"}],
    }))
    cloud.dirs.append("KFR_old")
    _add(cloud, "trip")
    assert asyncio.run(reg.push()) is True
    doc = reg.local_doc()
    assert _statuses(doc) == {"KFR_old": "deleted", "KFR_trip": "active"}
    assert doc["account"] == "shared"
    assert doc["koofr_user"] == "me@example.com"


def test_unreadable_login_changes_nothing_and_login_is_normalised(cloud):
    _add(cloud, "trip")
    _remove(cloud, "trip")
    assert asyncio.run(reg.push()) is True
    cloud.user = None  # login unreadable: no change
    assert asyncio.run(reg.push()) is True
    doc = reg.local_doc()
    assert doc["koofr_user"] == "me@example.com"
    assert _statuses(doc) == {"KFR_trip": "deleted"}
    assert reg._parse_doc("koofr_user: ' Me@Example.com '")["koofr_user"] == "me@example.com"


def test_unlistable_cloud_skips_the_push(cloud, monkeypatch):
    reg.LOCAL_PATH.write_text(yaml.safe_dump({
        "serial": TK, "albums": [{"folder": "KFR_old", "name": "Old", "status": "deleted"}],
    }))

    async def no_dirs(remote):
        return None

    monkeypatch.setattr(reg, "rclone_list_dirs", no_dirs)
    assert asyncio.run(reg.push()) is False
    assert _statuses(reg.local_doc()) == {"KFR_old": "deleted"}
