"""Fixture preparation tests; synthesis itself has real Windows tests separately."""

import importlib.util
import math
from pathlib import Path
import struct
import tempfile
import unittest
import wave

MODULE = Path(__file__).resolve().parents[1] / "examples/narrated-demo/prepare.py"
SPEC = importlib.util.spec_from_file_location("prepare_video_example", MODULE)
assert SPEC is not None and SPEC.loader is not None
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


def fake_voice(_text, output, _voice):
    with wave.open(str(output), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"".join(struct.pack("<h", int(900 * math.sin(i / 8))) for i in range(8000)))


class VideoPreparationTests(unittest.TestCase):
    def test_uses_measured_audio_for_nonoverlapping_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "new"
            result = PREPARE.prepare(output, speaker=fake_voice)
            self.assertEqual(result["status"], "prepared_not_rendered")
            self.assertEqual(len(result["audio"]), 4)
            for current, following in zip(result["audio"], result["audio"][1:]):
                self.assertLessEqual(current["start"] + current["duration"], following["start"])
            last = result["audio"][-1]
            self.assertGreater(result["duration_seconds"], last["start"] + last["duration"])
            markup = (output / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("@@", markup)
            self.assertEqual(markup.count("<audio "), 4)
            self.assertIn(str(result["duration_seconds"]), markup)
            self.assertTrue((output / "captions.vtt").read_text().startswith("WEBVTT"))
            self.assertTrue((output / "transcript.txt").is_file())

    def test_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            sentinel = output / "user.txt"
            sentinel.write_text("preserve")
            with self.assertRaises(ValueError):
                PREPARE.prepare(output, speaker=fake_voice)
            self.assertEqual(sentinel.read_text(), "preserve")

    def test_rejects_empty_audio(self):
        def empty_voice(_text, output, _voice):
            with wave.open(str(output), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                PREPARE.prepare(Path(temp) / "new", speaker=empty_voice)

    def test_subtitle_timestamp_carries_rounding(self):
        self.assertEqual(PREPARE.vtt_time(59.9996), "00:01:00.000")
        self.assertEqual(PREPARE.vtt_time(3601.2), "01:00:01.200")

    def test_rejects_silent_and_constant_pcm(self):
        for width, sample in ((1, b"\x80"), (2, b"\x00\x00"), (2, b"\x05\x00")):
            with self.subTest(width=width, sample=sample), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "silent.wav"
                with wave.open(str(path), "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(width)
                    audio.setframerate(8000)
                    audio.writeframes(sample * 8000)
                with self.assertRaisesRegex(ValueError, "Silent or constant"):
                    PREPARE.pcm_duration(path)

    def test_rejects_truncated_pcm_even_when_header_claims_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "truncated.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(8000)
                audio.writeframes(b"\x01\x00")
            payload = bytearray(path.read_bytes())
            payload[4:8] = struct.pack("<I", 16036)
            payload[40:44] = struct.pack("<I", 16000)
            path.write_bytes(payload)
            with self.assertRaisesRegex(ValueError, "Truncated"):
                PREPARE.pcm_duration(path)


if __name__ == "__main__":
    unittest.main()
