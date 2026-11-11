"""Minimal RFB (VNC) client, stdlib only: enough to drive and watch the agent desktop through wayvnc.

Protocol 3.8, security type None, 32-bit true-colour Raw frames, PointerEvent, KeyEvent (X keysyms),
DesktopSize/ExtendedDesktopSize so the server can resize its output, and SetDesktopSize to ask it to.
Used by agent_desk_server.py and view.py. `python3 -I rfb.py serve-input ...` runs the input broker: the single
permanent input client of the agent desktop (see serve_input for why), which agents and view.py talk to over a
unix socket with broker_call().
"""

import socket
import struct
import time

# Pixel format we ask for: 32 bpp, depth 24, little-endian, red at byte 0, green 1, blue 2, byte 3 unused.
PIXEL_FORMAT = struct.pack(">BBBBHHHBBB3x", 32, 24, 0, 1, 255, 255, 255, 0, 8, 16)
ENC_RAW = 0
ENC_DESKTOP_SIZE = -223
ENC_EXT_DESKTOP_SIZE = -308

BUTTONS = {"left": 1, "middle": 2, "right": 4}
WHEEL = {"up": 8, "down": 16, "left": 32, "right": 64}

# X keysyms for named keys (case-insensitive). Printable ASCII maps to its own code point.
KEYSYMS = {
    "backspace": 0xFF08, "tab": 0xFF09, "enter": 0xFF0D, "return": 0xFF0D, "esc": 0xFF1B, "escape": 0xFF1B,
    "delete": 0xFFFF, "del": 0xFFFF, "home": 0xFF50, "left": 0xFF51, "up": 0xFF52, "right": 0xFF53,
    "down": 0xFF54, "pageup": 0xFF55, "pagedown": 0xFF56, "end": 0xFF57, "insert": 0xFF63,
    "menu": 0xFF67, "print": 0xFF61, "space": 0x0020,
    "shift": 0xFFE1, "ctrl": 0xFFE3, "control": 0xFFE3, "alt": 0xFFE9, "super": 0xFFEB, "meta": 0xFFEB,
    "win": 0xFFEB, "cmd": 0xFFEB,
    **{f"f{i}": 0xFFBE + i - 1 for i in range(1, 13)},
}
SHIFT_CHARS = set('~!@#$%^&*()_+{}|:"<>?') | {chr(c) for c in range(ord("A"), ord("Z") + 1)}


class RFBError(RuntimeError):
    pass


def char_keysym(ch: str) -> int:
    """Keysym for one typed character. Latin-1 maps directly, other Unicode uses the 0x01000000 range."""
    if ch == "\n":
        return KEYSYMS["enter"]
    if ch == "\t":
        return KEYSYMS["tab"]
    cp = ord(ch)
    if 0x20 <= cp <= 0x7E or 0xA0 <= cp <= 0xFF:
        return cp
    if cp < 0x20:
        raise ValueError(f"cannot type control character {ch!r}; use key instead")
    return 0x01000000 | cp


def name_keysym(name: str) -> int:
    n = name.strip()
    if n.lower() in KEYSYMS:
        return KEYSYMS[n.lower()]
    if len(n) == 1:
        return char_keysym(n.lower() if n.isalpha() else n)
    raise ValueError(f"unknown key {name!r}; use names like enter, esc, tab, ctrl, shift, alt, super, f5, a, 1")


class RFBClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5910, timeout: float = 5.0) -> None:
        try:
            self.sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as err:
            raise RFBError(f"cannot reach VNC at {host}:{port}: {err}") from err
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buttons = 0
        self.x = 0
        self.y = 0
        self.ext_desktop = False
        self._handshake()

    # ---------- plumbing ----------

    def _recv(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self.sock.recv(min(n - len(buf), 1 << 20))
            if not chunk:
                raise RFBError("VNC server closed the connection")
            buf += chunk
        return bytes(buf)

    def _send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "RFBClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _handshake(self) -> None:
        version = self._recv(12)
        if not version.startswith(b"RFB 003."):
            raise RFBError(f"not a VNC server (greeting {version!r})")
        self._send(b"RFB 003.008\n")
        (count,) = struct.unpack(">B", self._recv(1))
        if count == 0:
            (n,) = struct.unpack(">I", self._recv(4))
            raise RFBError(f"VNC refused: {self._recv(n).decode(errors='replace')}")
        types = self._recv(count)
        if 1 not in types:
            raise RFBError(f"VNC server wants authentication (types {list(types)}); the agent desktop runs without it")
        self._send(b"\x01")
        (result,) = struct.unpack(">I", self._recv(4))
        if result != 0:
            raise RFBError("VNC security handshake failed")
        self._send(b"\x01")  # shared: do not kick other viewers
        w, h = struct.unpack(">HH", self._recv(4))
        self._recv(16)  # server pixel format, replaced below
        (name_len,) = struct.unpack(">I", self._recv(4))
        self.name = self._recv(name_len).decode(errors="replace")
        self.width, self.height = w, h
        self.fb = bytearray(w * h * 4)
        self._send(b"\x00\x00\x00\x00" + PIXEL_FORMAT)  # type 0, 3 pad, 16-byte format
        encs = [ENC_RAW, ENC_DESKTOP_SIZE, ENC_EXT_DESKTOP_SIZE]
        self._send(struct.pack(">BxH", 2, len(encs)) + b"".join(struct.pack(">i", e) for e in encs))

    # ---------- input ----------

    def pointer(self, x: int, y: int, buttons: int | None = None) -> None:
        self.x = max(0, min(int(x), self.width - 1))
        self.y = max(0, min(int(y), self.height - 1))
        if buttons is not None:
            self.buttons = buttons
        self._send(struct.pack(">BBHH", 5, self.buttons, self.x, self.y))

    def click(self, x: int, y: int, button: str = "left", count: int = 1) -> None:
        bit = BUTTONS[button]
        self.pointer(x, y, 0)
        time.sleep(0.05)
        for _ in range(max(1, min(count, 3))):
            self.pointer(x, y, bit)
            time.sleep(0.04)
            self.pointer(x, y, 0)
            time.sleep(0.06)

    def drag(self, x1: int, y1: int, x2: int, y2: int, steps: int = 12) -> None:
        self.pointer(x1, y1, 0)
        time.sleep(0.05)
        self.pointer(x1, y1, BUTTONS["left"])
        time.sleep(0.05)
        for i in range(1, steps + 1):
            self.pointer(round(x1 + (x2 - x1) * i / steps), round(y1 + (y2 - y1) * i / steps))
            time.sleep(0.03)
        self.pointer(x2, y2, 0)

    def scroll(self, x: int, y: int, down: int = 0, right: int = 0) -> None:
        self.pointer(x, y, 0)
        time.sleep(0.03)
        for direction, n in (("down" if down > 0 else "up", abs(down)), ("right" if right > 0 else "left", abs(right))):
            for _ in range(n):
                self.pointer(x, y, WHEEL[direction])
                self.pointer(x, y, 0)
                time.sleep(0.03)

    def key_event(self, keysym: int, down: bool) -> None:
        self._send(struct.pack(">BBxxI", 4, 1 if down else 0, keysym))

    def chord(self, keysyms: list[int]) -> None:
        for k in keysyms:
            self.key_event(k, True)
            time.sleep(0.01)
        for k in reversed(keysyms):
            self.key_event(k, False)
            time.sleep(0.01)

    def type_text(self, text: str, delay: float = 0.01) -> None:
        for ch in text:
            sym = char_keysym(ch)
            # wayvnc maps keysyms to keycodes through its keymap; send Shift for shifted ASCII so
            # apps that look at modifiers see a normal key press.
            if ch in SHIFT_CHARS:
                self.chord([KEYSYMS["shift"], sym])
            else:
                self.chord([sym])
            time.sleep(delay)

    def set_desktop_size(self, w: int, h: int) -> None:
        """Ask the server to resize its output (wayvnc does this for headless outputs)."""
        self._send(struct.pack(">BxHHBx", 251, w, h, 1) + struct.pack(">IHHHHI", 0, 0, 0, w, h, 0))

    # ---------- frames ----------

    def request(self, incremental: bool = True) -> None:
        self._send(struct.pack(">BBHHHH", 3, 1 if incremental else 0, 0, 0, self.width, self.height))

    def _resize(self, w: int, h: int) -> None:
        if (w, h) != (self.width, self.height):
            self.width, self.height = w, h
            self.fb = bytearray(w * h * 4)

    def read_message(self) -> str:
        """Read one server message, applying frame updates to self.fb. Returns its kind."""
        (kind,) = struct.unpack(">B", self._recv(1))
        if kind == 0:
            (n,) = struct.unpack(">xH", self._recv(3))
            for _ in range(n):
                x, y, w, h, enc = struct.unpack(">HHHHi", self._recv(12))
                if enc == ENC_RAW:
                    data = self._recv(w * h * 4)
                    stride = self.width * 4
                    for row in range(h):
                        off = (y + row) * stride + x * 4
                        self.fb[off:off + w * 4] = data[row * w * 4:(row + 1) * w * 4]
                elif enc == ENC_DESKTOP_SIZE:
                    self._resize(w, h)
                elif enc == ENC_EXT_DESKTOP_SIZE:
                    self.ext_desktop = True
                    (screens,) = struct.unpack(">B3x", self._recv(4))
                    self._recv(16 * screens)
                    self._resize(w, h)
                else:
                    raise RFBError(f"unexpected encoding {enc}")
            return "frame"
        if kind == 1:
            _, n = struct.unpack(">xHH", self._recv(5))
            self._recv(6 * n)
            return "colormap"
        if kind == 2:
            return "bell"
        if kind == 3:
            (n,) = struct.unpack(">3xI", self._recv(7))
            self._recv(n)
            return "cuttext"
        raise RFBError(f"unknown server message {kind}")

    def frame(self, incremental: bool = False, timeout: float = 5.0) -> bytearray:
        """Request and wait for one framebuffer update; returns the RGBX buffer (width*height*4)."""
        self.sock.settimeout(timeout)
        self.request(incremental)
        while self.read_message() != "frame":
            pass
        return self.fb

    def rgb(self) -> bytes:
        """The framebuffer as packed RGB (3 bytes per pixel)."""
        out = bytearray(self.width * self.height * 3)
        out[0::3] = self.fb[0::4]
        out[1::3] = self.fb[1::4]
        out[2::3] = self.fb[2::4]
        return bytes(out)


def png_encode(rgb: bytes, width: int, height: int, level: int = 3) -> bytes:
    """Encode packed RGB as PNG with zlib only."""
    import zlib

    stride = width * 3
    raw = bytearray()
    for row in range(height):
        raw += b"\x00" + rgb[row * stride:(row + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), level)) + chunk(b"IEND", b"")



def serve_input(host: str, port: int, sock_path: str, width: int, height: int) -> None:
    """Input broker: the one and only input client of the agent desktop's wayvnc.

    Why: wayvnc creates a virtual pointer per client and destroys it on disconnect. On cage 0.2.1 any
    Wayland client that starts after such a disconnect (a fresh Chrome, kitty, ...) segfaults, and a
    fresh connection's keyboard needs ~0.5 s before key presses land. So exactly one connection is
    opened, kept for the desktop's lifetime, and every agent/viewer sends input through this broker.

    Protocol on the unix socket: one JSON object per line, one JSON reply per line.
      {"op": "click", "x": 10, "y": 20, "button": "left", "count": 1}
      {"op": "move", "x": 10, "y": 20}            {"op": "pointer", "x": 1, "y": 2, "buttons": 1}
      {"op": "drag", "x1": .., "y1": .., "x2": .., "y2": ..}
      {"op": "scroll", "x": .., "y": .., "down": 3, "right": 0}
      {"op": "type", "text": "hi"}                {"op": "keys", "chords": [[65507, 108]]}
      {"op": "size"}
    The socket file only appears once VNC is connected and the output has its final size.
    """
    import json
    import os
    import selectors

    client = RFBClient(host, port)
    client.frame(timeout=10)
    if (client.width, client.height) != (width, height) and client.ext_desktop:
        client.set_desktop_size(width, height)
        for _ in range(30):
            client.frame(incremental=True, timeout=1)
            if (client.width, client.height) == (width, height):
                break
    client.sock.settimeout(None)
    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    listener.bind(sock_path)
    os.umask(old_umask)
    listener.listen(8)
    sel = selectors.DefaultSelector()
    sel.register(client.sock, selectors.EVENT_READ, "vnc")
    sel.register(listener, selectors.EVENT_READ, "listen")
    buffers: dict[socket.socket, bytearray] = {}

    def run(cmd: dict) -> dict:
        op = cmd.get("op")
        if op == "click":
            client.click(int(cmd["x"]), int(cmd["y"]), str(cmd.get("button", "left")), int(cmd.get("count", 1)))
        elif op == "move":
            client.pointer(int(cmd["x"]), int(cmd["y"]))
        elif op == "pointer":
            client.pointer(int(cmd["x"]), int(cmd["y"]), int(cmd["buttons"]))
        elif op == "drag":
            client.drag(int(cmd["x1"]), int(cmd["y1"]), int(cmd["x2"]), int(cmd["y2"]))
        elif op == "scroll":
            client.scroll(int(cmd["x"]), int(cmd["y"]), int(cmd.get("down", 0)), int(cmd.get("right", 0)))
        elif op == "type":
            client.type_text(str(cmd["text"]))
        elif op == "keys":
            for chord in cmd["chords"]:
                client.chord([int(k) for k in chord])
                time.sleep(0.05)
        elif op != "size":
            return {"ok": False, "error": f"unknown op {op!r}"}
        return {"ok": True, "width": client.width, "height": client.height, "x": client.x, "y": client.y}

    try:
        while True:
            for key, _ in sel.select():
                if key.data == "vnc":
                    if not client.sock.recv(65536):
                        return  # wayvnc went away: the desktop is gone
                elif key.data == "listen":
                    conn, _ = listener.accept()
                    buffers[conn] = bytearray()
                    sel.register(conn, selectors.EVENT_READ, "conn")
                else:
                    conn = key.fileobj
                    data = conn.recv(65536)
                    if not data:
                        sel.unregister(conn)
                        buffers.pop(conn, None)
                        conn.close()
                        continue
                    buf = buffers[conn]
                    buf += data
                    while b"\n" in buf:
                        line, _, rest = bytes(buf).partition(b"\n")
                        buf[:] = rest
                        try:
                            reply = run(json.loads(line))
                        except (ValueError, KeyError, TypeError) as err:
                            reply = {"ok": False, "error": f"bad command: {err}"}
                        try:
                            conn.sendall(json.dumps(reply).encode() + b"\n")
                        except OSError:
                            pass
    finally:
        try:
            os.unlink(sock_path)
        except OSError:
            pass


def broker_call(sock_path: str, cmd: dict, timeout: float = 60.0) -> dict:
    """Send one command to the input broker and wait for its reply."""
    import json

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        try:
            s.connect(sock_path)
        except OSError as err:
            raise RFBError(f"input broker not reachable at {sock_path}: {err}") from err
        s.sendall(json.dumps(cmd).encode() + b"\n")
        buf = bytearray()
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                raise RFBError("input broker closed the connection")
            buf += chunk
    reply = json.loads(buf)
    if not reply.get("ok"):
        raise RFBError(reply.get("error", "input broker error"))
    return reply


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 7 and sys.argv[1] == "serve-input":
        serve_input(sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5]), int(sys.argv[6]))
    else:
        raise SystemExit("usage: python3 -I rfb.py serve-input HOST PORT SOCKET WIDTH HEIGHT")
