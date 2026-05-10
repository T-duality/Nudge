# OpenClaw

This uses a fixed OpenClaw cron job plus local state. The cron schedule does not move. The agent wakes, runs the gate script, then either replies `HEARTBEAT_OK` or sends a short nudge.

## Install Locally

From the repo root:

```bash
python3 openclaw/nudge/scripts/install.py --force
```

This copies:

- the skill to `~/.openclaw/skills/nudge`
- runtime scripts to `~/.openclaw/nudge/scripts`
- initial state to `~/.openclaw/nudge/state.json`
- a cron job named `nudge`; if one with that name already exists, the installer updates it with the current schedule, message, channel, tools, and session settings

To install files without activating the background cron job:

```bash
python3 openclaw/nudge/scripts/install.py --force --no-create-cron
```

To check the install plan without writing files or changing cron:

```bash
python3 openclaw/nudge/scripts/install.py --check
```

The check reports target paths, whether the `openclaw` CLI is available, whether a cron job with the requested name already exists, and the planned cron command. During a real install, cron creation/update requires a successful `openclaw cron list --all --json` lookup; if that lookup fails, the installer stops instead of risking a duplicate cron job. Use `--no-create-cron` to install files only.

## Delivery Target

Default delivery uses `--channel last`, which asks OpenClaw to deliver alerts to the last usable chat route.

For a specific channel:

```bash
python3 openclaw/nudge/scripts/install.py --force --channel telegram --to "<chat-id>"
```

For testing without creating cron:

```bash
python3 openclaw/nudge/scripts/install.py --force --no-create-cron
```

Repeated installs update the existing `nudge` cron job by default. Use `--no-update-cron` to leave an existing job unchanged, or pass a different `--name` to create another job.

## Test Without Cron

Initialize state:

```bash
python3 openclaw/nudge/scripts/nudge_state.py --state /tmp/openclaw-nudge/state.json init
```

Check the gate:

```bash
python3 openclaw/nudge/scripts/nudge_gate.py --state /tmp/openclaw-nudge/state.json
```

Force a due wake:

```bash
python3 openclaw/nudge/scripts/nudge_gate.py --state /tmp/openclaw-nudge/state.json --force
```

Record a silent decision:

```bash
python3 openclaw/nudge/scripts/nudge_state.py --state /tmp/openclaw-nudge/state.json record-decision --decision silent --next-minutes 90 --reason "manual test"
```

## Runtime Contract

When not due, disabled, in quiet hours, or recently active, `nudge_gate.py` prints:

```json
{"status": "silent", "final_reply": "HEARTBEAT_OK"}
```

The agent must final-answer exactly `HEARTBEAT_OK`. OpenClaw drops OK-only `HEARTBEAT_OK` messages, making this the silent path.

When due, the gate prints `NUDGE_GATE_CONTEXT` and a JSON payload. It also sets `next_wake_at` to a 30 minute fallback before the agent runs. The agent should overwrite that fallback with an intentional next wake using `nudge_state.py record-decision`.
