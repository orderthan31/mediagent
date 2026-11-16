"""Explicit private-edge identity binding; never creates accounts or sessions.

Deployment prerequisite: independently verify the named HTTPS origin is reachable
only through the existing authenticated private edge (no Funnel/public listener).
Origin/Host checks are NOT network access control. All permitted edge visitors act
as this account. Use one API process: the CSRF token is ephemeral per process.
Unset both environment knobs and restart to restore ordinary login; old accounts
and sessions are untouched. Never enable this mode during maintenance.
"""

import re
import secrets
from urllib.parse import urlsplit

from video_service.postgres.accounts import public


class SingleUser:
    def __init__(self, database, account_id, private_origin, *, origins, secure, mode):
        if (
            not isinstance(account_id, str)
            or not re.fullmatch(r"[a-f0-9]{32}", account_id)
            or not isinstance(private_origin, str)
            or urlsplit(private_origin).scheme != "https"
            or not urlsplit(private_origin).hostname
            or urlsplit(private_origin).username is not None
            or urlsplit(private_origin).password is not None
            or urlsplit(private_origin).path
            or urlsplit(private_origin).query
            or urlsplit(private_origin).fragment
            or "*" in private_origin
            or set(origins) != {private_origin}
            or not secure
            or mode != "normal"
        ):
            raise ValueError("invalid_single_user_private_configuration")
        self.database = database
        self.account_id = account_id
        self.csrf_token = secrets.token_urlsafe(32)
        if self.session() is None:
            raise ValueError("single_user_active_account_required")

    def session(self):
        # Re-read on every request: deletion, deactivation and role changes take
        # effect without restart. Select public columns only, with existing grants.
        with self.database.connection() as db:
            row = db.execute(
                "SELECT id,username,role,active,created_at FROM accounts WHERE id=%s AND active",
                (self.account_id,),
            ).fetchone()
        if (
            not row
            or row["id"] != self.account_id
            or row["active"] is not True
            or row["role"] not in ("admin", "user")
        ):
            return None
        return {"user": public(row), "csrf_token": self.csrf_token}


def from_environment(environ):
    """Absence disables; empty/partial/malformed opt-ins never silently disable."""
    account = environ.get("MIDEAGENT_SINGLE_USER_ACCOUNT")
    origin = environ.get("MIDEAGENT_SINGLE_USER_PRIVATE_ORIGIN")
    if (account is None) != (origin is None):
        raise ValueError("single_user_requires_account_and_private_origin")
    if account is not None and (
        not re.fullmatch(r"[a-f0-9]{32}", account) or not origin
    ):
        raise ValueError("invalid_single_user_private_configuration")
    return account, origin
