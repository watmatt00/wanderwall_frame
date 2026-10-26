"""
WanderWall - Invite Storage.

JSON-based storage for contributor invite codes.
Invites grant contributor role on successful pairing.
"""

import json
import logging
import os
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from filelock import FileLock
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Storage location
INVITES_PATH = Path.home() / ".wanderwall" / "invites.json"
LOCK_TIMEOUT = 10

# Invite settings
CODE_LENGTH = 6
CODE_CHARS = string.ascii_uppercase + string.digits
INVITE_EXPIRY_HOURS = 48
MAX_PENDING_PER_HOUR = 3


class Invite(BaseModel):
    """A contributor invite record."""
    id: str
    code: str
    role: str = "contributor"
    created_at: datetime
    expires_at: datetime
    claimed: bool = False
    claimed_at: Optional[datetime] = None
    claimed_by: Optional[str] = None  # device name of the claimer


class InviteStorage:
    """
    Persistent storage for contributor invites.

    Uses JSON file with file locking for safe concurrent access.
    Atomic writes via temp-file-then-rename pattern.
    """

    def __init__(self, path: Path = INVITES_PATH):
        self._path = path
        self._lock_path = path.with_suffix(".lock")
        self._lock = FileLock(self._lock_path, timeout=LOCK_TIMEOUT)

    def _load(self) -> list[Invite]:
        """Load invites from file."""
        if not self._path.exists():
            return []
        try:
            with open(self._path) as f:
                data = json.load(f)
            return [Invite(**i) for i in data.get("invites", [])]
        except Exception as e:
            logger.error(f"Failed to load invites: {e}")
            return []

    def _save(self, invites: list[Invite]):
        """Save invites to file with atomic write and restrictive permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {"invites": [i.model_dump(mode="json") for i in invites]}
        temp_path = self._path.with_suffix(".tmp")
        with open(temp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.chmod(temp_path, 0o600)
        temp_path.rename(self._path)

    def create_invite(self) -> Optional[Invite]:
        """
        Create a new contributor invite.

        Rate limit: max 3 unclaimed invites created in the past hour.

        Returns:
            Invite if created successfully, None if rate limited.
        """
        with self._lock:
            invites = self._load()
            now = datetime.now(timezone.utc)

            # Rate limit: count unclaimed invites created in last hour
            cutoff = now - timedelta(hours=1)
            recent_pending = [
                i for i in invites
                if i.created_at > cutoff and not i.claimed
            ]
            if len(recent_pending) >= MAX_PENDING_PER_HOUR:
                return None

            # Generate formatted code: ABC-XYZ
            raw = "".join(secrets.choice(CODE_CHARS) for _ in range(CODE_LENGTH))
            code = f"{raw[:3]}-{raw[3:]}"

            invite = Invite(
                id=str(uuid.uuid4()),
                code=code,
                created_at=now,
                expires_at=now + timedelta(hours=INVITE_EXPIRY_HOURS),
            )
            invites.append(invite)
            self._save(invites)

            logger.info(f"Contributor invite created: {invite.id}")
            return invite

    def list_invites(self) -> list[Invite]:
        """Return all invite records (claimed and unclaimed)."""
        with self._lock:
            return self._load()

    def is_valid_invite(self, code: str) -> bool:
        """Return True if *code* is an unclaimed, unexpired invite. Does not claim it."""
        normalized = code.upper().strip()
        now = datetime.now(timezone.utc)
        with self._lock:
            return any(
                i.code.upper() == normalized and not i.claimed and now <= i.expires_at
                for i in self._load()
            )

    def verify_and_claim(self, code: str, device_name: str) -> Optional[Invite]:
        """
        Verify a contributor invite code and mark it as claimed.

        Args:
            code: The invite code to verify (case-insensitive)
            device_name: Name of the device claiming the invite

        Returns:
            The claimed Invite if valid, None if invalid/expired/already claimed.
        """
        normalized = code.upper().strip()
        now = datetime.now(timezone.utc)

        with self._lock:
            invites = self._load()
            for invite in invites:
                if invite.code.upper() == normalized:
                    if invite.claimed:
                        logger.warning(f"Invite {invite.id} already claimed")
                        return None
                    if now > invite.expires_at:
                        logger.warning(f"Invite {invite.id} expired")
                        return None
                    # Claim the invite
                    invite.claimed = True
                    invite.claimed_at = now
                    invite.claimed_by = device_name
                    self._save(invites)
                    logger.info(
                        f"Invite {invite.id} claimed by '{device_name}'"
                    )
                    return invite
            return None

    def revoke_invite(self, invite_id: str) -> bool:
        """
        Delete an unclaimed invite.

        Args:
            invite_id: ID of the invite to revoke

        Returns:
            True if revoked, False if not found or already claimed.
        """
        with self._lock:
            invites = self._load()
            target = next((i for i in invites if i.id == invite_id), None)

            if not target:
                return False
            if target.claimed:
                logger.warning(f"Cannot revoke claimed invite {invite_id}")
                return False

            invites = [i for i in invites if i.id != invite_id]
            self._save(invites)
            logger.info(f"Invite {invite_id} revoked")
            return True

    def revoke_all(self) -> int:
        """
        Delete every invite, claimed or not (demo frame reset, PL-151).

        Returns:
            Number of unclaimed invites that stopped working
        """
        with self._lock:
            invites = self._load()
            if not invites:
                return 0
            pending = sum(1 for i in invites if not i.claimed)
            self._save([])
            logger.info(f"All invites removed ({pending} unclaimed)")
            return pending


# Global storage instance
invite_storage = InviteStorage()
