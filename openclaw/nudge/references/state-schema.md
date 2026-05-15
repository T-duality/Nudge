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
| `activity_source` | object | Optional read-only activity source. OpenClaw installs can read matching session JSONL files for recent user message timestamps. |
| `fallback_minutes` | number | Fallback next wake if the agent fails to set one. Default `30`. |
| `quiet_hours` | array | Objects with `start` and `end` in `HH:MM`. Supports overnight windows. |
| `language` | object | Output language policy. Default fallback is English. |
| `topics` | array | User-editable topic inspirations. |
| `history` | array | Recent audit trail, capped by `max_history`. |

## Example

```json
{
  "version": 1,
  "enabled": true,
  "timezone": "Asia/Shanghai",
  "next_wake_at": "2026-05-10T14:30:00+08:00",
  "recent_activity_seconds": 300,
  "activity_source": {
    "enabled": true,
    "type": "openclaw_sessions",
    "channel": "qqbot",
    "to": "qqbot:c2c:<openid>",
    "account": "default",
    "thread_id": null,
    "sessions_path": "~/.openclaw/agents/main/sessions/sessions.json"
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

## Activity Sources

The gate can read user activity from three places:

- `last_user_activity_at` in this state file, usually written by `mark-activity`
- OpenClaw session files, when `activity_source.type` is `openclaw_sessions`
- a JSONL file through `--activity-log` or `NUDGE_ACTIVITY_LOG`

For recent-activity avoidance, the OpenClaw session source is read-only. It reads `sessions.json`, filters out cron sessions, matches the configured channel/target/account, then reads the matching session JSONL for the latest `type=message` event whose nested `message.role` is `user`. It uses only timestamps and does not use message content.

For sent nudges, `record-decision --decision sent --message ...` also best-effort mirrors the nudge into the matching non-cron OpenClaw chat transcript using OpenClaw's transcript append API. This writes a context-visible assistant message, then refreshes the session index freshness fields (`updatedAt`, `lastInteractionAt`, and daily-reset `sessionStartedAt` when needed) so the next user reply stays on that session and can see the nudge in context. Do not mark this mirror as OpenClaw's `delivery-mirror` or `gateway-injected` model; OpenClaw treats those models as transcript-only and removes them from replay history.

Each line may look like:

```json
{"role":"user","created_at":"2026-05-10T14:25:00+08:00","text":"我晚点再看"}
```

Supported role/type/event values are `user`, `user_message`, and `message:user`.
