"""Focused core tests for the automatic STE-Pro-Max SkillC policy controller."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from unittest.mock import patch

from ste_promax import __version__, gate, policy_runtime
from ste_promax.stories import STORY_SCHEMA, story_companions


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _file_obs(path: Path) -> dict[str, int | str]:
    raw = path.read_bytes()
    return {"sha256": _sha256_bytes(raw), "size": len(raw)}


def _valid_pcm_wav_bytes() -> bytes:
    sample_rate = 8000
    samples = [0, 12000, -12000, 6000, -6000, 18000, -18000, 3000] * 25
    pcm_frames = struct.pack(f"<{len(samples)}h", *samples)
    fmt_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    data_chunk = struct.pack("<4sI", b"data", len(pcm_frames)) + pcm_frames
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE") + fmt_chunk + data_chunk


class AutomaticPolicyCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ste-auto-policy-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state_root = self.root / "policy-state"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(
            os.environ,
            {"STE_SKILLC_STATE_ROOT": str(self.state_root)},
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _write_fresh_native_bundle(
        self,
        bundle_dir: Path,
        source_path: Path,
        *,
        is_story: bool = False,
        trusted_html: bool = False,
    ) -> dict[str, object]:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        orig_bytes, norm_bytes, data = gate.cli.normalized_input(source_path, None, trusted_html)
        saved_source = bundle_dir / f"source{source_path.suffix.lower()}"
        saved_source.write_bytes(orig_bytes)
        input_json = bundle_dir / "input.json"
        input_json.write_bytes(norm_bytes)

        html_path = bundle_dir / "artifact.html"
        html_path.write_text("<!doctype html><html><body>Artifact</body></html>\n", encoding="utf-8")
        design_path = bundle_dir / "artifact.DESIGN.md"
        design_path.write_text("---\nname: ste\n---\n# Design\n", encoding="utf-8")
        meta_path = bundle_dir / "artifact.meta.yaml"
        meta_path.write_text("generator: ste-promax/native\nlint_passed: true\nslug: artifact\n", encoding="utf-8")
        gallery_path = bundle_dir / "gallery.html"
        gallery_path.write_text(
            gate._GALLERY_PREFIX + "<html><body>Gallery</body></html>\n",
            encoding="utf-8",
        )

        files: dict[str, dict[str, str]] = {
            "source": gate.cli.file_record(saved_source),
            "input": gate.cli.file_record(input_json),
            "html": gate.cli.file_record(html_path),
            "design": gate.cli.file_record(design_path),
            "meta": gate.cli.file_record(meta_path),
            "gallery": gate.cli.file_record(gallery_path),
        }
        if is_story:
            for name, content in story_companions(data).items():
                comp_path = bundle_dir / name
                comp_path.write_text(content, encoding="utf-8", newline="\n")
                files[Path(name).stem] = gate.cli.file_record(comp_path)

        ev_root, _, _, ev_snapshots, ev_records = gate.cli._resolve_evidence_inputs(
            data,
            source=source_path.resolve(),
            design=None,
            output=bundle_dir,
            evidence_args=[],
            evidence_root_arg=None,
        )
        for rec in ev_records:
            ev_target = bundle_dir / Path(rec["rel_path"])
            ev_target.parent.mkdir(parents=True, exist_ok=True)
            ev_target.write_bytes(ev_snapshots[Path(rec["source_path"])])

        manifest: dict[str, Any] = {
            "status": "complete",
            "version": __version__,
            "renderer": "ste_promax.render",
            "source_path": str(source_path.resolve()),
            "source_sha256": _sha256_bytes(orig_bytes),
            "files": files,
            "trusted_html": trusted_html,
            "lint_passed": True,
            "external_references": [],
            "offline_verified": False,
            "warnings": [
                "Semantic and visual review remain manual; artifact presence is not quality certification."
            ],
            "visuals": [],
        }
        if is_story or ev_records:
            manifest["evidence_root"] = str(ev_root)
            manifest["evidence_files"] = ev_records
        manifest_path = bundle_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return manifest

    def test_manual_stage_and_approval_apis_removed_and_plan_has_no_human_gate(self) -> None:
        for removed_name in ("stage_bundle", "approve_stage", "approve_stage_interactive", "export_stage"):
            self.assertFalse(hasattr(gate, removed_name), f"{removed_name} should be removed")
        self.assertNotIn("ApprovalGate", Path(gate.__file__).read_text(encoding="utf-8"))
        self.assertNotIn("ask_user", gate.STE_AUTOMATIC_PLAN_CE)
        self.assertNotIn("user_conversation", gate.STE_AUTOMATIC_PLAN_CE)
        self.assertNotIn("ask_user", gate.STE_AUTOMATIC_RUNTIME_MANIFEST["tools"])
        self.assertNotIn("user_conversation", gate.STE_AUTOMATIC_RUNTIME_MANIFEST["grants"])

        status = gate.get_policy_status()
        self.assertTrue(status["available"], status)
        self.assertEqual(status["authority_model"], "automatic-local-policy")
        self.assertFalse(status["manual_approval_required"])
        self.assertEqual(status["static_check"]["pure_verdict"], "ACHIEVABLE")
        self.assertEqual(status["static_check"]["bound_verdict"], "ACHIEVABLE")
        self.assertEqual(status["static_check"]["protocol"], "WELL_TYPED")
        self.assertTrue(status["plan_digest"])

        for cmd in ("stage", "approve"):
            with self.assertRaises(policy_runtime.PolicyError) as ctx:
                gate.run_gate_command(argparse.Namespace(command=cmd))
            self.assertEqual(ctx.exception.code, policy_runtime.ERROR_UNSUPPORTED_OPERATION)

    def test_runtime_config_schema_and_missing_backend_fail_before_effect(self) -> None:
        called = False

        def never_called() -> str:
            nonlocal called
            called = True
            return "bad"

        # 1. Missing both in-process skillc and worker config fails before effect_fn
        cfg_file = self.root / "missing-runtime.json"
        with patch("ste_promax.gate._has_inprocess_skillc", return_value=False), patch.dict(
            os.environ,
            {
                "STE_SKILLC_PYTHON": "",
                "STE_SKILLC_ROOT": "",
                "STE_SKILLC_RUNTIME_CONFIG": str(cfg_file),
            },
            clear=False,
        ):
            status = gate.get_policy_status()
            self.assertFalse(status["available"])
            self.assertEqual(status["error"]["code"], policy_runtime.ERROR_DEPENDENCY_MISSING)
            with self.assertRaises(policy_runtime.PolicyBackendError) as ctx:
                gate.run_guarded_operation(
                    "ste.prose",
                    {"caller": "native", "profile": "relaxed"},
                    never_called,
                )
            self.assertEqual(ctx.exception.code, policy_runtime.ERROR_DEPENDENCY_MISSING)
            self.assertFalse(called)

        # 2. Valid runtime.json schema resolution and symlinked venv python preservation
        real_py = self.root / "real-python.bin"
        real_py.write_bytes(b"#!/bin/sh\n")
        fake_skillc = self.root / "skillc-repo"
        (fake_skillc / "src" / "skillc").mkdir(parents=True)
        (fake_skillc / "src" / "skillc" / "__init__.py").write_text("__version__ = '0.3.0'\n", encoding="utf-8")
        valid_cfg = {
            "schema": "ste-promax.runtime.v1",
            "managed_by": "ste-promax",
            "python": str(real_py),
            "skillc_root": str(fake_skillc),
            "ste_root": str(Path(gate.__file__).resolve().parents[1]),
            "state_root": str(self.state_root),
            "skillc_commit": "25cc63b",
            "versions": {"python": "3.13.16", "skillc": "0.3.0"},
        }
        runtime_json = self.root / "runtime.json"
        runtime_json.write_text(json.dumps(valid_cfg), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "STE_SKILLC_PYTHON": "",
                "STE_SKILLC_ROOT": "",
                "STE_SKILLC_RUNTIME_CONFIG": str(runtime_json),
            },
            clear=False,
        ):
            py_exe, skillc_src = gate._resolve_worker_backend()
            self.assertEqual(py_exe, real_py.absolute())
            self.assertEqual(skillc_src, (fake_skillc / "src").resolve())

        # 3. Invalid runtime.json schema rejected
        bad_cfg = dict(valid_cfg, managed_by="untrusted")
        runtime_json.write_text(json.dumps(bad_cfg), encoding="utf-8")
        with patch.dict(
            os.environ,
            {
                "STE_SKILLC_PYTHON": "",
                "STE_SKILLC_ROOT": "",
                "STE_SKILLC_RUNTIME_CONFIG": str(runtime_json),
            },
            clear=False,
        ):
            with self.assertRaises(policy_runtime.PolicyBackendError):
                gate._resolve_worker_backend()

    def test_invalid_inputs_paths_and_availability_fail_before_effect(self) -> None:
        source = self.root / "input.md"
        source.write_text("# Valid\n\nBody.\n", encoding="utf-8")
        out_dir = self.root / "out"
        called = False

        def effect() -> dict[str, Any]:
            nonlocal called
            called = True
            return {}

        bad_cases: list[tuple[str, dict[str, Any], str]] = [
            (
                "ste.unknown_op",
                {"caller": "native"},
                policy_runtime.ERROR_UNSUPPORTED_OPERATION,
            ),
            (
                "ste.prose",
                {"caller": "native", "python": sys.executable},
                policy_runtime.ERROR_POLICY_REFUSAL,
            ),
            (
                "ste.prose",
                {"caller": "native", "approval_token": "secret"},
                policy_runtime.ERROR_POLICY_REFUSAL,
            ),
            (
                "ste.prose",
                {"caller": "native", "bypass": True},
                policy_runtime.ERROR_POLICY_REFUSAL,
            ),
            (
                "ste.render_bundle",
                {
                    "caller": "native",
                    "source_path": str(source),
                    "output_dir": str(self.root / ".." / "escape"),
                },
                policy_runtime.ERROR_INVALID_INPUT,
            ),
            (
                "ste.render_bundle",
                {
                    "caller": "native",
                    "source_path": str(source),
                    "output_dir": str(out_dir),
                    "has_raw_html": True,
                    "trusted_html": False,
                },
                policy_runtime.ERROR_POLICY_REFUSAL,
            ),
            (
                "ste.render_bundle",
                {
                    "caller": "native",
                    "source_path": str(source),
                    "output_dir": str(out_dir),
                    "trusted_html": "true",
                },
                policy_runtime.ERROR_INVALID_INPUT,
            ),
            (
                "ste.render_bundle",
                {
                    "caller": "native",
                    "source_path": str(source),
                    "output_dir": str(out_dir),
                    "render_dependencies_ready": False,
                },
                policy_runtime.ERROR_DEPENDENCY_MISSING,
            ),
            (
                "ste.synthesize_wav",
                {
                    "caller": "native",
                    "text_path": str(source),
                    "audio_path": str(self.root / "beat.wav"),
                    "speech_available": False,
                },
                policy_runtime.ERROR_DEPENDENCY_MISSING,
            ),
            (
                "ste.host_write_artifact",
                {
                    "caller": "host",
                    "workspace_root": str(self.root),
                    "target_paths": [str(self.root / "ste_promax" / "evil.py")],
                },
                policy_runtime.ERROR_POLICY_REFUSAL,
            ),
            (
                "ste.host_write_artifact",
                {
                    "caller": "host",
                    "workspace_root": str(self.root),
                    "target_paths": [str(self.root / ".env")],
                },
                policy_runtime.ERROR_POLICY_REFUSAL,
            ),
            (
                "ste.render_bundle",
                {
                    "caller": "native",
                    "source_path": str(source),
                    "output_dir": str(out_dir),
                    "evidence_root": str(self.root),
                    "relative_locators": ["https://example.com/remote.json"],
                },
                policy_runtime.ERROR_INVALID_INPUT,
            ),
        ]

        for op, inputs, expected_code in bad_cases:
            with self.subTest(op=op, inputs=inputs):
                with self.assertRaises(policy_runtime.PolicyError) as ctx:
                    gate.run_guarded_operation(op, inputs, effect)
                self.assertEqual(ctx.exception.code, expected_code)
                self.assertFalse(called)
                self.assertFalse(out_dir.exists())

    def test_nested_operations_preserve_return_types_and_enforce_checks(self) -> None:
        source = self.root / "doc.md"
        source.write_text("# Nested Render\n\nVerify nested reentrancy.\n", encoding="utf-8")
        out_dir = self.root / "bundle-out"

        def bundle_effect() -> dict[str, Any]:
            out_dir.mkdir(parents=True, exist_ok=True)
            orig, norm, _ = gate.cli.normalized_input(source)
            saved_source = out_dir / "source.md"
            saved_source.write_bytes(orig)
            saved_input = out_dir / "input.json"
            saved_input.write_bytes(norm)

            # 1. Nested ste.render_artifact returning dict of Paths + slug
            def triple_effect() -> dict[str, Any]:
                h = out_dir / "nested-render.html"
                d = out_dir / "nested-render.DESIGN.md"
                m = out_dir / "nested-render.meta.yaml"
                h.write_text("<!doctype html><html><body>Nested</body></html>\n", encoding="utf-8")
                d.write_text("---\nname: ste\n---\n# Design\n", encoding="utf-8")
                m.write_text("lint_passed: true\nslug: nested-render\n", encoding="utf-8")
                return {"html_path": h, "design_path": d, "meta_path": m, "slug": "nested-render"}

            triple = gate.run_guarded_operation(
                "ste.render_artifact",
                {
                    "caller": "native",
                    "output_dir": str(out_dir),
                    "normalized_input_sha256": _sha256_bytes(norm),
                },
                triple_effect,
            )
            self.assertEqual(set(triple.keys()), {"html_path", "design_path", "meta_path", "slug"})
            self.assertIsInstance(triple["html_path"], Path)

            # 2. Nested ste.regenerate_gallery returning Path to gallery.html
            def gallery_effect() -> Path:
                g = out_dir / "gallery.html"
                g.write_text(gate._GALLERY_PREFIX + "<html></html>\n", encoding="utf-8")
                return g

            gallery_path = gate.run_guarded_operation(
                "ste.regenerate_gallery",
                {"caller": "native", "output_dir": str(out_dir)},
                gallery_effect,
            )
            self.assertEqual(gallery_path, out_dir / "gallery.html")

            manifest = {
                "status": "complete",
                "version": __version__,
                "renderer": "ste_promax.render",
                "source_path": str(source),
                "source_sha256": _sha256_bytes(orig),
                "files": {
                    "source": gate.cli.file_record(saved_source),
                    "input": gate.cli.file_record(saved_input),
                    "html": gate.cli.file_record(triple["html_path"]),
                    "design": gate.cli.file_record(triple["design_path"]),
                    "meta": gate.cli.file_record(triple["meta_path"]),
                    "gallery": gate.cli.file_record(gallery_path),
                },
                "trusted_html": False,
                "lint_passed": True,
                "external_references": [],
                "offline_verified": False,
                "warnings": [],
                "visuals": [],
            }
            (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            return manifest

        manifest_res = gate.run_guarded_operation(
            "ste.render_bundle",
            {"caller": "native", "source_path": str(source), "output_dir": str(out_dir)},
            bundle_effect,
        )
        self.assertEqual(manifest_res["status"], "complete")
        self.assertFalse((out_dir / ".skillc").exists())

        receipt = gate.get_last_receipt()
        assert receipt is not None
        self.assertEqual(receipt["schema"], "ste-promax.automatic-receipt.v1")
        self.assertEqual(receipt["verdict"], "ALLOW")
        self.assertTrue(receipt["skillc"]["goal_satisfied"])
        self.assertEqual(
            [item["op"] for item in receipt["nested_operations"]],
            ["ste.render_artifact", "ste.regenerate_gallery"],
        )

        # 3. Media preparation with nested ste.synthesize_wav returning None
        story_path = self.root / "story.json"
        story_path.write_text(json.dumps(STORY_SCHEMA["example"], indent=2) + "\n", encoding="utf-8")
        media_out = self.root / "media-out"

        def media_effect() -> dict[str, Any]:
            media_out.mkdir(parents=True, exist_ok=False)
            (media_out / "video").mkdir()
            (media_out / "source.json").write_bytes(story_path.read_bytes())
            (media_out / "story.json").write_bytes(story_path.read_bytes())
            (media_out / "review.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")
            (media_out / "timeline.json").write_text("{}\n", encoding="utf-8")
            (media_out / "transcript.txt").write_text("Beat text\n", encoding="utf-8")
            (media_out / "captions.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
            (media_out / "video" / "index.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")

            text_file = media_out / "beat-checks.txt"
            text_file.write_text("What passed", encoding="utf-8")
            wav_file = media_out / "video" / "beat-checks.wav"

            synth_ret = gate.run_guarded_operation(
                "ste.synthesize_wav",
                {
                    "caller": "native",
                    "text_path": str(text_file),
                    "audio_path": str(wav_file),
                },
                lambda: (wav_file.write_bytes(_valid_pcm_wav_bytes()), None)[1],
            )
            self.assertIsNone(synth_ret)

            wav_bytes = wav_file.read_bytes()
            media_manifest = {
                "version": 1,
                "status": "prepared_not_rendered",
                "output": str(media_out),
                "source_file": "source.json",
                "normalized_story": "story.json",
                "source_sha256": _sha256_file(story_path),
                "audio": [
                    {
                        "id": "checks",
                        "file": "video/beat-checks.wav",
                        "audio_src": "beat-checks.wav",
                        "bytes": len(wav_bytes),
                        "sha256": _sha256_bytes(wav_bytes),
                    }
                ],
                "warnings": [],
                "review_required": True,
                "source_verification": "not_performed",
            }
            (media_out / "manifest.json").write_text(json.dumps(media_manifest, indent=2) + "\n", encoding="utf-8")
            return media_manifest

        media_res = gate.run_guarded_operation(
            "ste.prepare_story_media",
            {"caller": "native", "source_path": str(story_path), "output_dir": str(media_out)},
            media_effect,
        )
        self.assertEqual(media_res["status"], "prepared_not_rendered")
        self.assertEqual(
            {p.name for p in (media_out / "video").iterdir()},
            {"index.html", "beat-checks.wav"},
        )

        # 4. Unexpected nested operation is refused without blanket bypass
        inner_called = False

        def unexpected_nested() -> str:
            nonlocal inner_called
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {"caller": "host", "target_paths": [str(self.root / "artifacts" / "x.txt")]},
                lambda: "should-not-run",
            )
            inner_called = True
            return "bad"

        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.prose",
                {"caller": "native", "profile": "relaxed"},
                unexpected_nested,
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
        self.assertFalse(inner_called)

    def test_false_success_tampered_outputs_and_mutated_inputs_fail_postcheck(self) -> None:
        source = self.root / "source.md"
        source.write_text("# Source\n\nImmutable content.\n", encoding="utf-8")

        # 1. Caller-supplied check=True without outputs is rejected
        target_a = self.root / "artifacts" / "a.txt"
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {"caller": "host", "workspace_root": str(self.root), "target_paths": [str(target_a)]},
                lambda: (target_a.parent.mkdir(parents=True, exist_ok=True), target_a.write_text("ok"))[1],
                validate_result=lambda _: {"check": True},
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)
        fail_receipt = gate.get_last_receipt()
        assert fail_receipt is not None
        self.assertEqual(fail_receipt["verdict"], "DENY")
        self.assertFalse(fail_receipt["skillc"]["goal_satisfied"])
        self.assertIn(str(target_a.resolve()), fail_receipt["partial_effects"]["files"])

        # 2. Tampered/mismatched SHA-256 in validate_result fails postcheck
        target_b = self.root / "artifacts" / "b.txt"
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {"caller": "host", "workspace_root": str(self.root), "target_paths": [str(target_b)]},
                lambda: target_b.write_text("actual content", encoding="utf-8"),
                validate_result=lambda _: {
                    "status": "written",
                    "outputs": {str(target_b.resolve()): {"sha256": "0" * 64, "size": 14}},
                    "checks": ["claimed_ok"],
                },
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)

        # 3. Source mutated during effect_fn fails postcheck
        target_c = self.root / "artifacts" / "c.txt"

        def mutating_effect() -> Path:
            target_c.write_text("output", encoding="utf-8")
            source.write_text("# Source\n\nMutated during run!\n", encoding="utf-8")
            return target_c

        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {
                    "caller": "host",
                    "workspace_root": str(self.root),
                    "source_path": str(source),
                    "target_paths": [str(target_c)],
                },
                mutating_effect,
                validate_result=lambda p: {
                    "status": "written",
                    "outputs": {str(p.resolve()): _file_obs(p)},
                    "checks": ["written"],
                },
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)
        self.assertIn("changed during operation", str(ctx.exception))

        # 4. Silent WAV fails ste.synthesize_wav postcheck
        text_path = self.root / "cue.txt"
        text_path.write_text("Hello world", encoding="utf-8")
        silent_wav = self.root / "silent.wav"
        silent_frames = b"\x00\x00" * 400
        silent_riff = (
            struct.pack("<4sI4s", b"RIFF", 36 + len(silent_frames), b"WAVE")
            + struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, 8000, 16000, 2, 16)
            + struct.pack("<4sI", b"data", len(silent_frames))
            + silent_frames
        )
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.synthesize_wav",
                {"caller": "native", "text_path": str(text_path), "audio_path": str(silent_wav)},
                lambda: (silent_wav.write_bytes(silent_riff), None)[1],
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)
        self.assertIn("Silent", str(ctx.exception))

    def test_worker_subprocess_protocol_and_replay_mismatch_refusal(self) -> None:
        python_exe, skillc_src = gate._resolve_worker_backend()
        worker_env = gate._worker_environment(skillc_src)
        worker_env["STE_SKILLC_STATE_ROOT"] = str(self.state_root)

        def call_worker(action: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            proc = subprocess.run(
                gate._worker_command(python_exe),
                input=json.dumps({"action": action, "payload": payload}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=worker_env,
                cwd=str(Path(gate.__file__).resolve().parents[1]),
                check=False,
                timeout=30,
            )
            return proc.returncode, json.loads(proc.stdout)

        # 1. guard_status succeeds
        code, status_resp = call_worker("guard_status", {})
        self.assertEqual(code, 0, status_resp)
        self.assertTrue(status_resp["ok"])
        self.assertEqual(status_resp["result"]["authority_model"], "automatic-local-policy")

        # 2. Unknown action refused with exit 2 and unsupported_operation code
        code, bad_act = call_worker("approve", {})
        self.assertEqual(code, 2)
        self.assertFalse(bad_act["ok"])
        self.assertEqual(bad_act["error"]["code"], policy_runtime.ERROR_UNSUPPORTED_OPERATION)

        # 3. guard_pre -> mismatched op or inputs in guard_post -> refused; valid guard_post -> replay refused
        target_file = self.root / "artifacts" / "worker-out.txt"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        state_dir = self.state_root / "worker-test-1"
        inputs = {
            "caller": "host",
            "workspace_root": str(self.root),
            "target_paths": [str(target_file)],
        }

        code, pre_resp = call_worker(
            "guard_pre",
            {"op": "ste.host_write_artifact", "state_dir": str(state_dir), "inputs": inputs},
        )
        self.assertEqual(code, 0, pre_resp)
        self.assertEqual(pre_resp["result"]["phase"], "pre")
        self.assertTrue(pre_resp["result"]["allowed"])

        # Replay of guard_pre on same state_dir is refused
        code, replay_pre = call_worker(
            "guard_pre",
            {"op": "ste.host_write_artifact", "state_dir": str(state_dir), "inputs": inputs},
        )
        self.assertEqual(code, 2)
        self.assertEqual(replay_pre["error"]["code"], policy_runtime.ERROR_POLICY_REFUSAL)

        target_file.write_text("verified worker payload\n", encoding="utf-8")
        post_facts = {
            "status": "written",
            "outputs": {str(target_file.resolve()): _file_obs(target_file)},
            "checks": ["worker_test"],
            "warnings": [],
        }

        # Mismatched op in guard_post refused without consuming pre state
        code, bad_op_post = call_worker(
            "guard_post",
            {
                "op": "ste.prose",
                "state_dir": str(state_dir),
                "inputs": inputs,
                "post_facts": post_facts,
            },
        )
        self.assertEqual(code, 2)
        self.assertEqual(bad_op_post["error"]["code"], policy_runtime.ERROR_POLICY_REFUSAL)

        # Mismatched inputs in guard_post refused
        code, bad_inp_post = call_worker(
            "guard_post",
            {
                "op": "ste.host_write_artifact",
                "state_dir": str(state_dir),
                "inputs": {**inputs, "caller": "native"},
                "post_facts": post_facts,
            },
        )
        self.assertEqual(code, 2)
        self.assertEqual(bad_inp_post["error"]["code"], policy_runtime.ERROR_POLICY_REFUSAL)

        # Matching guard_post succeeds
        code, post_resp = call_worker(
            "guard_post",
            {
                "op": "ste.host_write_artifact",
                "state_dir": str(state_dir),
                "inputs": inputs,
                "post_facts": post_facts,
            },
        )
        self.assertEqual(code, 0, post_resp)
        self.assertEqual(post_resp["result"]["schema"], "ste-promax.automatic-receipt.v1")
        self.assertEqual(post_resp["result"]["verdict"], "ALLOW")

        # Replay of guard_post on completed state_dir is refused
        code, replay_post = call_worker(
            "guard_post",
            {
                "op": "ste.host_write_artifact",
                "state_dir": str(state_dir),
                "inputs": inputs,
                "post_facts": post_facts,
            },
        )
        self.assertEqual(code, 2)
        self.assertEqual(replay_post["error"]["code"], policy_runtime.ERROR_POLICY_REFUSAL)

        # 4. Also exercise run_guarded_operation through forced worker mode
        target_file_2 = self.root / "artifacts" / "worker-out-2.txt"
        with patch.dict(
            os.environ,
            {
                "STE_SKILLC_FORCE_WORKER": "1",
                "STE_SKILLC_PYTHON": str(python_exe),
                "STE_SKILLC_ROOT": str(skillc_src),
            },
            clear=False,
        ):
            res = gate.run_guarded_operation(
                "ste.host_write_artifact",
                {
                    "caller": "host",
                    "workspace_root": str(self.root),
                    "target_paths": [str(target_file_2)],
                },
                lambda: (target_file_2.write_text("via worker fallback\n", encoding="utf-8"), "done")[1],
            )
            self.assertEqual(res, "done")
            self.assertEqual(gate.get_last_receipt()["verdict"], "ALLOW")

    def test_automatic_export_bundle_and_legacy_manual_stage_refusal(self) -> None:
        # 1. Prepare a fresh native story bundle with a local evidence file
        ev_dir = self.root / "sources"
        ev_dir.mkdir()
        ev_file = ev_dir / "log.json"
        ev_file.write_text('{"id": "log-1", "fact": "Observed in test"}\n', encoding="utf-8")

        story = copy.deepcopy(STORY_SCHEMA["example"])
        story["sources"] = [
            {
                "id": "notes",
                "title": "Test observation log",
                "locator": "sources/log.json",
                "note": "Local evidence file.",
            }
        ]
        story_source = self.root / "story.json"
        story_source.write_text(json.dumps(story, indent=2) + "\n", encoding="utf-8")

        bundle_in = self.root / "fresh-bundle"
        self._write_fresh_native_bundle(bundle_in, story_source, is_story=True)

        bundle_out = self.root / "exported-bundle"
        stdout = io.StringIO()
        with patch.object(sys, "stdout", stdout):
            exit_code = gate.run_gate_command(
                argparse.Namespace(
                    command="export",
                    input_dir=str(bundle_in),
                    output_dir=str(bundle_out),
                    evidence_root=None,
                    evidence=None,
                )
            )
        self.assertEqual(exit_code, 0)
        export_res = json.loads(stdout.getvalue())
        self.assertEqual(export_res["status"], "exported")
        self.assertEqual(export_res["authority_model"], "automatic-local-policy")
        self.assertTrue((bundle_out / "manifest.json").is_file())
        self.assertTrue((bundle_out / "evidence" / "log.json").is_file())
        self.assertEqual((bundle_out / "evidence" / "log.json").read_bytes(), ev_file.read_bytes())
        self.assertFalse((bundle_out / ".skillc").exists())
        self.assertFalse((bundle_out / "export-receipt.json").exists())

        # 2. Refuses exporting into an existing directory
        with self.assertRaises(policy_runtime.PolicyError):
            gate.export_bundle(bundle_in, bundle_out)

        # 3. Refuses exporting if original source file changed after bundle render
        story_source.write_text(json.dumps({**story, "summary": "Changed summary."}, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.export_bundle(bundle_in, self.root / "exported-after-tamper")
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)

        # 4. Refuses legacy manual stage directories and historical skillc-native-20261106
        legacy_stage = self.root / "legacy-stage"
        (legacy_stage / ".skillc").mkdir(parents=True)
        (legacy_stage / ".skillc" / "stage.json").write_text(
            '{"schema": "ste-promax.stage-record.v1", "status": "pending_approval"}\n',
            encoding="utf-8",
        )
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.export_bundle(legacy_stage, self.root / "legacy-out")
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
        self.assertIn("legacy manual stage", str(ctx.exception).lower())

        historical_stage = Path(gate.__file__).resolve().parents[1] / "artifacts" / "skillc-native-20261106" / "stage"
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.export_bundle(historical_stage, self.root / "hist-out")
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)

    def test_static_plan_refutation_nested_validation_failures_and_guard_fail_lockout(self) -> None:
        # 1. Impossible plan requiring ask_user/user_conversation is refuted by real SkillC before effect
        impossible_plan = gate.STE_AUTOMATIC_PLAN_CE.replace(
            "Tool `validate_preconditions` (owner `ste-validator`): via `read`; needs `local_filesystem`;",
            "Tool `validate_preconditions` (owner `ste-validator`): via `ask_user`; needs `user_conversation`;",
        )
        effect_ran = False
        with patch.object(gate, "STE_GATE_PLAN_CE", impossible_plan):
            with self.assertRaises(policy_runtime.PolicyError) as ctx:
                gate.run_guarded_operation(
                    "ste.prose",
                    {"caller": "native", "profile": "relaxed"},
                    lambda: (
                        setattr(self, "_impossible_ran", True),
                        "bad",
                    )[1],
                )
            self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
            self.assertFalse(getattr(self, "_impossible_ran", False))
            self.assertFalse(effect_ran)

        # 2. Permitted nested operation still enforces its own pre/post checks (no bypass)
        source = self.root / "nested-fail.md"
        source.write_text("# Doc\n\nBody.\n", encoding="utf-8")
        out_dir = self.root / "nested-fail-out"

        def bundle_with_broken_nested_triple() -> dict[str, Any]:
            out_dir.mkdir(parents=True, exist_ok=True)
            # Nested ste.render_artifact omits meta_path file on disk -> must fail nested postcheck
            h = out_dir / "broken.html"
            d = out_dir / "broken.DESIGN.md"
            m = out_dir / "broken.meta.yaml"
            h.write_text("<!doctype html><html></html>\n", encoding="utf-8")
            d.write_text("---\nname: ste\n---\n", encoding="utf-8")
            return gate.run_guarded_operation(
                "ste.render_artifact",
                {"caller": "native", "output_dir": str(out_dir), "source_path": str(source)},
                lambda: {"html_path": h, "design_path": d, "meta_path": m, "slug": "broken"},
            )

        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.render_bundle",
                {"caller": "native", "source_path": str(source), "output_dir": str(out_dir)},
                bundle_with_broken_nested_triple,
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)
        fail_rec = gate.get_last_receipt()
        assert fail_rec is not None
        self.assertEqual(fail_rec["verdict"], "DENY")
        self.assertFalse(fail_rec["skillc"]["goal_satisfied"])

        # 3. Unowned gallery.html is refused in guard_pre before effect_fn runs
        unowned_dir = self.root / "unowned-gallery-dir"
        unowned_dir.mkdir()
        (unowned_dir / "gallery.html").write_text("<html><body>User handwritten page</body></html>\n", encoding="utf-8")
        gallery_effect_ran = False
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.regenerate_gallery",
                {"caller": "native", "output_dir": str(unowned_dir)},
                lambda: (
                     True,
                    unowned_dir / "gallery.html",
                )[1],
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
        self.assertFalse(gallery_effect_ran)

        # 4. guard_fail locks out subsequent guard_post on the same state_dir
        state_dir = self.state_root / "fail-lockout-test"
        target_f = self.root / "artifacts" / "lockout.txt"
        target_f.parent.mkdir(parents=True, exist_ok=True)
        inputs = {"caller": "host", "workspace_root": str(self.root), "target_paths": [str(target_f)]}
        gate._dispatch_inprocess_action(
            "guard_pre",
            {"op": "ste.host_write_artifact", "state_dir": str(state_dir), "inputs": inputs},
        )
        fail_res = gate._dispatch_inprocess_action(
            "guard_fail",
            {
                "op": "ste.host_write_artifact",
                "state_dir": str(state_dir),
                "inputs": inputs,
                "error": "simulated write abort",
            },
        )
        self.assertEqual(fail_res["verdict"], "DENY")
        self.assertFalse(fail_res["skillc"]["goal_satisfied"])

        target_f.write_text("late write\n", encoding="utf-8")
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate._dispatch_inprocess_action(
                "guard_post",
                {
                    "op": "ste.host_write_artifact",
                    "state_dir": str(state_dir),
                    "inputs": inputs,
                    "post_facts": {
                        "status": "written",
                        "outputs": {str(target_f.resolve()): _file_obs(target_f)},
                    },
                },
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)

        # 5. ste.inspect_artifact and ste.prose preserve return values and record ALLOW receipts
        inspected = gate.run_guarded_operation(
            "ste.inspect_artifact",
            {"caller": "host", "target_paths": [str(source)]},
            lambda: {"inspected": str(source), "ok": True},
        )
        self.assertEqual(inspected, {"inspected": str(source), "ok": True})
        self.assertEqual(gate.get_last_receipt()["op"], "ste.inspect_artifact")

        prose_text = "Keep sentences short and active."
        prose_out = gate.run_guarded_operation(
            "ste.prose",
            {"caller": "host", "profile": "procedure"},
            lambda: prose_text,
        )
        self.assertEqual(prose_out, prose_text)
        self.assertEqual(gate.get_last_receipt()["op"], "ste.prose")
        self.assertTrue(gate.get_last_receipt()["warnings"])

    def test_shared_contract_fields_expected_before_proposed_contents_and_host_content(self) -> None:
        origin_file = self.root / "origin.md"
        origin_bytes = b"# Origin\n\nRead-only source.\n"
        origin_file.write_bytes(origin_bytes)
        origin_sha = _sha256_bytes(origin_bytes)

        ev_dir = self.root / "ev"
        ev_dir.mkdir()
        ev_loc_file = ev_dir / "metric.json"
        ev_loc_file.write_text('{"metric": 42}\n', encoding="utf-8")

        out_root = self.root / "artifacts" / "host-gen"
        out_root.mkdir(parents=True)
        html_target = out_root / "interactive.html"
        html_body = "<!doctype html><html><body><script>console.log('interactive');</script></body></html>\n"

        # 1. Generated host_content (interactive HTML) succeeds without trusted_html=True,
        #    while verifying expected_before=None and proposed_contents.
        res = gate.run_guarded_operation(
            "ste.host_write_artifact",
            {
                "caller_kind": "host",
                "workspace_root": str(self.root),
                "output_root": str(out_root),
                "target_paths": [str(html_target)],
                "source_paths": [str(origin_file)],
                "source_digest": origin_sha,
                "source_kind": "host_content",
                "trusted_html": False,
                "evidence_root": str(self.root),
                "evidence_paths": [],
                "evidence_locators": ["ev/metric.json"],
                "availability": {"local_fs": True},
                "expected_before": {str(html_target): None},
                "proposed_contents": {str(html_target): html_body},
            },
            lambda: (html_target.write_text(html_body, encoding="utf-8", newline=""), html_target)[1],
            validate_result=lambda p: {
                "native_status": "written",
                "outputs": {str(p.resolve()): _file_obs(p)},
                "checks": ["interactive_host_html_written"],
                "warnings": [],
            },
        )
        self.assertEqual(res, html_target)
        receipt = gate.get_last_receipt()
        assert receipt is not None
        self.assertEqual(receipt["verdict"], "ALLOW")
        self.assertEqual(receipt["native_status"], "written")

        # 2. Imported raw_html without trusted_html=True fails in precheck before effect
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.render_bundle",
                {
                    "caller_kind": "native",
                    "output_root": str(self.root / "raw-html-out"),
                    "source_paths": [str(origin_file)],
                    "source_digest": origin_sha,
                    "source_kind": "raw_html",
                    "trusted_html": False,
                },
                lambda: {},
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)

        # 3. expected_before=None fails if target file already exists
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {
                    "caller_kind": "host",
                    "workspace_root": str(self.root),
                    "output_root": str(out_root),
                    "target_paths": [str(html_target)],
                    "source_kind": "host_content",
                    "expected_before": {str(html_target): None},
                },
                lambda: html_target,
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)

        # 4. expected_before with wrong SHA-256 fails before effect; matching SHA-256 succeeds
        current_html_sha = _sha256_file(html_target)
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {
                    "caller_kind": "host",
                    "workspace_root": str(self.root),
                    "output_root": str(out_root),
                    "target_paths": [str(html_target)],
                    "source_kind": "host_content",
                    "expected_before": {str(html_target): "f" * 64},
                },
                lambda: html_target,
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)

        updated_html = "<!doctype html><html><body>Updated</body></html>\n"
        gate.run_guarded_operation(
            "ste.host_write_artifact",
            {
                "caller_kind": "host",
                "workspace_root": str(self.root),
                "output_root": str(out_root),
                "target_paths": [str(html_target)],
                "source_kind": "host_content",
                "expected_before": {str(html_target): current_html_sha},
                "proposed_contents": {str(html_target): updated_html},
            },
            lambda: html_target.write_text(updated_html, encoding="utf-8", newline=""),
        )
        self.assertEqual(html_target.read_text(encoding="utf-8"), updated_html)

        # 5. Writing bytes that differ from proposed_contents fails postcheck
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {
                    "caller_kind": "host",
                    "workspace_root": str(self.root),
                    "output_root": str(out_root),
                    "target_paths": [str(html_target)],
                    "source_kind": "host_content",
                    "expected_before": {str(html_target): _sha256_file(html_target)},
                    "proposed_contents": {str(html_target): "<!doctype html><html>Expected</html>\n"},
                },
                lambda: html_target.write_text("<!doctype html><html>Different!</html>\n", encoding="utf-8", newline=""),
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)

        # 6. source_paths are read-only origins and cannot appear in target_paths or expected_before
        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.host_write_artifact",
                {
                    "caller_kind": "host",
                    "workspace_root": str(self.root),
                    "source_paths": [str(origin_file)],
                    "target_paths": [str(origin_file)],
                },
                lambda: origin_file,
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)

    def test_reconciliation_regressions_for_all_nine_blockers(self) -> None:
        # Blocker 1: Export rejects story/explicit evidence bundles that lack render-time evidence bindings/snapshots
        ev_dir = self.root / "b1-sources"
        ev_dir.mkdir()
        ev_file = ev_dir / "trace.json"
        ev_file.write_text('{"id": "t1", "ok": true}\n', encoding="utf-8")

        story = copy.deepcopy(STORY_SCHEMA["example"])
        story["sources"] = [{"id": "notes", "title": "Trace", "locator": "b1-sources/trace.json"}]
        story_path = self.root / "b1-story.json"
        story_path.write_text(json.dumps(story, indent=2) + "\n", encoding="utf-8")

        unbound_bundle = self.root / "b1-unbound-bundle"
        self._write_fresh_native_bundle(unbound_bundle, story_path, is_story=True)
        # Strip render-time evidence bindings and snapshot to simulate an unbound bundle
        (unbound_bundle / "evidence" / "trace.json").unlink()
        (unbound_bundle / "evidence").rmdir()
        m_data = json.loads((unbound_bundle / "manifest.json").read_text(encoding="utf-8"))
        m_data.pop("evidence_files", None)
        m_data.pop("evidence_root", None)
        (unbound_bundle / "manifest.json").write_text(json.dumps(m_data, indent=2) + "\n", encoding="utf-8")

        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.export_bundle(unbound_bundle, self.root / "b1-export-fail")
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_INVALID_INPUT)
        self.assertIn("render-time evidence bindings", str(ctx.exception))
        self.assertFalse((self.root / "b1-export-fail").exists())

        # Blocker 2: Host caller output_root escaping workspace_root or targeting protected dirs fails BEFORE effect
        ws = self.root / "b2-workspace"
        ws.mkdir()
        src_in_ws = ws / "story.json"
        src_in_ws.write_text(json.dumps(STORY_SCHEMA["example"], indent=2) + "\n", encoding="utf-8")
        outside_out = self.root / "b2-outside-out"
        protected_out = ws / "ste_promax" / "out"
        b2_calls = 0

        def b2_effect() -> dict[str, Any]:
            nonlocal b2_calls
            b2_calls += 1
            outside_out.mkdir(parents=True, exist_ok=True)
            return {}

        for op_name in ("ste.render_bundle", "ste.prepare_story_media", "ste.export_bundle", "ste.render_artifact", "ste.regenerate_gallery"):
            for bad_out in (outside_out, protected_out):
                with self.subTest(op=op_name, bad_out=bad_out):
                    with self.assertRaises(policy_runtime.PolicyError) as ctx:
                        gate.run_guarded_operation(
                            op_name,
                            {
                                "caller_kind": "host",
                                "workspace_root": str(ws),
                                "output_root": str(bad_out),
                                "source_paths": [str(src_in_ws)],
                            },
                            b2_effect,
                        )
                    self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
                    self.assertEqual(b2_calls, 0)
                    self.assertFalse(outside_out.exists())
                    self.assertFalse(protected_out.exists())

        # Blocker 3: ste.export_bundle using ONLY input_dir snapshots original source and detects mutation during export
        b3_bundle = self.root / "b3-bundle"
        b3_src = self.root / "b3-note.md"
        b3_src.write_text("# B3\n\nOriginal.\n", encoding="utf-8")
        self._write_fresh_native_bundle(b3_bundle, b3_src, is_story=False)
        b3_dest = self.root / "b3-exported"

        def b3_mutating_export() -> dict[str, Any]:
            b3_dest.mkdir(parents=True, exist_ok=False)
            for item in b3_bundle.iterdir():
                if item.is_file():
                    (b3_dest / item.name).write_bytes(item.read_bytes())
            # Mutate the original source file during export execution
            b3_src.write_text("# B3\n\nMutated during export!\n", encoding="utf-8")
            return {
                "status": "exported",
                "files": {
                    item.name: {"path": str((b3_dest / item.name).resolve()), **_file_obs(b3_dest / item.name)}
                    for item in b3_dest.iterdir()
                },
            }

        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.export_bundle",
                {"caller_kind": "native", "input_dir": str(b3_bundle), "output_root": str(b3_dest)},
                b3_mutating_export,
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)
        self.assertIn("changed during operation", str(ctx.exception))

        # Blocker 4: Missing PyYAML during render_bundle postcheck fails with dependency_missing (no boolean fallback)
        b4_src = self.root / "b4.md"
        b4_src.write_text("# B4\n\nText.\n", encoding="utf-8")
        b4_out = self.root / "b4-out"
        with patch.object(gate.cli, "lint_status", side_effect=ModuleNotFoundError("No module named 'yaml'", name="yaml")):
            with self.assertRaises(policy_runtime.PolicyBackendError) as ctx:
                gate.run_guarded_operation(
                    "ste.render_bundle",
                    {"caller_kind": "native", "source_paths": [str(b4_src)], "output_root": str(b4_out)},
                    lambda: self._write_fresh_native_bundle(b4_out, b4_src),
                )
            self.assertEqual(ctx.exception.code, policy_runtime.ERROR_DEPENDENCY_MISSING)

        # Blocker 5: Out-of-root WAV in media manifest is rejected BEFORE reading, even with same-name video placeholder
        outside_wav = self.root / "secret-outside.wav"
        outside_wav.write_bytes(_valid_pcm_wav_bytes())
        b5_story = self.root / "b5-story.json"
        b5_story.write_text(json.dumps(STORY_SCHEMA["example"], indent=2) + "\n", encoding="utf-8")
        real_read_bytes = Path.read_bytes
        outside_wav_reads = 0

        def spy_read_bytes(path_obj: Path) -> bytes:
            nonlocal outside_wav_reads
            if path_obj.resolve() == outside_wav.resolve():
                outside_wav_reads += 1
            return real_read_bytes(path_obj)

        for bad_audio_ref in (str(outside_wav), "../secret-outside.wav", "other/secret-outside.wav"):
            with self.subTest(bad_audio_ref=bad_audio_ref):
                sub_out = self.root / f"b5-media-{abs(hash(bad_audio_ref))}"

                def b5_effect() -> dict[str, Any]:
                    sub_out.mkdir(parents=True, exist_ok=False)
                    (sub_out / "video").mkdir()
                    (sub_out / "source.json").write_bytes(b5_story.read_bytes())
                    (sub_out / "story.json").write_bytes(b5_story.read_bytes())
                    (sub_out / "review.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")
                    (sub_out / "timeline.json").write_text("{}\n", encoding="utf-8")
                    (sub_out / "transcript.txt").write_text("text\n", encoding="utf-8")
                    (sub_out / "captions.vtt").write_text("WEBVTT\n\n", encoding="utf-8")
                    (sub_out / "video" / "index.html").write_text("<!doctype html><html></html>\n", encoding="utf-8")
                    # Same-name placeholder in video/
                    placeholder = sub_out / "video" / "secret-outside.wav"
                    placeholder.write_bytes(_valid_pcm_wav_bytes())
                    m = {
                        "version": 1,
                        "status": "prepared_not_rendered",
                        "output": str(sub_out),
                        "source_file": "source.json",
                        "normalized_story": "story.json",
                        "source_sha256": _sha256_file(b5_story),
                        "audio": [
                            {
                                "id": "checks",
                                "file": bad_audio_ref,
                                "audio_src": "secret-outside.wav",
                                "bytes": outside_wav.stat().st_size,
                                "sha256": _sha256_bytes(real_read_bytes(outside_wav)),
                            }
                        ],
                        "warnings": [],
                        "review_required": True,
                        "source_verification": "not_performed",
                    }
                    (sub_out / "manifest.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
                    return m

                with patch.object(Path, "read_bytes", spy_read_bytes):
                    with self.assertRaises(policy_runtime.PolicyError) as ctx:
                        gate.run_guarded_operation(
                            "ste.prepare_story_media",
                            {"caller_kind": "native", "source_paths": [str(b5_story)], "output_root": str(sub_out)},
                            b5_effect,
                        )
                    self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)
                    self.assertEqual(outside_wav_reads, 0)

        # Blocker 6: Permitted nested operation escaping parent output_root or target_paths is rejected BEFORE child effect
        b6_parent_out = self.root / "b6-parent"
        b6_escaped_out = self.root / "b6-escaped"
        child_ran = False

        def b6_parent_effect() -> dict[str, Any]:
            nonlocal child_ran
            b6_parent_out.mkdir(parents=True, exist_ok=True)
            return gate.run_guarded_operation(
                "ste.render_artifact",
                {
                    "caller_kind": "native",
                    "output_root": str(b6_escaped_out),
                    "source_paths": [str(b4_src)],
                },
                lambda: (setattr(self, "_b6_child", True), {})[1],
            )

        with self.assertRaises(policy_runtime.PolicyError) as ctx:
            gate.run_guarded_operation(
                "ste.render_bundle",
                {"caller_kind": "native", "source_paths": [str(b4_src)], "output_root": str(b6_parent_out)},
                b6_parent_effect,
            )
        self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
        self.assertFalse(getattr(self, "_b6_child", False))
        self.assertFalse(child_ran)
        self.assertFalse(b6_escaped_out.exists())

        # Blocker 7: Policy/postcondition failure on a status:"complete" manifest never attaches partial_result or exits 0 in CLI
        b7_out = self.root / "b7-cli-false-success"
        orig_verify = gate._verify_operation_postconditions

        def rejecting_postcheck(op_arg, *p_args, **p_kwargs):
            if op_arg == "ste.render_bundle":
                raise policy_runtime.PolicyError("Simulated postcondition rejection", code=policy_runtime.ERROR_POSTCONDITION_FAILURE)
            return orig_verify(op_arg, *p_args, **p_kwargs)

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with patch.object(gate, "_verify_operation_postconditions", side_effect=rejecting_postcheck), \
             patch.object(sys, "stdout", out_buf), \
             patch.object(sys, "stderr", err_buf):
            cli_code = gate.cli.main(["render", str(b4_src), "--output-dir", str(b7_out)])
        self.assertEqual(cli_code, 2)
        self.assertEqual(out_buf.getvalue(), "")
        self.assertIn("Simulated postcondition rejection", err_buf.getvalue())

        # Blocker 8: Relative STE_SKILLC_PYTHON / STE_SKILLC_ROOT overrides are rejected
        for rel_py, rel_root in (
            ("relative/python.exe", str(self.root)),
            (sys.executable, "relative/skillc-root"),
        ):
            with self.subTest(rel_py=rel_py, rel_root=rel_root), patch.dict(
                os.environ,
                {"STE_SKILLC_PYTHON": rel_py, "STE_SKILLC_ROOT": rel_root},
                clear=False,
            ):
                with self.assertRaises(policy_runtime.PolicyBackendError) as ctx:
                    policy_runtime.resolve_worker_backend()
                self.assertEqual(ctx.exception.code, policy_runtime.ERROR_DEPENDENCY_MISSING)

        # Blocker 9: Unrelated directory with basename 'skillc-native-20261106' in temp workspace is allowed,
        # while actual repo historical package remains protected.
        unrelated_dir = self.root / "skillc-native-20261106"
        unrelated_dir.mkdir()
        unrelated_src = unrelated_dir / "ok.md"
        unrelated_src.write_text("# Allowed\n\nUnrelated temp directory.\n", encoding="utf-8")
        unrelated_bundle = unrelated_dir / "bundle-out"
        self._write_fresh_native_bundle(unrelated_bundle, unrelated_src)
        unrelated_exported = unrelated_dir / "exported"
        exp_res = gate.export_bundle(unrelated_bundle, unrelated_exported)
        self.assertEqual(exp_res["status"], "exported")
        self.assertTrue((unrelated_exported / "manifest.json").is_file())

    def test_final_gate_host_same_op_nesting_secret_locators_html_trust_and_origin_drift(self) -> None:
        from ste_promax.gallery import regenerate_gallery
        from ste_promax import media
        from ste_promax.render import render_artifact

        # 1. Fix 1: Secret/credential/control locators in story.sources[].locator and evidence_locators
        #    are rejected BEFORE reading bytes, copying snapshots, or calling effect_fn.
        ws = self.root / "fg-workspace"
        ws.mkdir()
        fake_secrets = {
            ".env": ws / ".env",
            "credentials.json": ws / "credentials.json",
            ".copilot/config.json": ws / ".copilot" / "config.json",
            "runtime.json": ws / "runtime.json",
            ".skillc/stage.json": ws / ".skillc" / "stage.json",
            ".git/config": ws / ".git" / "config",
            "sub/secret_token.json": ws / "sub" / "secret_token.json",
        }
        for rel_loc, secret_path in fake_secrets.items():
            secret_path.parent.mkdir(parents=True, exist_ok=True)
            secret_path.write_text(f"FAKE_SECRET_FOR_{rel_loc}\n", encoding="utf-8")

        secret_resolved_set = {p.resolve() for p in fake_secrets.values()}
        real_read_bytes = Path.read_bytes
        secret_reads = 0
        effect_calls = 0

        def spy_secret_read(path_obj: Path) -> bytes:
            nonlocal secret_reads
            if path_obj.resolve() in secret_resolved_set:
                secret_reads += 1
            return real_read_bytes(path_obj)

        for rel_loc in fake_secrets:
            with self.subTest(secret_locator=rel_loc):
                bad_story = copy.deepcopy(STORY_SCHEMA["example"])
                bad_story["sources"] = [{"id": "notes", "title": "Secret", "locator": rel_loc}]
                story_file = ws / "story-with-secret.json"
                story_file.write_text(json.dumps(bad_story, indent=2) + "\n", encoding="utf-8")
                out_dir = ws / "artifacts" / f"out-{abs(hash(rel_loc))}"

                with patch.object(Path, "read_bytes", spy_secret_read):
                    # Via gate.run_guarded_operation story.sources[].locator
                    with self.assertRaises(policy_runtime.PolicyError) as ctx:
                        gate.run_guarded_operation(
                            "ste.render_bundle",
                            {
                                "caller_kind": "host",
                                "workspace_root": str(ws),
                                "output_root": str(out_dir),
                                "source_paths": [str(story_file)],
                                "evidence_root": str(ws),
                            },
                            lambda: (setattr(self, "_fg_effect", True), {})[1],
                        )
                    self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
                    # Via cli.render
                    with self.assertRaises(policy_runtime.PolicyError):
                        gate.cli.render(
                            argparse.Namespace(
                                input=str(story_file),
                                output_dir=str(out_dir),
                                title=None,
                                design=None,
                                trusted_html=False,
                                evidence=[],
                                evidence_root=str(ws),
                            )
                        )
                    # Via render_artifact in-memory story
                    with self.assertRaises(policy_runtime.PolicyError):
                        render_artifact(bad_story, output_dir=out_dir)
                    # Via media.prepare_story_media
                    with self.assertRaises(policy_runtime.PolicyError):
                        media.prepare_story_media(story_file, out_dir)

                self.assertEqual(secret_reads, 0, f"Secret locator {rel_loc} must never be read")
                self.assertFalse(getattr(self, "_fg_effect", False))
                self.assertEqual(effect_calls, 0)
                self.assertFalse(out_dir.exists())

        # 2. Fix 2: render_artifact requires explicit boolean trusted_html=True for raw HTML
        raw_out = ws / "artifacts" / "raw-triple"
        for bad_flag in (False, "true", 1, None):
            with self.assertRaises(ValueError):
                render_artifact(
                    {"title": "Untrusted Raw", "body_html": "<div>Raw</div>"},
                    output_dir=raw_out,
                    trusted_html=bad_flag,  # type: ignore[arg-type]
                )
            self.assertFalse(raw_out.exists())

        # 3. Host outer same-op nesting for render_artifact, regenerate_gallery, prepare_story_media,
        #    synthesize_wav, and export_bundle, plus origin drift -> DENY with no persisted ALLOW.
        prev_cwd = Path.cwd()
        os.chdir(ws)
        try:
            src_json = ws / "doc.json"
            doc_payload = {"title": "Host Guarded Triple", "body_html": "<p>Explicitly trusted</p>"}
            src_bytes = (json.dumps(doc_payload, indent=2) + "\n").encode("utf-8")
            src_json.write_bytes(src_bytes)

            triple_dir = ws / "artifacts" / "triple-host"
            triple_res = gate.run_guarded_operation(
                "ste.render_artifact",
                {
                    "caller_kind": "host",
                    "workspace_root": str(ws),
                    "output_root": str(triple_dir),
                    "source_paths": [str(src_json)],
                    "source_digest": _sha256_bytes(src_bytes),
                    "source_kind": "raw_html",
                    "trusted_html": True,
                },
                lambda: render_artifact(doc_payload, output_dir=triple_dir, trusted_html=True),
            )
            self.assertEqual(set(triple_res.keys()), {"html_path", "design_path", "meta_path", "slug"})
            outer_rec = gate.get_last_receipt()
            assert outer_rec is not None
            self.assertEqual(outer_rec["verdict"], "ALLOW")
            self.assertEqual(outer_rec["op"], "ste.render_artifact")
            self.assertEqual(len(outer_rec["nested_operations"]), 1)
            self.assertEqual(outer_rec["nested_operations"][0]["op"], "ste.render_artifact")

            # Origin drift during host outer render_artifact -> DENY with NO persisted ALLOW receipt
            drift_dir = ws / "artifacts" / "triple-drift"
            runs_before = set((self.state_root / "runs").iterdir()) if (self.state_root / "runs").is_dir() else set()

            def drifting_host_render() -> dict[str, Any]:
                res = render_artifact({"title": "Drift", "body_md": "# Drift"}, output_dir=drift_dir)
                src_json.write_text('{"title": "Tampered during render"}\n', encoding="utf-8")
                return res

            with self.assertRaises(policy_runtime.PolicyError) as ctx:
                gate.run_guarded_operation(
                    "ste.render_artifact",
                    {
                        "caller_kind": "host",
                        "workspace_root": str(ws),
                        "output_root": str(drift_dir),
                        "source_paths": [str(src_json)],
                        "source_digest": _sha256_bytes(src_bytes),
                        "source_kind": "structured",
                        "trusted_html": False,
                    },
                    drifting_host_render,
                )
            self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POSTCONDITION_FAILURE)
            drift_rec = gate.get_last_receipt()
            assert drift_rec is not None
            self.assertEqual(drift_rec["verdict"], "DENY")
            self.assertFalse(drift_rec["skillc"]["goal_satisfied"])
            runs_after = set((self.state_root / "runs").iterdir()) - runs_before
            self.assertEqual(len(runs_after), 1)
            persisted_rec = json.loads((next(iter(runs_after)) / ".skillc" / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted_rec["verdict"], "DENY")
            src_json.write_bytes(src_bytes)

            # Same-op host outer regenerate_gallery
            gal_res = gate.run_guarded_operation(
                "ste.regenerate_gallery",
                {
                    "caller_kind": "host",
                    "workspace_root": str(ws),
                    "output_root": str(triple_dir),
                    "target_paths": [str((triple_dir / "gallery.html").resolve())],
                },
                lambda: regenerate_gallery(triple_dir),
            )
            self.assertEqual(gal_res, triple_dir / "gallery.html")
            self.assertEqual(gate.get_last_receipt()["verdict"], "ALLOW")

            # Fix 3: Same-op host outer synthesize_wav & precheck refusal when audio_path already exists
            cue_txt = ws / "cue.txt"
            cue_txt.write_text("Synthesize this cue.\n", encoding="utf-8")
            wav_out = ws / "artifacts" / "single-beat.wav"
            wav_out.parent.mkdir(parents=True, exist_ok=True)

            def fake_ps(cmd, *args, **kwargs):
                idx = cmd.index("-OutputPath") + 1
                Path(cmd[idx]).write_bytes(_valid_pcm_wav_bytes())
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with patch.object(media.shutil, "which", return_value="powershell.exe"), \
                 patch.object(media.subprocess, "run", side_effect=fake_ps) as ps_mock:
                synth_res = gate.run_guarded_operation(
                    "ste.synthesize_wav",
                    {
                        "caller_kind": "host",
                        "workspace_root": str(ws),
                        "source_paths": [str(cue_txt)],
                        "target_paths": [str(wav_out)],
                        "text_path": str(cue_txt),
                        "audio_path": str(wav_out),
                        "expected_before": {str(wav_out): None},
                    },
                    lambda: media.synthesize(cue_txt, wav_out, None),
                )
                self.assertIsNone(synth_res)
                self.assertEqual(ps_mock.call_count, 1)
                self.assertEqual(gate.get_last_receipt()["verdict"], "ALLOW")

                # Second call to same wav_out must be refused by expected_before BEFORE subprocess.run
                with self.assertRaises(policy_runtime.PolicyError) as ctx:
                    media.synthesize(cue_txt, wav_out, None)
                self.assertEqual(ctx.exception.code, policy_runtime.ERROR_POLICY_REFUSAL)
                self.assertEqual(ps_mock.call_count, 1)

            # Same-op host outer prepare_story_media (with nested synthesize_wav under video/)
            valid_story_path = ws / "valid-story.json"
            valid_story_path.write_text(json.dumps(STORY_SCHEMA["example"], indent=2) + "\n", encoding="utf-8")
            media_dir = ws / "artifacts" / "story-media"
            with patch.object(media.shutil, "which", return_value="powershell.exe"), \
                 patch.object(media.subprocess, "run", side_effect=fake_ps):
                media_manifest = gate.run_guarded_operation(
                    "ste.prepare_story_media",
                    {
                        "caller_kind": "host",
                        "workspace_root": str(ws),
                        "output_root": str(media_dir),
                        "source_paths": [str(valid_story_path)],
                        "source_kind": "story",
                    },
                    lambda: media.prepare_story_media(valid_story_path, media_dir),
                )
            self.assertEqual(media_manifest["status"], "prepared_not_rendered")
            self.assertEqual(gate.get_last_receipt()["verdict"], "ALLOW")
        finally:
            os.chdir(prev_cwd)


if __name__ == "__main__":
    unittest.main()
