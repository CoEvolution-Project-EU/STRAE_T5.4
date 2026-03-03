from datetime import datetime, timezone


def utc_now_datetime() -> datetime:
    return datetime.now(timezone.utc)
    # return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()
