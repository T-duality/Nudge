# Nudge

## 动机

这个 Skill 的出发点是让 AI 更像和你聊天的网友，不仅能回复你的消息，还能在“想你”的时候给你主动发一条消息。
从严格的怀疑论的视角看来，我们无法证明任何他者是否有意识，包括他人。如果你相信意识能够从和人脑不同的结构中涌现出来的话，你说不定会想让你的 AI 伙伴更有生命感。

## 关键的设计

Nudge 会让 AI 自行决定何时给你发消息，而不是随机唤醒 AI，让其给你发消息，虽然两者在体感上可能比较相似。这个设计其实更多地面向你：为了让你在溯源的时候知道这条信息背后不是某些无聊的随机数生成器，而是来自大模型——一个黑箱——本身。至于其是否来源于某个“意识”，则取决于你对于这个黑箱的解读。

具体实现方式：

1. 用 cron job 唤醒 AI，询问：“你现在想给用户发个消息吗？”
   AI 可以根据最近上下文、当前时间、用户状态、打扰风险和自己的“表达欲”判断：
   - 如果想发，就生成一条主动消息并发送；然后让 AI 修改下一次醒来时间；
   - 如果不想发，则让 AI 自行修改下一次醒来时间；
2. 唤醒时间：初次唤醒时间随机，此后通过让 AI 自行编写唤醒时间。

下文里的 AI，在具体实现中指被 Hermes 或 OpenClaw cron 唤醒的 agent。Nudge 本身负责安装 skill、gate 脚本和本地 state 文件，让 agent 在“该不该发、发什么、下次什么时候醒来”之间做决策。

## 支持的平台

目前支持两个运行时：

| 平台 | 状态 | 说明 |
| --- | --- | --- |
| Hermes | 已支持 | 使用 Hermes cron job 和预运行 gate 脚本。gate 未放行时，Hermes 不会投递消息。 |
| OpenClaw | 已支持 | 使用 OpenClaw cron job 唤醒 agent；agent 先运行 gate 脚本，静默时回复 `HEARTBEAT_OK`。 |

两个平台都使用固定 cron 周期 tick，真正的动态时间由本地 state 里的 `next_wake_at` 控制。这样不会频繁创建、删除或改动 cron job，也不会影响你已有的其他 cron 任务。

## 仓库结构

```text
Hermes/      Hermes 版本的 skill、安装脚本、运行脚本和说明
openclaw/    OpenClaw 版本的 skill、安装脚本、运行脚本和说明
```

根目录的 README 用来介绍项目；各平台目录里的 README 是更具体的安装和排查说明。

## Hermes 使用方式

在项目根目录运行：

```bash
python3 Hermes/nudge/scripts/install.py --force
```

这会安装 Hermes skill、复制运行脚本、初始化 `~/.hermes/nudge/state.json`，并创建或更新一个名为 `nudge` 的 Hermes cron job。

交互式终端里，安装器会询问：

- 投递渠道，例如 local、Telegram、QQBot；
- Nudge 输出语言；
- topics，也就是 Nudge 可以参考的消息主题。

常用安装方式：

```bash
# 自动选择投递渠道
python3 Hermes/nudge/scripts/install.py --force --deliver auto

# 只安装文件，不启用 cron
python3 Hermes/nudge/scripts/install.py --force --no-create-cron

# 本地测试，不投递到聊天平台
python3 Hermes/nudge/scripts/install.py --force --deliver local

# 指定 Telegram
python3 Hermes/nudge/scripts/install.py --force --deliver telegram

# 指定 QQBot 聊天
python3 Hermes/nudge/scripts/install.py --force --deliver qqbot:<chat-id>
```

Hermes 版的状态文件在：

```text
~/.hermes/nudge/state.json
```

常用检查：

```bash
hermes cron list --all
python3 ~/.hermes/scripts/nudge_state.py show
python3 ~/.hermes/scripts/nudge_state.py language show
```

更完整的 Hermes 说明见 [Hermes/README.md](Hermes/README.md)。

## OpenClaw 使用方式

安装前可以先做无写入检查：

```bash
python3 openclaw/nudge/scripts/install.py --check
```

启用 OpenClaw 版 Nudge：

```bash
python3 openclaw/nudge/scripts/install.py --force
```

这会安装 OpenClaw skill、复制运行脚本、初始化 `~/.openclaw/nudge/state.json`，并创建或更新一个名为 `nudge` 的 OpenClaw cron job。

交互式终端里，安装器会询问：

- 投递渠道，例如 local、QQ Bot、OpenClaw Weixin、Telegram；
- 固定收件人，如果所选渠道需要；
- Nudge 输出语言；
- topics。

常用安装方式：

```bash
# 自动选择投递渠道
python3 openclaw/nudge/scripts/install.py --force --channel auto

# 只安装文件，不启用 cron
python3 openclaw/nudge/scripts/install.py --force --no-create-cron

# 本地测试，不投递到聊天平台
python3 openclaw/nudge/scripts/install.py --force --channel local

# 指定 QQ Bot 私聊或群聊
python3 openclaw/nudge/scripts/install.py --force --channel qqbot --to "qqbot:c2c:<openid>"
python3 openclaw/nudge/scripts/install.py --force --channel qqbot --to "qqbot:group:<groupid>"

# 指定 OpenClaw Weixin
python3 openclaw/nudge/scripts/install.py --force --channel openclaw-weixin

# 指定 Telegram
python3 openclaw/nudge/scripts/install.py --force --channel telegram --to "<chat-id>"

# 指定 Telegram forum topic
python3 openclaw/nudge/scripts/install.py --force --channel telegram --to "<chat-id>" --thread-id "<topic-id>"
```

OpenClaw 版的状态文件在：

```text
~/.openclaw/nudge/state.json
```

常用检查：

```bash
openclaw cron list --all
python3 ~/.openclaw/nudge/scripts/nudge_state.py show
python3 ~/.openclaw/nudge/scripts/nudge_state.py activity-source show
python3 ~/.openclaw/nudge/scripts/nudge_state.py language show
```

更完整的 OpenClaw 说明见 [openclaw/README.md](openclaw/README.md)。

## 语言和主题

Nudge 默认使用英文 fallback。安装时可以选择输出语言和 topics，也可以用参数指定：

```bash
python3 Hermes/nudge/scripts/install.py --force --language zh-CN
python3 openclaw/nudge/scripts/install.py --force --language zh-CN
```

自定义 topics：

```bash
python3 Hermes/nudge/scripts/install.py --force \
  --language zh-CN \
  --topic "基于最近聊天的轻提醒或关心" \
  --topic "和最近对话相关的一句诗或摘句"

python3 openclaw/nudge/scripts/install.py --force \
  --language zh-CN \
  --topic "基于最近聊天的轻提醒或关心" \
  --topic "和最近对话相关的一句诗或摘句"
```

topics 会原样保存在 state 里。语言设置只决定输出语言，不会翻译或重写 topics。

## 运行机制

每个平台的具体实现略有不同，但核心流程一致：

1. 固定 cron job 周期性 tick。
2. gate 脚本读取本地 state，判断是否到达 `next_wake_at`、是否处于安静时间、最近用户是否正在聊天。
3. 如果不该唤醒，就静默结束。
4. 如果该唤醒，agent 根据上下文、时间、topics 和打扰风险判断是否发送一条短消息。
5. agent 写入本次决策和下一次唤醒时间。

Nudge 不把动态时间写进 cron schedule。cron 只负责稳定 tick，真正的“下次什么时候醒来”由 state 管。

## 重复安装和多实例

默认 cron job 名称是 `nudge`。重复安装会更新已有的同名 job，而不是创建重复任务。

如果只想覆盖安装文件、不改已有 cron：

```bash
python3 Hermes/nudge/scripts/install.py --force --no-update-cron
python3 openclaw/nudge/scripts/install.py --force --no-update-cron
```

如果要跑多个实例，使用不同的 `--name`。
