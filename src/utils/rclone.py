"""
WanderWall - rclone Wrapper.

Python wrapper for rclone operations (no shell scripts).

Provides:
- rclone_sync: Sync from remote to local
- rclone_copyto: Upload a single local file to a remote destination
- rclone_copy_dir: Upload a local folder's files without overwriting
- rclone_sync_up: Make a cloud folder match a local folder
- rclone_purge: Delete a cloud folder
- rclone_list_dirs: List the top-level folders of a remote
- rclone_count: Count files on remote
- rclone_check: Check if remote is accessible
- rclone_list_remotes: List configured remotes
- count_local_files: Count files in local directory
- get_sync_status: Compare local vs remote and return status
"""

import asyncio
import logging
import re
import shutil
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SyncStatus(str, Enum):
    """Sync status between local and remote."""
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


class RcloneResult(BaseModel):
    """Result of an rclone operation."""
    success: bool
    files_transferred: int = 0
    files_deleted: int = 0
    bytes_transferred: int = 0
    error: Optional[str] = None
    output: str = ""


async def rclone_sync(
    source: str,
    dest: str,
    extra_flags: list[str] | None = None,
) -> RcloneResult:
    """
    Sync files from source to destination using rclone.

    Args:
        source: Source path (can be remote like "koofr:folder")
        dest: Destination path (usually local)
        extra_flags: Additional rclone flags

    Returns:
        RcloneResult with operation details
    """
    # Validate inputs to prevent command injection
    if not _validate_remote(source):
        return RcloneResult(success=False, error=f"Invalid source: {source}")
    if not _validate_path(dest):
        return RcloneResult(success=False, error=f"Invalid destination: {dest}")

    cmd = ["rclone", "sync", source, dest, "--stats-one-line", "-v"]

    if extra_flags:
        # Filter potentially dangerous flags
        safe_flags = [f for f in extra_flags if _is_safe_flag(f)]
        cmd.extend(safe_flags)

    logger.info(f"Running: {' '.join(cmd)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()

        if proc.returncode == 0:
            # Parse output for stats
            transferred = _parse_transferred(output)
            return RcloneResult(
                success=True,
                files_transferred=transferred,
                output=output,
            )
        else:
            return RcloneResult(
                success=False,
                error=f"rclone exited with code {proc.returncode}",
                output=output,
            )

    except FileNotFoundError:
        return RcloneResult(
            success=False,
            error="rclone not found. Please install rclone.",
        )
    except Exception as e:
        return RcloneResult(success=False, error=str(e))


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}


def _validate_filename(filename: str) -> bool:
    """Bare filename only: no path separators, no traversal, image ext."""
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    if Path(filename).suffix.lower() not in IMAGE_EXTENSIONS:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-. ]+$', filename))


async def rclone_deletefile(rclone_remote: str, filename: str) -> RcloneResult:
    """Delete a single file from an rclone remote. No shell=True."""
    if not _validate_remote(rclone_remote):
        return RcloneResult(success=False, error=f"Invalid remote: {rclone_remote}")
    if not _validate_filename(filename):
        return RcloneResult(success=False, error=f"Invalid filename: {filename}")
    cmd = ["rclone", "deletefile", f"{rclone_remote}/{filename}"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()
    if proc.returncode == 0:
        return RcloneResult(success=True, files_deleted=1, output=output)
    return RcloneResult(
        success=False,
        error=f"rclone deletefile exited {proc.returncode}",
        output=output,
    )


async def rclone_movefile(rclone_remote: str, old_filename: str, new_filename: str) -> RcloneResult:
    """Rename a single file on an rclone remote using rclone movefile."""
    if not _validate_remote(rclone_remote):
        return RcloneResult(success=False, error=f"Invalid remote: {rclone_remote}")
    if not _validate_filename(old_filename) or not _validate_filename(new_filename):
        return RcloneResult(success=False, error="Invalid filename")
    cmd = ["rclone", "moveto", f"{rclone_remote}/{old_filename}", f"{rclone_remote}/{new_filename}"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()
    if proc.returncode == 0:
        return RcloneResult(success=True, output=output)
    return RcloneResult(success=False, error=f"rclone movefile exited {proc.returncode}", output=output)


def _validate_filename_raw(filename: str) -> bool:
    """Path-traversal-only check for filenames discovered on the local filesystem.

    Used by photo tools where filenames may legitimately contain spaces, curly
    braces, or other special characters that _validate_filename() rejects.
    Never use this for user-supplied filenames.
    """
    if not filename:
        return False
    return "/" not in filename and "\\" not in filename and ".." not in filename


def _validate_relative_path(path: str) -> bool:
    """Relative path validator for photos in subdirectories.

    Allows forward slashes as directory separators but blocks path traversal,
    absolute paths, and non-image extensions.
    Only for paths discovered from the local filesystem listing — NOT user input.
    """
    if not path or path.startswith("/") or "\\" in path or ".." in path:
        return False
    if Path(path).suffix.lower() not in IMAGE_EXTENSIONS:
        return False
    return True


async def rclone_deletefile_raw(rclone_remote: str, filename: str) -> RcloneResult:
    """Delete a single file from an rclone remote. Accepts filenames with special chars.

    Only safe for filenames discovered from the local filesystem — NOT user input.
    """
    if not _validate_remote(rclone_remote):
        return RcloneResult(success=False, error=f"Invalid remote: {rclone_remote}")
    if not _validate_filename_raw(filename):
        return RcloneResult(success=False, error=f"Unsafe filename: {filename}")
    cmd = ["rclone", "deletefile", f"{rclone_remote}/{filename}"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()
    if proc.returncode == 0:
        return RcloneResult(success=True, files_deleted=1, output=output)
    return RcloneResult(
        success=False,
        error=f"rclone deletefile exited {proc.returncode}",
        output=output,
    )


async def rclone_movefile_raw(rclone_remote: str, old_filename: str, new_filename: str) -> RcloneResult:
    """Rename a file on an rclone remote. Source accepts special chars; dest is strictly validated.

    Only safe for source filenames discovered from the local filesystem — NOT user input.
    """
    if not _validate_remote(rclone_remote):
        return RcloneResult(success=False, error=f"Invalid remote: {rclone_remote}")
    if not _validate_filename_raw(old_filename):
        return RcloneResult(success=False, error=f"Unsafe source filename: {old_filename}")
    if not _validate_filename(new_filename):
        return RcloneResult(success=False, error=f"Invalid destination filename: {new_filename}")
    cmd = ["rclone", "moveto",
           f"{rclone_remote}/{old_filename}",
           f"{rclone_remote}/{new_filename}"]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode()
    if proc.returncode == 0:
        return RcloneResult(success=True, output=output)
    return RcloneResult(
        success=False,
        error=f"rclone movefile exited {proc.returncode}",
        output=output,
    )


async def rclone_copyto(local_file: Path, remote_dest: str) -> RcloneResult:
    """Upload a single local file to a remote destination via rclone copyto."""
    if not _validate_remote(remote_dest):
        return RcloneResult(success=False, error=f"Invalid remote destination: {remote_dest}")
    cmd = ["rclone", "copyto", str(local_file), remote_dest]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        if proc.returncode == 0:
            return RcloneResult(success=True, files_transferred=1, output=output)
        return RcloneResult(
            success=False,
            error=f"rclone copyto exited {proc.returncode}",
            output=output,
        )
    except FileNotFoundError:
        return RcloneResult(success=False, error="rclone not found. Please install rclone.")
    except Exception as e:
        return RcloneResult(success=False, error=str(e))


async def rclone_copy_dir(local_dir: Path, remote_dest: str) -> RcloneResult:
    """
    Upload every file in a local folder to a remote folder (rclone copy).

    `--ignore-existing` never overwrites a file already in the cloud; nothing is
    deleted on either side.
    """
    if not _validate_path(str(local_dir)):
        return RcloneResult(success=False, error=f"Invalid local folder: {local_dir}")
    if not _validate_remote(remote_dest):
        return RcloneResult(success=False, error=f"Invalid remote destination: {remote_dest}")
    cmd = ["rclone", "copy", str(local_dir), remote_dest, "--ignore-existing", "--stats-one-line", "-v"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        if proc.returncode == 0:
            return RcloneResult(success=True, files_transferred=_parse_transferred(output), output=output)
        return RcloneResult(
            success=False,
            error=f"rclone copy exited {proc.returncode}",
            output=output,
        )
    except FileNotFoundError:
        return RcloneResult(success=False, error="rclone not found. Please install rclone.")
    except Exception as e:
        return RcloneResult(success=False, error=str(e))


def _is_remote_subfolder(remote: str) -> bool:
    """True for "name:folder…": a valid remote with a folder, never the whole account."""
    return _validate_remote(remote) and not remote.startswith("/") and bool(remote.split(":", 1)[1].strip("/"))


async def _run_rclone(cmd: list[str], what: str) -> RcloneResult:
    """Run an rclone command and wrap the outcome."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        if proc.returncode == 0:
            return RcloneResult(success=True, files_transferred=_parse_transferred(output), output=output)
        return RcloneResult(success=False, error=f"rclone {what} exited {proc.returncode}", output=output)
    except FileNotFoundError:
        return RcloneResult(success=False, error="rclone not found. Please install rclone.")
    except Exception as e:
        return RcloneResult(success=False, error=str(e))


async def rclone_sync_up(local_dir: Path, remote_dest: str) -> RcloneResult:
    """
    Make a remote folder match a local folder (rclone sync, local → cloud).

    Files in the cloud folder that aren't in the local one are deleted, so the
    destination must be a folder, never the root of the account.
    """
    if not _validate_path(str(local_dir)) or not Path(local_dir).is_dir():
        return RcloneResult(success=False, error=f"Invalid local folder: {local_dir}")
    if not _is_remote_subfolder(remote_dest):
        return RcloneResult(success=False, error=f"Invalid remote folder: {remote_dest}")
    return await _run_rclone(["rclone", "sync", str(local_dir), remote_dest, "--stats-one-line", "-v"], "sync")


async def rclone_purge(remote_folder: str) -> RcloneResult:
    """Delete a remote folder and everything in it (rclone purge). Never the root of the account."""
    if not _is_remote_subfolder(remote_folder):
        return RcloneResult(success=False, error=f"Invalid remote folder: {remote_folder}")
    return await _run_rclone(["rclone", "purge", remote_folder], "purge")


async def rclone_list_dirs(remote: str) -> list[str] | None:
    """
    List the folders directly under a remote (e.g. "koofr:").

    Returns:
        Folder names, or None if the listing failed
    """
    if not _validate_remote(remote):
        raise ValueError(f"Invalid remote: {remote}")
    cmd = ["rclone", "lsjson", remote, "--dirs-only"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(f"rclone lsjson {remote} failed: {stderr.decode().strip()}")
            return None
        import json
        return [entry["Name"] for entry in json.loads(stdout.decode() or "[]") if entry.get("IsDir")]
    except Exception as e:
        logger.error(f"Failed to list remote folders: {e}")
        return None


async def rclone_list_files(remote: str) -> list[str] | None:
    """
    List the files directly in a remote folder (e.g. "koofr:.picframe/frames").

    Returns:
        File names ([] if the folder doesn't exist), or None if the listing failed
    """
    if not _validate_remote(remote):
        raise ValueError(f"Invalid remote: {remote}")
    cmd = ["rclone", "lsjson", remote, "--files-only"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 3:  # rclone: directory not found
            return []
        if proc.returncode != 0:
            logger.error(f"rclone lsjson {remote} failed: {stderr.decode().strip()[:200]}")
            return None
        import json
        return [entry["Name"] for entry in json.loads(stdout.decode() or "[]") if not entry.get("IsDir")]
    except Exception as e:
        logger.error(f"Failed to list remote files: {e}")
        return None


async def rclone_cat(remote_file: str, max_bytes: int = 1024 * 1024) -> bytes | None:
    """
    Read a small file from a remote.

    Returns:
        The file's contents, or None if it couldn't be read or is bigger than max_bytes
    """
    if not _validate_remote(remote_file):
        raise ValueError(f"Invalid remote: {remote_file}")
    cmd = ["rclone", "cat", remote_file, "--count", str(max_bytes + 1)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            logger.error(f"rclone cat {remote_file} failed: {stderr.decode().strip()[:200]}")
            return None
        if len(stdout) > max_bytes:
            logger.error(f"rclone cat {remote_file}: file is bigger than {max_bytes} bytes")
            return None
        return stdout
    except Exception as e:
        logger.error(f"Failed to read remote file: {e}")
        return None


async def rclone_count(remote: str) -> int:
    """
    Count files in a remote.

    Args:
        remote: Remote path to count

    Returns:
        Number of files
    """
    if not _validate_remote(remote):
        raise ValueError(f"Invalid remote: {remote}")

    cmd = ["rclone", "size", remote, "--json"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode == 0:
            import json
            data = json.loads(stdout.decode())
            return data.get("count", 0)
        return 0

    except Exception as e:
        logger.error(f"Failed to count remote files: {e}")
        return 0


async def rclone_list_md5(remote: str) -> list[tuple[str, int, str]] | None:
    """
    List the files directly in a remote folder with their size and MD5.

    Koofr stores MD5 natively, so this is one listing call (no downloads).

    Args:
        remote: Remote folder, e.g. "kfr_frame:KFR_frame"

    Returns:
        (name, size, md5) per file (md5 may be "" if unknown), or None on failure.
    """
    if not _validate_remote(remote):
        raise ValueError(f"Invalid remote: {remote}")

    cmd = ["rclone", "lsjson", remote, "--files-only", "--hash", "--hash-type", "md5"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            logger.warning(f"rclone lsjson failed for {remote}: {stderr.decode().strip()[:200]}")
            return None
        import json
        items = json.loads(stdout.decode() or "[]")
        return [
            (i.get("Name", ""), int(i.get("Size", -1)), (i.get("Hashes") or {}).get("md5", "").lower())
            for i in items
        ]
    except Exception as e:
        logger.error(f"Failed to list remote hashes: {e}")
        return None


async def rclone_check(remote: str) -> bool:
    """
    Check if an rclone remote is accessible.

    Args:
        remote: Remote to check (e.g., "koofr:")

    Returns:
        True if remote is accessible
    """
    if not _validate_remote(remote):
        return False

    cmd = ["rclone", "lsd", remote, "--max-depth", "0"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0

    except Exception:
        return False


def _validate_remote(remote: str) -> bool:
    """Validate an rclone remote specification."""
    # Allow: name:path or /local/path
    if remote.startswith("/"):
        return _validate_path(remote)
    # Remote format: name:path
    if ":" not in remote:
        return False
    name, path = remote.split(":", 1)
    # Name should be alphanumeric + underscore
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return False
    return True


def _validate_path(path: str) -> bool:
    """Validate a local path (no traversal)."""
    if ".." in path:
        return False
    if not path.startswith("/"):
        return False
    return True


def _is_safe_flag(flag: str) -> bool:
    """Check if an rclone flag is safe to use."""
    # Blacklist dangerous flags
    dangerous = {
        "--config",
        "--delete-before",
        "--delete-during",
        "--delete-after",
        "--delete-excluded",
    }
    return flag.split("=")[0] not in dangerous


def _parse_transferred(output: str) -> int:
    """Parse the number of transferred files from rclone output.

    With --stats-one-line -v, rclone logs each transferred file as
    'filename: Copied (new)' or 'filename: Copied (replaced existing)'.
    Count those lines rather than looking for a summary 'Transferred: N' line,
    which is not emitted in that stats mode.
    """
    return len(re.findall(r": Copied ", output))


async def rclone_list_remotes() -> list[str]:
    """
    List configured rclone remotes.

    Returns:
        List of remote names (without trailing colon)
    """
    cmd = ["rclone", "listremotes"]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()

        if proc.returncode == 0:
            # Parse output - each line is "name:"
            remotes = []
            for line in stdout.decode().strip().split("\n"):
                line = line.strip()
                if line and line.endswith(":"):
                    remotes.append(line[:-1])
            return remotes
        return []

    except FileNotFoundError:
        logger.error("rclone not found. Please install rclone.")
        return []
    except Exception as e:
        logger.error(f"Failed to list remotes: {e}")
        return []


def count_local_files(path: str | Path) -> int:
    """
    Count files in a local directory.

    Args:
        path: Local directory path

    Returns:
        Number of files (0 if path doesn't exist)
    """
    path = Path(path).expanduser()

    if not path.exists():
        return 0

    if not path.is_dir():
        logger.warning(f"Path is not a directory: {path}")
        return 0

    try:
        count = sum(1 for f in path.rglob("*") if f.is_file())
        return count
    except PermissionError as e:
        logger.error(f"Permission denied counting files in {path}: {e}")
        return 0
    except Exception as e:
        logger.error(f"Error counting files in {path}: {e}")
        return 0


class SyncStatusResult(BaseModel):
    """Result of a sync status check."""
    status: SyncStatus
    local_count: int = 0
    remote_count: int = 0
    message: str = ""


async def get_sync_status(
    remote: str,
    local_path: str | Path,
) -> SyncStatusResult:
    """
    Compare local vs remote and return sync status.

    Args:
        remote: Remote path (e.g., "koofr:KFR_kframe")
        local_path: Local directory path

    Returns:
        SyncStatusResult with status, counts, and message
    """
    local_path = Path(local_path).expanduser()

    # Validate remote
    if not _validate_remote(remote):
        return SyncStatusResult(
            status=SyncStatus.ERROR,
            message=f"Invalid remote: {remote}",
        )

    # Check if remote is accessible
    if not await rclone_check(remote.split(":")[0] + ":"):
        return SyncStatusResult(
            status=SyncStatus.ERROR,
            message=f"Remote not accessible: {remote}",
        )

    # Get counts
    try:
        remote_count = await rclone_count(remote)
    except Exception as e:
        return SyncStatusResult(
            status=SyncStatus.ERROR,
            message=f"Failed to count remote files: {e}",
        )

    local_count = count_local_files(local_path)

    # Compare
    if remote_count == local_count:
        return SyncStatusResult(
            status=SyncStatus.MATCH,
            local_count=local_count,
            remote_count=remote_count,
            message=f"Synced: {local_count} files",
        )
    else:
        diff = abs(remote_count - local_count)
        direction = "behind" if remote_count > local_count else "ahead"
        return SyncStatusResult(
            status=SyncStatus.MISMATCH,
            local_count=local_count,
            remote_count=remote_count,
            message=f"Local is {diff} files {direction} remote",
        )


def is_rclone_available() -> bool:
    """Check if rclone is installed and available."""
    return shutil.which("rclone") is not None
