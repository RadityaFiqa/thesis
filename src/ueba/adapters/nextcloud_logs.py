"""Parse Nextcloud audit and Caddy access log records into NormalizedEvents.

The field mapping is documented in docs/data/field-mapping.md. Every pattern
here was taken from real samples (infra/scripts/phase2-sample-actions.sh).
Each parse returns either an event or the reason the record was skipped, so
nothing disappears without being counted (LOG-04).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

from ueba.domain.events import Action, NormalizedEvent, Outcome, Provenance, SourceSystem

AUDIT_LOCATION = "/var/log/nextcloud/audit.log"
APP_LOCATION = "/var/log/nextcloud/nextcloud.log"
PROXY_LOCATION = "/var/log/caddy/access.log"

SOURCE_BY_LOCATION = {
    AUDIT_LOCATION: SourceSystem.NEXTCLOUD_AUDIT,
    APP_LOCATION: SourceSystem.NEXTCLOUD_APP,
    PROXY_LOCATION: SourceSystem.PROXY_ACCESS,
}


@dataclass(frozen=True, slots=True)
class ParseResult:
    event: NormalizedEvent | None
    skip_reason: str | None = None

    @classmethod
    def skip(cls, reason: str) -> ParseResult:
        return cls(None, reason)


# ------------------------------------------------------------------ helpers
_NO_USER = {"", "--", None}
_DAV_FILES = re.compile(r"^/remote\.php/dav/files/(?P<user>[^/]+)(?P<path>/.*)?$")
_WEB_LOGIN_PATHS = {"/login", "/index.php/login"}
_LOGOUT_PATHS = {"/logout", "/index.php/logout"}


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    return None


def _user_files_path(path: str, user: str) -> str:
    """'/alice/files/a/b.txt' -> '/a/b.txt' (path inside the user's files)."""
    prefix = f"/{user}/files"
    return path[len(prefix) :] or "/" if path.startswith(prefix) else path


def _dav_target(url: str | None) -> tuple[str | None, str | None]:
    """(user, path) for a WebDAV files URL, query string dropped."""
    if not url:
        return None, None
    m = _DAV_FILES.match(unquote(urlsplit(url).path))
    if not m:
        return None, None
    return m["user"], (m["path"] or "/").rstrip("/") or "/"


def _url_path(url: str | None) -> str:
    return urlsplit(url or "").path


# ------------------------------------------------------------------ audit.log
_AUTH_OK = re.compile(r'^Login successful: "(?P<user>[^"]*)"')
_AUTH_FAIL = re.compile(r'^Login failed: "(?P<user>[^"]*)"')
_FILE_OP = re.compile(
    r'^File with id "\d+" (?P<op>created|written to|accessed|deleted): "(?P<path>.*)"$'
)
_RENAME = re.compile(r'^File renamed with id "\d+" from "(?P<src>.*)" to "(?P<dst>.*)"$')
_SHARE = re.compile(r'^The file "(?P<path>.*)" with ID "\d+" has been shared via (?P<via>\w+)')
_NOISE = (
    (re.compile(r"^Cache entry (inserted|updated|removed)"), "internal_cache"),
    (re.compile(r"^Login attempt: "), "login_attempt_precursor"),  # outcome follows in its own line
    (re.compile(r"^Interaction .*ShareAction"), "share_interaction_duplicate"),
)


def parse_audit(
    rec: dict[str, Any], *, raw_ref: str, ingest_time: datetime | None = None
) -> ParseResult:
    message = rec.get("message")
    event_time = _parse_time(rec.get("time"))
    if not isinstance(message, str) or event_time is None:
        return ParseResult.skip("invalid_record")
    for pattern, reason in _NOISE:
        if pattern.search(message):
            return ParseResult.skip(reason)

    method = rec.get("method") or None
    url = rec.get("url")
    user = None if rec.get("user") in _NO_USER else rec["user"]
    issues: list[str] = []
    resource: str | None = None

    if m := (_AUTH_OK.match(message) or _AUTH_FAIL.match(message)):
        user = m["user"] or user
        web = _url_path(url) in _WEB_LOGIN_PATHS
        action = Action.LOGIN if web else Action.AUTH
        outcome = Outcome.SUCCESS if message.startswith("Login successful") else Outcome.FAILURE
    elif message.startswith("Logout occurred"):
        if _url_path(url) not in _LOGOUT_PATHS:
            # WebDAV/API requests with basic auth end a temporary session and log
            # "Logout occurred" too; only a request to /logout is a user logging out
            return ParseResult.skip("session_churn")
        action, outcome = Action.LOGOUT, Outcome.SUCCESS
    else:
        if user is None:
            # File events without a user come from cron, occ or previews, not a person
            return ParseResult.skip("system_actor")
        outcome = Outcome.SUCCESS
        if m := _FILE_OP.match(message):
            resource = _user_files_path(m["path"], user)
            action, issue = _classify_file_op(m["op"], method, url, user, resource)
            if issue:
                issues.append(issue)
        elif m := _RENAME.match(message):
            action, resource = Action.RENAME, _user_files_path(m["src"], user)
        elif m := _SHARE.match(message):
            action, resource = Action.SHARE, _user_files_path(m["path"], user)
        else:
            action = Action.OTHER
            issues.append("unmapped_message")

    return ParseResult(
        NormalizedEvent(
            event_time=event_time,
            ingest_time=ingest_time,
            action=action,
            outcome=outcome,
            provenance=Provenance(SourceSystem.NEXTCLOUD_AUDIT, raw_ref, rec.get("reqId") or None),
            user_id=user,
            client_ip=rec.get("remoteAddr") or None,
            resource=resource,
            user_agent=None if rec.get("userAgent") in _NO_USER else rec["userAgent"],
            parse_issues=tuple(issues),
        )
    )


def _classify_file_op(
    op: str, method: str | None, url: str | None, user: str, resource: str
) -> tuple[Action, str | None]:
    """Map an audit file operation to an action, using the HTTP request it came from."""
    if op == "accessed":
        return (Action.DOWNLOAD, None) if method == "GET" else (Action.ACCESS, None)
    if op == "deleted":
        return Action.DELETE, None
    # created / written to: only a write aimed at this path is the user's own upload.
    # Others are side effects, e.g. the skeleton files copied on a user's first login.
    _, target = _dav_target(url)
    if method == "PUT" and target == resource:
        return Action.UPLOAD, None
    if method == "MOVE" and url and "/remote.php/dav/uploads/" in url:
        return Action.UPLOAD, None  # chunked upload being assembled
    if method == "MKCOL" and target == resource:
        return Action.MKDIR, None
    return Action.OTHER, "side_effect_write"


# ------------------------------------------------------------------ caddy access.log
_DAV_METHOD_ACTION = {
    "GET": Action.DOWNLOAD,
    "PUT": Action.UPLOAD,
    "PROPFIND": Action.ACCESS,
    "MKCOL": Action.MKDIR,
    "MOVE": Action.RENAME,
    "DELETE": Action.DELETE,
}
_SHARE_API = "/ocs/v2.php/apps/files_sharing/api/v1/shares"


def parse_proxy(
    rec: dict[str, Any], *, raw_ref: str, ingest_time: datetime | None = None
) -> ParseResult:
    req = rec.get("request")
    event_time = _parse_time(rec.get("ts"))
    if not isinstance(req, dict) or event_time is None:
        return ParseResult.skip("invalid_record")

    method = req.get("method")
    path = _url_path(req.get("uri"))
    status = rec.get("status")
    user, resource = _dav_target(req.get("uri"))
    issues: list[str] = []

    if user is not None:
        action = _DAV_METHOD_ACTION.get(method)
        if action is None:
            return ParseResult.skip("dav_protocol_request")  # OPTIONS, PROPPATCH, ...
        issues.append("user_from_url")
    elif method == "POST" and path in _WEB_LOGIN_PATHS:
        action = Action.LOGIN
    elif method == "GET" and path in _LOGOUT_PATHS:
        action = Action.LOGOUT
    elif method == "POST" and path.startswith(_SHARE_API):
        action = Action.SHARE
    else:
        return ParseResult.skip("not_a_user_action")  # pages, assets, polling

    if not isinstance(status, int):
        outcome = Outcome.UNKNOWN
        issues.append("missing_status")
    elif action is Action.LOGIN:
        outcome = Outcome.UNKNOWN  # success and failure both answer 303; audit log decides
    else:
        outcome = Outcome.SUCCESS if status < 400 else Outcome.FAILURE

    # File bytes only for successful transfers; a 404 body is not file data
    if outcome is not Outcome.SUCCESS:
        transferred = None
    elif action is Action.UPLOAD:
        transferred = rec.get("bytes_read")
    elif action is Action.DOWNLOAD:
        transferred = rec.get("size")
    else:
        transferred = None

    agents = (req.get("headers") or {}).get("User-Agent") or [None]
    return ParseResult(
        NormalizedEvent(
            event_time=event_time,
            ingest_time=ingest_time,
            action=action,
            outcome=outcome,
            provenance=Provenance(
                SourceSystem.PROXY_ACCESS, raw_ref, rec.get("request_id") or None
            ),
            user_id=user,
            client_ip=req.get("client_ip") or None,
            resource=resource,
            user_agent=agents[0],
            response_code=status if isinstance(status, int) else None,
            bytes_transferred=transferred if isinstance(transferred, int) else None,
            parse_issues=tuple(issues),
        )
    )


def parse_record(
    location: str, rec: dict[str, Any], *, raw_ref: str, ingest_time: datetime | None = None
) -> ParseResult:
    source = SOURCE_BY_LOCATION.get(location)
    if source is SourceSystem.NEXTCLOUD_AUDIT:
        return parse_audit(rec, raw_ref=raw_ref, ingest_time=ingest_time)
    if source is SourceSystem.PROXY_ACCESS:
        return parse_proxy(rec, raw_ref=raw_ref, ingest_time=ingest_time)
    # The application log explains failures but carries no user actions of its own
    return ParseResult.skip("application_log")
