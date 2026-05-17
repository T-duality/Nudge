#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import random
import sqlite3
import sys
import tempfile
import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_STATE_PATH = "~/.hermes/nudge/state.json"
DEFAULT_TOPICS = [
    "A gentle follow-up, care note, or light question based on recent chat history",
    "News, progress, or trend updates about topics the user likes (web search may be used)",
    "A poem, literary quote, or short excerpt related to a recent conversation topic",
    "A completely random signal",
]
DEFAULT_TOPICS_ZH = [
    "基于最近聊天记录的提醒、关心或轻轻追问",
    "关于用户喜欢话题的新闻、进展、动向（可用网络搜索）",
    "和最近对话话题相关的诗词、名著摘句",
    "完全随机电波",
]
DEFAULT_LANGUAGE = {
    "mode": "auto",
    "preferred": None,
    "fallback": "en",
}


def expand_path(value: str | None) -> pathlib.Path:
    return pathlib.Path(
        os.path.expanduser(value or os.environ.get("NUDGE_STATE", DEFAULT_STATE_PATH))
    ).resolve()


def hermes_home() -> pathlib.Path:
    return pathlib.Path(
        os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
    ).resolve()


def default_activity_source() -> dict[str, Any]:
    home = hermes_home()
    return {
        "enabled": False,
        "type": "none",
        "platform": None,
        "chat_id": None,
        "thread_id": None,
        "user_id": None,
        "db_path": str(home / "state.db"),
        "sessions_path": str(home / "sessions" / "sessions.json"),
    }


def local_tz() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def tz_from_state(state: dict[str, Any] | None = None) -> dt.tzinfo:
    tz_name = None
    if state:
        tz_name = state.get("timezone")
    tz_name = tz_name or os.environ.get("NUDGE_TIMEZONE")
    if tz_name:
        try:
            return ZoneInfo(str(tz_name))
        except ZoneInfoNotFoundError:
            return local_tz()
    return local_tz()


def now_iso(state: dict[str, Any] | None = None) -> str:
    return dt.datetime.now(tz_from_state(state)).replace(microsecond=0).isoformat()


def parse_time(value: str, state: dict[str, Any] | None = None) -> dt.datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz_from_state(state))
    return parsed


def iso(value: dt.datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def canonical_bundled_language(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    folded = raw.casefold().replace("_", "-")
    if folded in {"en", "en-us", "en-gb", "english"}:
        return "en"
    if folded in {
        "zh",
        "zh-cn",
        "zh-hans",
        "chinese",
        "simplified chinese",
        "mandarin",
        "中文",
        "汉语",
        "简体中文",
    }:
        return "zh-CN"
    return None


def normalize_language_name(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    return canonical_bundled_language(raw) or raw


def normalize_language(value: Any) -> dict[str, Any]:
    language = dict(DEFAULT_LANGUAGE)
    if isinstance(value, dict):
        for key in DEFAULT_LANGUAGE:
            if key in value:
                language[key] = value[key]
    mode = str(language.get("mode") or "auto").strip().lower()
    language["mode"] = mode if mode in {"auto", "fixed"} else "auto"
    language["preferred"] = normalize_language_name(language.get("preferred"))
    language["fallback"] = normalize_language_name(language.get("fallback")) or "en"
    return language


def normalize_activity_source(value: Any) -> dict[str, Any]:
    source = default_activity_source()
    if isinstance(value, dict):
        source.update(value)
    source["enabled"] = bool(source.get("enabled"))
    raw_type = str(source.get("type") or "none").strip().lower()
    source["type"] = raw_type if raw_type in {"none", "hermes_state_db"} else "none"
    for key in (
        "platform",
        "chat_id",
        "thread_id",
        "user_id",
        "db_path",
        "sessions_path",
    ):
        raw = source.get(key)
        source[key] = str(raw).strip() if raw is not None and str(raw).strip() else None
    if source["type"] == "none":
        source["enabled"] = False
    return source


def resolve_language(state: dict[str, Any]) -> str:
    language = normalize_language(state.get("language"))
    if language.get("preferred"):
        return str(language["preferred"])
    return str(language.get("fallback") or "en")


def topics_are_default(topics: Any) -> bool:
    items = list(topics or [])
    return items == DEFAULT_TOPICS


def topics_for_state(state: dict[str, Any]) -> dict[str, Any]:
    topics = list(state.get("topics") or DEFAULT_TOPICS)
    return {
        "topics": topics,
        "source": "default" if topics_are_default(topics) else "user_state",
    }


def default_state() -> dict[str, Any]:
    tz_name = (
        os.environ.get("NUDGE_TIMEZONE") or getattr(local_tz(), "key", None) or "local"
    )
    return {
        "version": 1,
        "enabled": True,
        "timezone": tz_name,
        "next_wake_at": None,
        "last_gate_at": None,
        "last_due_at": None,
        "last_user_activity_at": None,
        "last_sent_at": None,
        "last_decision": None,
        "last_reason": None,
        "last_message": None,
        "recent_activity_seconds": 300,
        "fallback_minutes": 30,
        "initial_wake_min_minutes": 15,
        "initial_wake_max_minutes": 180,
        "quiet_hours": [{"start": "23:00", "end": "08:00"}],
        "language": dict(DEFAULT_LANGUAGE),
        "activity_source": default_activity_source(),
        "topics": list(DEFAULT_TOPICS),
        "history": [],
        "max_history": 50,
    }


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    base = default_state()
    merged = {**base, **state}
    if not isinstance(merged.get("topics"), list):
        merged["topics"] = list(DEFAULT_TOPICS)
    merged["language"] = normalize_language(merged.get("language"))
    merged["activity_source"] = normalize_activity_source(merged.get("activity_source"))
    if not isinstance(merged.get("quiet_hours"), list):
        merged["quiet_hours"] = []
    if not isinstance(merged.get("history"), list):
        merged["history"] = []
    return merged


def load_state(path: pathlib.Path, create: bool = False) -> dict[str, Any]:
    if not path.exists():
        if create:
            return default_state()
        raise FileNotFoundError(f"state file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid state JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"state JSON must be an object: {path}")
    return normalize_state(data)


def save_state(path: pathlib.Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_state(state)
    max_history = int(normalized.get("max_history") or 50)
    normalized["history"] = list(normalized.get("history") or [])[-max_history:]
    content = (
        json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as fh:
        fh.write(content)
        temp_name = fh.name
    pathlib.Path(temp_name).replace(path)


def append_history(state: dict[str, Any], event: str, **fields: Any) -> None:
    item = {"at": now_iso(state), "event": event, **fields}
    state.setdefault("history", []).append(item)
    max_history = int(state.get("max_history") or 50)
    state["history"] = state["history"][-max_history:]


def context_injection_id(runtime: str, decision_at: str, message: str) -> str:
    digest = hashlib.sha256(f"{runtime}\n{decision_at}\n{message}".encode("utf-8")).hexdigest()
    return f"nudge:{digest[:24]}"


def parse_sort_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return 0.0
    raw = str(value).strip()
    if not raw:
        return 0.0
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def find_hermes_mirror_session(source: dict[str, Any]) -> tuple[str, pathlib.Path] | None:
    platform = str(source.get("platform") or "").strip()
    chat_id = str(source.get("chat_id") or "").strip()
    thread_id = str(source.get("thread_id") or "").strip()
    user_id = str(source.get("user_id") or "").strip()
    if not platform or not (chat_id or user_id):
        return None

    sessions_raw = source.get("sessions_path")
    if not sessions_raw:
        return None
    sessions_path = pathlib.Path(os.path.expanduser(str(sessions_raw))).resolve()
    try:
        data = json.loads(sessions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    candidates: list[tuple[float, str, dict[str, Any]]] = []
    platform_lower = platform.lower()
    for key, raw_entry in data.items():
        if ":cron:" in str(key):
            continue
        if not isinstance(raw_entry, dict):
            continue
        session_id = str(raw_entry.get("session_id") or raw_entry.get("sessionId") or "").strip()
        if not session_id or session_id.startswith("cron_"):
            continue
        origin = raw_entry.get("origin")
        origin = origin if isinstance(origin, dict) else {}
        entry_platform = str(origin.get("platform") or raw_entry.get("platform") or "").strip().lower()
        if entry_platform != platform_lower:
            continue

        origin_chat_id = str(origin.get("chat_id") or "").strip()
        origin_user_id = str(origin.get("user_id") or raw_entry.get("user_id") or "").strip()
        origin_thread_id = str(origin.get("thread_id") or "").strip()
        if chat_id and chat_id not in {origin_chat_id, origin_user_id}:
            continue
        if user_id and origin_user_id != user_id:
            continue
        if thread_id and origin_thread_id != thread_id:
            continue
        updated = parse_sort_time(raw_entry.get("updated_at") or raw_entry.get("updatedAt") or raw_entry.get("created_at"))
        candidates.append((updated, session_id, raw_entry))

    if not candidates:
        return None
    if not user_id:
        distinct_users = {
            str(((entry.get("origin") if isinstance(entry.get("origin"), dict) else {}) or {}).get("user_id") or entry.get("user_id") or "").strip()
            for _updated, _session_id, entry in candidates
        }
        distinct_users.discard("")
        if len(distinct_users) > 1:
            return None

    candidates.sort(reverse=True, key=lambda item: item[0])
    return candidates[0][1], sessions_path.parent


def transcript_has_nudge_injection(path: pathlib.Path, injection_id: str, message: str) -> bool:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return False
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if item.get("nudge_injection_id") == injection_id:
            return True
        item_time = parse_sort_time(item.get("timestamp"))
        is_recent = not item_time or time.time() - item_time < 600
        if is_recent and item.get("mirror_source") == "nudge" and item.get("content") == message:
            return True
    return False


def append_hermes_transcript_mirror(
    session_id: str,
    sessions_dir: pathlib.Path,
    message: str,
    decision_at: str,
    injection_id: str,
) -> tuple[bool, str | None]:
    transcript_path = sessions_dir / f"{session_id}.jsonl"
    if transcript_has_nudge_injection(transcript_path, injection_id, message):
        return True, "duplicate"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    mirror_message = {
        "role": "assistant",
        "content": message,
        "timestamp": now_iso(),
        "mirror": True,
        "mirror_source": "nudge",
        "nudge_injection_id": injection_id,
        "nudge_decision_at": decision_at,
    }
    try:
        with open(transcript_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(mirror_message, ensure_ascii=False) + "\n")
    except OSError as exc:
        return False, str(exc)
    return True, None


def append_hermes_sqlite_mirror(
    db_path: pathlib.Path,
    session_id: str,
    message: str,
) -> tuple[bool, str | None]:
    if not db_path.exists():
        return False, "state db not found"
    try:
        conn = sqlite3.connect(str(db_path), timeout=1.0)
    except sqlite3.Error as exc:
        return False, str(exc)
    try:
        conn.execute("PRAGMA busy_timeout=1000")
        row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return False, "session not found in state db"
        duplicate = conn.execute(
            "SELECT id FROM messages WHERE session_id = ? AND role = 'assistant' "
            "AND content = ? AND timestamp > ? ORDER BY timestamp DESC LIMIT 1",
            (session_id, message, time.time() - 600),
        ).fetchone()
        if duplicate:
            return True, "duplicate"
        with conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, "assistant", message, time.time()),
            )
            conn.execute(
                "UPDATE sessions SET message_count = message_count + 1 WHERE id = ?",
                (session_id,),
            )
    except sqlite3.Error as exc:
        return False, str(exc)
    finally:
        conn.close()
    return True, None


def touch_hermes_session_index(source: dict[str, Any], session_id: str, touched_at: str) -> tuple[bool, str | None]:
    sessions_raw = source.get("sessions_path")
    if not sessions_raw:
        return False, "sessions path missing"
    sessions_path = pathlib.Path(os.path.expanduser(str(sessions_raw))).resolve()
    try:
        data = json.loads(sessions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, str(exc)
    if not isinstance(data, dict):
        return False, "sessions index is not an object"

    changed = False
    for raw_entry in data.values():
        if not isinstance(raw_entry, dict):
            continue
        entry_session_id = str(raw_entry.get("session_id") or raw_entry.get("sessionId") or "").strip()
        if entry_session_id != session_id:
            continue
        raw_entry["updated_at"] = touched_at
        changed = True
    if not changed:
        return False, "session not found in sessions index"

    content = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(sessions_path.parent), delete=False) as fh:
            fh.write(content)
            temp_name = fh.name
        pathlib.Path(temp_name).replace(sessions_path)
    except OSError as exc:
        return False, str(exc)
    return True, None


def inject_sent_context(state: dict[str, Any], message: str | None, decision_at: str) -> dict[str, Any]:
    if not message:
        return {"enabled": False, "reason": "missing message"}
    source = normalize_activity_source(state.get("activity_source"))
    if not source.get("enabled") or source.get("type") != "hermes_state_db":
        return {"enabled": False, "reason": "activity source disabled"}

    session = find_hermes_mirror_session(source)
    if not session:
        return {"enabled": True, "ok": False, "reason": "no matching session"}
    session_id, sessions_dir = session
    injection_id = context_injection_id("hermes", decision_at, message)
    jsonl_ok, jsonl_error = append_hermes_transcript_mirror(
        session_id,
        sessions_dir,
        message,
        decision_at,
        injection_id,
    )
    db_raw = source.get("db_path") or str(hermes_home() / "state.db")
    db_ok, db_error = append_hermes_sqlite_mirror(
        pathlib.Path(os.path.expanduser(str(db_raw))).resolve(),
        session_id,
        message,
    )
    touch_ok, touch_error = touch_hermes_session_index(source, session_id, decision_at)
    result: dict[str, Any] = {
        "enabled": True,
        "ok": bool(jsonl_ok or db_ok),
        "runtime": "hermes",
        "session_id": session_id,
        "session_index_touched": touch_ok,
    }
    if jsonl_error:
        result["jsonl_error"] = jsonl_error
    if db_error:
        result["db_error"] = db_error
    if touch_error:
        result["session_index_error"] = touch_error
    return result


def set_random_initial_wake(state: dict[str, Any]) -> str:
    tz = tz_from_state(state)
    low = int(state.get("initial_wake_min_minutes") or 15)
    high = int(state.get("initial_wake_max_minutes") or 180)
    if high < low:
        high = low
    next_at = dt.datetime.now(tz).replace(microsecond=0) + dt.timedelta(
        minutes=random.randint(low, high)
    )
    state["next_wake_at"] = iso(next_at)
    append_history(state, "initial_next_wake", next_wake_at=state["next_wake_at"])
    return state["next_wake_at"]


def resolve_next_at(args: argparse.Namespace, state: dict[str, Any]) -> str:
    if args.at and args.minutes is not None:
        raise ValueError("use either --at or --minutes, not both")
    if args.at:
        return iso(parse_time(args.at, state))
    if args.minutes is not None:
        tz = tz_from_state(state)
        next_at = dt.datetime.now(tz).replace(microsecond=0) + dt.timedelta(
            minutes=float(args.minutes)
        )
        return iso(next_at)
    fallback = float(state.get("fallback_minutes") or 30)
    tz = tz_from_state(state)
    return iso(
        dt.datetime.now(tz).replace(microsecond=0) + dt.timedelta(minutes=fallback)
    )


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_init(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    if args.force or not state.get("next_wake_at"):
        set_random_initial_wake(state)
    append_history(state, "init", path=str(path))
    save_state(path, state)
    print_json(
        {"ok": True, "path": str(path), "next_wake_at": state.get("next_wake_at")}
    )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=args.create)
    print_json(state)
    return 0


def cmd_set_next(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    next_at = resolve_next_at(args, state)
    state["next_wake_at"] = next_at
    state["last_reason"] = args.reason
    append_history(state, "set_next", next_wake_at=next_at, reason=args.reason)
    save_state(path, state)
    print_json({"ok": True, "path": str(path), "next_wake_at": next_at})
    return 0


def cmd_record_decision(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    next_at = resolve_next_at(args, state)
    decision_at = now_iso(state)
    state["last_decision"] = args.decision
    state["last_reason"] = args.reason
    state["last_message"] = args.message
    state["next_wake_at"] = next_at
    if args.decision == "sent":
        state["last_sent_at"] = decision_at
    context_injection = None
    if args.decision == "sent":
        context_injection = inject_sent_context(state, args.message, decision_at)
    append_history(
        state,
        "decision",
        decision=args.decision,
        reason=args.reason,
        message=args.message,
        next_wake_at=next_at,
        context_injection=context_injection,
    )
    save_state(path, state)
    output = {
        "ok": True,
        "decision": args.decision,
        "next_wake_at": next_at,
        "path": str(path),
    }
    if context_injection is not None:
        output["context_injection"] = context_injection
    print_json(output)
    return 0


def cmd_mark_activity(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    activity_at = iso(parse_time(args.at, state)) if args.at else now_iso(state)
    state["last_user_activity_at"] = activity_at
    append_history(state, "user_activity", at_recorded=activity_at, source=args.source)
    save_state(path, state)
    print_json({"ok": True, "last_user_activity_at": activity_at, "path": str(path)})
    return 0


def cmd_language(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    language = normalize_language(state.get("language"))
    if args.language_action == "show":
        print_json({"language": language, "resolved": resolve_language(state)})
        return 0
    if args.language_action == "auto":
        language["mode"] = "auto"
        language["preferred"] = None
        if args.value:
            language["fallback"] = normalize_language_name(args.value) or "en"
        event = "language_auto"
    elif args.language_action == "set":
        if not args.value:
            raise ValueError("language set requires a language")
        language["mode"] = "fixed"
        language["preferred"] = normalize_language_name(args.value)
        event = "language_set"
    elif args.language_action == "fallback":
        if not args.value:
            raise ValueError("language fallback requires a language")
        language["fallback"] = normalize_language_name(args.value) or "en"
        event = "language_fallback"
    else:
        raise ValueError(f"unsupported language action: {args.language_action}")
    state["language"] = language
    append_history(state, event, value=args.value, resolved=resolve_language(state))
    save_state(path, state)
    print_json(
        {
            "ok": True,
            "language": language,
            "resolved": resolve_language(state),
            "path": str(path),
        }
    )
    return 0


def cmd_topic(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    topics = list(state.get("topics") or [])
    values = list(args.values or [])
    if args.topic_action == "list":
        print_json({"topics": topics})
        return 0
    if args.topic_action == "add":
        if len(values) != 1:
            raise ValueError("topic add requires exactly one value")
        if values[0] not in topics:
            topics.append(values[0])
        event = "topic_add"
    elif args.topic_action == "remove":
        if len(values) != 1:
            raise ValueError("topic remove requires exactly one value")
        topics = [item for item in topics if item != values[0]]
        event = "topic_remove"
    elif args.topic_action == "set":
        if not values:
            raise ValueError("topic set requires at least one value")
        topics = values
        event = "topic_set"
    elif args.topic_action == "reset":
        topics = list(DEFAULT_TOPICS)
        event = "topic_reset"
    else:
        raise ValueError(f"unsupported topic action: {args.topic_action}")
    state["topics"] = topics
    append_history(state, event, topics=topics)
    save_state(path, state)
    print_json({"ok": True, "topics": topics, "path": str(path)})
    return 0


def cmd_activity_source(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    source = normalize_activity_source(state.get("activity_source"))
    if args.activity_source_action == "show":
        print_json({"activity_source": source})
        return 0
    if args.activity_source_action == "disable":
        source["enabled"] = False
        source["type"] = "none"
        event = "activity_source_disable"
    elif args.activity_source_action == "hermes-state-db":
        source["enabled"] = True
        source["type"] = "hermes_state_db"
        for key in (
            "platform",
            "chat_id",
            "thread_id",
            "user_id",
            "db_path",
            "sessions_path",
        ):
            value = getattr(args, key)
            if value is not None:
                source[key] = str(value).strip() or None
        event = "activity_source_hermes_state_db"
    else:
        raise ValueError(
            f"unsupported activity source action: {args.activity_source_action}"
        )
    state["activity_source"] = normalize_activity_source(source)
    append_history(
        state,
        event,
        platform=state["activity_source"].get("platform"),
        chat_id=state["activity_source"].get("chat_id"),
        user_id=state["activity_source"].get("user_id"),
    )
    save_state(path, state)
    print_json(
        {"ok": True, "activity_source": state["activity_source"], "path": str(path)}
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage local state for the Hermes nudge."
    )
    parser.add_argument(
        "--state", help=f"State path. Defaults to {DEFAULT_STATE_PATH} or $NUDGE_STATE."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create or normalize the state file.")
    init.add_argument(
        "--force",
        action="store_true",
        help="Replace next_wake_at with a new randomized initial wake.",
    )
    init.set_defaults(func=cmd_init)

    show = sub.add_parser("show", help="Print current state JSON.")
    show.add_argument(
        "--create",
        action="store_true",
        help="Print defaults if the state file does not exist.",
    )
    show.set_defaults(func=cmd_show)

    set_next = sub.add_parser("set-next", help="Set the next wake time.")
    set_next.add_argument("--at", help="Absolute ISO timestamp.")
    set_next.add_argument("--minutes", type=float, help="Minutes from now.")
    set_next.add_argument("--reason", default="manual schedule update")
    set_next.set_defaults(func=cmd_set_next)

    decision = sub.add_parser(
        "record-decision", help="Record a due wake decision and set next wake."
    )
    decision.add_argument(
        "--decision", required=True, choices=["sent", "silent", "skipped", "error"]
    )
    decision.add_argument("--message", default=None)
    decision.add_argument("--at", help="Absolute ISO timestamp for next wake.")
    decision.add_argument(
        "--minutes", type=float, dest="minutes", help="Minutes from now for next wake."
    )
    decision.add_argument(
        "--next-minutes", type=float, dest="minutes", help="Alias for --minutes."
    )
    decision.add_argument("--reason", default="nudge decision")
    decision.set_defaults(func=cmd_record_decision)

    activity = sub.add_parser("mark-activity", help="Record recent user activity.")
    activity.add_argument(
        "--at", help="Activity time as ISO timestamp. Defaults to now."
    )
    activity.add_argument("--source", default="manual")
    activity.add_argument(
        "--text", help="Ignored. Kept so old activity hooks do not fail."
    )
    activity.set_defaults(func=cmd_mark_activity)

    activity_source = sub.add_parser(
        "activity-source", help="Show or configure recent activity sources."
    )
    activity_source.add_argument(
        "activity_source_action", choices=["show", "disable", "hermes-state-db"]
    )
    activity_source.add_argument("--platform")
    activity_source.add_argument("--chat-id")
    activity_source.add_argument("--thread-id")
    activity_source.add_argument("--user-id")
    activity_source.add_argument("--db-path")
    activity_source.add_argument("--sessions-path")
    activity_source.set_defaults(func=cmd_activity_source)

    language = sub.add_parser("language", help="Show or set language preferences.")
    language.add_argument(
        "language_action", choices=["show", "set", "auto", "fallback"]
    )
    language.add_argument("value", nargs="?")
    language.set_defaults(func=cmd_language)

    topic = sub.add_parser("topic", help="List, add, or remove topics.")
    topic.add_argument(
        "topic_action", choices=["list", "add", "remove", "set", "reset"]
    )
    topic.add_argument("values", nargs="*")
    topic.set_defaults(func=cmd_topic)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"nudge_state error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
