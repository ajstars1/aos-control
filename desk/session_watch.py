#!/usr/bin/env python3
"""Watch a claude_session from outside it and ping Discord if it dies mid-task.

The Stop hook (session_done_hook.py) cannot run when the session is killed (systemd-oomd kills the whole kitty
scope on low memory), so claude_session also starts this script in its own systemd user unit. It finds the
`claude --remote-control <name>` process, waits for it to exit, and if the session was busy (state file says
"busy", or no Stop hook ever fired) it posts a warning. Usage: session_watch.py <name> [channel]
"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aosconf import dm_channel  # noqa: E402
from session_done_hook import notify, state_file  # noqa: E402


def find_pid(name: str) -> int | None:
    out = subprocess.run(["pgrep", "-f", f"claude --remote-control {name} "], capture_output=True, text=True).stdout
    pids = [int(p) for p in out.split()]
    return min(pids) if pids else None


def main() -> None:
    name = sys.argv[1]
    channel = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else dm_channel()
    pid = None
    for _ in range(60):  # the session may take a few seconds to start
        pid = find_pid(name)
        if pid:
            break
        time.sleep(2)
    if not pid:
        return
    while Path(f"/proc/{pid}").exists():
        time.sleep(10)
    state = state_file(name)
    status = state.read_text().strip() if state.exists() else "busy"
    if status == "busy":
        oom = subprocess.run(["journalctl", "--user", "--since", "-3min", "--no-pager", "-q", "--grep", "oomd killed"],
                             capture_output=True, text=True).stdout.strip()
        why = "the PC ran out of memory (systemd-oomd)" if oom else "unknown reason"
        notify(channel, f"⚠️ **{name}** died mid-task: {why}. Its work so far is saved; say \"restart {name}\".")
    state.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
