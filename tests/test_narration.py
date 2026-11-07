"""Actual offline Windows speech synthesis; standard library only."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import wave


SCRIPT = (Path(__file__).resolve().parents[1] /
          "ste_promax/scripts/narrate.ps1")


@unittest.skipUnless(os.name == "nt", "System.Speech synthesis requires Windows")
class NarrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.powershell = shutil.which("powershell.exe")
        if not cls.powershell:
            raise unittest.SkipTest("Windows PowerShell 5.1 is not installed")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ste-narration-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.input = self.root / "input [UTF-8].txt"
        self.output = self.root / "spoken [offline].wav"
        self.input.write_text(
            "Hello. This is a local narration test. Caf\u00e9 means coffee.",
            encoding="utf-8",
        )

    def run_script(self, *args, env=None):
        assert self.powershell is not None
        run_env = None if env is None else {**os.environ, **env}
        return subprocess.run(
            [self.powershell, "-NoProfile", "-NonInteractive",
             "-File", str(SCRIPT), *map(str, args)],
            capture_output=True, text=True, timeout=60,
            env=run_env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def narrate(self, *args, env=None):
        return self.run_script(
            "-InputPath", self.input, "-OutputPath", self.output, *args, env=env)

    def assert_failure(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message.lower(), result.stderr.lower())
        self.assertFalse(self.output.exists(), result.stderr)

    def assert_audio(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        audio = self.output.read_bytes()
        self.assertEqual(audio[:4], b"RIFF")
        self.assertEqual(audio[8:12], b"WAVE")
        self.assertEqual(struct.unpack("<I", audio[4:8])[0], len(audio) - 8)
        with wave.open(str(self.output), "rb") as wav:
            self.assertEqual(wav.getcomptype(), "NONE")
            self.assertEqual(wav.getnchannels(), 1)
            self.assertEqual(wav.getsampwidth(), 2)
            self.assertGreater(wav.getframerate(), 0)
            duration = wav.getnframes() / wav.getframerate()
            self.assertGreater(duration, 0.5)
            frames = wav.readframes(wav.getnframes())
            self.assertEqual(len(frames), wav.getnframes() * 2)
            samples = [sample[0] for sample in struct.iter_unpack("<h", frames)]
            self.assertGreater(max(samples) - min(samples), 100)
            self.assertGreater(sum(sample != 0 for sample in samples), 1000)
        self.assertEqual(Path(summary["output_path"]), self.output)
        self.assertEqual(summary["bytes"], len(audio))
        self.assertAlmostEqual(summary["duration_seconds"], duration)
        self.assertIs(summary["non_silent_pcm"], True)
        self.assertTrue(summary["voice"])
        return summary

    def test_actual_default_synthesis(self):
        original = self.input.read_bytes()
        summary = self.assert_audio(self.narrate())
        self.assertEqual(self.input.read_bytes(), original)
        print(f"\nSynthesis verified: {summary['voice']}; "
              f"{summary['bytes']} bytes; {summary['duration_seconds']:.2f}s")

    def test_list_and_select_installed_voice_with_rate(self):
        result = self.run_script("-ListVoices")
        self.assertEqual(result.returncode, 0, result.stderr)
        voices = json.loads(result.stdout)["voices"]
        self.assertIsInstance(voices, list)
        self.assertTrue(voices, "Actual synthesis requires an installed voice")
        self.input.write_text("\ufeffHello from an installed voice.", encoding="utf-8")
        summary = self.assert_audio(self.narrate("-Voice", voices[-1], "-Rate", "1"))
        self.assertEqual(summary["voice"], voices[-1])

    def test_existing_output_is_preserved(self):
        original = b"Existing file: never overwrite."
        self.output.write_bytes(original)
        result = self.narrate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overwrite", result.stderr)
        self.assertEqual(self.output.read_bytes(), original)

    def test_input_cannot_be_output(self):
        original = self.input.read_bytes()
        result = self.run_script("-InputPath", self.input, "-OutputPath", self.input)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("overwrite", result.stderr)
        self.assertEqual(self.input.read_bytes(), original)

    def test_missing_input(self):
        self.input.unlink()
        self.assert_failure(self.narrate(), "existing readable text file")

    def test_directory_input(self):
        self.input = self.root
        self.assert_failure(self.narrate(), "existing readable text file")

    def test_empty_text(self):
        for text in ("", " \r\n\t", "\ufeff \n"):
            with self.subTest(text=repr(text)):
                self.input.write_text(text, encoding="utf-8")
                self.assert_failure(self.narrate(), "empty")

    def test_invalid_utf8(self):
        self.input.write_bytes(b"\xff\xfe\x00broken")
        self.assert_failure(self.narrate(), "Narration failed")

    def test_unavailable_voice(self):
        self.assert_failure(self.narrate("-Voice", "STE-nonexistent-voice"), "unavailable")

    def test_invalid_rate(self):
        self.assert_failure(self.narrate("-Rate", "11"), "Rate")

    def test_missing_arguments_are_noninteractive(self):
        self.assert_failure(self.run_script(), "required")

    def test_invalid_output_paths(self):
        for output in (self.root / "missing" / "out.wav", self.root / "out.mp3"):
            with self.subTest(output=output):
                self.output = output
                self.assert_failure(self.narrate(), "parent directory")

    def test_network_paths_are_rejected_before_access(self):
        self.input = Path(r"\\invalid-host\share\input.txt")
        self.assert_failure(self.narrate(), "local filesystem paths")

    def test_list_voices_stays_usable_without_skillc_backend(self):
        missing_cfg = self.root / "missing-runtime.json"
        result = self.run_script(
            "-ListVoices",
            env={
                "STE_SKILLC_PYTHON": "",
                "STE_SKILLC_ROOT": "",
                "STE_SKILLC_RUNTIME_CONFIG": str(missing_cfg),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        voices = json.loads(result.stdout)["voices"]
        self.assertIsInstance(voices, list)
        self.assertTrue(voices)
        self.assertFalse(self.output.exists())

    def test_missing_or_invalid_backend_refuses_before_creating_wav(self):
        original = self.input.read_bytes()
        missing_cfg = self.root / "missing-runtime.json"
        missing_py = self.root / "missing-python.exe"
        missing_root = self.root / "missing-skillc-root"
        for case_name, env_overrides, expected_msg in (
            (
                "missing_runtime_json",
                {
                    "STE_SKILLC_PYTHON": "",
                    "STE_SKILLC_ROOT": "",
                    "STE_SKILLC_RUNTIME_CONFIG": str(missing_cfg),
                },
                "runtime.json",
            ),
            (
                "partial_env_override",
                {
                    "STE_SKILLC_PYTHON": str(missing_py),
                    "STE_SKILLC_ROOT": "",
                },
                "STE_SKILLC_PYTHON and STE_SKILLC_ROOT",
            ),
            (
                "missing_env_python",
                {
                    "STE_SKILLC_PYTHON": str(missing_py),
                    "STE_SKILLC_ROOT": str(missing_root),
                },
                "Configured SkillC Python",
            ),
        ):
            with self.subTest(case=case_name):
                result = self.narrate(env=env_overrides)
                self.assert_failure(result, expected_msg)
                self.assertEqual(self.input.read_bytes(), original)

    def test_synthesis_emits_real_allow_receipt_and_validates_non_silent_wav(self):
        # 1. Overlapping state directory inside the WAV output directory is refused before writing WAV.
        resolved_root = self.root.resolve()
        self.input = resolved_root / "input [UTF-8].txt"
        self.output = resolved_root / "spoken [offline].wav"
        overlapping_state = resolved_root / "policy-state"
        overlapping_state.mkdir(parents=True, exist_ok=True)
        overlap_res = self.narrate(env={"STE_SKILLC_STATE_ROOT": str(overlapping_state)})
        self.assert_failure(overlap_res, "SkillC state must stay outside the WAV output directory")

        # 2. Separated audio/ output directory and sibling policy-state/ succeed with ALLOW receipt.
        audio_dir = resolved_root / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        self.output = audio_dir / "spoken [offline].wav"
        state_root = resolved_root / "policy-state"
        result = self.narrate(env={"STE_SKILLC_STATE_ROOT": str(state_root)})
        summary = self.assert_audio(result)
        runs_dir = state_root / "runs"
        self.assertTrue(runs_dir.is_dir())
        run_dirs = list(runs_dir.glob("ste-synthesize-wav-*"))
        self.assertEqual(len(run_dirs), 1)
        receipt_path = run_dirs[0] / ".skillc" / "receipt.json"
        self.assertTrue(receipt_path.is_file())
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema"], "ste-promax.automatic-receipt.v1")
        self.assertEqual(receipt["phase"], "post")
        self.assertEqual(receipt["op"], "ste.synthesize_wav")
        self.assertEqual(receipt["verdict"], "ALLOW")
        self.assertEqual(receipt["authority_model"], "automatic-local-policy")
        self.assertTrue(receipt["skillc"]["goal_satisfied"])
        out_key = str(self.output.resolve())
        self.assertIn(out_key, receipt["outputs"])
        wav_bytes = self.output.read_bytes()
        self.assertEqual(
            receipt["outputs"][out_key],
            {
                "sha256": hashlib.sha256(wav_bytes).hexdigest(),
                "size": len(wav_bytes),
            },
        )
        self.assertEqual(summary["bytes"], len(wav_bytes))

    def test_short_path_alias_does_not_hide_state_overlap(self):
        canonical_root = self.root.resolve()
        state_root = canonical_root / "policy-state"
        state_root.mkdir()
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(canonical_root), buffer, len(buffer))
        if not length or length >= len(buffer) or buffer.value.lower() == str(canonical_root).lower():
            self.skipTest("This filesystem does not expose a distinct Windows short-path alias")
        aliased_output = Path(buffer.value) / self.output.name
        result = self.run_script("-InputPath", self.input, "-OutputPath", aliased_output,
                                 env={"STE_SKILLC_STATE_ROOT": str(state_root)})
        self.assert_failure(result, "SkillC state must stay outside the WAV output directory")
        self.assertFalse((state_root / "runs").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
