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
    "A short note or web-informed digest based on topics the user likes",
    "A poem, literary quote, or short excerpt related to a recent conversation topic",
    "A completely random signal",
]
DEFAULT_TOPICS_ZH = [
    "基于最近聊天记录的提醒、关心或轻轻追问",
    "基于用户喜欢主题的短消息或搜索整理",
    "和最近对话主题相关的诗词、名著摘句",
    "完全随机电波",
]
DEFAULT_TOPIC_TRANSLATIONS = {
    "zh": DEFAULT_TOPICS_ZH,
    "zh-CN": DEFAULT_TOPICS_ZH,
    "zh-Hans": DEFAULT_TOPICS_ZH,
}
DEFAULT_LANGUAGE = {
    "mode": "auto",
    "preferred": None,
    "fallback": "en",
    "last_detected": None,
}


def expand_path(value: str | None) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(value or os.environ.get("NUDGE_STATE", DEFAULT_STATE_PATH))).resolve()


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


def normalize_language_code(value: Any) -> str | None:
    if value is None:
        return None
    code = str(value).strip()
    if not code:
        return None
    parts = code.replace("_", "-").split("-")
    if len(parts) == 1:
        return parts[0].lower()
    return "-".join([parts[0].lower(), *[part.upper() if len(part) == 2 else part.title() for part in parts[1:]]])


def is_english_language(value: Any) -> bool:
    code = normalize_language_code(value)
    return bool(code and code.split("-", 1)[0] == "en")


def detect_language_from_text(text: str | None) -> str | None:
    if not text:
        return None
    cjk = 0
    latin = 0
    for char in text:
        point = ord(char)
        if 0x4E00 <= point <= 0x9FFF:
            cjk += 1
        elif ("A" <= char <= "Z") or ("a" <= char <= "z"):
            latin += 1
    if cjk:
        return "zh-CN"
    if latin:
        return "en"
    return None


def normalize_language(value: Any) -> dict[str, Any]:
    language = dict(DEFAULT_LANGUAGE)
    if isinstance(value, dict):
        language.update(value)
    mode = str(language.get("mode") or "auto").strip().lower()
    language["mode"] = mode if mode in {"auto", "fixed"} else "auto"
    language["preferred"] = normalize_language_code(language.get("preferred"))
    language["fallback"] = normalize_language_code(language.get("fallback")) or "en"
    language["last_detected"] = normalize_language_code(language.get("last_detected"))
    return language


def resolve_language(state: dict[str, Any]) -> str:
    language = normalize_language(state.get("language"))
    if language.get("preferred"):
        return str(language["preferred"])
    if language.get("mode") == "auto" and language.get("last_detected"):
        return str(language["last_detected"])
    return str(language.get("fallback") or "en")


def default_topic_translations(value: Any) -> dict[str, list[str]]:
    translations = {key: list(items) for key, items in DEFAULT_TOPIC_TRANSLATIONS.items()}
    if isinstance(value, dict):
        for raw_key, raw_items in value.items():
            key = normalize_language_code(raw_key)
            if key and isinstance(raw_items, list) and all(isinstance(item, str) for item in raw_items):
                translations[key] = list(raw_items)
    return translations


def topics_are_default(topics: Any) -> bool:
    items = list(topics or [])
    return items == DEFAULT_TOPICS


def topics_for_language(state: dict[str, Any], language_code: str | None = None) -> dict[str, Any]:
    topics = list(state.get("topics") or DEFAULT_TOPICS)
    target = normalize_language_code(language_code) or resolve_language(state)
    if not topics_are_default(topics):
        return {"topics": topics, "language": target, "source": "user_state", "translated": False, "translation_available": None}
    if is_english_language(target):
        return {"topics": list(DEFAULT_TOPICS), "language": target, "source": "default", "translated": False, "translation_available": True}
    translations = default_topic_translations(state.get("topic_translations"))
    translated = translations.get(target) or translations.get(target.split("-", 1)[0])
    return {
        "topics": list(translated or DEFAULT_TOPICS),
        "language": target,
        "source": "default_translated" if translated else "default_untranslated",
        "translated": bool(translated),
        "translation_available": bool(translated),
    }


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
        "topics": list(DEFAULT_TOPICS),
        "topic_translations": {key: list(items) for key, items in DEFAULT_TOPIC_TRANSLATIONS.items()},
        "history": [],
        "max_history": 50,
    }


def normalize_state(state: dict[str, Any]) -> dict[str, Any]:
    merged = {**default_state(), **state}
    if not isinstance(merged.get("topics"), list):
        merged["topics"] = list(DEFAULT_TOPICS)
    merged["language"] = normalize_language(merged.get("language"))
    merged["topic_translations"] = default_topic_translations(merged.get("topic_translations"))
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
    detected_language = detect_language_from_text(args.text)
    if detected_language:
        language = normalize_language(state.get("language"))
        language["last_detected"] = detected_language
        state["language"] = language
    state["last_user_activity_at"] = activity_at
    append_history(state, "user_activity", at_recorded=activity_at, source=args.source, detected_language=detected_language)
    save_state(path, state)
    print_json({"ok": True, "last_user_activity_at": activity_at, "detected_language": detected_language, "path": str(path)})
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
            language["fallback"] = normalize_language_code(args.value) or "en"
        event = "language_auto"
    elif args.language_action == "set":
        if not args.value:
            raise ValueError("language set requires a language code")
        language["mode"] = "fixed"
        language["preferred"] = normalize_language_code(args.value)
        event = "language_set"
    elif args.language_action == "detected":
        if not args.value:
            raise ValueError("language detected requires a language code")
        language["last_detected"] = normalize_language_code(args.value)
        event = "language_detected"
    elif args.language_action == "fallback":
        if not args.value:
            raise ValueError("language fallback requires a language code")
        language["fallback"] = normalize_language_code(args.value) or "en"
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
    if args.topic_action == "list":
        print_json({"topics": topics})
        return 0
    if args.topic_action == "add":
        if not args.value:
            raise ValueError("topic add requires a value")
        if args.value not in topics:
            topics.append(args.value)
        event = "topic_add"
    elif args.topic_action == "remove":
        if not args.value:
            raise ValueError("topic remove requires a value")
        topics = [item for item in topics if item != args.value]
        event = "topic_remove"
    else:
        raise ValueError(f"unsupported topic action: {args.topic_action}")
    state["topics"] = topics
    append_history(state, event, topic=args.value)
    save_state(path, state)
    print_json({"ok": True, "topics": topics, "path": str(path)})
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
    activity.add_argument("--text")
    activity.set_defaults(func=cmd_mark_activity)

    language = sub.add_parser("language")
    language.add_argument("language_action", choices=["show", "set", "auto", "detected", "fallback"])
    language.add_argument("value", nargs="?")
    language.set_defaults(func=cmd_language)

    topic = sub.add_parser("topic")
    topic.add_argument("topic_action", choices=["list", "add", "remove"])
    topic.add_argument("value", nargs="?")
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
