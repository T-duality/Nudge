#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import pathlib
import random
import sqlite3
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
        try:
            seen_at = nudge_state.parse_time(str(raw_time), state)
        except ValueError:
            continue
        if latest is None or seen_at > latest:
            latest = seen_at
    return latest


def matching_session_ids_from_index(source: dict[str, Any]) -> list[str]:
    sessions_path = source.get("sessions_path")
    if not sessions_path:
        return []
    path = pathlib.Path(os.path.expanduser(str(sessions_path)))
    if not path.exists() or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []

    platform = str(source.get("platform") or "").strip()
    chat_id = str(source.get("chat_id") or "").strip()
    thread_id = str(source.get("thread_id") or "").strip()
    user_id = str(source.get("user_id") or "").strip()
    matches: list[str] = []
    for raw_entry in data.values():
        if not isinstance(raw_entry, dict):
            continue
        session_id = str(raw_entry.get("session_id") or "").strip()
        if not session_id or session_id.startswith("cron_"):
            continue
        origin = raw_entry.get("origin")
        origin = origin if isinstance(origin, dict) else {}
        entry_platform = str(origin.get("platform") or raw_entry.get("platform") or "").strip()
        if platform and entry_platform != platform:
            continue
        origin_chat_id = str(origin.get("chat_id") or "").strip()
        origin_user_id = str(origin.get("user_id") or "").strip()
        origin_thread_id = str(origin.get("thread_id") or "").strip()
        if chat_id and chat_id not in {origin_chat_id, origin_user_id}:
            continue
        if thread_id and origin_thread_id != thread_id:
            continue
        if user_id and origin_user_id != user_id:
            continue
        matches.append(session_id)
    return matches


def latest_activity_from_hermes_state_db(state: dict[str, Any]) -> dt.datetime | None:
    source = nudge_state.normalize_activity_source(state.get("activity_source"))
    if not source.get("enabled") or source.get("type") != "hermes_state_db":
        return None
    db_raw = source.get("db_path")
    if not db_raw:
        return None
    db_path = pathlib.Path(os.path.expanduser(str(db_raw))).resolve()
    if not db_path.exists() or not db_path.is_file():
        return None

    platform = str(source.get("platform") or "").strip()
    chat_id = str(source.get("chat_id") or "").strip()
    user_id = str(source.get("user_id") or "").strip()
    session_ids = matching_session_ids_from_index(source)
    try:
        conn = sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None
    try:
        conn.row_factory = sqlite3.Row
        if session_ids:
            placeholders = ",".join("?" for _ in session_ids)
            query = (
                "SELECT timestamp FROM messages "
                f"WHERE role = 'user' AND session_id IN ({placeholders}) "
                "ORDER BY timestamp DESC LIMIT 1"
            )
            params: list[str] = session_ids
        else:
            where = ["m.role = 'user'", "s.source != 'cron'"]
            params = []
            if platform:
                where.append("s.source = ?")
                params.append(platform)
            user_filter = user_id or chat_id
            if user_filter:
                where.append("s.user_id = ?")
                params.append(user_filter)
            query = (
                "SELECT m.timestamp FROM messages m "
                "JOIN sessions s ON s.id = m.session_id "
                f"WHERE {' AND '.join(where)} "
                "ORDER BY m.timestamp DESC LIMIT 1"
            )
        row = conn.execute(query, params).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    try:
        seen_at = dt.datetime.fromtimestamp(float(row["timestamp"]), dt.timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
    return seen_at


def latest_activity(state: dict[str, Any], activity_log: str | None) -> dt.datetime | None:
    candidates: list[dt.datetime] = []
    raw = state.get("last_user_activity_at")
    if raw:
        try:
            candidates.append(nudge_state.parse_time(str(raw), state))
        except ValueError:
            pass
    log_raw = activity_log or os.environ.get("NUDGE_ACTIVITY_LOG")
    if log_raw:
        log_seen = latest_activity_from_log(pathlib.Path(os.path.expanduser(log_raw)), state)
        if log_seen:
            candidates.append(log_seen)
    hermes_seen = latest_activity_from_hermes_state_db(state)
    if hermes_seen:
        candidates.append(hermes_seen)
    return max(candidates) if candidates else None


def print_silent(reason: str, state: dict[str, Any], path: pathlib.Path, extra: dict[str, Any] | None = None) -> None:
    payload = {
        "status": "silent",
        "reason": reason,
        "state_path": str(path),
        "next_wake_at": state.get("next_wake_at"),
    }
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    print(json.dumps({"wakeAgent": False, "reason": reason}, sort_keys=True))


def due_payload(state: dict[str, Any], path: pathlib.Path, now: dt.datetime, reason: str) -> dict[str, Any]:
    resolved_language = nudge_state.resolve_language(state)
    topic_payload = nudge_state.topics_for_state(state)
    language_config = nudge_state.normalize_language(state.get("language"))
    return {
        "status": "due",
        "reason": reason,
        "now": nudge_state.iso(now),
        "state_path": str(path),
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
            "Before the final response, run nudge_state.py record-decision to set the next wake.",
            "If silent, make the final response start with [SILENT].",
            "If sending, final response should be only the user-facing nudge message.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hermes cron gate for the nudge.")
    parser.add_argument("--state", help="State path. Defaults to ~/.hermes/nudge/state.json or $NUDGE_STATE.")
    parser.add_argument("--activity-log", help="Optional JSONL log containing user activity events.")
    parser.add_argument("--force", action="store_true", help="Wake the agent regardless of next_wake_at.")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without writing state.")
    parser.add_argument("--status", action="store_true", help="Print gate status without Hermes wakeAgent suppression line.")
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
        if args.status:
            print(json.dumps({"status": "initialized", "state_path": str(path), "next_wake_at": state.get("next_wake_at")}, indent=2))
        else:
            print_silent("initial_wake_scheduled", state, path)
        return 0

    if not state.get("enabled", True):
        if args.status:
            print(json.dumps({"status": "disabled", "state_path": str(path)}, indent=2))
        else:
            print_silent("disabled", state, path)
        return 0

    try:
        next_wake = nudge_state.parse_time(str(state.get("next_wake_at")), state).astimezone(tz)
    except ValueError:
        next_wake = now

    if not args.force and now < next_wake:
        if args.status:
            print(json.dumps({"status": "not_due", "now": nudge_state.iso(now), "next_wake_at": nudge_state.iso(next_wake)}, indent=2))
        else:
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
        if args.status:
            print(json.dumps({"status": "recent_user_activity", "next_wake_at": state["next_wake_at"]}, indent=2))
        else:
            print_silent("recent_user_activity", state, path, {"last_user_activity_at": nudge_state.iso(recent_seen.astimezone(tz))})
        return 0

    quiet_end = quiet_until(now, state)
    if quiet_end:
        jitter_minutes = random.randint(0, 30)
        next_at = quiet_end + dt.timedelta(minutes=jitter_minutes)
        state["next_wake_at"] = nudge_state.iso(next_at)
        state["last_gate_at"] = nudge_state.iso(now)
        nudge_state.append_history(state, "gate_silent", reason="quiet_hours", next_wake_at=state["next_wake_at"])
        if not args.dry_run:
            nudge_state.save_state(path, state)
        if args.status:
            print(json.dumps({"status": "quiet_hours", "next_wake_at": state["next_wake_at"]}, indent=2))
        else:
            print_silent("quiet_hours", state, path)
        return 0

    fallback_minutes = float(state.get("fallback_minutes") or 30)
    fallback_at = now + dt.timedelta(minutes=fallback_minutes)
    state["last_gate_at"] = nudge_state.iso(now)
    state["last_due_at"] = nudge_state.iso(now)
    state["last_decision"] = "pending"
    state["last_reason"] = "agent due wake pending"
    state["next_wake_at"] = nudge_state.iso(fallback_at)
    nudge_state.append_history(state, "gate_due", reason="due", fallback_next_wake_at=state["next_wake_at"])
    if not args.dry_run:
        nudge_state.save_state(path, state)

    payload = due_payload(state, path, now, "forced" if args.force else "due")
    print("NUDGE_GATE_CONTEXT")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
