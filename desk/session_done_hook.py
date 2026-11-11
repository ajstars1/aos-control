#!/usr/bin/env python3
"""Claude Code Stop hook for sessions opened by desk's claude_session.

Each time the session finishes a turn (task done, or it stopped to ask something), post its last reply to
the user on Discord with the bot, so a finished task pings their phone even if the aos session that dispatched it
is busy, restarted or was killed. Env: AOS_SESSION_NAME, AOS_NOTIFY_CHANNEL (Discord channel id, default the
owner's DM: AOS_DM_CHANNEL or the id the Discord agent saved, see aosconf.py). Never blocks the session: always
exits 0, and errors go to ~/.local/state/aos/notify-fallback.log.
"""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aosconf import dm_channel  # noqa: E402

BOT_ENV = Path.home() / ".claude" / "channels" / "discord" / ".env"
FALLBACK = Path.home() / ".local" / "state" / "aos" / "notify-fallback.log"
LIMIT = 1900


def last_reply(event: dict) -> str:
    text = event.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text.strip()
    path = event.get("transcript_path")
    if not path or not os.path.exists(path):
        return ""
    found = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant" or row.get("isSidechain"):
                continue
            parts = row.get("message", {}).get("content", [])
            if isinstance(parts, str):
                parts = [{"type": "text", "text": parts}]
            texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
            joined = "\n".join(t for t in texts if t.strip()).strip()
            if joined:
                found = joined
    return found


def chunks(text: str) -> list[str]:
    out = []
    while len(text) > LIMIT:
        cut = text.rfind("\n", 0, LIMIT)
        cut = cut if cut > 0 else LIMIT
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    out.append(text)
    return out[:4]  # keep the phone readable; the full text stays in the session


def attachments(reply: str) -> tuple[str, list[Path]]:
    """Lines "ATTACH: /abs/path" name files to upload (max 10, 25 MB each); they are removed from the text."""
    files, kept = [], []
    for line in reply.splitlines():
        m = re.match(r"^\s*[-*]?\s*ATTACH:\s*(/.+?)\s*$", line)
        if not m:
            kept.append(line)
            continue
        f = Path(m.group(1).strip("`'\""))
        if f.is_file() and f.stat().st_size <= 25 * 1024 * 1024 and len(files) < 10:
            files.append(f)
        else:
            kept.append(f"(could not attach {f.name})")
    return "\n".join(kept).strip(), files


def post(channel: str, token: str, content: str, files: list[Path] | None = None) -> None:
    headers = {"Authorization": f"Bot {token}", "User-Agent": "aos-desk (session-done, 1.0)"}
    payload = json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode()
    if files:
        boundary = f"aos{int(time.time() * 1000)}"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload_json\"\r\n"
                f"Content-Type: application/json\r\n\r\n").encode() + payload + b"\r\n"
        for i, f in enumerate(files):
            body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; "
                     f"filename=\"{f.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
            body += f.read_bytes() + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        body = payload
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"https://discord.com/api/v10/channels/{channel}/messages",
                                 data=body, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=60 if files else 8).read()


def state_file(name: str) -> Path:
    """busy/idle marker read by session_watch.py to tell a crash mid-task from a normal close."""
    d = Path.home() / ".cache" / "aos-desk" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.state"


def notify(channel: str, message: str, files: list[Path] | None = None) -> None:
    try:
        if not channel:
            raise RuntimeError("no Discord DM channel yet (start the Discord agent once, or set AOS_DM_CHANNEL)")
        m = re.search(r"^DISCORD_BOT_TOKEN=(.+)$", BOT_ENV.read_text(), re.M)
        if not m:
            raise RuntimeError("no DISCORD_BOT_TOKEN")
        parts = chunks(message)
        for i, part in enumerate(parts):
            post(channel, m.group(1).strip(), part, files if i == len(parts) - 1 else None)
    except Exception as err:  # never break the session over a ping
        FALLBACK.parent.mkdir(parents=True, exist_ok=True)
        with FALLBACK.open("a") as f:
            f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] (session-done: {type(err).__name__})\n{message}\n\n")


def main() -> None:
    name = os.environ.get("AOS_SESSION_NAME", "claude session")
    channel = os.environ.get("AOS_NOTIFY_CHANNEL") or dm_channel()
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    if event.get("hook_event_name") == "UserPromptSubmit":
        state_file(name).write_text("busy")
        return
    if event.get("hook_event_name") == "Notification":
        msg = str(event.get("message", ""))
        if "permission" in msg.lower():  # idle "waiting for input" notices repeat the Stop ping: skip them
            notify(channel, f"⏸️ **{name}** is stuck on a prompt: {msg}\nSay \"approve {name}\" or open the session.")
        return
    state_file(name).write_text("idle")
    reply, files = attachments(last_reply(event) or "(finished, no text reply)")
    notify(channel, f"🔔 **{name}** finished a turn:\n{reply}", files)


if __name__ == "__main__":
    main()
    sys.exit(0)
