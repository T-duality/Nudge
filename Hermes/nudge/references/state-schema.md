# Nudge State Schema

Default path: `~/.hermes/nudge/state.json`.

The state file is local runtime data. Do not commit real user state, secrets, channel IDs, or private messages.

## Fields

| Field | Type | Meaning |
|---|---:|---|
| `version` | number | Schema version. Currently `1`. |
| `enabled` | boolean | If false, the gate suppresses all ticks. |
| `timezone` | string | IANA timezone when available. Falls back to local timezone. |
| `next_wake_at` | string or null | ISO timestamp for the next due wake. |
| `last_gate_at` | string or null | Last time the gate script evaluated a tick. |
| `last_due_at` | string or null | Last time the gate allowed an agent wake. |
| `last_user_activity_at` | string or null | Last known user activity. Used for the 5 minute avoidance rule. |
| `last_sent_at` | string or null | Last sent nudge time. |
| `last_decision` | string or null | `sent`, `silent`, `skipped`, `error`, or `pending`. |
| `last_reason` | string or null | Short reason for the last schedule or decision. |
| `last_message` | string or null | Last sent message or null for silent decisions. |
| `recent_activity_seconds` | number | Activity avoidance window. Default `300`. |
| `activity_source` | object | Optional read-only activity source. Hermes installs can read `~/.hermes/state.db` for recent user messages matching the configured delivery target. |
| `fallback_minutes` | number | Fallback next wake if the agent fails to set one. Default `30`. |
| `initial_wake_min_minutes` | number | Lower bound for first randomized wake. |
| `initial_wake_max_minutes` | number | Upper bound for first randomized wake. |
| `quiet_hours` | array | Objects with `start` and `end` in `HH:MM`. Supports overnight windows. |
| `language` | object | Output language policy. Default fallback is English. |
| `topics` | array | User-editable topic inspirations. |
| `history` | array | Recent audit trail, capped by `max_history`. |
| `max_history` | number | Number of history entries to retain. |

## Example

```json
{
  "version": 1,
  "enabled": true,
  "timezone": "Asia/Shanghai",
  "next_wake_at": "2026-05-10T14:30:00+08:00",
  "last_user_activity_at": null,
  "recent_activity_seconds": 300,
  "activity_source": {
    "enabled": true,
    "type": "hermes_state_db",
    "platform": "qqbot",
    "chat_id": "<chat-id>",
    "thread_id": null,
    "user_id": null,
    "db_path": "~/.hermes/state.db",
    "sessions_path": "~/.hermes/sessions/sessions.json"
  },
  "fallback_minutes": 30,
  "language": {
    "mode": "auto",
    "preferred": null,
    "fallback": "en"
  },
  "quiet_hours": [
    {"start": "23:00", "end": "08:00"}
  ],
  "topics": [
    "A gentle follow-up, care note, or light question based on recent chat history",
    "News, progress, or trend updates about topics the user likes (web search may be used)",
    "A poem, literary quote, or short excerpt related to a recent conversation topic",
    "A completely random signal"
  ],
  "history": []
}
```

## Activity Log Hook

The gate can read user activity from three places:

- `last_user_activity_at` in this state file, usually written by `mark-activity`
- Hermes `~/.hermes/state.db`, when `activity_source.type` is `hermes_state_db`
- a JSONL file through `--activity-log` or `NUDGE_ACTIVITY_LOG`

For recent-activity avoidance, the Hermes SQLite source is read-only. It joins `messages` to `sessions`, filters `messages.role = 'user'`, excludes cron sessions, and matches the configured platform/chat when available. It uses the latest matching user message timestamp for the recent-activity avoidance rule.

For sent nudges, `record-decision --decision sent --message ...` also best-effort mirrors the nudge into the matching non-cron Hermes chat session. This writes a small assistant `delivery-mirror` row to the chat transcript and SQLite state DB, then refreshes the session index timestamp so the next user reply stays on that session and has the nudge in context.

Each line may look like:

```json
{"role":"user","created_at":"2026-05-10T14:25:00+08:00"}
```

Supported role/type/event values are `user`, `user_message`, and `message:user`.
