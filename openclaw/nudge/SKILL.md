---
name: nudge
description: Use when running an OpenClaw cron-powered autonomous nudge that gates frequent cron wakes, replies HEARTBEAT_OK when silent, sends only short proactive messages when useful, and records the next wake time in local state.
---

# Nudge

## Overview

This skill implements the OpenClaw Nudge workflow. A fixed OpenClaw cron job wakes the agent regularly; the agent runs `nudge_gate.py` first, then either replies `HEARTBEAT_OK` for silence or sends one short proactive nudge.

## Operating Model

Use these components:

- `scripts/nudge_gate.py`: evaluates local state and prints either a silent status or `NUDGE_GATE_CONTEXT`.
- `scripts/nudge_state.py`: initializes state, records decisions, sets next wake time, tracks activity, and manages language/topics.
- `references/state-schema.md`: state file contract.
- `references/openclaw.md`: installation and cron setup recipe.

Default state path: `~/.openclaw/nudge/state.json`.

OpenClaw cron does not have a Hermes-style pre-run script hook, so the cron job wakes the agent first. The first agent action must be running the gate script.

## Cron Wake Workflow

On every cron wake:

1. Run `python3 ~/.openclaw/nudge/scripts/nudge_gate.py`.
2. If the gate output has `"status": "silent"`, do not run `nudge_state.py record-decision`; final-answer exactly `HEARTBEAT_OK`.
3. If the gate prints `NUDGE_GATE_CONTEXT`, decide whether to send one short proactive message.
4. Before the final answer, run `nudge_state.py record-decision` to set the next wake time.
5. If sending a nudge, final-answer only the user-facing message.
6. If not sending, final-answer exactly `HEARTBEAT_OK`.

OpenClaw strips and drops OK-only `HEARTBEAT_OK` messages, so this is the silent path. Gate-silent ticks have already been handled by the gate and must not reschedule `next_wake_at`.

## Decision Rules

- Prefer `HEARTBEAT_OK` when the value of the message is weak.
- Keep sent messages short: one or two sentences, no report formatting.
- 消息不宜过长，避免形成阅读负担。
- Do not mention cron, gate scripts, state files, or wake mechanics in user-facing nudges.
- Respect `quiet_hours`, `recent_activity_seconds`, and `enabled` from state.
- Write the final user-facing nudge in `language.target` from the gate context.
- Use configured `topics` as inspiration, not as a rotation that must be exhausted.
- If web search is unavailable, skip search-based topics instead of inventing fresh news.
- If state looks corrupt or missing, initialize it and final-answer `HEARTBEAT_OK`.

## Language Rules

Default language is English. Resolve output language in this order:

1. `language.preferred`, when set.
2. `language.last_detected`, when `language.mode` is `auto`.
3. `language.fallback`, defaulting to `en`.

When the resolved language is not English and the user is still using the default topic list, the gate injects a translated topic list when a translation table is available. If no translation table exists, translate the default topics into `language.target` before using them and keep the final nudge in `language.target`.

## Default Topic List

Use these defaults when the user's state file does not already define `topics`:

- A gentle follow-up, care note, or light question based on recent chat history
- A short note or web-informed digest based on topics the user likes
- A poem, literary quote, or short excerpt related to a recent conversation topic
- A completely random signal

Treat the list as a set of inspirations. Do not force a message just to use a topic.

## Scheduling Rules

After every due wake that prints `NUDGE_GATE_CONTEXT`, choose the next wake time before replying:

- No message sent: usually 45 minutes to 4 hours.
- Message sent: usually 2 to 8 hours.
- Recently active user: 1 hour.
- Uncertain or tool failure: 30 minutes.
- Night or quiet hours: after the quiet period ends, with a small random delay.

Use:

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py record-decision --decision silent --next-minutes 90 --reason "not worth interrupting"
python3 ~/.openclaw/nudge/scripts/nudge_state.py record-decision --decision sent --message "..." --next-minutes 180 --reason "useful check-in"
```

## Common Pitfalls

1. Do not create or edit unrelated OpenClaw cron jobs.
2. Do not answer with explanations on silent ticks. Use exactly `HEARTBEAT_OK`.
3. Do not leave `next_wake_at` unset after a due wake. The gate sets a fallback, but the agent should overwrite it with an intentional schedule.
4. Do not call `record-decision` after a gate-silent response such as `not_due`, `disabled`, `quiet_hours`, or `recent_user_activity`; that would keep pushing the real wake time forward.
5. Do not rely on OpenClaw cron session memory alone. Use the state file.
6. Do not store secrets or channel credentials in the nudge state file.
