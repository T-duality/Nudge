# Hermes Nudge

Hermes 版 Nudge 使用一个固定 Hermes cron job 周期性 tick，由 gate 脚本判断是否真正唤醒 agent。是否发消息、下一次什么时候醒来，都记录在本地 state 文件里。

## 安装并启用

在项目根目录运行：

```bash
python3 Hermes/nudge/scripts/install.py --force
```

这会：

- 安装 skill 到 `~/.hermes/skills/productivity/nudge`
- 安装脚本到 `~/.hermes/scripts/`
- 初始化 state 到 `~/.hermes/nudge/state.json`
- 创建或更新一个名为 `nudge` 的 Hermes cron job
- 在交互式终端里显示投递平台数字选择菜单，例如 `QQBot dm -> qqbot:<id>`

如果已存在同名 cron job，安装脚本会用本次选择的投递渠道、schedule、prompt、skill、script 和 workdir 更新它。传 `--no-update-cron` 可以只覆盖安装文件、不改已有 cron；需要多实例时传不同的 `--name`。

## 只安装，不启用 cron

```bash
python3 Hermes/nudge/scripts/install.py --force --no-create-cron
```

## 指定投递渠道

自动选择菜单：

```bash
python3 Hermes/nudge/scripts/install.py --force --deliver auto
```

菜单使用数字选择，直接按 Enter 会选择默认项。

本地测试：

```bash
python3 Hermes/nudge/scripts/install.py --force --deliver local
```

Telegram：

```bash
python3 Hermes/nudge/scripts/install.py --force --deliver telegram
```

指定具体聊天：

```bash
python3 Hermes/nudge/scripts/install.py --force --deliver qqbot:<chat-id>
```

非交互环境下，`--deliver auto` 会回退到 `local`。如果你不想弹选择菜单，也可以显式传 `--no-delivery-prompt`。

## 重复安装

默认重复安装会覆盖 skill 和脚本，并更新同名 cron：

```bash
python3 Hermes/nudge/scripts/install.py --force
```

只覆盖文件，不更新已有 cron：

```bash
python3 Hermes/nudge/scripts/install.py --force --no-update-cron
```

## 常用检查

查看 cron：

```bash
hermes cron list --all
```

如果手动创建 cron，`--script` 必须只写脚本文件名：

```bash
--script nudge_gate.py
```

不要写 `~/.hermes/scripts/nudge_gate.py` 或绝对路径；Hermes 会自动从 `~/.hermes/scripts/` 查找。

查看状态：

```bash
python3 ~/.hermes/scripts/nudge_state.py show
```

查看语言策略：

```bash
python3 ~/.hermes/scripts/nudge_state.py language show
```

设置中文输出：

```bash
python3 ~/.hermes/scripts/nudge_state.py language set zh-CN
```

恢复自动语言选择，默认英文：

```bash
python3 ~/.hermes/scripts/nudge_state.py language auto en
```

## 说明

这个 README 位于仓库的 `Hermes/` 目录，不在 `Hermes/nudge/` skill 目录内。安装脚本只复制 `Hermes/nudge/`，因此本文件不会被安装进用户的 Hermes skill。
