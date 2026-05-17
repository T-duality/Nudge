#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import random
import shutil
import subprocess
import sys
import tempfile
import time
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
    "关于用户喜欢话题的新闻、进展、动向（可用网络搜索）",
    "和最近对话话题相关的诗词、名著摘句",
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


def context_injection_id(runtime: str, decision_at: str, message: str) -> str:
    digest = hashlib.sha256(f"{runtime}\n{decision_at}\n{message}".encode("utf-8")).hexdigest()
    return f"nudge:{digest[:24]}"


def parse_sort_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        raw = float(value)
        return raw / 1000 if raw > 10_000_000_000 else raw
    if value is None:
        return 0.0
    raw = str(value).strip()
    if not raw:
        return 0.0
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def openclaw_config_path(source: dict[str, Any]) -> pathlib.Path:
    raw_path = source.get("sessions_path")
    if raw_path:
        sessions_path = pathlib.Path(os.path.expanduser(str(raw_path))).resolve()
        try:
            return sessions_path.parents[3] / "openclaw.json"
        except IndexError:
            pass
    return openclaw_home() / "openclaw.json"


def normalize_reset_mode(value: Any) -> str | None:
    raw = str(value or "").strip().lower()
    return raw if raw in {"daily", "idle"} else None


def normalize_reset_hour(value: Any) -> int:
    try:
        hour = int(value)
    except (TypeError, ValueError):
        return 4
    return min(23, max(0, hour))


def openclaw_reset_policy(source: dict[str, Any]) -> tuple[str, int]:
    try:
        cfg = json.loads(openclaw_config_path(source).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "daily", 4
    session_cfg = cfg.get("session") if isinstance(cfg, dict) else None
    session_cfg = session_cfg if isinstance(session_cfg, dict) else {}
    base_reset = session_cfg.get("reset")
    base_reset = base_reset if isinstance(base_reset, dict) else None
    reset_by_type = session_cfg.get("resetByType")
    reset_by_type = reset_by_type if isinstance(reset_by_type, dict) else {}
    type_reset = reset_by_type.get("direct") or reset_by_type.get("dm")
    type_reset = type_reset if isinstance(type_reset, dict) else None
    reset_by_channel = session_cfg.get("resetByChannel")
    reset_by_channel = reset_by_channel if isinstance(reset_by_channel, dict) else {}
    channel = str(source.get("channel") or "").strip().lower()
    channel_reset = reset_by_channel.get(channel)
    channel_reset = channel_reset if isinstance(channel_reset, dict) else None

    selected = channel_reset or type_reset or base_reset
    has_explicit_reset = bool(base_reset or type_reset or channel_reset or reset_by_type or reset_by_channel)
    mode = normalize_reset_mode(selected.get("mode") if selected else None)
    if not mode:
        mode = "idle" if not has_explicit_reset and session_cfg.get("idleMinutes") is not None else "daily"
    at_hour = normalize_reset_hour(selected.get("atHour") if selected else None)
    return mode, at_hour


def daily_reset_boundary_ms(now_ms: int, at_hour: int) -> int:
    now = dt.datetime.fromtimestamp(now_ms / 1000, local_tz())
    reset_at = now.replace(hour=normalize_reset_hour(at_hour), minute=0, second=0, microsecond=0)
    if now < reset_at:
        reset_at -= dt.timedelta(days=1)
    return int(reset_at.timestamp() * 1000)


def normalize_match_value(value: Any) -> str:
    return str(value or "").strip().casefold()


def openclaw_session_matches_source(key: str, meta: dict[str, Any], source: dict[str, Any]) -> bool:
    if ":cron:" in key:
        return False
    origin = meta.get("origin")
    origin = origin if isinstance(origin, dict) else {}
    delivery = meta.get("deliveryContext")
    delivery = delivery if isinstance(delivery, dict) else {}

    channel = normalize_match_value(source.get("channel"))
    if channel:
        channels = {
            normalize_match_value(meta.get("lastChannel")),
            normalize_match_value(origin.get("provider")),
            normalize_match_value(origin.get("surface")),
            normalize_match_value(delivery.get("channel")),
        }
        if channel not in channels:
            return False

    account = normalize_match_value(source.get("account"))
    if account:
        accounts = {
            normalize_match_value(meta.get("lastAccountId")),
            normalize_match_value(origin.get("accountId")),
            normalize_match_value(delivery.get("accountId")),
            normalize_match_value(delivery.get("account")),
        }
        if account not in accounts:
            return False

    target = normalize_match_value(source.get("to"))
    if target:
        targets = {
            normalize_match_value(meta.get("lastTo")),
            normalize_match_value(origin.get("from")),
            normalize_match_value(origin.get("to")),
            normalize_match_value(origin.get("label")),
            normalize_match_value(delivery.get("to")),
        }
        if target not in targets:
            return False

    thread_id = normalize_match_value(source.get("thread_id"))
    if thread_id:
        threads = {
            normalize_match_value(meta.get("threadId")),
            normalize_match_value(meta.get("lastThreadId")),
            normalize_match_value(origin.get("threadId")),
            normalize_match_value(origin.get("thread_id")),
            normalize_match_value(delivery.get("threadId")),
            normalize_match_value(delivery.get("thread_id")),
        }
        if thread_id not in threads:
            return False

    return bool(channel or account or target or thread_id)


def openclaw_session_target(meta: dict[str, Any]) -> str:
    origin = meta.get("origin")
    origin = origin if isinstance(origin, dict) else {}
    delivery = meta.get("deliveryContext")
    delivery = delivery if isinstance(delivery, dict) else {}
    return normalize_match_value(meta.get("lastTo") or delivery.get("to") or origin.get("to") or origin.get("from") or origin.get("label"))


def find_openclaw_mirror_session(source: dict[str, Any]) -> tuple[str, str, pathlib.Path] | None:
    raw_path = source.get("sessions_path")
    if not raw_path:
        return None
    sessions_path = pathlib.Path(os.path.expanduser(str(raw_path))).resolve()
    try:
        data = json.loads(sessions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    candidates: list[tuple[float, str, str, pathlib.Path, dict[str, Any]]] = []
    base_dir = sessions_path.parent
    for key, raw_meta in data.items():
        if not isinstance(raw_meta, dict) or not openclaw_session_matches_source(str(key), raw_meta, source):
            continue
        session_id = str(raw_meta.get("sessionId") or raw_meta.get("session_id") or "").strip()
        session_key = str(key).strip()
        raw_session_file = raw_meta.get("sessionFile")
        if not session_id or not session_key or not raw_session_file:
            continue
        session_file = pathlib.Path(os.path.expanduser(str(raw_session_file)))
        if not session_file.is_absolute():
            session_file = base_dir / session_file
        updated = parse_sort_time(raw_meta.get("updatedAt") or raw_meta.get("updated_at") or raw_meta.get("lastInteractionAt"))
        candidates.append((updated, session_key, session_id, session_file, raw_meta))

    if not candidates:
        return None
    if not str(source.get("to") or "").strip():
        distinct_targets = {openclaw_session_target(meta) for *_prefix, meta in candidates}
        distinct_targets.discard("")
        if len(distinct_targets) > 1:
            return None

    candidates.sort(reverse=True, key=lambda item: item[0])
    _updated, session_key, session_id, session_file, _meta = candidates[0]
    return session_key, session_id, session_file


def transcript_nudge_injection_status(path: pathlib.Path, injection_id: str, message: str) -> str | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-400:]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        msg = item.get("message")
        if not isinstance(msg, dict):
            continue
        provider = str(msg.get("provider") or "").strip()
        model = str(msg.get("model") or "").strip()
        if msg.get("idempotencyKey") == injection_id:
            if provider == "openclaw" and model in {"delivery-mirror", "gateway-injected"}:
                return "transcript_only"
            return "visible"
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        texts = [str(part.get("text") or "").strip() for part in content if isinstance(part, dict) and part.get("type") == "text"]
        if "\n".join(text for text in texts if text).strip() != message.strip():
            continue
        item_time = parse_sort_time(item.get("timestamp") or msg.get("timestamp"))
        is_recent = not item_time or time.time() - item_time < 600
        if not is_recent:
            continue
        if not provider and not model:
            return "visible"
        if provider == "openclaw" and model == "delivery-mirror":
            return "transcript_only"
    return None


def openclaw_agent_harness_module() -> pathlib.Path | None:
    candidates: list[pathlib.Path] = []
    package_dir = os.environ.get("OPENCLAW_PACKAGE_DIR")
    if package_dir:
        candidates.append(pathlib.Path(os.path.expanduser(package_dir)) / "dist" / "plugin-sdk" / "agent-harness.js")
    openclaw_bin = shutil.which("openclaw")
    if openclaw_bin:
        resolved = pathlib.Path(openclaw_bin).resolve()
        candidates.append(resolved.parent / "dist" / "plugin-sdk" / "agent-harness.js")
        candidates.append(resolved.parent.parent / "openclaw" / "dist" / "plugin-sdk" / "agent-harness.js")
    candidates.extend([
        pathlib.Path("/opt/homebrew/lib/node_modules/openclaw/dist/plugin-sdk/agent-harness.js"),
        pathlib.Path("/usr/local/lib/node_modules/openclaw/dist/plugin-sdk/agent-harness.js"),
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def append_openclaw_transcript_with_node(
    session_key: str,
    session_id: str,
    session_file: pathlib.Path,
    message: str,
    injection_id: str,
) -> tuple[bool, str | None]:
    module = openclaw_agent_harness_module()
    if module is None:
        return False, "openclaw agent-harness module not found"
    node = shutil.which("node")
    if not node:
        return False, "node not found on PATH"

    payload = {
        "moduleUrl": module.as_uri(),
        "sessionKey": session_key,
        "sessionId": session_id,
        "sessionFile": str(session_file),
        "now": int(time.time() * 1000),
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": message}],
            # OpenClaw excludes openclaw/delivery-mirror assistant messages from replay history.
            # Leave provider/model unset so the proactive nudge is visible to the next turn.
            "usage": {
                "input": 0,
                "output": 0,
                "cacheRead": 0,
                "cacheWrite": 0,
                "totalTokens": 0,
                "cost": {
                    "input": 0,
                    "output": 0,
                    "cacheRead": 0,
                    "cacheWrite": 0,
                    "total": 0,
                },
            },
            "stopReason": "stop",
            "timestamp": int(time.time() * 1000),
            "idempotencyKey": injection_id,
        },
    }
    script = """
let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const input = JSON.parse(raw);
const mod = await import(input.moduleUrl);
const result = await mod.appendSessionTranscriptMessage({
  transcriptPath: input.sessionFile,
  sessionId: input.sessionId,
  message: input.message,
  now: input.now,
  config: { session: { writeLock: { acquireTimeoutMs: 5000 } } }
});
process.stdout.write(JSON.stringify({ ok: true, messageId: result.messageId }));
"""
    try:
        result = subprocess.run(
            [node, "--input-type=module", "-e", script],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return False, detail or f"node exited with {result.returncode}"
    return True, None


def touch_openclaw_session_index(
    source: dict[str, Any],
    session_key: str,
    session_id: str,
    session_file: pathlib.Path,
) -> tuple[bool, str | None]:
    raw_path = source.get("sessions_path")
    if not raw_path:
        return False, "sessions path missing"
    sessions_path = pathlib.Path(os.path.expanduser(str(raw_path))).resolve()
    try:
        data = json.loads(sessions_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, str(exc)
    if not isinstance(data, dict):
        return False, "sessions index is not an object"

    entry = data.get(session_key)
    if not isinstance(entry, dict):
        return False, "session key not found in sessions index"
    entry_session_id = str(entry.get("sessionId") or entry.get("session_id") or "").strip()
    if entry_session_id != session_id:
        return False, "session id changed in sessions index"
    now_ms = int(time.time() * 1000)
    entry["updatedAt"] = now_ms
    entry["lastInteractionAt"] = now_ms
    reset_mode, reset_at_hour = openclaw_reset_policy(source)
    session_started_ms = int(parse_sort_time(entry.get("sessionStartedAt")) * 1000)
    if reset_mode == "daily" and session_started_ms < daily_reset_boundary_ms(now_ms, reset_at_hour):
        entry["sessionStartedAt"] = now_ms
    entry["sessionFile"] = str(session_file)

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
    if not source.get("enabled") or source.get("type") != "openclaw_sessions":
        return {"enabled": False, "reason": "activity source disabled"}

    session = find_openclaw_mirror_session(source)
    if not session:
        return {"enabled": True, "ok": False, "reason": "no matching session"}
    session_key, session_id, session_file = session
    injection_id = context_injection_id("openclaw", decision_at, message)
    existing_injection = transcript_nudge_injection_status(session_file, injection_id, message)
    if existing_injection == "visible":
        touch_ok, touch_error = touch_openclaw_session_index(source, session_key, session_id, session_file)
        return {
            "enabled": True,
            "ok": True,
            "runtime": "openclaw",
            "context_visible": True,
            "session_key": session_key,
            "session_id": session_id,
            "duplicate": True,
            "session_index_touched": touch_ok,
            **({"session_index_error": touch_error} if touch_error else {}),
        }
    ok, error = append_openclaw_transcript_with_node(
        session_key,
        session_id,
        session_file,
        message,
        injection_id,
    )
    touch_ok, touch_error = touch_openclaw_session_index(source, session_key, session_id, session_file)
    result: dict[str, Any] = {
        "enabled": True,
        "ok": ok,
        "runtime": "openclaw",
        "context_visible": ok,
        "session_key": session_key,
        "session_id": session_id,
        "session_index_touched": touch_ok,
    }
    if error:
        result["error"] = error
    if touch_error:
        result["session_index_error"] = touch_error
    if existing_injection == "transcript_only":
        result["replaced_transcript_only"] = True
    return result


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
    context_injection = None
    if args.decision == "sent":
        context_injection = inject_sent_context(state, args.message, state["last_sent_at"])
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
    output = {"ok": True, "decision": args.decision, "next_wake_at": next_at, "path": str(path)}
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
