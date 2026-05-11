#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import random
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import nudge_state  # noqa: E402


def parse_hhmm(value: str) -> tuple[int, int]:
    hour_raw, minute_raw = value.split(":", 1)
    hour = int(hour_raw)
    minute = int(minute_raw)
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        raise ValueError(f"invalid HH:MM value: {value}")
    if hour == 24 and minute != 0:
        raise ValueError(f"invalid HH:MM value: {value}")
    return hour, minute


def with_time(base: dt.datetime, hhmm: str) -> dt.datetime:
    hour, minute = parse_hhmm(hhmm)
    if hour == 24:
        return base.replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def quiet_until(now: dt.datetime, state: dict[str, Any]) -> dt.datetime | None:
    for window in state.get("quiet_hours") or []:
        if not isinstance(window, dict):
            continue
        start_raw = window.get("start")
        end_raw = window.get("end")
        if not start_raw or not end_raw:
            continue
        start = with_time(now, str(start_raw))
        end = with_time(now, str(end_raw))
        if start < end:
            if start <= now < end:
                return end
            continue
        if now >= start:
            return end + dt.timedelta(days=1)
        if now < end:
            return end
    return None


def latest_activity_from_log(path: pathlib.Path, state: dict[str, Any]) -> dt.datetime | None:
    if not path.exists() or not path.is_file():
        return None
    latest: dt.datetime | None = None
    try:
        lines = collections.deque(path.read_text(encoding="utf-8").splitlines(), maxlen=200)
    except OSError:
        return None
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("type") or item.get("event") or "").lower()
        if role not in {"user", "user_message", "message:user"}:
            continue
        raw_time = item.get("created_at") or item.get("timestamp") or item.get("at")
        if not raw_time:
            continue
        seen_at = parse_activity_time(raw_time, state)
        if not seen_at:
            continue
        if latest is None or seen_at > latest:
            latest = seen_at
    return latest


def parse_activity_time(value: Any, state: dict[str, Any]) -> dt.datetime | None:
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return parse_activity_time(int(raw), state)
    try:
        return nudge_state.parse_time(raw, state)
    except ValueError:
        return None


def normalize_target(value: Any) -> str:
    return str(value or "").strip().casefold()


def session_matches_source(key: str, meta: dict[str, Any], source: dict[str, Any]) -> bool:
    if ":cron:" in key:
        return False
    origin = meta.get("origin")
    origin = origin if isinstance(origin, dict) else {}

    channel = normalize_target(source.get("channel"))
    if channel:
        channels = {
            normalize_target(meta.get("lastChannel")),
            normalize_target(origin.get("provider")),
            normalize_target(origin.get("surface")),
        }
        if channel not in channels:
            return False

    account = normalize_target(source.get("account"))
    if account:
        accounts = {
            normalize_target(meta.get("lastAccountId")),
            normalize_target(origin.get("accountId")),
        }
        if account not in accounts:
            return False

    target = normalize_target(source.get("to"))
    if target:
        targets = {
            normalize_target(meta.get("lastTo")),
            normalize_target(origin.get("from")),
            normalize_target(origin.get("to")),
            normalize_target(origin.get("label")),
        }
        if target not in targets:
            return False

    thread_id = normalize_target(source.get("thread_id"))
    if thread_id:
        threads = {
            normalize_target(meta.get("threadId")),
            normalize_target(meta.get("lastThreadId")),
            normalize_target(origin.get("threadId")),
            normalize_target(origin.get("thread_id")),
        }
        if thread_id not in threads:
            return False

    return bool(channel or account or target or thread_id)


def latest_user_message_from_session_file(path: pathlib.Path, state: dict[str, Any]) -> dt.datetime | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        lines = collections.deque(path.read_text(encoding="utf-8").splitlines(), maxlen=400)
    except OSError:
        return None
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        message = item.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        seen_at = parse_activity_time(message.get("timestamp") or item.get("timestamp"), state)
        if seen_at:
            return seen_at
    return None


def latest_activity_from_openclaw_sessions(state: dict[str, Any]) -> dt.datetime | None:
    source = nudge_state.normalize_activity_source(state.get("activity_source"))
    if not source.get("enabled") or source.get("type") != "openclaw_sessions":
        return None
    raw_path = source.get("sessions_path")
    if not raw_path:
        return None
    sessions_path = pathlib.Path(os.path.expanduser(str(raw_path))).resolve()
    if not sessions_path.exists() or not sessions_path.is_file():
        return None
    try:
        data = json.loads(sessions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    candidates: list[dt.datetime] = []
    base_dir = sessions_path.parent
    for key, raw_meta in data.items():
        if not isinstance(raw_meta, dict) or not session_matches_source(str(key), raw_meta, source):
            continue
        raw_session_file = raw_meta.get("sessionFile")
        if not raw_session_file:
            continue
        session_file = pathlib.Path(os.path.expanduser(str(raw_session_file)))
        if not session_file.is_absolute():
            session_file = base_dir / session_file
        seen_at = latest_user_message_from_session_file(session_file, state)
        if seen_at:
            candidates.append(seen_at)
    return max(candidates) if candidates else None


def latest_activity(state: dict[str, Any], activity_log: str | None) -> dt.datetime | None:
    candidates: list[dt.datetime] = []
    raw = state.get("last_user_activity_at")
    if raw:
        seen_at = parse_activity_time(raw, state)
        if seen_at:
            candidates.append(seen_at)
    log_raw = activity_log or os.environ.get("NUDGE_ACTIVITY_LOG")
    if log_raw:
        log_seen = latest_activity_from_log(pathlib.Path(os.path.expanduser(log_raw)), state)
        if log_seen:
            candidates.append(log_seen)
    session_seen = latest_activity_from_openclaw_sessions(state)
    if session_seen:
        candidates.append(session_seen)
    return max(candidates) if candidates else None


def print_silent(reason: str, state: dict[str, Any], path: pathlib.Path, extra: dict[str, Any] | None = None) -> None:
    payload = {
        "status": "silent",
        "reason": reason,
        "state_path": str(path),
        "next_wake_at": state.get("next_wake_at"),
        "final_reply": "HEARTBEAT_OK",
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def due_payload(state: dict[str, Any], path: pathlib.Path, now: dt.datetime, reason: str) -> dict[str, Any]:
    resolved_language = nudge_state.resolve_language(state)
    topic_payload = nudge_state.topics_for_state(state)
    language_config = nudge_state.normalize_language(state.get("language"))
    return {
        "status": "due",
        "reason": reason,
        "now": nudge_state.iso(now),
        "state_path": str(path),
        "state_script": str(SCRIPT_DIR / "nudge_state.py"),
        "next_wake_at_fallback": state.get("next_wake_at"),
        "last_sent_at": state.get("last_sent_at"),
        "last_user_activity_at": state.get("last_user_activity_at"),
        "language": {
            "target": resolved_language,
            "mode": language_config.get("mode"),
            "preferred": language_config.get("preferred"),
            "fallback": language_config.get("fallback"),
        },
        "topics": topic_payload["topics"],
        "topics_source": topic_payload["source"],
        "quiet_hours": state.get("quiet_hours") or [],
        "instructions": [
            "Decide whether one short proactive message is worth sending now.",
            "Write the final user-facing nudge in language.target.",
            "Because this gate printed NUDGE_GATE_CONTEXT, run nudge_state.py record-decision before the final reply to set the next wake.",
            "If silent, final reply must be exactly HEARTBEAT_OK.",
            "If sending, final reply should be only the user-facing nudge message.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenClaw cron gate for the nudge.")
    parser.add_argument("--state", help="State path. Defaults to ~/.openclaw/nudge/state.json or $NUDGE_STATE.")
    parser.add_argument("--activity-log", help="Optional JSONL log containing user activity events.")
    parser.add_argument("--force", action="store_true", help="Print due context regardless of next_wake_at.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without writing state.")
    parser.add_argument("--status", action="store_true", help="Print status JSON without extra labels.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = nudge_state.expand_path(args.state)
    state = nudge_state.load_state(path, create=True)
    tz = nudge_state.tz_from_state(state)
    now = dt.datetime.now(tz).replace(microsecond=0)

    if not state.get("next_wake_at"):
        nudge_state.set_random_initial_wake(state)
        if not args.dry_run:
            nudge_state.save_state(path, state)
        print_silent("initial_wake_scheduled", state, path)
        return 0

    if not state.get("enabled", True):
        print_silent("disabled", state, path)
        return 0

    try:
        next_wake = nudge_state.parse_time(str(state.get("next_wake_at")), state).astimezone(tz)
    except ValueError:
        next_wake = now

    if not args.force and now < next_wake:
        print_silent("not_due", state, path, {"now": nudge_state.iso(now)})
        return 0

    recent_seen = latest_activity(state, args.activity_log)
    recent_seconds = int(state.get("recent_activity_seconds") or 300)
    if recent_seen and (now - recent_seen.astimezone(tz)).total_seconds() < recent_seconds:
        next_at = now + dt.timedelta(hours=1)
        state["next_wake_at"] = nudge_state.iso(next_at)
        state["last_gate_at"] = nudge_state.iso(now)
        nudge_state.append_history(
            state,
            "gate_silent",
            reason="recent_user_activity",
            last_user_activity_at=nudge_state.iso(recent_seen.astimezone(tz)),
            next_wake_at=state["next_wake_at"],
        )
        if not args.dry_run:
            nudge_state.save_state(path, state)
        print_silent("recent_user_activity", state, path, {"last_user_activity_at": nudge_state.iso(recent_seen.astimezone(tz))})
        return 0

    quiet_end = quiet_until(now, state)
    if quiet_end:
        next_at = quiet_end + dt.timedelta(minutes=random.randint(0, 30))
        state["next_wake_at"] = nudge_state.iso(next_at)
        state["last_gate_at"] = nudge_state.iso(now)
        nudge_state.append_history(state, "gate_silent", reason="quiet_hours", next_wake_at=state["next_wake_at"])
        if not args.dry_run:
            nudge_state.save_state(path, state)
        print_silent("quiet_hours", state, path)
        return 0

    fallback_at = now + dt.timedelta(minutes=float(state.get("fallback_minutes") or 30))
    state["last_gate_at"] = nudge_state.iso(now)
    state["last_due_at"] = nudge_state.iso(now)
    state["last_decision"] = "pending"
    state["last_reason"] = "agent due wake pending"
    state["next_wake_at"] = nudge_state.iso(fallback_at)
    nudge_state.append_history(state, "gate_due", reason="due", fallback_next_wake_at=state["next_wake_at"])
    if not args.dry_run:
        nudge_state.save_state(path, state)

    payload = due_payload(state, path, now, "forced" if args.force else "due")
    if args.status:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("NUDGE_GATE_CONTEXT")
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
