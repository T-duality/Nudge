# Hermes

This uses a fixed Hermes cron job plus local state. The cron schedule does not move. The gate script checks `next_wake_at` and only wakes the agent when due.

## Install Locally

From the repo root:

```bash
python3 Hermes/nudge/scripts/install.py --force
```

This copies:

- the skill to `~/.hermes/skills/productivity/nudge`
- `nudge_gate.py` and `nudge_state.py` to `~/.hermes/scripts`
- initial state to `~/.hermes/nudge/state.json`
- a Hermes cron job named `nudge`; if one with that name already exists, the installer updates it with the current schedule, prompt, delivery target, skill, script, and workdir
- an interactive delivery picker when a TTY is available and `--deliver` is left as `auto`
- interactive language and topic setup when a TTY is available

To install files without activating the background cron job:

```bash
python3 Hermes/nudge/scripts/install.py --force --no-create-cron
```

## Delivery Target

Default `--deliver auto` opens a numbered picker based on `~/.hermes/channel_directory.json`. It shows human-readable options such as `QQBot dm: <name> -> qqbot:<id>`. Enter selects the default option.

Non-interactive installs fall back to `local`.

Repeated installs update the existing `nudge` cron job by default. Use `--no-update-cron` to leave an existing job unchanged, or pass a different `--name` to create another job.

After a cron create or update, the installer stores the selected delivery target in `~/.hermes/nudge/state.json` as the Hermes activity source. The gate then reads `~/.hermes/state.db` to find recent `role=user` messages for the same platform/chat and applies `recent_activity_seconds` before waking the agent. When a nudge is sent, `record-decision --decision sent --message ...` also mirrors that nudge into the matching non-cron chat transcript so the next reply has context. `--no-create-cron` and `--no-update-cron` do not change that activity source.

Interactive installs ask for language and topics. English and Simplified Chinese show bundled default topics and allow customization. Custom language has no bundled defaults and requires custom topics. Non-interactive installs leave existing language/topics unchanged unless `--language` or `--topic` is passed. Language is user-configured and is not inferred from recent activity.

For local file delivery:

```bash
python3 Hermes/nudge/scripts/install.py --force --deliver local
```

For Telegram delivery, replace `local`:

```bash
python3 Hermes/nudge/scripts/install.py --force --deliver telegram
```

For a specific chat:

```bash
python3 Hermes/nudge/scripts/install.py --force --deliver qqbot:<chat-id>
```

The generated command has this shape:

```bash
hermes cron create "every 10m" \
  "Use the nudge skill. The pre-run gate output is the source of truth. If the gate wakes you, decide whether to send one short proactive message. Before your final response, update the nudge state with nudge_state.py record-decision; when sending, pass --message with the exact final user-facing nudge text so it can be mirrored into chat context. If silent, final response must start exactly with [SILENT]." \
  --name nudge \
  --deliver qqbot:<chat-id> \
  --skill nudge \
  --script nudge_gate.py \
  --workdir ~/.hermes/skills/productivity/nudge
```

## Test Without Creating Cron

Initialize state:

```bash
python3 Hermes/nudge/scripts/nudge_state.py --state /tmp/nudge/state.json init
```

Check the gate:

```bash
python3 Hermes/nudge/scripts/nudge_gate.py --state /tmp/nudge/state.json --status
```

Force a due wake:

```bash
python3 Hermes/nudge/scripts/nudge_gate.py --state /tmp/nudge/state.json --force
```

Record a silent decision:

```bash
python3 Hermes/nudge/scripts/nudge_state.py --state /tmp/nudge/state.json record-decision --decision silent --next-minutes 90 --reason "manual test"
```

Check language settings:

```bash
python3 Hermes/nudge/scripts/nudge_state.py --state /tmp/nudge/state.json language show
```

Force Chinese output for testing:

```bash
python3 Hermes/nudge/scripts/nudge_state.py --state /tmp/nudge/state.json language set zh-CN
```

Return to the default English fallback:

```bash
python3 Hermes/nudge/scripts/nudge_state.py --state /tmp/nudge/state.json language auto en
```

## Runtime Contract

When not due, disabled, in quiet hours, or recently active, `nudge_gate.py` prints a final JSON line:

```json
{"wakeAgent": false, "reason": "not_due"}
```

Hermes treats this as a silent tick.

When due, the gate prints `NUDGE_GATE_CONTEXT` and a JSON payload. It also sets `next_wake_at` to a 30 minute fallback before the agent runs. The agent should overwrite that fallback with an intentional next wake using `nudge_state.py record-decision`.

The due payload includes `language.target`. Default language is English. Topics are read exactly from state; the gate does not rewrite or translate the topic list at runtime.
