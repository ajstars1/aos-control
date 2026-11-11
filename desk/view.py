#!/usr/bin/env python3
"""Watch a Wayland desktop inside a kitty window (default: the agent desktop), using the kitty graphics protocol.

  python3 desk/view.py                     # agent desktop, frames from its view-only VNC (127.0.0.1:5911)
  python3 desk/view.py -i                  # same, and forward mouse + keys to the agent desktop
  python3 desk/view.py --wayland wayland-1 # any Wayland display through grim polling (read-only)

Ctrl+] quits and restores the terminal. Stdlib only.

How it draws: frames go to kitty as raw RGB through POSIX shared memory (t=s, a file in /dev/shm whose
name is sent base64-encoded) when the terminal accepts it, else as PNG in 4096-byte base64 chunks (f=100).
The image is fitted to the window using the cell size in pixels (CSI 16 t), redrawn only when the frame
hash changes, only the newest frame is kept, and two image ids alternate so the old image is deleted
after the new one is on screen (no flicker). Patterns after github.com/govijr/terminal-mac (MIT),
reimplemented here.
"""

import argparse
import base64
import fcntl
import hashlib
import os
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import tty
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rfb import KEYSYMS, RFBClient, RFBError, broker_call, png_encode  # noqa: E402

RUN = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
BROKER_SOCK = f"{RUN}/aos-agent-input.sock"
CHUNK = 4096
IDS = (7701, 7702)
QUIT = b"\x1d"  # Ctrl+]


# ---------- kitty graphics encoding (pure, unit-testable) ----------

def apc(ctrl: str, payload: bytes = b"") -> bytes:
    """One graphics command: ESC _ G <control> ; <payload> ESC \\ ."""
    return b"\x1b_G" + ctrl.encode() + (b";" + payload if payload else b"") + b"\x1b\\"


def png_chunks(png: bytes, ctrl: str) -> list[bytes]:
    """Direct transmission: base64 PNG split into 4096-byte chunks, control keys on the first one only."""
    data = base64.standard_b64encode(png)
    parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [b""]
    out = []
    for n, part in enumerate(parts):
        more = 1 if n < len(parts) - 1 else 0
        out.append(apc((f"f=100,{ctrl},m={more}" if n == 0 else f"m={more}"), part))
    return out


def shm_command(name: str, width: int, height: int, ctrl: str) -> bytes:
    """Shared-memory transmission of packed RGB; kitty reads and unlinks the object."""
    return apc(f"f=24,t=s,s={width},v={height},S={width * height * 3},{ctrl}",
               base64.standard_b64encode(name.encode()))


def write_shm(name: str, data: bytes) -> None:
    path = "/dev/shm/" + name.lstrip("/")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def fit(img_w: int, img_h: int, cols: int, rows: int, cell_w: int, cell_h: int) -> tuple[int, int, int, int]:
    """Largest cell box with the image's aspect ratio inside cols x rows. Returns (col0, row0, cols, rows)."""
    scale = min(cols * cell_w / img_w, rows * cell_h / img_h)
    c = max(1, min(cols, round(img_w * scale / cell_w)))
    r = max(1, min(rows, round(img_h * scale / cell_h)))
    return (cols - c) // 2, (rows - r) // 2, c, r


def rgbx_to_rgb(buf: bytes) -> bytes:
    out = bytearray(len(buf) // 4 * 3)
    out[0::3] = buf[0::4]
    out[1::3] = buf[1::4]
    out[2::3] = buf[2::4]
    return bytes(out)


def parse_ppm(data: bytes) -> tuple[int, int, bytes]:
    m = re.match(rb"P6\s+(\d+)\s+(\d+)\s+(\d+)\s", data)
    if not m:
        raise ValueError("not a binary PPM")
    w, h = int(m.group(1)), int(m.group(2))
    return w, h, data[m.end():m.end() + w * h * 3]


# ---------- frame sources: keep only the newest frame ----------

class Latest:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seq = 0
        self.frame: tuple[int, int, bytes] | None = None
        self.error = ""

    def put(self, w: int, h: int, rgb: bytes) -> None:
        with self.lock:
            self.frame = (w, h, rgb)
            self.seq += 1

    def get(self) -> tuple[int, tuple[int, int, bytes] | None]:
        with self.lock:
            return self.seq, self.frame


def vnc_source(host: str, port: int, latest: Latest) -> None:
    while True:
        try:
            client = RFBClient(host, port)
            client.sock.settimeout(None)
            client.request(incremental=False)
            while True:
                if client.read_message() == "frame":
                    latest.put(client.width, client.height, rgbx_to_rgb(bytes(client.fb)))
                    client.request(incremental=True)
        except (RFBError, OSError) as err:
            latest.error = f"VNC {host}:{port}: {err}; retrying"
            time.sleep(2)


def grim_source(display: str, fps: float, latest: Latest) -> None:
    env = dict(os.environ, WAYLAND_DISPLAY=display)
    while True:
        r = subprocess.run(["grim", "-c", "-t", "ppm", "-"], capture_output=True, env=env, timeout=15)
        if r.returncode == 0:
            latest.put(*parse_ppm(r.stdout))
            latest.error = ""
        else:
            latest.error = f"grim on {display}: {r.stderr.decode(errors='replace').strip()[:80]}"
        time.sleep(1 / fps)


# ---------- terminal ----------

class Term:
    def __init__(self) -> None:
        self.fd_in = sys.stdin.fileno()
        self.fd_out = sys.stdout.fileno()
        self.saved = termios.tcgetattr(self.fd_in)
        self.pending = bytearray()

    def write(self, data: bytes) -> None:
        view = memoryview(data)
        while view:
            n = os.write(self.fd_out, view)
            view = view[n:]

    def read(self, timeout: float) -> bytes:
        r, _, _ = select.select([self.fd_in], [], [], timeout)
        return os.read(self.fd_in, 65536) if r else b""

    def wait_for(self, pattern: bytes, timeout: float) -> re.Match | None:
        """Read replies until `pattern` matches; other bytes are kept for the input handler."""
        end = time.time() + timeout
        while time.time() < end:
            self.pending += self.read(max(0.0, end - time.time()))
            m = re.search(pattern, bytes(self.pending))  # a copy: the match must survive the del below
            if m:
                del self.pending[m.start():m.end()]
                return m
        return None

    def size(self) -> tuple[int, int, int, int]:
        """cols, rows, cell width px, cell height px."""
        cols, rows = os.get_terminal_size(self.fd_out)
        cols, rows = cols or 80, rows or 24
        self.write(b"\x1b[16t")
        m = self.wait_for(rb"\x1b\[6;(\d+);(\d+)t", 0.5)
        if m and int(m.group(1)) and int(m.group(2)):
            return cols, rows, int(m.group(2)), int(m.group(1))
        ws = fcntl.ioctl(self.fd_out, termios.TIOCGWINSZ, b"\0" * 8)
        r, c, xp, yp = struct.unpack("HHHH", ws)
        if xp and yp:
            return cols, rows, xp // c, yp // r
        return cols, rows, 10, 20

    def probe(self) -> str:
        """'shm' if kitty takes shared memory, 'direct' if it only takes inline data, '' if no graphics."""
        name = f"aos-view-probe-{os.getpid()}"
        try:
            write_shm(name, b"\0\0\0")
            self.write(apc("i=31,a=q,t=s,f=24,s=1,v=1", base64.standard_b64encode(name.encode())))
            self.write(apc("i=32,a=q,f=24,s=1,v=1", base64.standard_b64encode(b"\0\0\0")))
            self.write(b"\x1b[c")  # DA1 as a sentinel: every terminal answers it, after the graphics replies
            got = {}
            end = time.time() + 2
            while time.time() < end:
                self.pending += self.read(0.1)
                for m in re.finditer(rb"\x1b_Gi=(3[12]);([^\x1b]*)\x1b\\", self.pending):
                    got[m.group(1)] = m.group(2)
                if re.search(rb"\x1b\[\?[\d;]*c", self.pending):
                    break
            self.pending = re.sub(rb"\x1b_Gi=3[12];[^\x1b]*\x1b\\|\x1b\[\?[\d;]*c", b"", bytes(self.pending))
            self.pending = bytearray(self.pending)
        finally:
            try:
                os.unlink("/dev/shm/" + name)
            except FileNotFoundError:
                pass
        if got.get(b"31") == b"OK":
            return "shm"
        if got.get(b"32") == b"OK":
            return "direct"
        return ""

    def enter(self, mouse: bool) -> None:
        tty.setraw(self.fd_in)
        self.write(b"\x1b[?1049h\x1b[?25l\x1b[2J")
        if mouse:
            self.write(b"\x1b[?1000h\x1b[?1002h\x1b[?1006h\x1b[?1016h")

    def leave(self) -> None:
        self.write(b"\x1b[?1016l\x1b[?1006l\x1b[?1002l\x1b[?1000l")
        for i in IDS:
            self.write(apc(f"a=d,d=I,i={i},q=2"))
        self.write(b"\x1b[?25h\x1b[?1049l")
        termios.tcsetattr(self.fd_in, termios.TCSADRAIN, self.saved)


# ---------- input forwarding (agent desktop only) ----------

ESC_KEYS = {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left", b"[H": "home", b"[F": "end",
            b"[3~": "delete", b"[5~": "pageup", b"[6~": "pagedown", b"[2~": "insert"}


class Forwarder:
    def __init__(self) -> None:
        self.buttons = 0
        self.box = (0, 0, 1, 1, 1, 1)  # x0 px, y0 px, width px, height px, fb w, fb h

    def call(self, cmd: dict) -> None:
        try:
            broker_call(BROKER_SOCK, cmd, timeout=10)
        except (RFBError, OSError, ValueError):
            pass

    def to_fb(self, x: int, y: int) -> tuple[int, int]:
        x0, y0, w, h, fw, fh = self.box
        return (max(0, min(fw - 1, (x - x0) * fw // w)), max(0, min(fh - 1, (y - y0) * fh // h)))

    def mouse(self, b: int, x: int, y: int, release: bool) -> None:
        fx, fy = self.to_fb(x - 1, y - 1)
        if b & 64:
            down = {64: -1, 65: 1}.get(b & ~(4 | 8 | 16 | 32), 0)
            right = {66: -1, 67: 1}.get(b & ~(4 | 8 | 16 | 32), 0)
            self.call({"op": "scroll", "x": fx, "y": fy, "down": down, "right": right})
            return
        bit = {0: 1, 1: 2, 2: 4}.get(b & 3, 0)
        if b & 32:  # motion with a button held
            self.call({"op": "pointer", "x": fx, "y": fy, "buttons": self.buttons})
            return
        self.buttons = (self.buttons & ~bit) if release else (self.buttons | bit)
        self.call({"op": "pointer", "x": fx, "y": fy, "buttons": self.buttons})

    def keys(self, data: bytes) -> None:
        i = 0
        text = bytearray()

        def flush() -> None:
            if text:
                self.call({"op": "type", "text": text.decode(errors="replace")})
                text.clear()

        while i < len(data):
            ch = data[i]
            if ch == 0x1B:
                flush()
                rest = data[i + 1:]
                for seq, name in ESC_KEYS.items():
                    if rest.startswith(seq):
                        self.call({"op": "keys", "chords": [[KEYSYMS[name]]]})
                        i += 1 + len(seq)
                        break
                else:
                    self.call({"op": "keys", "chords": [[KEYSYMS["escape"]]]})
                    i += 1
                continue
            if ch in (0x0D, 0x0A):
                flush()
                self.call({"op": "keys", "chords": [[KEYSYMS["enter"]]]})
            elif ch == 0x7F:
                flush()
                self.call({"op": "keys", "chords": [[KEYSYMS["backspace"]]]})
            elif ch == 0x09:
                flush()
                self.call({"op": "keys", "chords": [[KEYSYMS["tab"]]]})
            elif 1 <= ch <= 26:
                flush()
                self.call({"op": "keys", "chords": [[KEYSYMS["ctrl"], ord("a") + ch - 1]]})
            elif ch >= 0x20:
                text.append(ch)
            i += 1
        flush()


MOUSE_RE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")


# ---------- main loop ----------

def main() -> int:
    ap = argparse.ArgumentParser(description="Watch a Wayland desktop in kitty (Ctrl+] quits).")
    ap.add_argument("--vnc", default="127.0.0.1:5911", help="VNC host:port to watch (default: agent desktop)")
    ap.add_argument("--wayland", default="", help="watch this Wayland socket via grim instead (e.g. wayland-1)")
    ap.add_argument("--fps", type=float, default=0, help="max redraws per second (default 15 shm, 5 direct)")
    ap.add_argument("--transport", choices=("auto", "shm", "direct"), default="auto")
    ap.add_argument("-i", "--interactive", action="store_true", help="forward mouse and keys to the agent desktop")
    args = ap.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("view.py needs a terminal (run it in a kitty window)", file=sys.stderr)
        return 2
    if args.interactive and args.wayland:
        print("--interactive only works for the agent desktop (not --wayland)", file=sys.stderr)
        return 2

    term = Term()
    latest = Latest()
    stop = {"now": False, "resized": True}
    signal.signal(signal.SIGWINCH, lambda *_: stop.update(resized=True))
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.update(now=True))
    fwd = Forwarder() if args.interactive else None
    failure = ""
    term.enter(mouse=bool(fwd))
    try:
        mode = term.probe() if args.transport == "auto" else args.transport
        if not mode:
            failure = "this terminal does not speak the kitty graphics protocol; run view.py inside kitty"
            return 2
        fps = args.fps or (15 if mode == "shm" else 5)
        if args.wayland:
            source = f"{args.wayland} (grim)"
            threading.Thread(target=grim_source, args=(args.wayland, min(fps, 10), latest), daemon=True).start()
        else:
            host, port = args.vnc.rsplit(":", 1)
            source = f"agent desktop ({args.vnc})"
            threading.Thread(target=vnc_source, args=(host, int(port), latest), daemon=True).start()

        cols = rows = cw = ch = 0
        drawn_seq, drawn_hash, which, shown = -1, b"", 0, None
        frames_drawn, t0, rate = 0, time.time(), 0.0
        shm_names: list[str] = []
        status_text = ""
        while not stop["now"]:
            data = term.read(1 / fps)
            if data:
                term.pending += data
            buf = bytes(term.pending)
            term.pending.clear()
            if QUIT in buf:
                break
            if fwd:
                for m in MOUSE_RE.finditer(buf):
                    fwd.mouse(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) == b"m")
                rest = MOUSE_RE.sub(b"", buf)
                if rest:
                    fwd.keys(rest)
            if stop["resized"]:
                stop["resized"] = False
                cols, rows, cw, ch = term.size()
                term.write(b"\x1b[2J")
                drawn_hash = b""
            seq, frame = latest.get()
            if frame is not None and seq != drawn_seq:
                drawn_seq = seq
                w, h, rgb = frame
                digest = hashlib.blake2b(rgb, digest_size=16).digest() + struct.pack("HH", w, h)
                if digest != drawn_hash:
                    drawn_hash = digest
                    col0, row0, c, r = fit(w, h, cols, max(1, rows - 1), cw, ch)
                    new_id = IDS[which]
                    which ^= 1
                    ctrl = f"a=T,i={new_id},c={c},r={r},C=1,q=2"
                    out = [f"\x1b[{row0 + 1};{col0 + 1}H".encode()]
                    if mode == "shm":
                        name = f"aos-view-{os.getpid()}-{seq}"
                        write_shm(name, rgb)
                        shm_names.append(name)
                        out.append(shm_command(name, w, h, ctrl))
                    else:
                        out.extend(png_chunks(png_encode(rgb, w, h, level=1), ctrl))
                    if shown is not None:
                        out.append(apc(f"a=d,d=I,i={shown},q=2"))
                    term.write(b"".join(out))
                    shown = new_id
                    if fwd:
                        fwd.box = (col0 * cw, row0 * ch, c * cw, r * ch, w, h)
                    frames_drawn += 1
                    # kitty unlinks shm objects it has read; clean up any it skipped, two frames later
                    while len(shm_names) > 2:
                        try:
                            os.unlink("/dev/shm/" + shm_names.pop(0))
                        except FileNotFoundError:
                            pass
            now = time.time()
            if now - t0 >= 1:
                rate, frames_drawn, t0 = frames_drawn / (now - t0), 0, now
            size = f"{frame[0]}x{frame[1]}" if frame else "waiting for first frame"
            text = (f" {source} {size} | {mode} | {rate:.1f} fps | "
                    f"{'mouse+keys forwarded | ' if fwd else ''}Ctrl+] quit {latest.error}")[:max(1, cols - 1)]
            if text != status_text:
                status_text = text
                term.write(f"\x1b[{rows};1H\x1b[2K\x1b[7m{text}\x1b[0m".encode())
        for name in shm_names:
            try:
                os.unlink("/dev/shm/" + name)
            except FileNotFoundError:
                pass
    finally:
        try:
            term.leave()
        except termios.error:
            pass
        if failure:
            print(failure, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
