#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import random
import sys
import tempfile
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_STATE_PATH = "~/.openclaw/nudge/state.json"
DEFAULT_TOPICS = [
    "A gentle follow-up, care note, or light question based on recent chat history",
    "News, progress, or trend updates about topics the user likes (web search may be used)",
    "A poem, literary quote, or short excerpt related to a recent conversation topic",
    "A completely random signal",
]
DEFAULT_TOPICS_ZH = [
    "基于最近聊天记录的提醒、关心或轻轻追问",
    "关于用户喜欢主题的新闻、进展、动向（可用网络搜索）",
    "和最近对话主题相关的诗词、名著摘句",
    "完全随机电波",
]
DEFAULT_LANGUAGE = {
    "mode": "auto",
    "preferred": None,
    "fallback": "en",
}
GATE_SILENT_REASONS = {
    "disabled",
    "initial_wake_scheduled",
    "not_due",
    "quiet_hours",
    "recent_user_activity",
}


def expand_path(value: str | None) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(value or os.environ.get("NUDGE_STATE", DEFAULT_STATE_PATH))).resolve()


def openclaw_home() -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(os.environ.get("OPENCLAW_HOME", "~/.openclaw"))).resolve()


def default_activity_source() -> dict[str, Any]:
    home = openclaw_home()
    return {
        "enabled": False,
        "type": "none",
        "channel": None,
        "to": None,
        "account": None,
        "thread_id": None,
        "sessions_path": str(home / "agents" / "main" / "sessions" / "sessions.json"),
    }


def local_tz() -> dt.tzinfo:
    return dt.datetime.now().astimezone().tzinfo or dt.timezone.utc


def tz_from_state(state: dict[str, Any] | None = None) -> dt.tzinfo:
    tz_name = state.get("timezone") if state else None
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
    if folded in {"zh", "zh-cn", "zh-hans", "chinese", "simplified chinese", "mandarin", "中文", "汉语", "简体中文"}:
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
    source["type"] = raw_type if raw_type in {"none", "openclaw_sessions"} else "none"
    for key in ("channel", "to", "account", "thread_id", "sessions_path"):
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
    return {"topics": topics, "source": "default" if topics_are_default(topics) else "user_state"}


def default_state() -> dict[str, Any]:
    tz_name = os.environ.get("NUDGE_TIMEZONE") or getattr(local_tz(), "key", None) or "local"
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
    merged = {**default_state(), **state}
    if not isinstance(merged.get("topics"), list):
        merged["topics"] = list(DEFAULT_TOPICS)
    merged["language"] = normalize_language(merged.get("language"))
    merged["activity_source"] = normalize_activity_source(merged.get("activity_source"))
    merged.pop("topic_translations", None)
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
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"state JSON must be an object: {path}")
    return normalize_state(data)


def save_state(path: pathlib.Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_state(state)
    max_history = int(normalized.get("max_history") or 50)
    normalized["history"] = list(normalized.get("history") or [])[-max_history:]
    content = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as fh:
        fh.write(content)
        temp_name = fh.name
    pathlib.Path(temp_name).replace(path)


def append_history(state: dict[str, Any], event: str, **fields: Any) -> None:
    state.setdefault("history", []).append({"at": now_iso(state), "event": event, **fields})
    state["history"] = state["history"][-int(state.get("max_history") or 50):]


def set_random_initial_wake(state: dict[str, Any]) -> str:
    tz = tz_from_state(state)
    low = int(state.get("initial_wake_min_minutes") or 15)
    high = int(state.get("initial_wake_max_minutes") or 180)
    if high < low:
        high = low
    next_at = dt.datetime.now(tz).replace(microsecond=0) + dt.timedelta(minutes=random.randint(low, high))
    state["next_wake_at"] = iso(next_at)
    append_history(state, "initial_next_wake", next_wake_at=state["next_wake_at"])
    return state["next_wake_at"]


def resolve_next_at(args: argparse.Namespace, state: dict[str, Any]) -> str:
    if args.at and args.minutes is not None:
        raise ValueError("use either --at or --minutes, not both")
    if args.at:
        return iso(parse_time(args.at, state))
    minutes = args.minutes if args.minutes is not None else float(state.get("fallback_minutes") or 30)
    return iso(dt.datetime.now(tz_from_state(state)).replace(microsecond=0) + dt.timedelta(minutes=float(minutes)))


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def normalized_reason(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def is_stale_gate_silent_decision(args: argparse.Namespace, state: dict[str, Any]) -> bool:
    if args.decision != "silent":
        return False
    if normalized_reason(args.reason) not in GATE_SILENT_REASONS:
        return False
    return state.get("last_decision") != "pending"


def cmd_init(args: argparse.Namespace) -> int:
    path = expand_path(args.state)
    state = load_state(path, create=True)
    if args.force or not state.get("next_wake_at"):
        set_random_initial_wake(state)
    append_history(state, "init", path=str(path))
    save_state(path, state)
    print_json({"ok": True, "path": str(path), "next_wake_at": state.get("next_wake_at")})
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    print_json(load_state(expand_path(args.state), create=args.create))
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
    if is_stale_gate_silent_decision(args, state):
        print_json({
            "ok": True,
            "ignored": True,
            "reason": args.reason,
            "next_wake_at": state.get("next_wake_at"),
            "path": str(path),
        })
        return 0
    next_at = resolve_next_at(args, state)
    state["last_decision"] = args.decision
    state["last_reason"] = args.reason
    state["last_message"] = args.message
    state["next_wake_at"] = next_at
    if args.decision == "sent":
        state["last_sent_at"] = now_iso(state)
    append_history(state, "decision", decision=args.decision, reason=args.reason, message=args.message, next_wake_at=next_at)
    save_state(path, state)
    print_json({"ok": True, "decision": args.decision, "next_wake_at": next_at, "path": str(path)})
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
    print_json({"ok": True, "language": language, "resolved": resolve_language(state), "path": str(path)})
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
    elif args.activity_source_action == "openclaw-sessions":
        source["enabled"] = True
        source["type"] = "openclaw_sessions"
        for key in ("channel", "to", "account", "thread_id", "sessions_path"):
            value = getattr(args, key)
            if value is not None:
                source[key] = str(value).strip() or None
        event = "activity_source_openclaw_sessions"
    else:
        raise ValueError(f"unsupported activity source action: {args.activity_source_action}")
    state["activity_source"] = normalize_activity_source(source)
    append_history(
        state,
        event,
        channel=state["activity_source"].get("channel"),
        to=state["activity_source"].get("to"),
        account=state["activity_source"].get("account"),
    )
    save_state(path, state)
    print_json({"ok": True, "activity_source": state["activity_source"], "path": str(path)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage local state for the OpenClaw nudge.")
    parser.add_argument("--state", help=f"State path. Defaults to {DEFAULT_STATE_PATH} or $NUDGE_STATE.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    show = sub.add_parser("show")
    show.add_argument("--create", action="store_true")
    show.set_defaults(func=cmd_show)

    set_next = sub.add_parser("set-next")
    set_next.add_argument("--at")
    set_next.add_argument("--minutes", type=float)
    set_next.add_argument("--reason", default="manual schedule update")
    set_next.set_defaults(func=cmd_set_next)

    decision = sub.add_parser("record-decision")
    decision.add_argument("--decision", required=True, choices=["sent", "silent", "skipped", "error"])
    decision.add_argument("--message")
    decision.add_argument("--at")
    decision.add_argument("--minutes", type=float, dest="minutes")
    decision.add_argument("--next-minutes", type=float, dest="minutes")
    decision.add_argument("--reason", default="nudge decision")
    decision.set_defaults(func=cmd_record_decision)

    activity = sub.add_parser("mark-activity")
    activity.add_argument("--at")
    activity.add_argument("--source", default="manual")
    activity.add_argument("--text", help="Ignored. Kept so old activity hooks do not fail.")
    activity.set_defaults(func=cmd_mark_activity)

    activity_source = sub.add_parser("activity-source")
    activity_source.add_argument("activity_source_action", choices=["show", "disable", "openclaw-sessions"])
    activity_source.add_argument("--channel")
    activity_source.add_argument("--to")
    activity_source.add_argument("--account")
    activity_source.add_argument("--thread-id")
    activity_source.add_argument("--sessions-path")
    activity_source.set_defaults(func=cmd_activity_source)

    language = sub.add_parser("language")
    language.add_argument("language_action", choices=["show", "set", "auto", "fallback"])
    language.add_argument("value", nargs="?")
    language.set_defaults(func=cmd_language)

    topic = sub.add_parser("topic")
    topic.add_argument("topic_action", choices=["list", "add", "remove", "set", "reset"])
    topic.add_argument("values", nargs="*")
    topic.set_defaults(func=cmd_topic)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"nudge_state error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
