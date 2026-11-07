"""Fixture preparation tests; synthesis itself has real Windows tests separately."""

import importlib.util
import math
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from ste_promax import gate
from ste_promax.policy_runtime import PolicyBackendError, PolicyError

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
            self.assertFalse((output / ".skillc").exists())
            receipt = gate.get_last_receipt()
            self.assertIsNotNone(receipt)
            assert receipt is not None
            self.assertEqual(receipt["verdict"], "ALLOW")
            self.assertEqual(receipt["op"], "ste.host_write_artifact")
            self.assertIn(str((output / "manifest.json").resolve()), receipt["outputs"])

    def test_prepare_enforces_sequential_policy_operations_and_fails_closed_when_backend_missing(self):
        real_guard = gate.run_guarded_operation
        observed_ops: list[tuple[str, dict]] = []

        def spy_guard(op, inputs, effect_fn, *, validate_result=None):
            if len(observed_ops) == 0:
                self.assertFalse(Path(inputs["output_root"]).exists())
            observed_ops.append((op, inputs))
            return real_guard(op, inputs, effect_fn, validate_result=validate_result)

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "guarded-demo"
            with patch("ste_promax.gate.run_guarded_operation", side_effect=spy_guard):
                result = PREPARE.prepare(output, speaker=fake_voice)
            self.assertEqual(result["status"], "prepared_not_rendered")
            self.assertEqual(
                [item[0] for item in observed_ops],
                [
                    "ste.host_write_artifact",
                    "ste.synthesize_wav",
                    "ste.synthesize_wav",
                    "ste.synthesize_wav",
                    "ste.synthesize_wav",
                    "ste.host_write_artifact",
                ],
            )
            first_inputs = observed_ops[0][1]
            self.assertEqual(len(first_inputs["proposed_contents"]), 4)
            self.assertEqual(set(first_inputs["expected_before"].values()), {None})
            self.assertEqual(len(first_inputs["source_paths"]), 2)

            blocked_output = Path(temp) / "blocked-demo"
            with patch(
                "ste_promax.gate.run_guarded_operation",
                side_effect=PolicyBackendError("SkillC backend is unavailable"),
            ):
                with self.assertRaises(PolicyBackendError):
                    PREPARE.prepare(blocked_output, speaker=fake_voice)
            self.assertFalse(blocked_output.exists())

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
            out_dir = Path(temp) / "new"
            with self.assertRaises(ValueError):
                PREPARE.prepare(out_dir, speaker=empty_voice)
            self.assertFalse((out_dir / "index.html").exists())
            self.assertFalse((out_dir / "manifest.json").exists())
            receipt = gate.get_last_receipt()
            self.assertIsNotNone(receipt)
            assert receipt is not None
            self.assertEqual(receipt["verdict"], "DENY")

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

    def test_mid_run_template_or_script_mutation_is_rejected_without_final_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            temp_root = Path(temp).resolve()
            temp_here = temp_root / "demo-src"
            temp_here.mkdir(parents=True, exist_ok=True)
            orig_script = (PREPARE.HERE / "script.json").read_bytes()
            orig_comp = (PREPARE.HERE / "composition.html").read_bytes()
            (temp_here / "script.json").write_bytes(orig_script)
            (temp_here / "composition.html").write_bytes(orig_comp)

            out_dir = temp_root / "mutated-template-out"
            calls = 0

            def mutating_speaker(text_path, audio_path, voice):
                nonlocal calls
                calls += 1
                fake_voice(text_path, audio_path, voice)
                if calls == 2:
                    (temp_here / "composition.html").write_bytes(orig_comp + b"\n<!-- mutated mid-run -->\n")

            with patch.object(PREPARE, "HERE", temp_here):
                with self.assertRaisesRegex(PolicyError, "composition.html changed during preparation"):
                    PREPARE.prepare(out_dir, speaker=mutating_speaker)

            self.assertFalse((out_dir / "index.html").exists())
            self.assertFalse((out_dir / "manifest.json").exists())
            self.assertFalse((out_dir / "captions.vtt").exists())
            self.assertFalse((out_dir / "transcript.txt").exists())
            receipt = gate.get_last_receipt()
            self.assertIsNotNone(receipt)
            assert receipt is not None
            self.assertNotEqual(receipt.get("op"), "ste.host_write_artifact")

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
