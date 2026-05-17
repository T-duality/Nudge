# OpenClaw Nudge

OpenClaw 版 Nudge 使用固定 cron job 周期性唤醒 agent。agent 每次先运行本地 gate 脚本；如果未到真正唤醒时间，就回复 `HEARTBEAT_OK` 静默结束；如果到点，再决定是否发送一条短消息。
gate 返回静默时不会再次写 state；只有真正到点并输出 `NUDGE_GATE_CONTEXT` 后，agent 才会记录本次决策和下一次唤醒时间。

## 安装并启用

在项目根目录运行：

```bash
python3 openclaw/nudge/scripts/install.py --force
```

这会：

- 安装 skill 到 `~/.openclaw/skills/nudge`
- 安装运行脚本到 `~/.openclaw/nudge/scripts/`
- 初始化 state 到 `~/.openclaw/nudge/state.json`
- 创建或更新一个名为 `nudge` 的 OpenClaw cron job
- 在交互式终端里显示投递平台数字选择菜单
- 在交互式终端里询问输出语言和话题（topics）；非交互环境默认不改已有偏好

如果已存在同名 cron job，安装脚本会用本次选择的投递渠道、schedule、message、tools 和 session 设置更新它，避免重复；需要多实例时传不同的 `--name`。

创建或更新 cron 成功后，安装器会把本次选择的投递目标记录到 `~/.openclaw/nudge/state.json` 的 `activity_source`。gate 会只读 `~/.openclaw/agents/main/sessions/sessions.json` 和匹配的 session JSONL，只使用 `message.role=user` 的时间戳判断最近活动，不读取或使用消息内容。发送 nudge 时，`record-decision --decision sent --message ...` 会尽力用 OpenClaw 的 transcript append API 把这条 nudge 作为上下文可见的 assistant 消息镜像进同一聊天的非 cron 会话记录，并刷新 session 索引里的 freshness 时间，让用户后续回复时 AI 能看到刚刚主动发出的内容。这里不能使用 OpenClaw 的 `delivery-mirror` / `gateway-injected` 标记，因为它们会被运行时当作 transcript-only 消息从 replay history 中移除。

安装前可以先做无写入检查：

```bash
python3 openclaw/nudge/scripts/install.py --check
```

这会检查目标路径、OpenClaw CLI、同名 cron job，并打印计划执行的 cron 创建或更新命令。实际启用时，如果安装器无法通过 `openclaw cron list --all --json` 确认现有 cron 状态，会停止而不是冒险创建重复任务。

## 只安装，不启用 cron

```bash
python3 openclaw/nudge/scripts/install.py --force --no-create-cron
```

## 指定投递渠道

默认使用 `--channel auto`。在交互式终端里，它会显示数字选择菜单；非交互环境或传 `--no-delivery-prompt` 时，会选择 `openclaw channels status --json` 返回的第一个不需要额外目标的活跃渠道；如果没有这样的渠道，则回退到 local/no-deliver。

自动选择菜单：

```bash
python3 openclaw/nudge/scripts/install.py --force --channel auto
```

菜单会读取 `openclaw channels status --json`，自动列出当前已配置并运行的渠道，例如 QQ Bot、OpenClaw Weixin 或 Telegram。显式传 `--channel` 时不会弹菜单。

如果选择的渠道需要固定收件人，安装器会继续询问 `--to`。QQ Bot 会优先读取 `~/.openclaw/qqbot/data/known-users.json`，把最近已知的私聊/群目标列成菜单；没有可用记录时再回退到手动输入。QQ Bot 目标格式通常是 `qqbot:c2c:<openid>`（私聊）或 `qqbot:group:<groupid>`（群）。

## 语言和话题

交互式安装会询问 Nudge 输出语言：

- `English`：展示英文默认话题（topics），可直接使用或自定义。
- `简体中文`：展示中文默认话题（topics），可直接使用或自定义。
- `Custom language`：没有内置默认话题（topics），必须输入自定义话题。

非交互环境默认不改已有语言和话题；新 state 会保留英文 fallback 和英文默认话题。也可以显式传参数：

```bash
python3 openclaw/nudge/scripts/install.py --force --language zh-CN
python3 openclaw/nudge/scripts/install.py --force --language Japanese --topic "短い休憩のリマインド" --topic "最近の会話に関係する一言"
```

语言由用户配置决定，不会根据最近聊天内容自动检测或切换。

指定 QQ Bot：

```bash
python3 openclaw/nudge/scripts/install.py --force --channel qqbot --to "qqbot:c2c:<openid>"
python3 openclaw/nudge/scripts/install.py --force --channel qqbot --to "qqbot:group:<groupid>"
```

指定 OpenClaw Weixin：

```bash
python3 openclaw/nudge/scripts/install.py --force --channel openclaw-weixin
```

指定 Telegram：

```bash
python3 openclaw/nudge/scripts/install.py --force --channel telegram --to "<chat-id>"
```

指定 Telegram 论坛话题：

```bash
python3 openclaw/nudge/scripts/install.py --force --channel telegram --to "<chat-id>" --thread-id "<topic-id>"
```

只保留 OpenClaw 里的 cron 运行结果，不投递到聊天：

```bash
python3 openclaw/nudge/scripts/install.py --force --channel local
```

## 常用检查

查看 cron：

```bash
openclaw cron list --all
```

查看状态：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py show
```

查看最近活动来源：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py activity-source show
```

查看语言策略：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py language show
```

设置中文输出：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py language set zh-CN
```

恢复默认英文 fallback：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py language auto en
```

## 说明

这个 README 位于仓库的 `openclaw/` 目录，不在 `openclaw/nudge/` skill 目录内。安装脚本只复制 `openclaw/nudge/` 到 OpenClaw skill 目录，因此本文件不会被安装进用户的 OpenClaw skill。
