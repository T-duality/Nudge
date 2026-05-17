# Nudge

[简体中文](README.md) | [English](README.en.md)

## Motivation

This skill is built around a simple idea: make AI feel more like an online friend you chat with, not only something that replies when you message it, but something that can also send you a message when it "misses" you.

From a strictly skeptical point of view, we cannot prove whether any other being is conscious, including other humans. If you believe consciousness may emerge from structures unlike the human brain, you may also want your AI companion to feel a little more alive.

## Key Design

Nudge lets the AI decide when to message you, instead of randomly waking the AI and forcing it to send something. The two may feel similar in practice, but the design is aimed more at your interpretation of the message: when you trace the message back to its source, it should feel less like a boring random-number generator and more like it came from the model, a black box, itself. Whether that black box has anything like "consciousness" is left to your own reading.

The mechanism is:

1. Use a cron job to wake the AI and ask: "Do you want to send the user a message right now?"
   The AI can judge from recent context, current time, user state, interruption risk, and its own "urge to speak":
   - If yes, it generates and sends one proactive message, then chooses the next wake time.
   - If no, it still chooses the next wake time.
2. The first wake time is randomized. After that, the AI writes its own next wake time.

## Supported Platforms

Nudge currently supports two runtimes:

| Platform | Status | Notes |
| --- | --- | --- |
| Hermes | Supported | Uses a Hermes cron job plus a pre-run gate script. If the gate does not allow the wake, Hermes does not deliver a message. |
| OpenClaw | Supported | Uses an OpenClaw cron job to wake the agent. The agent runs the gate script first, and replies `HEARTBEAT_OK` when silent. |

Both platforms use a stable fixed cron tick. The real dynamic timing is controlled by `next_wake_at` in local state, so Nudge does not need to keep creating, deleting, or editing cron jobs, and it does not interfere with your other cron tasks.

## Repository Layout

```text
Hermes/      Hermes skill, installer, runtime scripts, and docs
openclaw/    OpenClaw skill, installer, runtime scripts, and docs
```

The root README introduces the project. The README files under each platform directory contain platform-specific installation and troubleshooting notes.

## Hermes Usage

Run this from the repository root:

```bash
python3 Hermes/nudge/scripts/install.py --force
```

This installs the Hermes skill, copies runtime scripts, initializes `~/.hermes/nudge/state.json`, and creates or updates a Hermes cron job named `nudge`.

In an interactive terminal, the installer asks for:

- delivery target, such as local, Telegram, or QQBot;
- Nudge output language;
- topics, which are the message inspirations Nudge may use.

Hermes state file:

```text
~/.hermes/nudge/state.json
```

For more Hermes details, see [Hermes/README.md](Hermes/README.md).

## OpenClaw Usage

You can run a no-write check first:

```bash
python3 openclaw/nudge/scripts/install.py --check
```

To enable OpenClaw Nudge:

```bash
python3 openclaw/nudge/scripts/install.py --force
```

This installs the OpenClaw skill, copies runtime scripts, initializes `~/.openclaw/nudge/state.json`, and creates or updates an OpenClaw cron job named `nudge`.

In an interactive terminal, the installer asks for:

- delivery channel, such as local, QQ Bot, OpenClaw Weixin, or Telegram;
- fixed recipient, if required by the selected channel;
- Nudge output language;
- topics.

OpenClaw state file:

```text
~/.openclaw/nudge/state.json
```

For more OpenClaw details, see [openclaw/README.md](openclaw/README.md).

## Language And Topics

Nudge uses English as the default fallback language. During installation, you can choose both the output language and the topics for outgoing nudges.

Built-in default topics currently exist only for two languages:

English:

1. A gentle follow-up, care note, or light question based on recent chat history
2. News, progress, or trend updates about topics the user likes (web search may be used)
3. A poem, literary quote, or short excerpt related to a recent conversation topic
4. A completely random signal

Simplified Chinese:

1. 基于最近聊天记录的提醒、关心或轻轻追问
2. 关于用户喜欢话题的新闻、进展、动向（可用网络搜索）
3. 和最近对话话题相关的诗词、名著摘句
4. 完全随机电波

Other languages do not have built-in default topics. You must enter topics manually during installation.

You can later modify topics with the built-in commands:

Hermes:

```bash
# Show current topics
python3 ~/.hermes/scripts/nudge_state.py topic list

# Replace current topics with a new list
python3 ~/.hermes/scripts/nudge_state.py topic set "Topic 1" "Topic 2"

# Add one topic
python3 ~/.hermes/scripts/nudge_state.py topic add "New topic"

# Remove one topic
python3 ~/.hermes/scripts/nudge_state.py topic remove "Old topic"

# Reset to English default topics
python3 ~/.hermes/scripts/nudge_state.py topic reset
```

OpenClaw:

```bash
# Show current topics
python3 ~/.openclaw/nudge/scripts/nudge_state.py topic list

# Replace current topics with a new list
python3 ~/.openclaw/nudge/scripts/nudge_state.py topic set "Topic 1" "Topic 2"

# Add one topic
python3 ~/.openclaw/nudge/scripts/nudge_state.py topic add "New topic"

# Remove one topic
python3 ~/.openclaw/nudge/scripts/nudge_state.py topic remove "Old topic"

# Reset to English default topics
python3 ~/.openclaw/nudge/scripts/nudge_state.py topic reset
```

You can also edit `state.json` manually:

```text
Hermes:   ~/.hermes/nudge/state.json
OpenClaw: ~/.openclaw/nudge/state.json
```

Find the `topics` field and change it to the list of topics you want Nudge to use:

```json
{
  "topics": [
    "A gentle follow-up, care note, or light question based on recent chat history",
    "News, progress, or trend updates about topics the user likes",
    "A poem, literary quote, or short excerpt related to a recent conversation topic",
    "A completely random signal"
  ]
}
```

The real `state.json` contains other fields. Do not replace the whole file with the snippet above; only edit the `topics` array. Keep the file valid JSON: use double quotes for strings and do not add a trailing comma after the last item.

## Runtime Model

The two platform implementations differ in details, but the core flow is the same:

1. A fixed cron job ticks periodically.
2. The gate script reads local state and checks whether `next_wake_at` is due, whether quiet hours apply, and whether the user has been active recently.
3. If the agent should not wake, the tick exits silently.
4. If the agent should wake, it decides from context, time, topics, and interruption risk whether to send one short message.
5. The agent records the decision and the next wake time.

Nudge does not write dynamic timing into the cron schedule. Cron only provides a stable tick; local state controls when the next real wake should happen.

## Reinstalling And Multiple Instances

The default cron job name is `nudge`. Reinstalling updates the existing job with the same name instead of creating duplicates.

To update installed files without changing an existing cron job:

```bash
python3 Hermes/nudge/scripts/install.py --force --no-update-cron
python3 openclaw/nudge/scripts/install.py --force --no-update-cron
```

To run multiple instances, use a different `--name`.
