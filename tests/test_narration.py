"""Actual offline Windows speech synthesis; standard library only."""
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

    def run_script(self, *args):
        assert self.powershell is not None
        return subprocess.run(
            [self.powershell, "-NoProfile", "-NonInteractive",
             "-File", str(SCRIPT), *map(str, args)],
            capture_output=True, text=True, timeout=60,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def narrate(self, *args):
        return self.run_script(
            "-InputPath", self.input, "-OutputPath", self.output, *args)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
