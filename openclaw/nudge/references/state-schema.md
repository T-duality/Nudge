# Nudge State Schema

Default path: `~/.openclaw/nudge/state.json`.

The state file is local runtime data. Do not commit real user state, secrets, channel IDs, or private messages.

## Fields

| Field | Type | Meaning |
|---|---:|---|
| `version` | number | Schema version. Currently `1`. |
| `enabled` | boolean | If false, the gate suppresses all ticks. |
| `timezone` | string | IANA timezone when available. Falls back to local timezone. |
| `next_wake_at` | string or null | ISO timestamp for the next due wake. |
| `last_gate_at` | string or null | Last time the gate script evaluated a tick. |
| `last_due_at` | string or null | Last time the gate allowed a due wake. |
| `last_user_activity_at` | string or null | Last known user activity. Used for the 5 minute avoidance rule. |
| `last_sent_at` | string or null | Last sent nudge time. |
| `last_decision` | string or null | `sent`, `silent`, `skipped`, `error`, or `pending`. |
| `recent_activity_seconds` | number | Activity avoidance window. Default `300`. |
| `fallback_minutes` | number | Fallback next wake if the agent fails to set one. Default `30`. |
| `quiet_hours` | array | Objects with `start` and `end` in `HH:MM`. Supports overnight windows. |
| `language` | object | Output language policy. Default fallback is English. |
| `topics` | array | User-editable topic inspirations. |
| `topic_translations` | object | Translations for the default topic list, keyed by language code. |
| `history` | array | Recent audit trail, capped by `max_history`. |

## Example

```json
{
  "version": 1,
  "enabled": true,
  "timezone": "Asia/Shanghai",
  "next_wake_at": "2026-05-10T14:30:00+08:00",
  "recent_activity_seconds": 300,
  "fallback_minutes": 30,
  "language": {
    "mode": "auto",
    "preferred": null,
    "fallback": "en",
    "last_detected": null
  },
  "quiet_hours": [
    {"start": "23:00", "end": "08:00"}
  ],
  "topics": [
    "A gentle follow-up, care note, or light question based on recent chat history",
    "A short note or web-informed digest based on topics the user likes",
    "A poem, literary quote, or short excerpt related to a recent conversation topic",
    "A completely random signal"
  ],
  "topic_translations": {
    "zh-CN": [
      "基于最近聊天记录的提醒、关心或轻轻追问",
      "基于用户喜欢主题的短消息或搜索整理",
      "和最近对话主题相关的诗词、名著摘句",
      "完全随机电波"
    ]
  },
  "history": []
}
```

## Activity Log Hook

The gate can read a JSONL file through `--activity-log` or `NUDGE_ACTIVITY_LOG`.

Each line may look like:

```json
{"role":"user","created_at":"2026-05-10T14:25:00+08:00","text":"我晚点再看"}
```

Supported role/type/event values are `user`, `user_message`, and `message:user`.
