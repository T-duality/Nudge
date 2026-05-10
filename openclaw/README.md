# OpenClaw Nudge

OpenClaw 版 Nudge 使用固定 cron job 周期性唤醒 agent。agent 每次先运行本地 gate 脚本；如果未到真正唤醒时间，就回复 `HEARTBEAT_OK` 静默结束；如果到点，再决定是否发送一条短消息。

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

如果已存在同名 cron job，安装脚本会更新它，避免重复；需要多实例时传不同的 `--name`。

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

默认使用 `--channel last`，也就是 OpenClaw 最近可用的聊天路由。

指定 Telegram：

```bash
python3 openclaw/nudge/scripts/install.py --force --channel telegram --to "<chat-id>"
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

查看语言策略：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py language show
```

设置中文输出：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py language set zh-CN
```

恢复自动语言选择，默认英文：

```bash
python3 ~/.openclaw/nudge/scripts/nudge_state.py language auto en
```

## 说明

这个 README 位于仓库的 `openclaw/` 目录，不在 `openclaw/nudge/` skill 目录内。安装脚本只复制 `openclaw/nudge/` 到 OpenClaw skill 目录，因此本文件不会被安装进用户的 OpenClaw skill。
