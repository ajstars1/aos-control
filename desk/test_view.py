"""Offline tests for view.py's kitty graphics output. Run: python3 desk/test_view.py

The pty test plays a minimal kitty: it answers the graphics probe and the cell-size query, then checks the
escape stream view.py writes and that Ctrl+] restores the terminal. It needs a frame source; set
AOS_VIEW_TEST_DISPLAY to a Wayland socket (e.g. the agent desktop's) to run it, otherwise it is skipped.
"""

import base64
import fcntl
import os
import pty
import re
import select
import struct
import sys
import termios
import time
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import view  # noqa: E402
from rfb import png_encode  # noqa: E402


class Encoder(unittest.TestCase):
    def test_apc(self) -> None:
        self.assertEqual(view.apc("a=d,d=I,i=7,q=2"), b"\x1b_Ga=d,d=I,i=7,q=2\x1b\\")
        self.assertEqual(view.apc("a=q", b"QUJD"), b"\x1b_Ga=q;QUJD\x1b\\")

    def test_png_chunks(self) -> None:
        png = os.urandom(10000)
        chunks = view.png_chunks(png, "a=T,i=7701,c=80,r=24,C=1,q=2")
        self.assertEqual(len(chunks), 4)  # 13336 base64 bytes -> 4096*3 + 1048
        payload = b""
        for n, c in enumerate(chunks):
            m = re.fullmatch(rb"\x1b_G([^;]*);([A-Za-z0-9+/=]*)\x1b\\", c)
            self.assertIsNotNone(m)
            ctrl, data = m.group(1), m.group(2)
            self.assertLessEqual(len(data), 4096)
            if n == 0:
                self.assertTrue(ctrl.startswith(b"f=100,a=T,i=7701"))
                self.assertTrue(ctrl.endswith(b"m=1"))
            else:
                self.assertEqual(ctrl, b"m=1" if n < 3 else b"m=0")
            payload += data
        self.assertEqual(base64.standard_b64decode(payload), png)

    def test_single_chunk(self) -> None:
        (only,) = view.png_chunks(b"x" * 10, "a=T")
        self.assertIn(b"m=0", only)

    def test_shm(self) -> None:
        cmd = view.shm_command("aos-view-1-2", 1280, 800, "a=T,i=7702,c=100,r=40,C=1,q=2")
        m = re.fullmatch(rb"\x1b_G([^;]*);([A-Za-z0-9+/=]*)\x1b\\", cmd)
        self.assertEqual(m.group(1), b"f=24,t=s,s=1280,v=800,S=3072000,a=T,i=7702,c=100,r=40,C=1,q=2")
        self.assertEqual(base64.standard_b64decode(m.group(2)), b"aos-view-1-2")

    def test_fit(self) -> None:
        # 1280x800 into 200x50 cells of 10x20 px: height-bound, 1600 px tall would not fit
        col0, row0, c, r = view.fit(1280, 800, 200, 50, 10, 20)
        self.assertEqual((r, row0), (50, 0))
        self.assertAlmostEqual(c * 10 / (r * 20), 1280 / 800, delta=0.03)
        self.assertEqual(col0, (200 - c) // 2)

    def test_pixels(self) -> None:
        self.assertEqual(view.rgbx_to_rgb(bytes([1, 2, 3, 0, 4, 5, 6, 0])), bytes([1, 2, 3, 4, 5, 6]))
        w, h, rgb = view.parse_ppm(b"P6\n2 1\n255\n" + bytes(range(6)))
        self.assertEqual((w, h, rgb), (2, 1, bytes(range(6))))
        png = png_encode(bytes(range(6)), 2, 1)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        self.assertEqual(zlib.decompress(idat), b"\x00" + bytes(range(6)))


@unittest.skipUnless(os.environ.get("AOS_VIEW_TEST_DISPLAY"), "set AOS_VIEW_TEST_DISPLAY=wayland-N")
class FakeKitty(unittest.TestCase):
    def run_view(self, shm_ok: bool) -> bytes:
        pid, fd = pty.fork()
        if pid == 0:
            os.execv(sys.executable, [sys.executable, "-I", str(HERE / "view.py"),
                                      "--wayland", os.environ["AOS_VIEW_TEST_DISPLAY"], "--fps", "4"])
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 1200, 800))  # 120x40 cells of 10x20
        out = bytearray()
        quit_at = None
        end = time.time() + 15
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.1)
            if r:
                try:
                    chunk = os.read(fd, 1 << 20)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
                if b"i=31,a=q" in chunk:  # graphics probe: answer like kitty
                    os.write(fd, b"\x1b_Gi=31;" + (b"OK" if shm_ok else b"EBADF:no shm") + b"\x1b\\"
                             + b"\x1b_Gi=32;OK\x1b\\\x1b[?62;c")
                if b"\x1b[16t" in chunk:
                    os.write(fd, b"\x1b[6;20;10t")
                if quit_at is None and (b"t=s," in out or b"f=100," in out):
                    quit_at = time.time() + 0.5
            if quit_at and time.time() > quit_at:
                os.write(fd, b"\x1d")  # Ctrl+]
                quit_at = float("inf")
        _, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        return bytes(out)

    def check_common(self, out: bytes) -> None:
        self.assertIn(b"\x1b[?1049h", out)
        self.assertIn(b"\x1b[16t", out)
        self.assertTrue(out.rstrip().endswith(b"\x1b[?25h\x1b[?1049l"), out[-80:])
        self.assertIn(b"a=d,d=I,i=7701,q=2", out)

    def test_shm_path(self) -> None:
        out = self.run_view(shm_ok=True)
        self.check_common(out)
        m = re.search(rb"\x1b_Gf=24,t=s,s=(\d+),v=(\d+),S=\d+,a=T,i=770[12],c=(\d+),r=(\d+),C=1,q=2;([^\x1b]+)", out)
        self.assertIsNotNone(m, "no shm frame")
        # 1280x800 fitted into 120x39 cells of 10x20 px keeps the aspect ratio
        c, r = int(m.group(3)), int(m.group(4))
        self.assertLessEqual(c, 120)
        self.assertLessEqual(r, 39)
        self.assertAlmostEqual(c * 10 / (r * 20), int(m.group(1)) / int(m.group(2)), delta=0.05)
        name = base64.standard_b64decode(m.group(5)).decode()
        self.assertTrue(name.startswith("aos-view-"))
        self.assertFalse(Path("/dev/shm", name).exists(), "view.py left a shm object behind")

    def test_direct_path(self) -> None:
        out = self.run_view(shm_ok=False)
        self.check_common(out)
        self.assertNotIn(b"f=24,t=s,", out)
        first = re.search(rb"\x1b_Gf=100,a=T,i=770[12],c=\d+,r=\d+,C=1,q=2,m=1;([^\x1b]+)\x1b\\", out)
        self.assertIsNotNone(first, "no direct PNG frame")
        self.assertLessEqual(len(first.group(1)), 4096)
        data = base64.standard_b64decode(first.group(1)[:4096 // 4 * 4])
        self.assertTrue(data.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
