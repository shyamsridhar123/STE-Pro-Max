import copy
import hashlib
import html
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave
import xml.etree.ElementTree as ET

from ste_promax import media
from ste_promax.charts import CHART_SCHEMA
from ste_promax.diagrams import DIAGRAM_SCHEMA, diagram_svg
from ste_promax.stories import STORY_SCHEMA, story_companions


def pcm(frames=1600, *, channels=1, width=2, rate=8000, constant=False):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        first = (128 if width == 1 else 0).to_bytes(width, "little") * channels
        second = first if constant else (140 if width == 1 else 1024).to_bytes(width, "little") * channels
        audio.writeframes((first + second) * (frames // 2))
    return stream.getvalue()


class Tags(HTMLParser):
    def __init__(self, markup):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.json"
        self.output = self.root / "prepared"
        self.audio = self.root / "audio"
        self.audio.mkdir()
        self.story = copy.deepcopy(STORY_SCHEMA["example"])

    def save(self):
        data = b"\xef\xbb\xbf" + json.dumps(self.story, ensure_ascii=False, indent=4).encode() + b"\r\n"
        self.source.write_bytes(data)
        return data

    def inputs(self):
        result = []
        for index, beat in enumerate(self.story["beats"], 1):
            data = pcm(1600 * index)
            (self.audio / f"{beat['id']}.wav").write_bytes(data)
            result.append(data)
        return result

    def prepare(self):
        return media.prepare_story_media(self.source, self.output, audio_dir=self.audio)

    def test_one_two_seven_and_thirty_two_beats_keep_order_audio_and_source(self):
        for count in (1, 2, 7, 32):
            with self.subTest(count=count):
                self.output = self.root / f"prepared-{count}"
                self.story["beats"] = [
                    {"id": f"part-{i}", "title": f"Part {i}", "claim_ids": ["validation"],
                     "narration": f"Reviewed narration {i}."} for i in range(count)
                ]
                original = self.save()
                audios = self.inputs()
                expected_companions = story_companions(self.story)
                result = self.prepare()
                self.assertEqual(result["status"], "prepared_not_rendered")
                self.assertEqual((self.output / "source.json").read_bytes(), original)
                self.assertEqual(json.loads((self.output / "story.json").read_text()), self.story)
                self.assertEqual(result["source_sha256"], hashlib.sha256(original).hexdigest())
                for name, contents in expected_companions.items():
                    self.assertEqual((self.output / name).read_text(encoding="utf-8"), contents)
                clock = 0
                timeline = json.loads((self.output / "timeline.json").read_text(encoding="utf-8"))
                for i, (record, data) in enumerate(zip(result["audio"], audios)):
                    self.assertEqual(record["id"], f"part-{i}")
                    self.assertEqual(record["file"], f"video/beat-part-{i}.wav")
                    self.assertEqual(record["audio_src"], f"beat-part-{i}.wav")
                    self.assertEqual(record["start"], clock)
                    self.assertEqual(record["duration"], (1600 * (i + 1)) / 8000)
                    self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
                    self.assertEqual((self.output / record["file"]).read_bytes(), data)
                    self.assertEqual(timeline["beats"][i]["text"], f"Reviewed narration {i}.")
                    clock += record["duration"]
                self.assertEqual(result["duration_seconds"], clock)
                tags = Tags((self.output / result["composition"]).read_text(encoding="utf-8")).tags
                roots = [a for t, a in tags if a.get("data-composition-id") == "story-video"]
                self.assertEqual(len(roots), 1)
                self.assertEqual(roots[0]["data-start"], "0")
                self.assertEqual(float(roots[0]["data-duration"]), clock)
                self.assertEqual(len([t for t, a in tags if t == "audio"]), count)
                self.assertEqual(len([t for t, a in tags if t == "section"]), count)
                self.assertEqual(len([t for t, a in tags if a.get("class") == "clip caption"]), count)
                self.assertEqual(len([t for t, a in tags if t == "script"]), 0)
                self.assertEqual(json.loads((self.output / "manifest.json").read_text()), result)

    def test_speaker_receives_exact_companion_cues_and_voice(self):
        self.story["beats"][1]["narration"] = "Authored wording; review its qualifications."
        self.save()
        calls = []

        def speaker(text, output, voice):
            self.assertEqual(text.parent, self.output)
            self.assertEqual(output.parent, self.output / "video")
            calls.append((text.read_text(encoding="utf-8"), voice))
            output.write_bytes(pcm())

        result = media.prepare_story_media(self.source, self.output, voice="Local voice", speaker=speaker)
        expected = json.loads(story_companions(self.story)["narration.json"])["cues"]
        self.assertEqual(calls, [(cue["text"], "Local voice") for cue in expected])
        self.assertIn("Scope: The tested build only.", calls[0][0])
        self.assertTrue(all(cue["review_required"] for cue in expected))
        self.assertEqual(result["narration"], "injected test speaker")
        self.assertEqual((self.output / "transcript.txt").read_text(encoding="utf-8"),
                         "\n\n".join(cue["text"] for cue in expected) + "\n")

    def test_native_validation_precedes_all_output_io_and_speech(self):
        mutations = [
            lambda: self.story["beats"][0].update(claim_ids=["missing"]),
            lambda: self.story["sources"][0].update(url="javascript:alert(1)"),
            lambda: self.story["beats"][0].update(id="../escape"),
            lambda: self.story["beats"][0].update(visual={"kind": "chart", "title": "invalid"}),
            lambda: self.story.update(version=True),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.story = copy.deepcopy(STORY_SCHEMA["example"])
                mutation()
                self.save()
                with patch.object(media, "synthesize") as speaker, patch.object(Path, "mkdir") as mkdir:
                    with self.assertRaises(ValueError):
                        media.prepare_story_media(self.source, self.output)
                    mkdir.assert_not_called()
                    speaker.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_duplicate_json_fields_at_any_depth_fail_before_output_io(self):
        text = json.dumps(self.story)
        inputs = [
            text.replace('"version": 1', '"version": 1, "version": 1'),
            text.replace('"id": "checks"', '"id": "checks", "id": "gate"'),
            text.replace('"claim_ids": ["validation"]',
                         '"claim_ids": ["missing"], "claim_ids": ["validation"]'),
        ]
        for text in inputs:
            with self.subTest(text=text):
                self.source.write_text(text, encoding="utf-8")
                with patch.object(Path, "mkdir") as mkdir, patch.object(media, "synthesize") as speaker:
                    with self.assertRaisesRegex(ValueError, "Duplicate JSON field"):
                        self.prepare()
                    mkdir.assert_not_called()
                    speaker.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_lossy_literal_numbers_in_nested_story_chart_fail_before_output_io(self):
        visual = copy.deepcopy(CHART_SCHEMA["example"])
        visual["series"][0]["values"][0] = "__literal_number__"
        self.story["beats"][0]["visual"] = visual
        text = json.dumps(self.story)
        for token in ("1e-400", "-1e-400", "9007199254740993.0", "1e400"):
            with self.subTest(token=token):
                # Insert source tokens literally: constructing Python floats first loses the evidence.
                original = text.replace('"__literal_number__"', token).encode("utf-8")
                self.source.write_bytes(original)
                with patch.object(Path, "mkdir") as mkdir, \
                        patch.object(media, "synthesize") as speaker, \
                        patch.object(media, "validate_story") as validate:
                    with self.assertRaisesRegex(
                        ValueError,
                        r"input\.beats\[0\]\.visual\.series\[0\]\.values\[0\].*without changing",
                    ):
                        self.prepare()
                    mkdir.assert_not_called()
                    speaker.assert_not_called()
                    validate.assert_not_called()
                self.assertFalse(self.output.exists())
                self.assertEqual(self.source.read_bytes(), original)

    def test_strict_loader_nonfinite_and_deep_nesting_fail_before_output_io(self):
        texts = ['{"extra": ' + token + "}" for token in ("NaN", "Infinity", "-Infinity")]
        texts.append('{"extra":' + "[" * 70 + "0" + "]" * 70 + "}")
        for text in texts:
            with self.subTest(text=text):
                self.source.write_text(text, encoding="utf-8")
                with patch.object(Path, "mkdir") as mkdir, patch.object(media, "synthesize") as speaker:
                    with self.assertRaisesRegex(ValueError, "finite JSON number|nesting exceeds"):
                        self.prepare()
                    mkdir.assert_not_called()
                    speaker.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_supported_integer_and_float_evidence_survive_media_preparation(self):
        visual = copy.deepcopy(CHART_SCHEMA["example"])
        visual["series"][0]["values"] = [9007199254740993, 0.1]
        self.story["beats"][0]["visual"] = visual
        original = self.save()
        self.inputs()
        self.prepare()
        normalized = json.loads((self.output / "story.json").read_text(encoding="utf-8"))
        numbers = normalized["beats"][0]["visual"]["series"][0]["values"]
        self.assertEqual(numbers, [9007199254740993, 0.1])
        self.assertIs(type(numbers[0]), int)
        self.assertIs(type(numbers[1]), float)
        self.assertEqual((self.output / "source.json").read_bytes(), original)

    def test_missing_audio_leaves_clear_partial_manifest_and_evidence(self):
        self.save()
        (self.audio / "checks.wav").write_bytes(pcm())
        with self.assertRaises(FileNotFoundError):
            self.prepare()
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "partial_failure_not_rendered")
        self.assertEqual(manifest["failed_beat_id"], "gate")
        self.assertEqual([a["id"] for a in manifest["audio"]], ["checks"])
        self.assertTrue((self.output / "evidence.json").exists())
        self.assertFalse((self.output / "video/index.html").exists())
        with self.assertRaisesRegex(ValueError, "new output"):
            self.prepare()

    def test_bad_pcm_rejected_and_never_copied_as_valid_audio(self):
        good = pcm()
        wrong_rate = bytearray(good)
        struct.pack_into("<I", wrong_rate, 28, 1)
        float_audio = bytearray(good)
        struct.pack_into("<H", float_audio, 20, 3)
        misaligned = bytearray(good[:-1])
        struct.pack_into("<I", misaligned, 4, len(misaligned) - 8)
        struct.pack_into("<I", misaligned, 40, len(misaligned) - 44)
        for i, data in enumerate((good[:-8], b"not audio", pcm(constant=True), pcm(frames=0),
                                  bytes(wrong_rate), bytes(float_audio), bytes(misaligned),
                                  good + b"extra", good[:36])):
            with self.subTest(case=i):
                self.output = self.root / f"bad-{i}"
                self.save()
                (self.audio / "checks.wav").write_bytes(data)
                with self.assertRaises(ValueError):
                    self.prepare()
                manifest = json.loads((self.output / "manifest.json").read_text())
                self.assertEqual(manifest["status"], "partial_failure_not_rendered")
                self.assertEqual(manifest["audio"], [])
                self.assertFalse((self.output / "video/beat-checks.wav").exists())

    def test_pcm_widths_and_stereo_are_accepted_without_resampling(self):
        for channels in (1, 2):
            for width in (1, 2, 3, 4):
                with self.subTest(channels=channels, width=width):
                    info = media._pcm_info(pcm(channels=channels, width=width))
                    self.assertEqual(info["duration"], .2)
                    self.assertEqual(info["channels"], channels)
                    self.assertEqual(info["sample_width"], width)
        with self.assertRaisesRegex(ValueError, "Silent"):
            media._pcm_info(pcm(width=1, constant=True))

    def test_audio_size_and_total_size_are_bounded(self):
        self.save()
        self.inputs()
        with patch.object(media, "MAX_AUDIO_BYTES", 100):
            with self.assertRaisesRegex(ValueError, "limit"):
                self.prepare()
        self.output = self.root / "total-limit"
        with patch.object(media, "MAX_TOTAL_AUDIO_BYTES", 5000):
            with self.assertRaisesRegex(ValueError, "Total audio"):
                self.prepare()
        result = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(len(result["audio"]), 1)

    def test_source_size_is_bounded_before_output(self):
        self.save()
        with patch.object(media, "MAX_SOURCE_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "limit"):
                self.prepare()
        self.assertFalse(self.output.exists())

    def test_hostile_text_is_data_not_html_script_attributes_or_vtt_cues(self):
        attack = '</script><script>alert(1)</script><img src="https://bad/x" onerror="run()">'
        self.story["title"] = attack  # Document title is escaped; beat titles stay short.
        self.story["summary"] = attack
        self.story["claims"][0]["text"] = attack
        self.story["beats"][0]["narration"] = attack + "\n\n00:00:00.000 --> 00:10:00.000"
        self.story["sources"][0]["url"] = 'https://example.org/?q="><script>bad</script>'
        self.save()
        self.inputs()
        self.prepare()
        markup = (self.output / "video/index.html").read_text(encoding="utf-8")
        self.assertNotIn(attack, markup)
        self.assertIn(html.escape(attack, quote=False).replace('"', "&#34;"), markup)
        tags = Tags(markup).tags
        self.assertEqual(len([t for t, a in tags if t == "script"]), 0)
        self.assertFalse(any(t in ("img", "iframe", "object") for t, a in tags))
        self.assertFalse(any(k.startswith("on") for t, a in tags for k in a))
        self.assertFalse(any(a.get("src", "").startswith("http") for t, a in tags))
        vtt = (self.output / "captions.vtt").read_text()
        self.assertNotIn("<script>", vtt)
        self.assertNotIn("\n\n00:00:00.000", vtt)
        self.assertIn(attack, (self.output / "transcript.txt").read_text())

    def test_new_directory_and_parent_traversal_checks_preserve_existing_files(self):
        self.save()
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_text("unchanged")
        with self.assertRaisesRegex(ValueError, "new output"):
            self.prepare()
        self.assertEqual(sentinel.read_text(), "unchanged")
        self.output = self.root / "audio" / ".." / "escape"
        with self.assertRaisesRegex(ValueError, "traversal"):
            self.prepare()
        self.assertFalse((self.root / "escape").exists())
        self.output = self.root / "missing-parent" / "new"
        with self.assertRaisesRegex(ValueError, "parent"):
            self.prepare()
        self.assertFalse(self.output.parent.exists())

    def symlink(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError as error:
            self.skipTest(f"Symlinks unavailable: {error}")

    def test_linked_output_parent_rejected_without_writes(self):
        self.save()
        link = self.root / "alias"
        self.symlink(link, self.audio, True)
        self.output = link / "escape"
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            self.prepare()
        self.assertFalse((self.audio / "escape").exists())

    def test_linked_audio_rejected_without_following(self):
        self.save()
        outside = self.root / "outside.wav"
        outside.write_bytes(pcm())
        self.symlink(self.audio / "checks.wav", outside)
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            self.prepare()
        self.assertFalse((self.output / "video/beat-checks.wav").exists())

    def test_linked_source_and_dangling_output_are_rejected(self):
        self.save()
        link = self.root / "source-link.json"
        self.symlink(link, self.source)
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            media.prepare_story_media(link, self.output, audio_dir=self.audio)
        self.assertFalse(self.output.exists())
        self.symlink(self.output, self.root / "missing", True)
        with self.assertRaisesRegex(ValueError, "Symlinks"):
            self.prepare()

    def test_device_network_and_stream_paths_rejected(self):
        for path in ("//server/share/new", "x/../new", "con.wav", "file:stream", "ambiguous."):
            with self.subTest(path=path), self.assertRaises(ValueError):
                media._local_path(Path(path))

    def test_default_speaker_unavailable_has_no_success_claim(self):
        self.save()
        with patch.object(media.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "System.Speech"):
                media.prepare_story_media(self.source, self.output)
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "partial_failure_not_rendered")
        self.assertEqual(manifest["audio"], [])
        self.assertFalse((self.output / "video/index.html").exists())

    def test_system_speech_invocation_uses_existing_helper_and_argument_list(self):
        self.assertEqual(media.NARRATOR, Path(media.__file__).resolve().parent / "scripts/narrate.ps1")
        with patch.object(media.shutil, "which", return_value="powershell.exe"), \
                patch.object(media.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0)
            media.synthesize(self.root / "text.txt", self.root / "out.wav", "Voice; not a command")
            args, kwargs = run.call_args
            self.assertIn(str(media.NARRATOR), args[0])
            self.assertEqual(args[0][-2:], ["-Voice", "Voice; not a command"])
            self.assertFalse(kwargs.get("shell", False))
            run.return_value = subprocess.CompletedProcess([], 1, stderr="No installed voice")
            with self.assertRaisesRegex(RuntimeError, "No installed voice"):
                media.synthesize(self.root / "text.txt", self.root / "out.wav", None)

    def test_speaker_failure_after_one_beat_is_recorded(self):
        self.save()
        count = 0

        def speaker(text, output, voice):
            nonlocal count
            count += 1
            if count == 2:
                output.write_bytes(b"partial")
                raise RuntimeError("Local engine failed")
            output.write_bytes(pcm())

        with self.assertRaisesRegex(RuntimeError, "Local engine failed"):
            media.prepare_story_media(self.source, self.output, speaker=speaker)
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(len(manifest["audio"]), 1)
        self.assertEqual(manifest["failed_beat_id"], "gate")
        self.assertEqual(manifest["error"]["type"], "RuntimeError")
        self.assertFalse((self.output / "video/index.html").exists())

    def test_audio_and_voice_or_speaker_are_mutually_exclusive(self):
        self.save()
        for kwargs in ({"voice": "voice"}, {"speaker": lambda *args: None}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "Choose"):
                media.prepare_story_media(self.source, self.output, audio_dir=self.audio, **kwargs)
        self.assertFalse(self.output.exists())

    def test_dense_text_and_visuals_fail_actionable_preflight_without_partial_readiness(self):
        visual = copy.deepcopy(CHART_SCHEMA["example"])
        visual["categories"] = [f"category-{i}" for i in range(40)]
        visual["series"][0]["values"] = list(range(40))
        for field, value in (("title", "Very long title " * 100),
                             ("text", "Unabridged qualification " * 100), ("visual", visual)):
            with self.subTest(field=field):
                self.story = copy.deepcopy(STORY_SCHEMA["example"])
                self.story["beats"][0][field] = value
                self.save()
                with self.assertRaisesRegex(ValueError, "shorter title|split"):
                    self.prepare()
                self.assertFalse(self.output.exists())

    def test_native_chart_and_diagram_renderers_are_reused(self):
        for i, schema in enumerate((CHART_SCHEMA, DIAGRAM_SCHEMA)):
            self.story["beats"][i]["visual"] = copy.deepcopy(schema["example"])
        self.save()
        self.inputs()
        result = self.prepare()
        markup = (self.output / "video/index.html").read_text(encoding="utf-8")
        review = (self.output / "review.html").read_text(encoding="utf-8")
        self.assertIn("<svg", markup)
        self.assertIn("ste-chart", review)
        self.assertIn("ste-diagram", review)
        self.assertEqual(result["status"], "prepared_not_rendered")
        for beat in self.story["beats"]:
            self.assertIn(html.escape(beat["visual"]["title"]), review)

    def test_composition_timing_is_seek_safe_and_only_references_local_audio(self):
        self.save()
        self.inputs()
        result = self.prepare()
        markup = (self.output / "video/index.html").read_text(encoding="utf-8")
        tags = Tags(markup).tags
        root = next(a for t, a in tags if t == "main")
        self.assertEqual(float(root["data-duration"]), result["duration_seconds"])
        self.assertEqual(root["data-no-timeline"], "true")
        for attrs, record in zip((a for t, a in tags if t == "audio"), result["audio"]):
            self.assertEqual(attrs["src"], record["audio_src"])
            self.assertEqual((self.output / result["composition"]).parent / attrs["src"],
                             self.output / record["file"])
            self.assertEqual(float(attrs["data-start"]), record["start"])
            self.assertEqual(float(attrs["data-duration"]), record["duration"])
            self.assertNotIn("crossorigin", attrs)
        self.assertNotIn("<script>", markup)
        self.assertNotIn('class="progress"', markup)
        for bad in ("setTimeout", "requestAnimationFrame", "Math.random", "Date.now", ".play()", "fetch("):
            self.assertNotIn(bad, markup)

    def retry_story(self):
        fixture = Path(__file__).resolve().parents[1] / "examples/suite/retry-explanation.json"
        self.story = json.loads(fixture.read_text(encoding="utf-8"))
        self.save()
        self.inputs()
        # Deliberately uneven frame count exercises deterministic remainder allocation.
        (self.audio / "trace.wav").write_bytes(pcm(frames=48014))

    def test_short_retry_stages_every_message_without_placeholder_or_changed_chart_values(self):
        self.retry_story()
        original = self.source.read_bytes()
        result = self.prepare()
        self.assertEqual(result["status"], "prepared_not_rendered")
        timeline = json.loads((self.output / "timeline.json").read_text(encoding="utf-8"))
        stages = timeline["beats"][0]["stages"]
        visual = self.story["beats"][0]["visual"]
        self.assertEqual(len(stages), len(visual["messages"]))
        for index, (stage, message) in enumerate(zip(stages, visual["messages"]), 1):
            self.assertEqual(stage["number"], index)
            self.assertEqual(stage["count"], 5)
            self.assertEqual(stage["message"], message)
            self.assertEqual(stage["svg"], diagram_svg({**visual, "messages": [message]}))
            groups = [e.attrib for e in ET.fromstring(stage["svg"]).iter() if "data-edge" in e.attrib]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["data-from"], message["from"])
            self.assertEqual(groups[0]["data-to"], message["to"])
        self.assertEqual(timeline["beats"][1]["stages"], [])
        self.assertTrue(all(beat["caption_visible"] for beat in timeline["beats"]))
        from ste_promax.charts import chart_svg
        self.assertEqual(timeline["beats"][1]["visual"]["svg"],
                         chart_svg(self.story["beats"][1]["visual"]))
        markup = (self.output / "video/index.html").read_text(encoding="utf-8")
        self.assertEqual(markup.count('class="clip scene"'), 6)
        for number in range(1, 6):
            self.assertIn(f"Stage {number}/5", markup)
        self.assertIn("Demonstration pacing, not measured event time", markup)
        self.assertIn("Speech-to-message alignment is unverified", markup)
        self.assertNotIn("Prepared, not rendered", markup)
        self.assertNotIn("prepared_not_rendered", markup)
        for phrase in ("too dense", "Split the beat", "full title in review", "class=\"progress\""):
            self.assertNotIn(phrase, markup)
        self.assertEqual((self.output / "source.json").read_bytes(), original)
        self.assertEqual(json.loads((self.output / "evidence.json").read_text(encoding="utf-8"))["source_story"],
                         self.story)
        review = (self.output / "review.html").read_text(encoding="utf-8")
        self.assertEqual(len([a for t, a in Tags(review).tags if "data-edge" in a]), 5)

    def test_message_stage_times_partition_real_pcm_and_are_deterministic(self):
        self.retry_story()
        self.prepare()
        first_html = (self.output / "video/index.html").read_bytes()
        first_timeline = (self.output / "timeline.json").read_bytes()
        beat = json.loads(first_timeline)["beats"][0]
        stages = beat["stages"]
        self.assertEqual(stages[0]["start"], beat["start"])
        self.assertEqual(stages[-1]["end"], beat["end"])
        self.assertEqual(sum(s["audio_frame_end"] - s["audio_frame_start"] for s in stages), beat["frames"])
        for left, right in zip(stages, stages[1:]):
            self.assertEqual(left["end"], right["start"])
            self.assertEqual(left["audio_frame_end"], right["audio_frame_start"])
        scene_attrs = [a for t, a in Tags(first_html.decode()).tags
                       if a.get("id", "").startswith("scene-trace-stage-")]
        for stage, attrs in zip(stages, scene_attrs):
            self.assertEqual(attrs["class"], "clip scene")
            self.assertEqual(float(attrs["data-start"]), stage["start"])
            self.assertEqual(float(attrs["data-duration"]), stage["duration"])
            self.assertEqual(stage["speech_to_message_alignment"], "unverified")
        # Same time => exactly one authored state, independent of seek direction.
        for stage in reversed(stages):
            midpoint = (stage["start"] + stage["end"]) / 2
            self.assertEqual([s["number"] for s in stages if s["start"] <= midpoint < s["end"]],
                             [stage["number"]])
        self.output = self.root / "repeated"
        self.prepare()
        self.assertEqual((self.output / "video/index.html").read_bytes(), first_html)
        self.assertEqual((self.output / "timeline.json").read_bytes(), first_timeline)

    def test_visual_claim_text_qualifications_and_source_caption_are_visible(self):
        self.retry_story()
        claim = self.story["claims"][0]
        claim.update(text="Both receipts match.", scope="One trace.", attributed_to="Trace author",
                     basis="Authored event log", uncertainty="Fictional only.")
        self.story["beats"][0]["text"] = ""
        visual = self.story["beats"][0]["visual"]
        visual["description"] = "A fictional retry."
        visual["caption"] = "Source: retry-log."
        visual["messages"][1]["note"] = '<script>not executable</script> original note'
        self.save()
        self.prepare()
        timeline = json.loads((self.output / "timeline.json").read_text(encoding="utf-8"))
        markup = (self.output / "video/index.html").read_text(encoding="utf-8")
        for beat in self.story["beats"]:
            self.assertIn(html.escape(beat["visual"]["caption"]), markup)
            for identifier in beat["claim_ids"]:
                claim = next(c for c in self.story["claims"] if c["id"] == identifier)
                for key in ("text", "scope", "uncertainty", "attributed_to", "basis"):
                    if key in claim:
                        self.assertIn(html.escape(claim[key]), markup)
        self.assertEqual(timeline["beats"][0]["stages"][1]["message"]["note"],
                         visual["messages"][1]["note"])
        self.assertNotIn("<script>", markup)

    def test_oversized_visual_qualifications_block_before_output_instead_of_disappearing(self):
        self.retry_story()
        self.story["claims"][0]["uncertainty"] = "A material qualification. " * 100
        self.save()
        with self.assertRaisesRegex(ValueError, "claim qualifications exceed.*split the beat"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_sequence_with_insufficient_audio_has_failure_not_prepared_manifest(self):
        self.retry_story()
        (self.audio / "trace.wav").write_bytes(pcm(frames=8000))
        with self.assertRaisesRegex(ValueError, "at least one second"):
            self.prepare()
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "partial_failure_not_rendered")
        self.assertEqual(manifest["failed_beat_id"], "trace")
        self.assertFalse((self.output / "video/index.html").exists())

    def test_review_has_explicit_readable_local_shell_and_complete_story(self):
        self.retry_story()
        self.prepare()
        review = (self.output / "review.html").read_text(encoding="utf-8")
        self.assertIn("background:var(--surface);color:var(--text-1)", review)
        self.assertIn("--surface:#171513;--text-1:#f4eee7;--text-2:#c8c2ba", review)
        self.assertIn("a{color:#efa276}", review)
        self.assertIn("clamp(16px,4vw,60px)", review)
        self.assertIn(self.story["limitations"][0], review)
        self.assertNotIn('<link rel="stylesheet"', review)

    def test_video_tree_contains_only_composition_and_audio_not_review_documents(self):
        self.save()
        inputs = self.inputs()
        result = self.prepare()
        self.assertEqual(result["composition"], "video/index.html")
        self.assertEqual(result["video_directory"], "video")
        self.assertEqual(result["review"], "review.html")
        video = self.output / result["video_directory"]
        self.assertEqual([p.relative_to(video).as_posix() for p in video.rglob("*.html")], ["index.html"])
        self.assertEqual({p.relative_to(video).as_posix() for p in video.rglob("*")},
                         {"index.html", *(a["audio_src"] for a in result["audio"])})
        self.assertFalse((self.output / "index.html").exists())  # No obsolete root composition.
        for name in ("source.json", "story.json", "story.md", "evidence.json", "storyboard.json",
                     "narration.json", "review.html", "transcript.txt", "captions.vtt", "timeline.json"):
            self.assertTrue((self.output / name).is_file(), name)
        review = (self.output / result["review"]).read_text(encoding="utf-8")
        self.assertFalse(any("data-composition-id" in attrs for tag, attrs in Tags(review).tags))
        self.assertNotIn("data-no-timeline", review)
        self.assertNotIn("data-duration", review)
        timeline = json.loads((self.output / result["timeline"]).read_text(encoding="utf-8"))
        for record, beat, original in zip(result["audio"], timeline["beats"], inputs):
            self.assertEqual(Path(record["audio_src"]).name, record["audio_src"])
            self.assertNotIn("/", record["audio_src"])
            self.assertNotIn("\\", record["audio_src"])
            self.assertEqual(record["file"], f"video/{record['audio_src']}")
            self.assertEqual(beat["audio_src"], record["audio_src"])
            self.assertEqual(beat["file"], record["file"])
            self.assertEqual((self.output / record["file"]).read_bytes(), original)
            self.assertEqual((self.audio / f"{record['id']}.wav").read_bytes(), original)

    def test_default_speaker_receives_nested_video_output_and_root_text(self):
        self.save()
        calls = []

        def synthesize(text_path, audio_path, voice):
            self.assertEqual(text_path.parent, self.output)
            self.assertEqual(audio_path.parent, self.output / "video")
            self.assertTrue(audio_path.parent.is_dir())
            calls.append(audio_path)
            audio_path.write_bytes(pcm())

        with patch.object(media, "synthesize", side_effect=synthesize):
            result = media.prepare_story_media(self.source, self.output)
        self.assertEqual(calls, [self.output / record["file"] for record in result["audio"]])
        self.assertTrue((self.output / result["composition"]).is_file())

    def test_video_directory_creation_failure_records_partial_manifest(self):
        self.save()
        mkdir = Path.mkdir

        def fail_video(path, *args, **kwargs):
            if path == self.output / "video":
                raise PermissionError("Video directory creation denied")
            return mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", autospec=True, side_effect=fail_video), \
                patch.object(media, "synthesize") as speaker:
            with self.assertRaisesRegex(PermissionError, "Video directory creation denied"):
                media.prepare_story_media(self.source, self.output)
            speaker.assert_not_called()
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "partial_failure_not_rendered")
        self.assertEqual(manifest["error"]["type"], "PermissionError")
        self.assertEqual(manifest["audio"], [])
        self.assertIsNone(manifest["failed_beat_id"])
        self.assertTrue((self.output / "review.html").is_file())
        self.assertTrue((self.output / "evidence.json").is_file())
        self.assertFalse((self.output / "video/index.html").exists())


if __name__ == "__main__":
    unittest.main()
