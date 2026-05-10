#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


@dataclass
class CronLookup:
    job: tuple[str, str] | None = None
    error: str | None = None


def expand(value: str) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(value)).resolve()


def openclaw_home() -> pathlib.Path:
    return expand(os.environ.get("OPENCLAW_HOME", "~/.openclaw"))


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


def build_prompt(gate_script: pathlib.Path, state_script: pathlib.Path) -> str:
    return (
        f"Use the nudge skill. First run: python3 {gate_script}. "
        "If the gate output status is silent, final reply exactly HEARTBEAT_OK. "
        "If the gate prints NUDGE_GATE_CONTEXT, decide whether to send one short proactive message. "
        f"Before final reply, update state with python3 {state_script} record-decision. "
        "If silent, final reply exactly HEARTBEAT_OK. If sending, final reply only the user-facing nudge."
    )


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


def add_optional_cron_args(cmd: list[str], args: argparse.Namespace) -> None:
    if args.to:
        cmd.extend(["--to", args.to])
    if args.account:
        cmd.extend(["--account", args.account])
    if args.model:
        cmd.extend(["--model", args.model])
    if args.thinking:
        cmd.extend(["--thinking", args.thinking])


def cron_add_cmd(args: argparse.Namespace, prompt: str) -> list[str]:
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
        "--announce",
        "--channel",
        args.channel,
        "--message",
        prompt,
        "--tools",
        args.tools,
    ]
    add_optional_cron_args(cmd, args)
    return cmd


def cron_edit_cmd(args: argparse.Namespace, job_id: str, prompt: str) -> list[str]:
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
        "--announce",
        "--channel",
        args.channel,
        "--message",
        prompt,
        "--tools",
        args.tools,
    ]
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
) -> int:
    print("OpenClaw nudge install check")
    ok = True
    ok = check_path("skill target", skill_target) and ok
    ok = check_path("runtime target", runtime_target) and ok
    ok = check_path("state file", state_path) and ok

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
            print(shlex.join(cron_edit_cmd(args, job_id, prompt)))
        else:
            print("cron command to create job:")
            print(shlex.join(cron_add_cmd(args, prompt)))
    elif lookup.job and args.no_update_cron:
        job_id, job_name = lookup.job
        print(f"planned cron action: leave existing job unchanged: {job_name} ({job_id})")
    elif lookup.job:
        job_id, _ = lookup.job
        print("planned cron action: update existing job")
        print(shlex.join(cron_edit_cmd(args, job_id, prompt)))
    else:
        print("planned cron action: create job")
        print(shlex.join(cron_add_cmd(args, prompt)))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and activate the OpenClaw nudge locally.")
    parser.add_argument("--skill-target", default=str(openclaw_home() / "skills" / "nudge"))
    parser.add_argument("--runtime-target", default=str(openclaw_home() / "nudge"))
    parser.add_argument("--state", default=str(openclaw_home() / "nudge" / "state.json"))
    parser.add_argument("--schedule", default="10m", help="OpenClaw --every duration.")
    parser.add_argument("--name", default="nudge")
    parser.add_argument("--session", choices=["isolated", "main"], default="isolated")
    parser.add_argument("--channel", default="last")
    parser.add_argument("--to", default="")
    parser.add_argument("--account", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--thinking", default="")
    parser.add_argument("--tools", default="exec,read,write")
    parser.add_argument("--force", action="store_true", help="Replace installed skill/runtime files.")
    parser.add_argument("--check", action="store_true", help="Check paths and planned cron action without installing files or editing cron.")
    parser.add_argument("--no-create-cron", action="store_true", help="Install files only; do not create the OpenClaw cron job.")
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
    lookup = find_cron_job(args.name)

    if args.check:
        return run_check(args, skill_target, runtime_target, state_path, lookup, prompt)

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
    prompt = build_prompt(gate_script, state_script)

    existing_job = lookup.job
    existing_job_id = existing_job[0] if existing_job else None
    existing_job_name = existing_job[1] if existing_job else None
    create_cmd = cron_add_cmd(args, prompt)

    if args.no_create_cron:
        if lookup.error:
            print(f"could not check existing cron job: {lookup.error}")
        if existing_job_id and not args.no_update_cron:
            print("cron command not run. Update the existing job with:")
            print(shlex.join(cron_edit_cmd(args, existing_job_id, prompt)))
        else:
            print("cron command not run. Create it with:")
            print(shlex.join(create_cmd))
    elif existing_job_id and args.no_update_cron:
        print(f"cron job already exists, leaving it unchanged: {existing_job_name} ({existing_job_id})")
        print("omit --no-update-cron to update it, or use a different --name to create another job")
    elif existing_job_id:
        print(f"cron job already exists, updating it: {existing_job_name} ({existing_job_id})")
        run_checked(cron_edit_cmd(args, existing_job_id, prompt))
    else:
        run_checked(create_cmd)

    print(f"gate script: {gate_script}")
    print(f"state file: {state_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
