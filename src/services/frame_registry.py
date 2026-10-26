"""
WanderWall - Frame album registry (PL-147 follow-up).

Each frame keeps a list of the albums it owns: every cloud folder (KFR_*) it
has used, active or deleted. Recover Albums uses it to tell this frame's
folders apart from other frames' when several frames share one Koofr account.

- Local copy:  ~/.wanderwall/frame_albums.yaml
- Cloud copy:  <koofr remote>:.picframe/frames/<pi-serial>.yaml — outside the
  KFR_* folders, so sync, photo counts and the traffic light never see it

Rules:
- Each frame writes only its own cloud file. The one exception is a takeover,
  which sets `replaced_by` on the old frame's file.
- Entries are never removed, only marked deleted, so a freshly reinstalled
  frame can't wipe its own history.
- Identity is the Pi's board serial, which survives reflashing. When the SD
  card moves to another Pi, the serial in the local copy no longer matches the
  board, and the dashboard asks once whether the card was moved or copied.
- The account is marked `dedicated` only when the frame first claims it and
  every KFR_* folder there is its own; otherwise `shared`. A dedicated
  account counts as shared again as soon as another frame's file appears.
- The list belongs to one Koofr account (`koofr_user`). When the frame is
  moved to another account (Save & Verify with a new login), the next push
  starts a fresh list with only the albums on the frame and decides the
  account again; the old account's history stays in its own cloud file.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Coroutine, Optional

import yaml
from filelock import FileLock

from src.config.settings import get_settings
from src.services import source_manager as sources
from src.services.source_manager import PhotoSource, find_koofr_remote
from src.utils.rclone import rclone_cat, rclone_copyto, rclone_list_dirs, rclone_list_files

logger = logging.getLogger(__name__)

LOCAL_PATH = Path.home() / ".wanderwall" / "frame_albums.yaml"
# Written by Delete Album before the registry existed; folded in once (fb27b58)
LEGACY_DELETED_PATH = Path.home() / ".wanderwall" / "deleted_albums.yaml"
# Kept from v4: the Koofr account is shared by all frames, so this cloud path can't follow the rename
CLOUD_DIR = ".picframe/frames"
FOLDER_RE = re.compile(r"^KFR_[A-Za-z0-9_]+$")
SERIAL_RE = re.compile(r"^[0-9a-f]{8,32}$")
SERIAL_SOURCES = (
    Path("/sys/firmware/devicetree/base/serial-number"),
    Path("/proc/cpuinfo"),
    Path("/etc/machine-id"),  # not a Pi (dev machines)
)
# A frame seen this recently may still be running: taking it over needs its name typed
RECENT = timedelta(hours=24)
# last_seen is refreshed after a sync once this much time has passed
HEARTBEAT = timedelta(hours=20)
CLOUD_FIELDS = ("version", "serial", "frame_name", "account", "koofr_user", "last_seen",
                "replaced_by", "replaced_at", "taken_over", "albums")

_loop: Optional[asyncio.AbstractEventLoop] = None
_push_lock = asyncio.Lock()


class RegistryError(Exception):
    """A registry action can't go ahead; `status_code` is the HTTP status to answer with."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --- Identity and time ---------------------------------------------------------

def board_serial() -> Optional[str]:
    """This Pi's board serial (lowercase hex), or the machine id off a Pi; None if neither."""
    for path in SERIAL_SOURCES:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if path.name == "cpuinfo":
            m = re.search(r"^Serial\s*:\s*([0-9a-fA-F]+)", text, re.MULTILINE)
            text = m.group(1) if m else ""
        value = text.strip("\0 \n").lower()
        if SERIAL_RE.match(value):
            return value
    return None


def short_serial(serial: Optional[str]) -> Optional[str]:
    """The last 6 characters of a serial, as shown on the dashboard (…343a2b)."""
    return f"…{serial[-6:]}" if serial else None


def _now() -> str:
    """Current UTC time, ISO 8601 to the second."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_time(value: Any) -> Optional[datetime]:
    """An ISO timestamp as an aware datetime, or None."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _seen_recently(last_seen: Any) -> bool:
    """True if a frame checked in within RECENT (or its time can't be read)."""
    seen = _parse_time(last_seen)
    return seen is None or datetime.now(timezone.utc) - seen < RECENT


# --- Documents -----------------------------------------------------------------

def _folder_of(rclone_remote: Optional[str]) -> Optional[str]:
    """The KFR_* folder of an album's rclone remote ("koofr:KFR_trip" → "KFR_trip"), or None."""
    if not rclone_remote or ":" not in rclone_remote:
        return None
    folder = rclone_remote.split(":", 1)[1].strip("/")
    return folder if FOLDER_RE.match(folder) else None


def _clean_albums(raw: Any) -> list[dict[str, Any]]:
    """Album entries with a valid folder and status; anything else is dropped."""
    albums = []
    seen = set()
    for a in raw if isinstance(raw, list) else []:
        if not isinstance(a, dict) or not FOLDER_RE.match(str(a.get("folder", ""))):
            continue
        if a["folder"] in seen:
            continue
        seen.add(a["folder"])
        entry = {
            "folder": a["folder"],
            "name": str(a.get("name") or a["folder"][4:].replace("_", " "))[:50],
            "status": "active" if a.get("status") == "active" else "deleted",
        }
        if entry["status"] == "deleted" and a.get("deleted_at"):
            entry["deleted_at"] = str(a["deleted_at"])
        albums.append(entry)
    return albums


def _clean_serial(value: Any) -> Optional[str]:
    """A valid serial, or None."""
    return value if isinstance(value, str) and SERIAL_RE.match(value) else None


def _parse_doc(text: str) -> Optional[dict[str, Any]]:
    """A registry document from YAML, normalised; None if it isn't one."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    doc = {
        "version": 1,
        "serial": _clean_serial(data.get("serial")),
        "frame_name": str(data.get("frame_name") or "")[:50],
        "account": data.get("account") if data.get("account") in ("shared", "dedicated") else None,
        "koofr_user": str(data.get("koofr_user") or "").strip().lower()[:254] or None,
        "last_seen": str(data["last_seen"]) if data.get("last_seen") else None,
        "replaced_by": _clean_serial(data.get("replaced_by")),
        "replaced_at": str(data["replaced_at"]) if data.get("replaced_at") else None,
        "taken_over": [s for s in data.get("taken_over") or [] if _clean_serial(s)],
        "albums": _clean_albums(data.get("albums")),
    }
    # Local-only fields
    doc["pending_swap"] = _clean_serial(data.get("pending_swap"))
    doc["pending_replace"] = [s for s in data.get("pending_replace") or [] if _clean_serial(s)]
    doc["last_pushed"] = str(data["last_pushed"]) if data.get("last_pushed") else None
    return doc


def _new_doc(serial: Optional[str]) -> dict[str, Any]:
    """An empty registry document for this board."""
    doc = _parse_doc("{}")
    doc["serial"] = serial
    return doc


def _lock() -> FileLock:
    """Lock for the local copy (path looked up at call time, for tests)."""
    return FileLock(str(LOCAL_PATH) + ".lock", timeout=10)


def _write_local(doc: dict[str, Any]) -> None:
    """Write the local copy atomically, owner-only."""
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL_PATH.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(doc, sort_keys=False, default_flow_style=False))
    os.chmod(tmp, 0o600)
    tmp.replace(LOCAL_PATH)


def _legacy_deleted() -> list[dict[str, Any]]:
    """Albums recorded by Delete Album in deleted_albums.yaml (before the registry)."""
    if not LEGACY_DELETED_PATH.exists():
        return []
    try:
        data = yaml.safe_load(LEGACY_DELETED_PATH.read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        logger.error(f"Failed to read {LEGACY_DELETED_PATH}: {e}")
        return []
    return _clean_albums([
        {"folder": _folder_of(a.get("rclone_remote")), "name": a.get("name"),
         "status": "deleted", "deleted_at": a.get("deleted_at")}
        for a in data.get("albums", []) if isinstance(a, dict)
    ])


def _load_or_init() -> dict[str, Any]:
    """The local copy; created for this board (with legacy deletions) if missing. Call under _lock()."""
    if LOCAL_PATH.exists():
        try:
            doc = _parse_doc(LOCAL_PATH.read_text())
            if doc is not None:
                return doc
        except OSError as e:
            logger.error(f"Failed to read {LOCAL_PATH}: {e}")
        logger.error(f"{LOCAL_PATH} is unreadable; starting a new album registry")
    doc = _new_doc(board_serial())
    doc["albums"] = _legacy_deleted()
    return doc


def _reconcile(doc: dict[str, Any], current: list[PhotoSource]) -> bool:
    """
    Bring the album list in line with the frame's albums.

    Albums on the frame are active; entries no longer on the frame are marked
    deleted (never removed).

    Returns:
        True if anything that goes to the cloud changed
    """
    active: dict[str, str] = {}
    for source in current:
        folder = _folder_of(source.rclone_remote)
        if folder:
            active.setdefault(folder, source.name)
    before = (repr(doc["albums"]), doc["frame_name"])
    by_folder = {a["folder"]: a for a in doc["albums"]}
    for folder, name in active.items():
        entry = by_folder.get(folder)
        if entry is None:
            doc["albums"].append({"folder": folder, "name": name, "status": "active"})
        else:
            entry.update(name=name, status="active")
            entry.pop("deleted_at", None)
    for entry in doc["albums"]:
        if entry["status"] == "active" and entry["folder"] not in active:
            entry["status"] = "deleted"
            entry["deleted_at"] = _now()
    doc["frame_name"] = get_settings().frame.name
    return (repr(doc["albums"]), doc["frame_name"]) != before


def _reset_for_account(doc: dict[str, Any]) -> None:
    """Start a fresh list for a new Koofr account; _reconcile adds the albums on the frame."""
    doc.update(account=None, albums=[], taken_over=[], pending_replace=[],
               replaced_by=None, replaced_at=None, last_seen=None, last_pushed=None)


def _merge_albums(doc: dict[str, Any], albums: list[dict[str, Any]]) -> int:
    """Add entries this frame doesn't have yet (reinstall, takeover). Returns how many were added."""
    have = {a["folder"] for a in doc["albums"]}
    added = 0
    for entry in albums:
        if entry["folder"] not in have:
            doc["albums"].append(dict(entry))
            have.add(entry["folder"])
            added += 1
    return added


# --- Local hooks -----------------------------------------------------------------

def _schedule(coro: Coroutine) -> None:
    """Run a coroutine on the API's event loop, from any thread; dropped if not started."""
    if _loop is None or _loop.is_closed():
        coro.close()
        return
    asyncio.run_coroutine_threadsafe(coro, _loop)


def note_change(current: list[PhotoSource]) -> None:
    """Sources listener: update the local copy after an album change, then push it."""
    with _lock():
        doc = _load_or_init()
        changed = _reconcile(doc, current)
        _write_local(doc)
    if changed:
        _schedule(push())


def maybe_heartbeat() -> None:
    """After a sync: refresh last_seen in the cloud if it's been HEARTBEAT since the last push."""
    if _loop is None:
        return
    try:
        doc = local_doc()
    except Exception as e:  # never fail the sync over the registry
        logger.error(f"Album registry unreadable: {e}")
        return
    pushed = _parse_time(doc.get("last_pushed"))
    if pushed is None or datetime.now(timezone.utc) - pushed >= HEARTBEAT:
        _schedule(push())


def local_doc() -> dict[str, Any]:
    """The local copy (read-only use)."""
    with _lock():
        return _load_or_init()


def banner() -> dict[str, Any]:
    """What the dashboard banner needs: an SD card move to confirm, or a takeover by another Pi."""
    try:
        doc = local_doc()
    except Exception as e:  # the dashboard must render regardless
        logger.error(f"Album registry unreadable: {e}")
        return {"pending_swap": None, "replaced_by": None, "replaced_at": None}
    return {
        "pending_swap": short_serial(doc["pending_swap"]),
        "replaced_by": short_serial(doc["replaced_by"]),
        "replaced_at": doc["replaced_at"],
    }


def start() -> None:
    """At API startup: follow album changes, check the board, and sync with the cloud copy."""
    global _loop
    _loop = asyncio.get_running_loop()
    sources.source_manager.add_listener(note_change)
    serial = board_serial()
    with _lock():
        doc = _load_or_init()
        if doc["pending_swap"] and doc["serial"] == serial:
            doc["pending_swap"] = None  # the card went back to its original board
        if serial and doc["serial"] != serial and not doc["pending_swap"]:
            if doc["serial"]:
                doc["pending_swap"] = doc["serial"]
                logger.warning(
                    f"SD card was last used on board {doc['serial']}, now on {serial}: "
                    "waiting for the dashboard to confirm moved or copied"
                )
            else:
                doc["serial"] = serial
        _reconcile(doc, sources.source_manager.list_sources())
        _write_local(doc)
    _schedule(push())


# --- Cloud -------------------------------------------------------------------------

async def _koofr_remote() -> Optional[str]:
    """The Koofr rclone remote's name, or None if there isn't one."""
    try:
        return await asyncio.to_thread(find_koofr_remote)
    except Exception as e:
        logger.error(f"Couldn't look up the Koofr remote: {e}")
        return None


async def _koofr_user(remote: str) -> Optional[str]:
    """The Koofr login (email, lowercase) the rclone remote uses, or None if it can't be read."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "rclone", "config", "dump",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
            logger.error("rclone config dump timed out")
            return None
        user = json.loads(stdout.decode() or "{}").get(remote, {}).get("user", "")
    except (OSError, ValueError, AttributeError) as e:
        logger.error(f"Couldn't read the Koofr login from the rclone config: {e}")
        return None
    return str(user).strip().lower() or None


async def _from_other_account(remote: str, doc: dict[str, Any]) -> Optional[bool]:
    """
    For a list from before koofr_user was recorded: True if it came from another account.

    Delete Album keeps the cloud folder, so when none of the deleted albums'
    folders are on this account, the list was made on another one.

    Returns:
        True/False, or None if the cloud couldn't be listed
    """
    deleted = {a["folder"] for a in doc["albums"] if a["status"] == "deleted"}
    if not deleted:
        return False
    dirs = await rclone_list_dirs(f"{remote}:")
    if dirs is None:
        return None
    return not deleted & set(dirs)


def _cloud_path(remote: str, serial: str) -> str:
    """A frame's registry file in the cloud."""
    return f"{remote}:{CLOUD_DIR}/{serial}.yaml"


async def cloud_frames(remote: str) -> Optional[dict[str, dict[str, Any]]]:
    """Every frame's registry file on the account, by serial; None if they couldn't be read."""
    names = await rclone_list_files(f"{remote}:{CLOUD_DIR}")
    if names is None:
        return None
    frames = {}
    for name in names:
        serial = name[:-5] if name.endswith(".yaml") else ""
        if not SERIAL_RE.match(serial):
            continue
        data = await rclone_cat(_cloud_path(remote, serial))
        if data is None:
            return None
        doc = _parse_doc(data.decode(errors="replace"))
        if doc is not None and doc["serial"] == serial:
            frames[serial] = doc
        else:
            logger.warning(f"Ignoring unreadable frame registry {CLOUD_DIR}/{name}")
    return frames


async def _upload(remote: str, doc: dict[str, Any]) -> bool:
    """Write a registry document to its cloud file (cloud fields only)."""
    LOCAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LOCAL_PATH.with_name(f".upload-{doc['serial']}.yaml")
    tmp.write_text(yaml.safe_dump({k: doc[k] for k in CLOUD_FIELDS}, sort_keys=False, default_flow_style=False))
    os.chmod(tmp, 0o600)
    try:
        result = await rclone_copyto(tmp, _cloud_path(remote, doc["serial"]))
    finally:
        tmp.unlink(missing_ok=True)
    if not result.success:
        logger.error(f"Couldn't upload frame registry {doc['serial']}: {result.error}")
    return result.success


async def _decide_account(remote: str, doc: dict[str, Any], others: dict[str, Any]) -> Optional[str]:
    """Dedicated if no other frame is on the account and every KFR_* folder is this frame's."""
    if others:
        return "shared"
    dirs = await rclone_list_dirs(f"{remote}:")
    if dirs is None:
        return None
    mine = {a["folder"] for a in doc["albums"]}
    theirs = {d for d in dirs if FOLDER_RE.match(d)} - mine
    return "shared" if theirs else "dedicated"


async def _mark_replaced(remote: str, old: str, new: str, frames: dict[str, dict[str, Any]]) -> bool:
    """Set replaced_by on another frame's cloud file. True when done (or there's no file)."""
    target = frames.get(old)
    if target is None or target["replaced_by"]:
        return True
    target.update(replaced_by=new, replaced_at=_now())
    ok = await _upload(remote, target)
    if ok:
        logger.info(f"Frame registry {old} marked as replaced by {new}")
    return ok


async def push(clear_replaced: bool = False) -> bool:
    """
    Sync this frame's registry with its cloud file and upload it.

    Entries only in the cloud copy are merged in (reinstall); replaced_by comes
    from the cloud (another frame sets it) unless `clear_replaced` (Undo).
    If the Koofr login changed, the list starts again for the new account.

    Returns:
        True if the cloud file was written
    """
    async with _push_lock:
        doc = local_doc()
        if doc["pending_swap"] or not doc["serial"]:
            return False
        remote = await _koofr_remote()
        if not remote:
            return False
        frames = await cloud_frames(remote)
        if frames is None:
            return False
        own = frames.pop(doc["serial"], None)

        user = await _koofr_user(remote)
        switched = False
        if user and doc["koofr_user"] != user:
            switched = bool(doc["koofr_user"]) or await _from_other_account(remote, doc)
            if switched is None:
                return False

        with _lock():
            doc = _load_or_init()
            if doc["pending_swap"]:
                return False
            if switched:
                logger.info(f"Koofr account changed to {user}: starting a new album list for it")
                _reset_for_account(doc)
                # A cloud file on the new account written from the old list isn't this account's history
                if own and own["koofr_user"] != user:
                    own = None
            if user:
                doc["koofr_user"] = user
            if own:
                _merge_albums(doc, own["albums"])
                doc["account"] = doc["account"] or own["account"]
                doc["taken_over"] = sorted(set(doc["taken_over"]) | set(own["taken_over"]))
                if not clear_replaced:
                    doc["replaced_by"], doc["replaced_at"] = own["replaced_by"], own["replaced_at"]
            if clear_replaced:
                doc["replaced_by"] = doc["replaced_at"] = None
            _reconcile(doc, sources.source_manager.list_sources())
            _write_local(doc)

        account = doc["account"] or await _decide_account(remote, doc, frames)
        doc["account"] = account
        doc["last_seen"] = _now()
        if not await _upload(remote, doc):
            return False

        done = [old for old in doc["pending_replace"] if await _mark_replaced(remote, old, doc["serial"], frames)]
        with _lock():
            saved = _load_or_init()
            saved.update(account=account, last_seen=doc["last_seen"], last_pushed=doc["last_seen"])
            saved["pending_replace"] = [s for s in saved["pending_replace"] if s not in done]
            _write_local(saved)
        return True


# --- Dashboard actions ---------------------------------------------------------------

async def cloud_view() -> dict[str, Any]:
    """
    Unused KFR_* cloud folders, split into this frame's and unclaimed, plus other frames.

    A folder another frame claims is never included.

    Returns:
        remote, mine [{folder, name, deleted_at}], unclaimed [{folder}], dedicated,
        frames [{serial, short, frame_name, last_seen, recent, albums, deleted}]

    Raises:
        RegistryError: no Koofr remote, or the cloud couldn't be listed
    """
    remote = await _koofr_remote()
    if not remote:
        raise RegistryError(502, "No Koofr cloud storage is set up on this frame.")
    dirs, frames = await asyncio.gather(rclone_list_dirs(f"{remote}:"), cloud_frames(remote))
    if dirs is None or frames is None:
        raise RegistryError(502, "Couldn't list the cloud storage folders.")
    doc = local_doc()
    frames.pop(doc["serial"], None)

    used = {_folder_of(s.rclone_remote) for s in sources.source_manager.list_sources()}
    mine = {a["folder"]: a for a in doc["albums"]}
    claimed = {a["folder"] for other in frames.values() for a in other["albums"]}
    result: dict[str, Any] = {
        "remote": remote,
        "mine": [],
        "unclaimed": [],
        "dedicated": doc["account"] == "dedicated" and not frames,
        "frames": [],
    }
    for folder in sorted(d for d in dirs if FOLDER_RE.match(d) and d not in used):
        if folder in mine:
            result["mine"].append({"folder": folder, "name": mine[folder]["name"],
                                   "deleted_at": mine[folder].get("deleted_at")})
        elif folder not in claimed:
            result["unclaimed"].append({"folder": folder})
    for serial, other in sorted(frames.items(), key=lambda kv: kv[1]["last_seen"] or "", reverse=True):
        if other["replaced_by"]:
            continue
        result["frames"].append({
            "serial": serial,
            "short": short_serial(serial),
            "frame_name": other["frame_name"] or short_serial(serial),
            "last_seen": other["last_seen"],
            "recent": _seen_recently(other["last_seen"]),
            "albums": len(other["albums"]),
            "deleted": sum(a["status"] == "deleted" for a in other["albums"]),
        })
    return result


async def resolve_swap(moved: bool) -> dict[str, Any]:
    """
    Answer the SD-card question after the card moved to another Pi.

    moved=True: same frame on a new board; it keeps every album and takes over
    the old board's cloud file. moved=False: a new frame copied from that card;
    it keeps only the albums on it, and the original frame keeps the rest.
    """
    serial = board_serial()
    with _lock():
        doc = _load_or_init()
        old = doc["pending_swap"]
        if not old:
            raise RegistryError(409, "There's no SD card move to confirm.")
        doc.update(serial=serial, pending_swap=None, replaced_by=None, replaced_at=None,
                   last_pushed=None, last_seen=None)
        if moved:
            doc["taken_over"] = sorted(set(doc["taken_over"]) | {old})
            doc["pending_replace"] = sorted(set(doc["pending_replace"]) | {old})
        else:
            doc["albums"] = [a for a in doc["albums"] if a["status"] == "active"]
            doc.update(account=None, taken_over=[], pending_replace=[])
        _write_local(doc)
    logger.info(f"SD card from board {old} on board {serial}: {'moved' if moved else 'copied'}")
    cloud_updated = await push()
    return {"moved": moved, "old": short_serial(old), "cloud_updated": cloud_updated}


async def take_over(serial: str, confirm_name: str = "") -> dict[str, Any]:
    """
    Take over another frame's albums (a new board with a fresh SD card).

    A frame seen in the last 24 hours may still be running, so its name must be
    typed to confirm.
    """
    if not SERIAL_RE.match(serial or ""):
        raise RegistryError(400, "Invalid frame.")
    remote = await _koofr_remote()
    if not remote:
        raise RegistryError(502, "No Koofr cloud storage is set up on this frame.")
    frames = await cloud_frames(remote)
    if frames is None:
        raise RegistryError(502, "Couldn't read the frames on this cloud account.")
    doc = local_doc()
    if serial == doc["serial"]:
        raise RegistryError(400, "That's this frame.")
    target = frames.get(serial)
    if target is None:
        raise RegistryError(404, "That frame isn't on this cloud account.")
    name = target["frame_name"] or short_serial(serial)
    if target["replaced_by"]:
        raise RegistryError(409, f"{name} was already taken over by another Pi ({short_serial(target['replaced_by'])}).")
    if _seen_recently(target["last_seen"]) and confirm_name.strip().lower() != name.strip().lower():
        raise RegistryError(409, f"{name} checked in within the last 24 hours. Type its name to confirm.")

    with _lock():
        doc = _load_or_init()
        added = _merge_albums(doc, target["albums"])
        doc["taken_over"] = sorted(set(doc["taken_over"]) | {serial})
        doc["pending_replace"] = sorted(set(doc["pending_replace"]) | {serial})
        _reconcile(doc, sources.source_manager.list_sources())
        _write_local(doc)
    logger.info(f"Took over frame {name} ({serial}): {added} album(s) added to this frame's list")
    cloud_updated = await push()
    return {"frame_name": name, "albums_added": added, "cloud_updated": cloud_updated}


async def undo_takeover() -> dict[str, Any]:
    """Clear the takeover mark another Pi put on this frame's cloud file."""
    doc = local_doc()
    if not doc["replaced_by"]:
        raise RegistryError(409, "This frame hasn't been taken over.")
    by = doc["replaced_by"]
    if not await push(clear_replaced=True):
        raise RegistryError(502, "Couldn't update the cloud storage. Try again.")
    logger.info(f"Undid takeover of this frame by {by}")
    return {"undone": short_serial(by)}
