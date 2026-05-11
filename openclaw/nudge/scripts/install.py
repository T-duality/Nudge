#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
import json
import os
import pathlib
import shutil
import shlex
import stat
import subprocess
import sys
from typing import Any

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import nudge_state  # noqa: E402


@dataclass
class CronLookup:
    job: tuple[str, str] | None = None
    error: str | None = None


@dataclass
class Delivery:
    label: str
    channel: str = ""
    to: str = ""
    account: str = ""
    thread_id: str = ""
    announce: bool = True


@dataclass
class QQBotTarget:
    label: str
    to: str
    account: str = ""
    last_seen_ms: int | None = None
    interaction_count: int | None = None


DESTINATION_REQUIRED_CHANNELS = {"qqbot", "telegram", "discord", "whatsapp", "signal", "sms"}
DESTINATION_HINTS = {
    "qqbot": "qqbot:c2c:<openid> for direct messages, or qqbot:group:<groupid> for groups",
    "telegram": "Telegram chat id, for example 123456789 or -1001234567890",
    "discord": "Discord channel or user id",
    "whatsapp": "Phone number in E.164 format, for example +15555550123",
    "signal": "Phone number in E.164 format, for example +15555550123",
    "sms": "Phone number in E.164 format, for example +15555550123",
    "openclaw-weixin": "Weixin contact/conversation id if OpenClaw requires one",
}


def expand(value: str) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(value)).resolve()


def openclaw_home() -> pathlib.Path:
    return expand(os.environ.get("OPENCLAW_HOME", "~/.openclaw"))


def clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def json_values_from_openclaw_stdout(stdout: str) -> list[Any]:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    for index, char in enumerate(stdout):
        if char not in "{[":
            continue
        try:
            data, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        values.append(data)
    return values


def platform_label(platform: str) -> str:
    labels = {
        "qqbot": "QQBot",
        "telegram": "Telegram",
        "discord": "Discord",
        "whatsapp": "WhatsApp",
        "slack": "Slack",
        "signal": "Signal",
        "mattermost": "Mattermost",
        "matrix": "Matrix",
        "email": "Email",
        "sms": "SMS",
        "feishu": "Feishu",
        "wecom": "WeCom",
        "weixin": "Weixin",
        "bluebubbles": "BlueBubbles",
        "yuanbao": "Yuanbao",
    }
    return labels.get(platform, platform.replace("_", " ").title())


def load_channel_status() -> dict[str, Any]:
    if shutil.which("openclaw") is None:
        return {}
    try:
        result = subprocess.run(
            ["openclaw", "channels", "status", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return {}
    if result.returncode != 0:
        return {}
    for value in json_values_from_openclaw_stdout(result.stdout):
        if isinstance(value, dict):
            return value
    return {}


def is_active_channel(status: Any) -> bool:
    if not isinstance(status, dict):
        return False
    if status.get("configured") is False or status.get("enabled") is False:
        return False
    if status.get("running") is True or status.get("connected") is True:
        return True
    if status.get("lastInboundAt") or status.get("lastOutboundAt") or status.get("lastEventAt"):
        return True
    return status.get("configured") is True and not status.get("lastError")


def configured_account_ids(accounts: Any) -> list[str]:
    if not isinstance(accounts, list):
        return []
    values: list[str] = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        if account.get("enabled") is False or account.get("configured") is False:
            continue
        account_id = account.get("accountId") or account.get("id")
        if account_id is not None and str(account_id).strip():
            values.append(str(account_id).strip())
    return values


def discovered_channel_deliveries(status: dict[str, Any]) -> list[Delivery]:
    channels = status.get("channels") if isinstance(status.get("channels"), dict) else {}
    accounts = status.get("channelAccounts") if isinstance(status.get("channelAccounts"), dict) else {}
    default_accounts = status.get("channelDefaultAccountId") if isinstance(status.get("channelDefaultAccountId"), dict) else {}
    labels = status.get("channelLabels") if isinstance(status.get("channelLabels"), dict) else {}
    detail_labels = status.get("channelDetailLabels") if isinstance(status.get("channelDetailLabels"), dict) else {}
    ordered = status.get("channelOrder") if isinstance(status.get("channelOrder"), list) else []

    channel_ids = [str(item) for item in ordered if str(item) in channels]
    channel_ids.extend(sorted(str(item) for item in channels if str(item) not in channel_ids))

    deliveries: list[Delivery] = []
    for channel_id in channel_ids:
        channel_status = channels.get(channel_id)
        if not is_active_channel(channel_status):
            continue
        account_ids = configured_account_ids(accounts.get(channel_id))
        default_account = default_accounts.get(channel_id)
        if default_account is not None and str(default_account).strip() and str(default_account) not in account_ids:
            account_ids.insert(0, str(default_account).strip())
        if not account_ids:
            account_ids = [""]
        for account_id in account_ids:
            label = str(labels.get(channel_id) or platform_label(channel_id))
            detail = str(detail_labels.get(channel_id) or "").strip()
            if detail and detail != label:
                label = detail if detail.startswith(label) else f"{label} ({detail})"
            if account_id:
                label = f"{label} account: {account_id}"
            deliveries.append(Delivery(label=label, channel=channel_id, account=account_id))
    return deliveries


def local_delivery() -> Delivery:
    return Delivery(label="Local only: keep output in OpenClaw, no chat delivery", announce=False)


def auto_discovered_deliveries() -> list[Delivery]:
    return discovered_channel_deliveries(load_channel_status())


def delivery_options(discovered: list[Delivery] | None = None) -> list[Delivery]:
    options = list(discovered if discovered is not None else auto_discovered_deliveries())
    options.append(Delivery(label="Local only: keep output in OpenClaw, no chat delivery", announce=False))
    options.append(Delivery(label="Custom target: type OpenClaw channel and destination", channel="__custom__"))
    return options


def delivery_display(delivery: Delivery) -> str:
    if not delivery.announce:
        return "--no-deliver"
    parts = [f"--channel {delivery.channel}"]
    if delivery.to:
        parts.append(f"--to {delivery.to}")
    if delivery.thread_id:
        parts.append(f"--thread-id {delivery.thread_id}")
    if delivery.account:
        parts.append(f"--account {delivery.account}")
    return " ".join(parts)


def select_delivery_option_numbered(options: list[Delivery], default_index: int) -> Delivery:
    print("\nChoose where Nudge should send messages:")
    for idx, option in enumerate(options, start=1):
        marker = " (default)" if idx - 1 == default_index else ""
        print(f"  {idx}. {option.label} -> {delivery_display(option)}{marker}")
    while True:
        choice = input(f"Delivery target [1-{len(options)}; Enter for {default_index + 1}]: ").strip()
        if not choice:
            return options[default_index]
        try:
            return options[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid choice. Enter a number from the list.")


def custom_delivery() -> Delivery:
    while True:
        channel = input("Channel [qqbot/openclaw-weixin/telegram/local]: ").strip()
        if channel in {"local", "none", "off"}:
            return local_delivery()
        if not channel:
            print("Channel cannot be empty.")
            continue
        account = input("Account --account [optional]: ").strip()
        to = prompt_destination(channel, account=account)
        thread_id = input("Thread id --thread-id [optional]: ").strip()
        return Delivery(label="Custom target", channel=channel, to=to, account=account, thread_id=thread_id)


def destination_required(channel: str) -> bool:
    return channel in DESTINATION_REQUIRED_CHANNELS


def destination_hint(channel: str) -> str:
    return DESTINATION_HINTS.get(channel, "destination accepted by OpenClaw for this channel")


def qqbot_known_users_path() -> pathlib.Path:
    return openclaw_home() / "qqbot" / "data" / "known-users.json"


def qqbot_known_user_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("users", "knownUsers", "known_users", "items", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def qqbot_item_target(item: dict[str, Any]) -> str:
    explicit = clean_str(item.get("to") or item.get("target") or item.get("targetId"))
    if explicit.startswith("qqbot:"):
        return explicit

    kind = clean_str(item.get("type") or item.get("kind") or item.get("chatType")).lower()
    if kind in {"group", "guild", "channel"}:
        group_id = clean_str(
            item.get("groupid")
            or item.get("groupId")
            or item.get("groupOpenid")
            or item.get("groupOpenId")
            or item.get("id")
            or explicit
        )
        return f"qqbot:group:{group_id}" if group_id else ""

    openid = clean_str(
        item.get("openid")
        or item.get("openId")
        or item.get("userOpenid")
        or item.get("userOpenId")
        or item.get("id")
        or explicit
    )
    if openid and kind in {"", "c2c", "direct", "dm", "private", "user"}:
        return f"qqbot:c2c:{openid}"
    return ""


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_epoch_ms(value: int | None) -> str:
    if value is None:
        return ""
    try:
        return dt.datetime.fromtimestamp(value / 1000, tz=dt.datetime.now().astimezone().tzinfo).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return ""


def mask_identifier(value: str) -> str:
    if len(value) <= 14:
        return value
    return f"{value[:4]}...{value[-6:]}"


def short_qqbot_target(target: str) -> str:
    parts = target.split(":", 2)
    if len(parts) == 3 and parts[0] == "qqbot":
        return f"{parts[0]}:{parts[1]}:{mask_identifier(parts[2])}"
    return mask_identifier(target)


def qqbot_target_label(item: dict[str, Any], target: str) -> str:
    parts = target.split(":", 2)
    kind = parts[1] if len(parts) == 3 and parts[0] == "qqbot" else "target"
    parts = [f"QQBot {kind}"]
    account = clean_str(item.get("accountId") or item.get("account") or item.get("account_id"))
    if account:
        parts.append(f"account: {account}")
    last_seen = format_epoch_ms(int_or_none(item.get("lastSeenAt") or item.get("last_seen_at")))
    if last_seen:
        parts.append(f"last seen: {last_seen}")
    interactions = int_or_none(item.get("interactionCount") or item.get("interaction_count"))
    if interactions is not None:
        parts.append(f"interactions: {interactions}")
    parts.append(short_qqbot_target(target))
    return ", ".join(parts)


def qqbot_target_options(account: str = "") -> list[QQBotTarget]:
    path = qqbot_known_users_path()
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

    expected_account = account.strip()
    targets: list[QQBotTarget] = []
    seen: set[str] = set()
    for item in qqbot_known_user_items(data):
        item_account = clean_str(item.get("accountId") or item.get("account") or item.get("account_id"))
        if expected_account and item_account and item_account != expected_account:
            continue
        target = qqbot_item_target(item)
        if not target or target in seen:
            continue
        seen.add(target)
        last_seen = int_or_none(item.get("lastSeenAt") or item.get("last_seen_at"))
        interactions = int_or_none(item.get("interactionCount") or item.get("interaction_count"))
        targets.append(QQBotTarget(
            label=qqbot_target_label(item, target),
            to=target,
            account=item_account,
            last_seen_ms=last_seen,
            interaction_count=interactions,
        ))

    targets.sort(key=lambda item: (item.last_seen_ms or 0, item.interaction_count or 0), reverse=True)
    return targets


def prompt_raw_destination(channel: str, must_fill: bool) -> str:
    hint = destination_hint(channel)
    suffix = "required" if must_fill else "optional; Enter to skip"
    while True:
        value = input(f"Destination --to for {channel} [{suffix}; {hint}]: ").strip()
        if value or not must_fill:
            return value
        print("Destination is required for this channel.")


def prompt_qqbot_target(account: str, must_fill: bool) -> str | None:
    targets = qqbot_target_options(account)
    if not targets:
        return None

    manual_index = len(targets) + 1
    print("\nChoose QQBot target:")
    for idx, target in enumerate(targets, start=1):
        marker = " (default)" if idx == 1 else ""
        print(f"  {idx}. {target.label} -> {target.to}{marker}")
    print(f"  {manual_index}. Type manually")
    while True:
        choice = input(f"QQBot target [1-{manual_index}; Enter for 1]: ").strip()
        if not choice:
            return targets[0].to
        try:
            selected = int(choice)
        except ValueError:
            print("Invalid choice. Enter a number from the list.")
            continue
        if 1 <= selected <= len(targets):
            return targets[selected - 1].to
        if selected == manual_index:
            return prompt_raw_destination("qqbot", must_fill)
        print("Invalid choice. Enter a number from the list.")


def prompt_destination(channel: str, required: bool | None = None, account: str = "") -> str:
    must_fill = destination_required(channel) if required is None else required
    if channel == "qqbot":
        selected = prompt_qqbot_target(account, must_fill)
        if selected:
            return selected
    return prompt_raw_destination(channel, must_fill)


def maybe_prompt_destination(delivery: Delivery, no_prompt: bool = False) -> Delivery:
    if no_prompt or not delivery.announce or delivery.to:
        if delivery.announce and not delivery.to and destination_required(delivery.channel):
            raise ValueError(f"--channel {delivery.channel} requires --to ({destination_hint(delivery.channel)})")
        return delivery
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        if destination_required(delivery.channel):
            raise ValueError(f"--channel {delivery.channel} requires --to ({destination_hint(delivery.channel)})")
        return delivery
    if not destination_required(delivery.channel) and delivery.channel not in DESTINATION_HINTS:
        return delivery
    delivery.to = prompt_destination(delivery.channel, account=delivery.account)
    return delivery


def choose_delivery(args: argparse.Namespace, no_prompt: bool = False) -> Delivery:
    channel = str(args.channel or "auto").strip()
    if channel not in {"auto", ""}:
        if channel in {"local", "none", "off"}:
            return local_delivery()
        return maybe_prompt_destination(Delivery(
            label="Command line target",
            channel=channel,
            to=args.to,
            account=args.account,
            thread_id=args.thread_id,
        ), no_prompt=no_prompt or args.no_delivery_prompt)
    if args.to or args.account or args.thread_id:
        discovered = auto_discovered_deliveries()
        if len(discovered) != 1:
            raise ValueError("--to, --account, and --thread-id require an explicit --channel when --channel is auto")
        base = discovered[0]
        return maybe_prompt_destination(Delivery(
            label="Command line target",
            channel=base.channel,
            to=args.to,
            account=args.account or base.account,
            thread_id=args.thread_id,
        ), no_prompt=no_prompt or args.no_delivery_prompt)
    discovered = auto_discovered_deliveries()
    if no_prompt or args.no_delivery_prompt or not sys.stdin.isatty() or not sys.stdout.isatty():
        if discovered:
            eligible = [item for item in discovered if item.to or not destination_required(item.channel)]
            if not eligible:
                print("delivery auto: no interactive picker and no active channel with an implicit destination found, using local")
                return local_delivery()
            selected = eligible[0]
            print(f"delivery auto: no interactive picker, using {selected.label}")
            return selected
        print("delivery auto: no interactive picker and no active channel found, using local")
        return local_delivery()

    options = delivery_options(discovered)
    default_index = 0
    while True:
        selected = select_delivery_option_numbered(options, default_index)
        if selected.channel != "__custom__":
            return maybe_prompt_destination(selected)
        custom = custom_delivery()
        if custom.channel or not custom.announce:
            return maybe_prompt_destination(custom)


def select_language_numbered() -> str:
    options = [
        ("English", "en"),
        ("简体中文", "zh-CN"),
        ("Custom language", "__custom__"),
    ]
    print("\nChoose Nudge language:")
    for idx, (label, _value) in enumerate(options, start=1):
        marker = " (default)" if idx == 1 else ""
        print(f"  {idx}. {label}{marker}")
    while True:
        choice = input(f"Language [1-{len(options)}; Enter for 1]: ").strip()
        if not choice:
            selected = options[0][1]
        else:
            try:
                selected = options[int(choice) - 1][1]
            except (ValueError, IndexError):
                print("Invalid choice. Enter a number from the list.")
                continue
        if selected != "__custom__":
            return selected
        custom = input("Custom language: ").strip()
        if custom:
            return custom
        print("Custom language cannot be empty.")


def default_topics_for_language(language: str) -> list[str] | None:
    canonical = nudge_state.canonical_bundled_language(language)
    if canonical == "en":
        return list(nudge_state.DEFAULT_TOPICS)
    if canonical == "zh-CN":
        return list(nudge_state.DEFAULT_TOPICS_ZH)
    return None


def prompt_custom_topics() -> list[str]:
    print("Enter topics, one per line. Empty line to finish.")
    topics: list[str] = []
    while True:
        value = input(f"Topic {len(topics) + 1}: ").strip()
        if not value:
            if topics:
                return topics
            print("At least one topic is required.")
            continue
        topics.append(value)


def choose_topics(language: str, cli_topics: list[str] | None, no_prompt: bool) -> list[str]:
    if cli_topics:
        return cli_topics
    defaults = default_topics_for_language(language)
    if not sys.stdin.isatty() or not sys.stdout.isatty() or no_prompt:
        if defaults is not None:
            return defaults
        raise ValueError("--topic is required when --language is a custom language in non-interactive installs")
    if defaults is None:
        print("\nNo bundled default topics for this language.")
        return prompt_custom_topics()

    print("\nDefault Nudge topics:")
    for idx, topic in enumerate(defaults, start=1):
        print(f"  {idx}. {topic}")
    print("\nChoose topics:")
    print("  1. Use defaults")
    print("  2. Customize now")
    while True:
        choice = input("Topics [1-2; Enter for 1]: ").strip()
        if not choice or choice == "1":
            return defaults
        if choice == "2":
            return prompt_custom_topics()
        print("Invalid choice. Enter 1 or 2.")


def choose_preferences(args: argparse.Namespace) -> tuple[str | None, list[str] | None]:
    cli_topics = list(args.topic or [])
    explicit_language = args.language != "auto"
    no_prompt = args.no_preference_prompt or args.check
    can_prompt = not no_prompt and sys.stdin.isatty() and sys.stdout.isatty()
    if explicit_language:
        language = args.language.strip()
        if not language:
            raise ValueError("--language cannot be empty")
        return language, choose_topics(language, cli_topics, no_prompt)
    if cli_topics:
        return "en", cli_topics
    if not can_prompt:
        return None, None
    language = select_language_numbered()
    return language, choose_topics(language, None, False)


def copy_tree(src: pathlib.Path, dst: pathlib.Path, force: bool) -> None:
    if src.resolve() == dst.resolve():
        print(f"source and target are the same, skipping copy: {dst}")
        return
    if dst.exists():
        if not force:
            raise FileExistsError(f"target exists, pass --force to replace: {dst}")
        shutil.rmtree(dst)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")
    shutil.copytree(src, dst, ignore=ignore)


def copy_script(src: pathlib.Path, dst_dir: pathlib.Path) -> pathlib.Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


def run_checked(cmd: list[str]) -> None:
    print("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)


def activity_source_args_from_delivery(delivery: Delivery) -> list[str]:
    if not delivery.announce or not delivery.channel:
        return ["disable"]
    args = ["openclaw-sessions", "--channel", delivery.channel]
    if delivery.to:
        args.extend(["--to", delivery.to])
    if delivery.account:
        args.extend(["--account", delivery.account])
    if delivery.thread_id:
        args.extend(["--thread-id", delivery.thread_id])
    return args


def configure_activity_source(state_script: pathlib.Path, state_path: pathlib.Path, delivery: Delivery) -> None:
    run_checked([
        sys.executable,
        str(state_script),
        "--state",
        str(state_path),
        "activity-source",
        *activity_source_args_from_delivery(delivery),
    ])


def configure_preferences(state_script: pathlib.Path, state_path: pathlib.Path, language: str | None, topics: list[str] | None) -> None:
    if language:
        run_checked([sys.executable, str(state_script), "--state", str(state_path), "language", "set", language])
    if topics:
        run_checked([sys.executable, str(state_script), "--state", str(state_path), "topic", "set", *topics])


def build_prompt(gate_script: pathlib.Path, state_script: pathlib.Path) -> str:
    return (
        f"Use the nudge skill. First run: python3 {gate_script}. "
        "If the gate JSON has status silent, do not run any other command and final reply exactly HEARTBEAT_OK. "
        "Only if the gate prints NUDGE_GATE_CONTEXT, decide whether to send one short proactive message. "
        f"After a NUDGE_GATE_CONTEXT decision, update state with python3 {state_script} record-decision "
        "--decision sent|silent --next-minutes <minutes>. "
        "Then final reply exactly HEARTBEAT_OK for a due-but-silent decision, or only the user-facing nudge when sending."
    )


def cron_jobs_from_json(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("jobs", "crons", "cron_jobs", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    for key in ("data", "result", "payload"):
        nested = data.get(key)
        if isinstance(nested, (dict, list)):
            jobs = cron_jobs_from_json(nested)
            if jobs:
                return jobs
    if any(key in data for key in ("id", "job_id", "uuid")) and "name" in data:
        return [data]
    return []


def cron_job_identity(job: dict[str, Any]) -> tuple[str, str] | None:
    raw_name = job.get("name")
    raw_id = job.get("id", job.get("job_id", job.get("uuid")))
    if raw_name is None or raw_id is None:
        return None
    name = str(raw_name)
    job_id = str(raw_id)
    if not name or not job_id:
        return None
    return job_id, name


def find_cron_job(name: str) -> CronLookup:
    if shutil.which("openclaw") is None:
        return CronLookup(error="openclaw CLI not found on PATH")
    try:
        result = subprocess.run(
            ["openclaw", "cron", "list", "--all", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return CronLookup(error="openclaw CLI not found on PATH")
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        if detail:
            return CronLookup(error=f"openclaw cron list failed: {detail}")
        return CronLookup(error=f"openclaw cron list failed with exit code {result.returncode}")
    values = json_values_from_openclaw_stdout(result.stdout)
    if not values:
        return CronLookup(error="could not parse JSON from openclaw cron list --all --json")
    for data in values:
        for job in cron_jobs_from_json(data):
            identity = cron_job_identity(job)
            if identity and identity[1] == name:
                return CronLookup(job=identity)
    return CronLookup()


def add_delivery_cron_args(cmd: list[str], delivery: Delivery) -> None:
    if not delivery.announce:
        cmd.append("--no-deliver")
        return
    cmd.extend(["--announce", "--channel", delivery.channel])
    if delivery.to:
        cmd.extend(["--to", delivery.to])
    if delivery.account:
        cmd.extend(["--account", delivery.account])
    if delivery.thread_id:
        cmd.extend(["--thread-id", delivery.thread_id])


def add_optional_cron_args(cmd: list[str], args: argparse.Namespace) -> None:
    if args.model:
        cmd.extend(["--model", args.model])
    if args.thinking:
        cmd.extend(["--thinking", args.thinking])


def cron_add_cmd(args: argparse.Namespace, prompt: str, delivery: Delivery) -> list[str]:
    cmd = [
        "openclaw",
        "cron",
        "add",
        "--every",
        args.schedule,
        "--name",
        args.name,
        "--session",
        args.session,
        "--message",
        prompt,
        "--tools",
        args.tools,
    ]
    add_delivery_cron_args(cmd, delivery)
    add_optional_cron_args(cmd, args)
    return cmd


def cron_edit_cmd(args: argparse.Namespace, job_id: str, prompt: str, delivery: Delivery) -> list[str]:
    cmd = [
        "openclaw",
        "cron",
        "edit",
        job_id,
        "--every",
        args.schedule,
        "--name",
        args.name,
        "--session",
        args.session,
        "--message",
        prompt,
        "--tools",
        args.tools,
    ]
    add_delivery_cron_args(cmd, delivery)
    add_optional_cron_args(cmd, args)
    return cmd


def writable_parent(path: pathlib.Path) -> pathlib.Path | None:
    candidate = path if path.exists() and path.is_dir() else path.parent
    while not candidate.exists():
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent
    return candidate if os.access(candidate, os.W_OK) else None


def check_path(label: str, path: pathlib.Path) -> bool:
    parent = writable_parent(path)
    status = f"writable parent: {parent}" if parent else "no writable parent found"
    print(f"{label}: {path} ({status})")
    return parent is not None


def run_check(
    args: argparse.Namespace,
    skill_target: pathlib.Path,
    runtime_target: pathlib.Path,
    state_path: pathlib.Path,
    lookup: CronLookup,
    prompt: str,
    delivery: Delivery,
) -> int:
    print("OpenClaw nudge install check")
    ok = True
    ok = check_path("skill target", skill_target) and ok
    ok = check_path("runtime target", runtime_target) and ok
    ok = check_path("state file", state_path) and ok
    print(f"delivery: {delivery.label} ({delivery_display(delivery)})")

    openclaw = shutil.which("openclaw")
    if openclaw:
        print(f"openclaw CLI: {openclaw}")
    else:
        print("openclaw CLI: not found on PATH")
        if not args.no_create_cron:
            ok = False

    if lookup.error:
        print(f"cron lookup: unavailable ({lookup.error})")
        if not args.no_create_cron:
            ok = False
    elif lookup.job:
        job_id, job_name = lookup.job
        print(f"cron lookup: found {job_name} ({job_id})")
    else:
        print(f"cron lookup: no existing job named {args.name!r}")

    if args.no_create_cron:
        print("planned cron action: none (--no-create-cron)")
        if lookup.job and not args.no_update_cron:
            job_id, _ = lookup.job
            print("cron command to update existing job:")
            print(shlex.join(cron_edit_cmd(args, job_id, prompt, delivery)))
        else:
            print("cron command to create job:")
            print(shlex.join(cron_add_cmd(args, prompt, delivery)))
    elif lookup.job and args.no_update_cron:
        job_id, job_name = lookup.job
        print(f"planned cron action: leave existing job unchanged: {job_name} ({job_id})")
    elif lookup.job:
        job_id, _ = lookup.job
        print("planned cron action: update existing job")
        print(shlex.join(cron_edit_cmd(args, job_id, prompt, delivery)))
    else:
        print("planned cron action: create job")
        print(shlex.join(cron_add_cmd(args, prompt, delivery)))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and activate the OpenClaw nudge locally.")
    parser.add_argument("--skill-target", default=str(openclaw_home() / "skills" / "nudge"))
    parser.add_argument("--runtime-target", default=str(openclaw_home() / "nudge"))
    parser.add_argument("--state", default=str(openclaw_home() / "nudge" / "state.json"))
    parser.add_argument("--schedule", default="10m", help="OpenClaw --every duration.")
    parser.add_argument("--name", default="nudge")
    parser.add_argument("--session", choices=["isolated", "main"], default="isolated")
    parser.add_argument("--channel", default="auto", help="Delivery channel. Use auto for an interactive picker, local to disable chat delivery, or a channel id such as qqbot, openclaw-weixin, or telegram.")
    parser.add_argument("--to", default="")
    parser.add_argument("--account", default="")
    parser.add_argument("--thread-id", default="")
    parser.add_argument("--language", default="auto", help="Nudge language. Use auto for an interactive picker, or pass a language such as en, zh-CN, Japanese.")
    parser.add_argument("--topic", action="append", help="Custom topic. Repeat to set multiple topics.")
    parser.add_argument("--model", default="")
    parser.add_argument("--thinking", default="")
    parser.add_argument("--tools", default="exec,read,write")
    parser.add_argument("--force", action="store_true", help="Replace installed skill/runtime files.")
    parser.add_argument("--check", action="store_true", help="Check paths and planned cron action without installing files or editing cron.")
    parser.add_argument("--no-create-cron", action="store_true", help="Install files only; do not create the OpenClaw cron job.")
    parser.add_argument("--no-delivery-prompt", action="store_true", help="With --channel auto, skip the picker and use the first active channel, or local if none are active.")
    parser.add_argument("--no-preference-prompt", action="store_true", help="Do not prompt for language or topics unless explicitly passed.")
    parser.add_argument("--no-update-cron", action="store_true", help="If a cron job with --name exists, leave it unchanged instead of editing it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    package_dir = pathlib.Path(__file__).resolve().parents[1]
    script_dir = package_dir / "scripts"
    skill_target = expand(args.skill_target)
    runtime_target = expand(args.runtime_target)
    runtime_scripts = runtime_target / "scripts"
    state_path = expand(args.state)
    state_script_target = runtime_scripts / "nudge_state.py"
    gate_script_target = runtime_scripts / "nudge_gate.py"
    prompt = build_prompt(gate_script_target, state_script_target)
    try:
        delivery = choose_delivery(args, no_prompt=args.check)
        language, topics = choose_preferences(args)
    except ValueError as exc:
        print(f"install error: {exc}", file=sys.stderr)
        return 2
    lookup = find_cron_job(args.name)

    if args.check:
        return run_check(args, skill_target, runtime_target, state_path, lookup, prompt, delivery)

    if lookup.error and not args.no_create_cron:
        print(f"cannot safely create or update cron: {lookup.error}", file=sys.stderr)
        print("fix `openclaw cron list --all --json`, or rerun with --no-create-cron to install files only", file=sys.stderr)
        return 2

    copy_tree(package_dir, skill_target, args.force)
    print(f"installed skill: {skill_target}")

    runtime_target.mkdir(parents=True, exist_ok=True)
    state_script = copy_script(script_dir / "nudge_state.py", runtime_scripts)
    gate_script = copy_script(script_dir / "nudge_gate.py", runtime_scripts)
    print(f"installed runtime scripts: {runtime_scripts}")

    run_checked([sys.executable, str(state_script), "--state", str(state_path), "init"])
    configure_preferences(state_script, state_path, language, topics)
    prompt = build_prompt(gate_script, state_script)

    existing_job = lookup.job
    existing_job_id = existing_job[0] if existing_job else None
    existing_job_name = existing_job[1] if existing_job else None
    create_cmd = cron_add_cmd(args, prompt, delivery)

    if args.no_create_cron:
        if lookup.error:
            print(f"could not check existing cron job: {lookup.error}")
        if existing_job_id and not args.no_update_cron:
            print("cron command not run. Update the existing job with:")
            print(shlex.join(cron_edit_cmd(args, existing_job_id, prompt, delivery)))
        else:
            print("cron command not run. Create it with:")
            print(shlex.join(create_cmd))
    elif existing_job_id and args.no_update_cron:
        print(f"cron job already exists, leaving it unchanged: {existing_job_name} ({existing_job_id})")
        print("omit --no-update-cron to update it, or use a different --name to create another job")
    elif existing_job_id:
        print(f"cron job already exists, updating it: {existing_job_name} ({existing_job_id})")
        run_checked(cron_edit_cmd(args, existing_job_id, prompt, delivery))
        configure_activity_source(state_script, state_path, delivery)
    else:
        run_checked(create_cmd)
        configure_activity_source(state_script, state_path, delivery)

    print(f"gate script: {gate_script}")
    print(f"state file: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
