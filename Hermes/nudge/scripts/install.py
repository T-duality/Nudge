#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import shlex
import stat
import subprocess
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import nudge_state  # noqa: E402


PROMPT = (
    "Use the nudge skill. The pre-run gate output is the source of truth. "
    "If the gate wakes you, decide whether to send one short proactive message. "
    "Before your final response, update the nudge state with nudge_state.py record-decision; "
    "when sending, pass --message with the exact final user-facing nudge text so it can be mirrored into chat context. "
    "If silent, final response must start exactly with [SILENT]."
)


def expand(value: str) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(value)).resolve()


def hermes_scripts_dir() -> pathlib.Path:
    return expand(os.environ.get("HERMES_HOME", "~/.hermes")) / "scripts"


def hermes_home() -> pathlib.Path:
    return expand(os.environ.get("HERMES_HOME", "~/.hermes"))


def delivery_target(platform: str, item: dict) -> str | None:
    chat_id = item.get("id")
    if not chat_id:
        return None
    thread_id = item.get("thread_id")
    if thread_id:
        return f"{platform}:{chat_id}:{thread_id}"
    return f"{platform}:{chat_id}"


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


def load_channel_directory() -> dict:
    path = hermes_home() / "channel_directory.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    platforms = data.get("platforms")
    return platforms if isinstance(platforms, dict) else {}


def delivery_options() -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for platform, items in sorted(load_channel_directory().items()):
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            target = delivery_target(platform, item)
            if not target:
                continue
            name = str(item.get("name") or item.get("id") or target)
            kind = str(item.get("type") or "chat")
            options.append({
                "label": f"{platform_label(platform)} {kind}: {name}",
                "target": target,
            })
    options.append({"label": "Local only: save output locally, no chat notification", "target": "local"})
    options.append({"label": "Custom target: type a Hermes delivery target manually", "target": "__custom__"})
    return options


def select_delivery_option_numbered(options: list[dict[str, str]], default_index: int) -> dict[str, str]:
    print("\nChoose where Nudge should send messages:")
    for idx, option in enumerate(options, start=1):
        marker = " (default)" if idx - 1 == default_index else ""
        print(f"  {idx}. {option['label']} -> {option['target']}{marker}")
    while True:
        choice = input(f"Delivery target [1-{len(options)}; Enter for {default_index + 1}]: ").strip()
        if not choice:
            return options[default_index]
        try:
            return options[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid choice. Enter a number from the list.")


def choose_delivery(deliver: str, no_prompt: bool) -> str:
    if deliver != "auto":
        return deliver
    if no_prompt or not sys.stdin.isatty() or not sys.stdout.isatty():
        print("delivery auto: no interactive TTY, using local")
        return "local"

    options = delivery_options()
    default_index = 0
    while True:
        selected = select_delivery_option_numbered(options, default_index)
        if selected["target"] != "__custom__":
            return selected["target"]
        custom = input("Enter target, e.g. telegram, telegram:<chat_id>, qqbot:<chat_id>, local: ").strip()
        if custom:
            return custom
        print("Custom target cannot be empty.")


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
    if no_prompt:
        return defaults

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
    can_prompt = not args.no_preference_prompt and sys.stdin.isatty() and sys.stdout.isatty()
    if explicit_language:
        language = args.language.strip()
        if not language:
            raise ValueError("--language cannot be empty")
        return language, choose_topics(language, cli_topics, args.no_preference_prompt)
    if cli_topics:
        return "en", cli_topics
    if not can_prompt:
        return None, None
    language = select_language_numbered()
    return language, choose_topics(language, None, False)


def copy_tree(src: pathlib.Path, dst: pathlib.Path, force: bool) -> None:
    if src.resolve() == dst.resolve():
        print(f"skill source and target are the same, skipping copy: {dst}")
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
    current = dst.stat().st_mode
    dst.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dst


def run_checked(cmd: list[str]) -> None:
    print("+ " + shlex.join(cmd))
    subprocess.run(cmd, check=True)


def activity_source_args_from_deliver(deliver: str) -> list[str]:
    for raw_target in str(deliver or "").split(","):
        target = raw_target.strip()
        if not target or target in {"local", "origin"}:
            continue
        if ":" not in target:
            return ["hermes-state-db", "--platform", target.lower()]

        platform, rest = target.split(":", 1)
        platform = platform.strip().lower()
        parts = [part.strip() for part in rest.split(":") if part.strip()]
        if not platform or not parts:
            continue

        chat_id = parts[0]
        thread_id = parts[1] if len(parts) > 1 else None
        if parts[0].lower() in {"c2c", "dm", "user", "private", "group", "channel", "room"} and len(parts) > 1:
            chat_id = parts[1]
            thread_id = parts[2] if len(parts) > 2 else None

        args = ["hermes-state-db", "--platform", platform, "--chat-id", chat_id]
        if thread_id:
            args.extend(["--thread-id", thread_id])
        return args
    return ["disable"]


def configure_activity_source(state_script: pathlib.Path, state_path: pathlib.Path, deliver: str) -> None:
    run_checked([
        sys.executable,
        str(state_script),
        "--state",
        str(state_path),
        "activity-source",
        *activity_source_args_from_deliver(deliver),
    ])


def configure_preferences(state_script: pathlib.Path, state_path: pathlib.Path, language: str | None, topics: list[str] | None) -> None:
    if language:
        run_checked([sys.executable, str(state_script), "--state", str(state_path), "language", "set", language])
    if topics:
        run_checked([sys.executable, str(state_script), "--state", str(state_path), "topic", "set", *topics])


def find_cron_job(name: str) -> tuple[str, str] | None:
    try:
        result = subprocess.run(
            ["hermes", "cron", "list", "--all"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    current_job_id = None
    for line in result.stdout.splitlines():
        header = re.match(r"\s*([A-Za-z0-9_-]+)\s+\[[^\]]+\]\s*$", line)
        if header:
            current_job_id = header.group(1)
            continue
        if current_job_id and line.strip().startswith("Name:"):
            job_name = line.split(":", 1)[1].strip()
            if job_name == name:
                return current_job_id, job_name
    return None


def cron_create_cmd(args: argparse.Namespace, deliver: str, gate_script: pathlib.Path, skill_target: pathlib.Path) -> list[str]:
    return [
        "hermes",
        "cron",
        "create",
        args.schedule,
        PROMPT,
        "--name",
        args.name,
        "--deliver",
        deliver,
        "--skill",
        "nudge",
        "--script",
        gate_script.name,
        "--workdir",
        str(skill_target),
    ]


def cron_edit_cmd(
    args: argparse.Namespace,
    job_id: str,
    deliver: str,
    gate_script: pathlib.Path,
    skill_target: pathlib.Path,
) -> list[str]:
    return [
        "hermes",
        "cron",
        "edit",
        job_id,
        "--schedule",
        args.schedule,
        "--prompt",
        PROMPT,
        "--name",
        args.name,
        "--deliver",
        deliver,
        "--skill",
        "nudge",
        "--script",
        gate_script.name,
        "--workdir",
        str(skill_target),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and activate the Hermes nudge locally.")
    parser.add_argument("--skill-target", default="~/.hermes/skills/productivity/nudge")
    parser.add_argument("--script-target", default="~/.hermes/scripts")
    parser.add_argument("--state", default="~/.hermes/nudge/state.json")
    parser.add_argument("--schedule", default="every 10m")
    parser.add_argument("--deliver", default="auto", help="Delivery target. Use auto for an interactive picker, or pass local/telegram/platform:chat_id.")
    parser.add_argument("--language", default="auto", help="Nudge language. Use auto for an interactive picker, or pass a language such as en, zh-CN, Japanese.")
    parser.add_argument("--topic", action="append", help="Custom topic. Repeat to set multiple topics.")
    parser.add_argument("--name", default="nudge")
    parser.add_argument("--force", action="store_true", help="Replace existing installed skill directory.")
    parser.add_argument("--skip-skill-copy", action="store_true")
    parser.add_argument("--skip-script-copy", action="store_true")
    parser.add_argument("--no-create-cron", action="store_true", help="Install files only; do not create the Hermes cron job.")
    parser.add_argument("--no-delivery-prompt", action="store_true", help="With --deliver auto, skip the picker and use local.")
    parser.add_argument("--no-preference-prompt", action="store_true", help="Do not prompt for language or topics unless explicitly passed.")
    parser.add_argument("--no-update-cron", action="store_true", help="If a cron job with --name exists, leave it unchanged instead of editing it.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skill_dir = pathlib.Path(__file__).resolve().parents[1]
    script_dir = skill_dir / "scripts"
    skill_target = expand(args.skill_target)
    script_target = expand(args.script_target)
    state_path = expand(args.state)
    expected_script_target = hermes_scripts_dir()
    deliver = choose_delivery(args.deliver, args.no_delivery_prompt)
    try:
        language, topics = choose_preferences(args)
    except ValueError as exc:
        print(f"install error: {exc}", file=sys.stderr)
        return 2

    if not args.skip_skill_copy:
        copy_tree(skill_dir, skill_target, args.force)
        print(f"installed skill: {skill_target}")
    else:
        skill_target = skill_dir

    if args.skip_script_copy:
        gate_script = script_dir / "nudge_gate.py"
        state_script = script_dir / "nudge_state.py"
    else:
        state_script = copy_script(script_dir / "nudge_state.py", script_target)
        gate_script = copy_script(script_dir / "nudge_gate.py", script_target)
        print(f"installed scripts: {script_target}")

    run_checked([sys.executable, str(state_script), "--state", str(state_path), "init"])
    configure_preferences(state_script, state_path, language, topics)

    if not args.no_create_cron and script_target != expected_script_target:
        raise ValueError(
            "Hermes cron requires --script to name a file inside ~/.hermes/scripts. "
            f"Use --script-target {expected_script_target} or pass --no-create-cron."
        )

    existing_job = find_cron_job(args.name)
    existing_job_id = existing_job[0] if existing_job else None
    existing_job_name = existing_job[1] if existing_job else None
    create_cmd = cron_create_cmd(args, deliver, gate_script, skill_target)

    if args.no_create_cron:
        if existing_job_id and not args.no_update_cron:
            print("cron command not run. Update the existing job with:")
            print(shlex.join(cron_edit_cmd(args, existing_job_id, deliver, gate_script, skill_target)))
        else:
            print("cron command not run. Create it with:")
            print(shlex.join(create_cmd))
    elif existing_job_id and args.no_update_cron:
        print(f"cron job already exists, leaving it unchanged: {existing_job_name} ({existing_job_id})")
        print("omit --no-update-cron to update it, or use a different --name to create another job")
    elif existing_job_id:
        print(f"cron job already exists, updating it: {existing_job_name} ({existing_job_id})")
        run_checked(cron_edit_cmd(args, existing_job_id, deliver, gate_script, skill_target))
        configure_activity_source(state_script, state_path, deliver)
    else:
        run_checked(create_cmd)
        configure_activity_source(state_script, state_path, deliver)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
