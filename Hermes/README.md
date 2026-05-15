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
- 在交互式终端里询问输出语言和 topics；非交互环境默认不改已有偏好

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

## 语言和主题

交互式安装会询问 Nudge 输出语言：

- `English`：展示英文默认 topics，可直接使用或自定义。
- `简体中文`：展示中文默认 topics，可直接使用或自定义。
- `Custom language`：没有内置默认 topics，必须输入自定义 topics。

非交互环境默认不改已有语言和 topics；新 state 会保留英文 fallback 和英文默认 topics。也可以显式传参数：

```bash
python3 Hermes/nudge/scripts/install.py --force --language zh-CN
python3 Hermes/nudge/scripts/install.py --force --language Japanese --topic "短い休憩のリマインド" --topic "最近の会話に関係する一言"
```

语言由用户配置决定，不会根据最近聊天内容自动检测或切换。

## 最近活动回避

创建或更新 cron 成功后，安装器会把本次选择的投递目标记录到 `~/.hermes/nudge/state.json` 的 `activity_source`。gate 会只读查询 `~/.hermes/state.db`，查找同一平台/会话里最近的 `role=user` 消息，用于 `recent_activity_seconds` 回避规则。

最近活动判断只读 Hermes 的 SQLite state。发送 nudge 时，`record-decision --decision sent --message ...` 会尽力把这条 nudge 镜像进同一聊天的非 cron 会话记录，并刷新 session 索引时间，让用户后续回复时 AI 能看到刚刚主动发出的内容。`--no-create-cron` 和 `--no-update-cron` 不会改 activity source，避免 state 和实际 cron 投递目标不一致。

## Cron 投递包装

Hermes 默认会给 cron 投递到聊天的内容加一层包装，例如：

```text
Cronjob Response: nudge
(job_id: ...)
-------------

...

To stop or manage this job, send me a new message (e.g. "stop reminder nudge").
```

这层文字由 Hermes cron 投递层生成，不是 Nudge 的回复内容。当前 Hermes 只提供全局开关，不能只针对 `nudge` 这一个 cron job 单独关闭。Nudge 安装器不会修改用户的 `~/.hermes/config.yaml`。

如果你希望所有 Hermes cron job 都使用纯正文投递，可以手动编辑 `~/.hermes/config.yaml`：

```yaml
cron:
  wrap_response: false
```

这会影响所有 Hermes cron job。要恢复默认包装，把它改回 `true` 或删除该配置项。

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

恢复默认英文 fallback：

```bash
python3 ~/.hermes/scripts/nudge_state.py language auto en
```

## 说明

这个 README 位于仓库的 `Hermes/` 目录，不在 `Hermes/nudge/` skill 目录内。安装脚本只复制 `Hermes/nudge/`，因此本文件不会被安装进用户的 Hermes skill。
