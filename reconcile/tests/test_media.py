"""Tests for media mode (images / audio). `python -m unittest discover -s tests -v`

Media mode is deliberately NOT identity recognition. These tests lock that in:
the report must carry the disclaimer, and the verdict must only speak about
file characteristics.
"""

from __future__ import annotations

import contextlib
import io
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile as rc  # noqa: E402


def make_image(path: Path, *, size: tuple[int, int] = (200, 200), patch: bool = False) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, (240, 240, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 120, 120], fill=(200, 30, 30))
    if patch:
        draw.rectangle([20, 20, 60, 60], fill=(30, 30, 200))
    img.save(path)


def make_wav(path: Path, *, seconds: float = 1.0, rate: int = 8000, amplitude: int = 12000) -> None:
    frames = b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(int(seconds * rate))
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


class TestImages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.same_a = self.root / "a.png"
        self.same_b = self.root / "b.png"
        self.patched = self.root / "c.png"
        self.bigger = self.root / "d.png"
        self.other_format = self.root / "a.jpg"
        make_image(self.same_a)
        make_image(self.same_b)
        make_image(self.patched, patch=True)
        make_image(self.bigger, size=(300, 200))
        self.same_a.convert if False else None
        from PIL import Image

        Image.open(self.same_a).convert("RGB").save(self.other_format)

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_images(self):
        data = rc.compare_images(self.same_a, self.same_b)
        self.assertTrue(data["same_size"])
        self.assertEqual(data["hash_distance"], 0)
        self.assertLess(data["changed_ratio"], 0.001)
        self.assertIsNone(data["bbox"])

    def test_patched_image(self):
        data = rc.compare_images(self.same_a, self.patched)
        self.assertGreater(data["changed_ratio"], 0.01)
        self.assertIsNotNone(data["bbox"])
        self.assertGreater(data["max_channel_delta"], 50)

    def test_different_size(self):
        data = rc.compare_images(self.same_a, self.bigger)
        self.assertFalse(data["same_size"])
        self.assertNotIn("changed_ratio", data)

    def test_cross_format_compares(self):
        data = rc.compare_images(self.same_a, self.other_format)
        self.assertTrue(data["same_size"])
        self.assertLessEqual(data["hash_distance"], 6)

    def test_report_has_disclaimer(self):
        data = rc.compare_images(self.same_a, self.patched)
        report = rc.render_media(self.same_a, self.patched, data)
        self.assertIn("这不是身份识别", report)
        self.assertNotIn("同一个人（", report)


class TestAudio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.a = self.root / "a.wav"
        self.b = self.root / "b.wav"
        self.longer = self.root / "c.wav"
        self.quieter = self.root / "d.wav"
        make_wav(self.a)
        make_wav(self.b)
        make_wav(self.longer, seconds=1.5)
        make_wav(self.quieter, amplitude=1200)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stats(self):
        stats = rc.wav_stats(self.a)
        self.assertEqual(stats["rate"], 8000)
        self.assertEqual(stats["channels"], 1)
        self.assertAlmostEqual(stats["duration"], 1.0, places=2)
        self.assertIsNotNone(stats["rms_db"])

    def test_identical_audio(self):
        data = rc.compare_audio(self.a, self.b)
        self.assertLess(data["duration_delta_ratio"], 0.001)
        self.assertLess(data["rms_delta_db"], 0.01)

    def test_duration_diff(self):
        data = rc.compare_audio(self.a, self.longer)
        self.assertAlmostEqual(data["duration_delta"], 0.5, places=2)

    def test_loudness_diff(self):
        data = rc.compare_audio(self.a, self.quieter)
        self.assertGreater(data["rms_delta_db"], 10)

    def test_report_says_not_identity(self):
        data = rc.compare_audio(self.a, self.longer)
        report = rc.render_media(self.a, self.longer, data)
        self.assertIn("不能说明是不是同一个人", report)
        self.assertIn("文件特征不同", report)


class TestDispatch(unittest.TestCase):
    def test_run_pair_dispatches_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_image(root / "a.png")
            make_image(root / "b.png", patch=True)
            result = quiet(rc.run_pair, root / "a.png", root / "b.png", out=root / "out")
            self.assertEqual(result["mode"], "image")
            self.assertTrue((root / "out" / "a_vs_b.md").exists())

    def test_run_pair_dispatches_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_wav(root / "a.wav")
            make_wav(root / "b.wav", seconds=1.2)
            result = quiet(rc.run_pair, root / "a.wav", root / "b.wav", out=root / "out")
            self.assertEqual(result["mode"], "audio")
            self.assertEqual(result["diffs"], 1)

    def test_mixed_pair_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_image(root / "a.png")
            (root / "b.md").write_text("一段文字\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                quiet(rc.run_pair, root / "a.png", root / "b.md", out=root / "out")


if __name__ == "__main__":
    unittest.main()
