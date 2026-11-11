"""Live view of the desktop in Discord: one webhook message whose screenshot is swapped every few seconds.

Started by the desk MCP (live_start). Usage: python3 -I live.py <minutes> <every_seconds>
Stdlib only. The webhook URL comes from the repo's .env.local (DISCORD_WEBHOOK_URL).
"""

import hashlib
import json
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env.local"
PID_FILE = Path.home() / ".cache" / "aos-desk" / "live.pid"
HEARTBEAT_SECONDS = 60   # unchanged screen: refresh only the caption, at most this often
IDLE_STOP_MINUTES = 10   # unchanged this long: stop early


def webhook_url() -> str:
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DISCORD_WEBHOOK_URL="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("DISCORD_WEBHOOK_URL missing in the repo's .env.local")


def grab() -> bytes | None:
    r = subprocess.run(["grim", "-c", "-t", "png", "-l", "4", "-"], capture_output=True, timeout=15)
    return r.stdout if r.returncode == 0 else None


def send(method: str, url: str, content: str, png: bytes | None) -> dict:
    payload: dict = {"content": content, "allowed_mentions": {"parse": []}}
    if png is None:
        body, ctype = json.dumps(payload).encode(), "application/json"
    else:
        payload["attachments"] = [{"id": 0, "filename": "screen.png"}]
        b = uuid.uuid4().hex
        body = b"".join([
            f'--{b}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'.encode(),
            json.dumps(payload).encode(),
            f'\r\n--{b}\r\nContent-Disposition: form-data; name="files[0]"; filename="screen.png"\r\nContent-Type: image/png\r\n\r\n'.encode(),
            png,
            f"\r\n--{b}--\r\n".encode(),
        ])
        ctype = f"multipart/form-data; boundary={b}"
    req = urllib.request.Request(url, data=body, method=method,
                                 headers={"Content-Type": ctype, "User-Agent": "aos-desk-live (1.0)"})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as err:
            if err.code != 429:
                raise
            time.sleep(float(json.loads(err.read() or b"{}").get("retry_after", 2)))
    return {}


def main() -> None:
    minutes, every = float(sys.argv[1]), float(sys.argv[2])
    hook = webhook_url()
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    end = time.time() + minutes * 60
    stamp = lambda: time.strftime("%H:%M:%S")  # noqa: E731
    first = grab()
    msg = send("POST", hook + "?wait=true", f"🔴 live view, {minutes:g} min ({stamp()})", first)
    edit = f"{hook}/messages/{msg['id']}"
    # Only upload when the screen changed: same picture, no Discord edit (rate limits, bandwidth).
    last_hash = hashlib.sha256(first).hexdigest() if first else ""
    changed_at = last_caption = time.time()
    why = "last frame"
    try:
        while not stop["now"] and time.time() < end:
            time.sleep(every)
            png = grab()
            now = time.time()
            ends = time.strftime('%H:%M', time.localtime(end))
            if png is None:
                send("PATCH", edit, f"🔴 live {stamp()}, ends {ends}: screen locked or capture failed", None)
                last_caption = now
                continue
            digest = hashlib.sha256(png).hexdigest()
            if digest != last_hash:
                send("PATCH", edit, f"🔴 live {stamp()}, ends {ends}", png)
                last_hash, changed_at, last_caption = digest, now, now
            elif now - changed_at >= IDLE_STOP_MINUTES * 60:
                why = f"no change for {IDLE_STOP_MINUTES} min"
                break
            elif now - last_caption >= HEARTBEAT_SECONDS:
                since = time.strftime("%H:%M:%S", time.localtime(changed_at))
                send("PATCH", edit, f"🔴 live {stamp()}, ends {ends} (no change since {since})", None)
                last_caption = now
    finally:
        send("PATCH", edit, f"⏹ live view ended {stamp()} ({why})", None)
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
