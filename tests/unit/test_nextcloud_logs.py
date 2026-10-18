from ueba.adapters import nextcloud_logs
from ueba.domain.events import Action, Outcome


def parse_audit(rec):
    return nextcloud_logs.parse_audit(rec, raw_ref="test")


def parse_proxy(rec):
    return nextcloud_logs.parse_proxy(rec, raw_ref="test")


DAV = "/remote.php/dav/files/alice"


def audit(message, *, user="alice", method="GET", url=f"{DAV}/a.txt", **extra):
    return {
        "reqId": "r1",
        "time": "2026-10-18T10:00:00.5+00:00",
        "remoteAddr": "36.86.63.1",
        "user": user,
        "method": method,
        "url": url,
        "message": message,
        "userAgent": "ua",
        **extra,
    }


def proxy(method, uri, status, **extra):
    return {
        "ts": 1792318800.25,
        "request_id": "r1",
        "status": status,
        "size": 10,
        "bytes_read": 20,
        "request": {
            "client_ip": "36.86.63.1",
            "method": method,
            "uri": uri,
            "headers": {"User-Agent": ["ua"]},
        },
        **extra,
    }


def test_web_login_vs_per_request_auth():
    web = parse_audit(
        audit('Login successful: "alice"', user="--", method="POST", url="/login")
    ).event
    dav = parse_audit(
        audit('Login successful: "alice"', user="--", method="PROPFIND", url=f"{DAV}/")
    ).event
    assert (web.action, web.outcome, web.user_id) == (Action.LOGIN, Outcome.SUCCESS, "alice")
    assert dav.action is Action.AUTH


def test_failed_login_takes_user_from_message():
    event = parse_audit(
        audit('Login failed: "alice"', user="--", method="POST", url="/login")
    ).event
    assert (event.action, event.outcome, event.user_id) == (Action.LOGIN, Outcome.FAILURE, "alice")


def test_logout_only_counts_for_logout_requests():
    assert (
        parse_audit(audit("Logout occurred", url="/logout?requesttoken=x")).event.action
        is Action.LOGOUT
    )
    assert parse_audit(audit("Logout occurred", method="PUT")).skip_reason == "session_churn"


def test_upload_requires_put_to_the_same_path():
    msg = 'File with id "5" written to: "/alice/files/a.txt"'
    assert parse_audit(audit(msg, method="PUT")).event.action is Action.UPLOAD
    # skeleton files copied during a first request are side effects, not uploads
    side = parse_audit(
        audit('File with id "6" created: "/alice/files/Readme.md"', method="MKCOL")
    ).event
    assert side.action is Action.OTHER and "side_effect_write" in side.parse_issues


def test_download_and_system_access():
    msg = 'File with id "5" accessed: "/alice/files/a.txt"'
    event = parse_audit(audit(msg)).event
    assert (event.action, event.resource) == (Action.DOWNLOAD, "/a.txt")
    assert parse_audit(audit(msg, user="--", method="")).skip_reason == "system_actor"


def test_noise_is_counted_not_parsed():
    reasons = {
        parse_audit(audit(m)).skip_reason
        for m in (
            'Cache entry inserted for fileid "1", path "files" on storageid "4"',
            'Login attempt: "alice"',
            "Interaction OCP\\Interaction\\Actions\\ShareAction from user alice on 5 to x",
        )
    }
    assert reasons == {"internal_cache", "login_attempt_precursor", "share_interaction_duplicate"}


def test_proxy_failed_download_has_no_file_bytes():
    event = parse_proxy(proxy("GET", f"{DAV}/missing.txt", 404)).event
    assert (event.action, event.outcome, event.user_id) == (
        Action.DOWNLOAD,
        Outcome.FAILURE,
        "alice",
    )
    assert event.bytes_transferred is None


def test_proxy_bytes_direction():
    assert parse_proxy(proxy("PUT", f"{DAV}/a.txt", 201)).event.bytes_transferred == 20
    assert parse_proxy(proxy("GET", f"{DAV}/a.txt", 200)).event.bytes_transferred == 10


def test_proxy_login_outcome_is_unknown_and_assets_skipped():
    assert parse_proxy(proxy("POST", "/login", 303)).event.outcome is Outcome.UNKNOWN
    assert (
        parse_proxy(proxy("GET", "/apps/files/js/main.js", 200)).skip_reason == "not_a_user_action"
    )
    assert parse_proxy(proxy("OPTIONS", f"{DAV}/", 200)).skip_reason == "dav_protocol_request"


def test_query_strings_never_reach_the_event():
    event = parse_proxy(proxy("GET", f"{DAV}/a.txt?token=secret", 200)).event
    assert event.resource == "/a.txt"
