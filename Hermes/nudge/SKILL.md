---
name: nudge
description: Use when setting up or running a Hermes cron-powered autonomous nudge that decides whether to send a short proactive message, suppresses itself when not due or recently active, and records the next wake time in local state.
---

# Nudge

## Overview

This skill implements a local-first Hermes nudge for gentle autonomous check-ins. A fixed Hermes cron job wakes often, a gate script decides whether the agent should run, and the agent records each decision plus the next wake time in a state file.

## Operating Model

Do not create, edit, or delete Hermes cron jobs from inside a nudge cron run. Hermes disables recursive cron management during cron execution, and the stable pattern is a fixed scheduler plus mutable nudge state.

Use these components:

- `scripts/nudge_gate.py`: Hermes cron pre-run script. It silently skips ticks that are not due, inside quiet hours, disabled, or within the recent activity window.
- `scripts/nudge_state.py`: State editor used by the agent and by humans. It initializes state, records decisions, marks recent activity, and sets the next wake time.
- `references/state-schema.md`: State file contract.
- `references/hermes.md`: Installation and cron setup recipe.

Default state path: `~/.hermes/nudge/state.json`.

## Due Wake Workflow

When the cron pre-run script wakes the agent, use the gate output as the source of truth. The gate has already set a fallback `next_wake_at` 30 minutes in the future so a failed agent run does not create a tight loop.

1. Read the gate context injected into the prompt.
2. Decide whether a proactive message is worth sending now.
3. Before the final response, update state with `nudge_state.py record-decision`.
4. If sending a nudge, make the final response exactly the short user-facing message.
5. If not sending, make the final response start with `[SILENT]` so Hermes suppresses delivery.

Use this command shape from the skill directory or from the installed script directory:

```bash
python3 scripts/nudge_state.py record-decision \
  --decision sent \
  --message "Saw this and thought of you: take a small pause before the next thing." \
  --next-minutes 120 \
  --reason "light daytime check-in"
```

For a silent decision:

```bash
python3 scripts/nudge_state.py record-decision \
  --decision silent \
  --next-minutes 90 \
  --reason "not enough reason to interrupt"
```

## Decision Rules

- Prefer silence when the value of the message is weak.
- Keep sent messages short: one or two sentences, no report formatting.
- 消息不宜过长，避免形成阅读负担。
- Do not mention that a cron job or script woke you.
- Respect `quiet_hours`, `recent_activity_seconds`, and `enabled` from state.
- Write the final user-facing nudge in `language.target` from the gate context.
- Use the configured `topics` as inspiration, not as a rotation that must be exhausted.
- If web search is unavailable, skip search-based topics instead of inventing fresh news.
- If state looks corrupt or missing, use `nudge_state.py init` and stay silent for this tick.

## Language Rules

Default language is English. Use the language object in state:

```json
{
  "mode": "auto",
  "preferred": null,
  "fallback": "en"
}
```

Resolve output language in this order:

1. `preferred`, when set.
2. `fallback`, defaulting to `en`.

Language is configured by the user or installer; do not infer or change it from recent activity. Keep the final nudge in `language.target`. Use topics exactly as stored in state; language does not rewrite the topic list at runtime.

## Default Topic List

Use these defaults when the user's state file does not already define `topics`:

- A gentle follow-up, care note, or light question based on recent chat history
- News, progress, or trend updates about topics the user likes (web search may be used)
- A poem, literary quote, or short excerpt related to a recent conversation topic
- A completely random signal

Treat the list as a set of inspirations. Do not force a message just to use a topic.

## Scheduling Rules

After every due wake, choose the next wake time before replying:

- No message sent: usually 45 minutes to 4 hours.
- Message sent: usually 2 to 8 hours.
- Recently active user: 1 hour.
- Uncertain or tool failure: 30 minutes.
- Night or quiet hours: after the quiet period ends, with a small random delay.

The state editor accepts either relative minutes or an absolute ISO timestamp:

```bash
python3 scripts/nudge_state.py set-next --minutes 180 --reason "after sent message"
python3 scripts/nudge_state.py set-next --at "2026-05-10T18:30:00+08:00" --reason "evening follow-up"
```

## Setup Reference

For installation and the exact Hermes cron command, read `references/hermes.md`.

For the state file fields, read `references/state-schema.md`.

## Common Pitfalls

1. Do not call `cronjob(...)` or `hermes cron create/edit` during a nudge cron run.
2. Do not final-answer with explanation when the decision is silent. Start with `[SILENT]`.
3. Do not leave `next_wake_at` unset after a due wake. The gate sets a fallback, but the agent should overwrite it with an intentional schedule.
4. Do not rely on Hermes cron session memory. Cron jobs run in fresh sessions, so use the state file.
5. Do not store secrets or channel credentials in the nudge state file.
