"""Focused unit and security boundary tests for host operation dispatch, outer guards, and sensitive read paths.

Covers:
1. Fix 1: Strict JSON boolean preservation (`trusted_html`, `headless_browser`, `is_directory`,
   `require_document_extension`) and closed accepted-field validation in `dispatch_host_operation`
   (strings, numbers, lists, null, and unknown argument keys refused before effects; valid booleans work).
2. Fix 2: Outer `gate.run_guarded_operation` (`caller_kind="host"`, real workspace, original source/design/evidence
   paths) wrapping every host native operation (`host_render_bundle`, `host_render_artifact`,
   `host_regenerate_gallery`, `host_prepare_story_media`, `host_synthesize_wav`, `host_export_bundle`),
   single outer persisted ALLOW receipt, `render_artifact(..., trusted_html=...)` forwarding, source/design
   drift producing DENY + retained partial files, gallery `expected_before` + bound origins, synthesis
   existing-WAV refusal via `expected_before=None` before native callback, media `audio_dir`/`voice`/origins,
   and export preflight validation of all manifest origins before native helper.
3. Fix 3: Shared `policy_runtime.check_sensitive_read_path` in `_resolve_host_read_path` and owned fake
   `.env`, `credentials.json`, `.copilot/config.json`, and `runtime.json` story-locator and origin regressions
   proving no sensitive read/copy, no artifact creation, and no ALLOW receipt.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from integrations.mcp import (  # noqa: E402
    dispatch_host_operation,
    host_export_bundle,
    host_prepare_story_media,
    host_regenerate_gallery,
    host_render_artifact,
    host_render_bundle,
    host_synthesize_wav,
    validate_host_target_path,
)
from integrations.mcp import operations as mcp_ops  # noqa: E402
from ste_promax import gate, policy_runtime  # noqa: E402

mcp_ops._ensure_render_deps_on_path()
from ste_promax import media, render  # noqa: E402


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_pcm_wav_bytes() -> bytes:
    sample_rate = 8000
    samples = [0, 12000, -12000, 6000, -6000, 18000, -18000, 3000] * 125
    pcm_frames = struct.pack(f"<{len(samples)}h", *samples)
    fmt_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    data_chunk = struct.pack("<4sI", b"data", len(pcm_frames)) + pcm_frames
    riff_size = 4 + len(fmt_chunk) + len(data_chunk)
    return struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE") + fmt_chunk + data_chunk


def _make_story_dict(locator: str) -> dict[str, Any]:
    return {
        "kind": "story",
        "version": 1,
        "title": "Boundary Check Brief",
        "audience": "Security engineers verifying origin confinement",
        "question": "Does the story workflow reject sensitive local locators?",
        "purpose": "incident-review",
        "summary": "Verify story locator origin checks.",
        "context": "Synthetic unit test using owned fake files.",
        "sources": [
            {
                "id": "src-1",
                "title": "Test Source",
                "locator": locator,
                "note": "Owned test locator.",
            }
        ],
        "claims": [
            {
                "id": "claim-1",
                "type": "observation",
                "text": "Queue latency remained within target bounds.",
                "source_ids": ["src-1"],
                "attributed_to": "Test Source",
                "basis": "Synthetic test",
                "scope": "Local test workspace",
                "uncertainty": "None",
            }
        ],
        "beats": [
            {
                "id": "beat-1",
                "title": "Latency Check",
                "role": "Observed metric",
                "text": "Queue latency remained within target bounds.",
                "claim_ids": ["claim-1"],
                "narration": "Queue latency remained within target bounds.",
            }
        ],
    }


class HostGuardBoundariesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ste-host-guard-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "workspace"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.state_root = self.root / "policy-state"
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.env_patch = patch.dict(
            os.environ,
            {
                "STE_SKILLC_STATE_ROOT": str(self.state_root),
                "STE_TRUSTED_WORKSPACE": str(self.workspace),
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _run_dirs(self) -> set[Path]:
        runs_dir = self.state_root / "runs"
        if not runs_dir.is_dir():
            return set()
        return set(runs_dir.iterdir())

    def test_fix1_strict_booleans_and_closed_argument_keys(self) -> None:
        src_md = self.workspace / "docs" / "input.md"
        src_md.parent.mkdir(parents=True, exist_ok=True)
        src_md.write_text("# Valid Input\n\nCheck strict boolean handling.\n", encoding="utf-8")

        non_booleans: list[Any] = ["false", "true", "", 0, 1, [], [True], {}, None]

        # 1. trusted_html in ste_write_artifact, ste_render_bundle, ste_render_artifact
        for bad_val in non_booleans:
            sentinel_write = self.workspace / "artifacts" / "bad-bool-write.html"
            res_w = dispatch_host_operation(
                "ste_write_artifact",
                {
                    "target_path": "artifacts/bad-bool-write.html",
                    "content": "<!doctype html><html><body>Raw</body></html>\n",
                    "source_kind": "raw_html",
                    "trusted_html": bad_val,
                },
                workspace_root=self.workspace,
            )
            self.assertFalse(res_w["ok"], f"Expected failure for trusted_html={bad_val!r}")
            self.assertEqual(res_w["error"]["code"], "invalid_input")
            self.assertFalse(sentinel_write.exists())
            self.assertIsNone(gate.get_last_receipt())

            sentinel_bundle = self.workspace / "artifacts" / "bad-bool-bundle"
            res_b = dispatch_host_operation(
                "ste_render_bundle",
                {
                    "input_path": str(src_md),
                    "output_dir": str(sentinel_bundle),
                    "trusted_html": bad_val,
                },
                workspace_root=self.workspace,
            )
            self.assertFalse(res_b["ok"], f"Expected failure for trusted_html={bad_val!r}")
            self.assertEqual(res_b["error"]["code"], "invalid_input")
            self.assertFalse(sentinel_bundle.exists())

            sentinel_triple = self.workspace / "artifacts" / "bad-bool-triple"
            res_a = dispatch_host_operation(
                "ste_render_artifact",
                {
                    "output_dir": str(sentinel_triple),
                    "input_path": str(src_md),
                    "trusted_html": bad_val,
                },
                workspace_root=self.workspace,
            )
            self.assertFalse(res_a["ok"], f"Expected failure for trusted_html={bad_val!r}")
            self.assertEqual(res_a["error"]["code"], "invalid_input")
            self.assertFalse(sentinel_triple.exists())

        # 2. headless_browser in ste_inspect_artifact
        for bad_val in non_booleans:
            res_i = dispatch_host_operation(
                "ste_inspect_artifact",
                {
                    "target_path": str(src_md),
                    "headless_browser": bad_val,
                },
                workspace_root=self.workspace,
            )
            self.assertFalse(res_i["ok"], f"Expected failure for headless_browser={bad_val!r}")
            self.assertEqual(res_i["error"]["code"], "invalid_input")

        # 3. is_directory and require_document_extension in ste_validate_target and validate_host_target_path
        for bad_val in non_booleans:
            res_vt1 = dispatch_host_operation(
                "ste_validate_target",
                {
                    "target_path": "artifacts/out-dir",
                    "is_directory": bad_val,
                },
                workspace_root=self.workspace,
            )
            self.assertFalse(res_vt1["ok"], f"Expected failure for is_directory={bad_val!r}")
            self.assertEqual(res_vt1["error"]["code"], "invalid_input")

            res_vt2 = dispatch_host_operation(
                "ste_validate_target",
                {
                    "target_path": "artifacts/out.md",
                    "is_directory": False,
                    "require_document_extension": bad_val,
                },
                workspace_root=self.workspace,
            )
            self.assertFalse(res_vt2["ok"], f"Expected failure for require_document_extension={bad_val!r}")
            self.assertEqual(res_vt2["error"]["code"], "invalid_input")

            with self.assertRaises(policy_runtime.PolicyError) as ctx_dir:
                validate_host_target_path(
                    "artifacts/out",
                    self.workspace,
                    is_directory=bad_val,  # type: ignore[arg-type]
                )
            self.assertEqual(ctx_dir.exception.code, "invalid_input")

        # 4. Unknown argument keys rejected for every tool before effects
        for tool_name, base_args in (
            ("ste_status", {}),
            ("ste_validate_target", {"target_path": "artifacts/x.md"}),
            ("ste_check_prose", {"text": "Keep sentences clear."}),
            ("ste_write_artifact", {"target_path": "artifacts/x.md", "content": "# X\n"}),
            ("ste_render_bundle", {"input_path": str(src_md), "output_dir": "artifacts/b"}),
            ("ste_render_artifact", {"output_dir": "artifacts/t", "input_path": str(src_md)}),
            ("ste_regenerate_gallery", {"artifact_dir": "artifacts/t"}),
            ("ste_prepare_story_media", {"input_path": str(src_md), "output_dir": "artifacts/m"}),
            ("ste_synthesize_wav", {"text_path": str(src_md), "audio_path": "artifacts/a.wav"}),
            ("ste_inspect_artifact", {"target_path": str(src_md)}),
            ("ste_export_bundle", {"input_dir": "artifacts/b", "output_dir": "artifacts/e"}),
        ):
            bad_args = {**base_args, "unexpected_extra_key": True}
            res_unk = dispatch_host_operation(tool_name, bad_args, workspace_root=self.workspace)
            self.assertFalse(res_unk["ok"], f"Expected unknown key refusal for {tool_name}")
            self.assertEqual(res_unk["error"]["code"], "invalid_input")
            self.assertIn("unexpected_extra_key", res_unk["error"]["message"])

        # 5. Valid booleans still work
        ok_vt = dispatch_host_operation(
            "ste_validate_target",
            {
                "target_path": "artifacts/valid-doc.md",
                "is_directory": False,
                "require_document_extension": True,
            },
            workspace_root=self.workspace,
        )
        self.assertTrue(ok_vt["ok"], ok_vt)

        ok_raw = dispatch_host_operation(
            "ste_write_artifact",
            {
                "target_path": "artifacts/trusted-raw.html",
                "content": "<!doctype html><html><body><p>Trusted raw HTML</p></body></html>\n",
                "source_kind": "raw_html",
                "trusted_html": True,
            },
            workspace_root=self.workspace,
        )
        self.assertTrue(ok_raw["ok"], ok_raw)
        self.assertTrue((self.workspace / "artifacts" / "trusted-raw.html").is_file())

    def test_fix2_outer_host_guards_single_persisted_receipt_and_drift_refusal(self) -> None:
        src_md = self.workspace / "docs" / "guide.md"
        src_md.parent.mkdir(parents=True, exist_ok=True)
        src_md.write_text("# Valve Inspection\n\nClose the inlet valve before removing the filter.\n", encoding="utf-8")
        ev_file = self.workspace / "docs" / "pressure-log.txt"
        ev_file.write_text("Inlet pressure = 0 kPa.\n", encoding="utf-8")

        # 1. host_render_artifact: outer guard + nested native render_artifact -> single persisted ALLOW receipt
        triple_dir = self.workspace / "artifacts" / "triple-01"
        before_runs = self._run_dirs()
        res_triple = host_render_artifact(
            output_dir=str(triple_dir),
            input_path=str(src_md),
            trusted_html=False,
            workspace_root=self.workspace,
        )
        self.assertTrue(res_triple["ok"], res_triple)
        new_runs = self._run_dirs() - before_runs
        self.assertEqual(len(new_runs), 1)
        persisted_triple_rec = json.loads((next(iter(new_runs)) / ".skillc" / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted_triple_rec["verdict"], "ALLOW")
        self.assertEqual(persisted_triple_rec["op"], "ste.render_artifact")
        self.assertEqual(len(persisted_triple_rec.get("nested_operations", [])), 1)
        self.assertEqual(persisted_triple_rec["nested_operations"][0]["op"], "ste.render_artifact")
        for key in ("html_path", "design_path", "meta_path"):
            self.assertIsInstance(res_triple["result"][key], str)
            self.assertTrue(Path(res_triple["result"][key]).is_file())

        # Untrusted raw HTML in host_render_artifact (both input_data and input_path) is refused before effect
        untrusted_triple_dir = self.workspace / "artifacts" / "triple-untrusted-raw"
        res_untrusted_data = host_render_artifact(
            output_dir=str(untrusted_triple_dir),
            input_data={"title": "Raw", "body_html": "<p>Untrusted</p>"},
            trusted_html=False,
            workspace_root=self.workspace,
        )
        self.assertFalse(res_untrusted_data["ok"])
        self.assertEqual(res_untrusted_data["error"]["code"], "policy_refusal")
        self.assertFalse(untrusted_triple_dir.exists())

        # Trusted raw HTML in host_render_artifact succeeds when trusted_html=True
        trusted_triple_dir = self.workspace / "artifacts" / "triple-trusted-raw"
        res_trusted_data = host_render_artifact(
            output_dir=str(trusted_triple_dir),
            input_data={"title": "Trusted Raw", "body_html": "<p>Explicitly trusted</p>"},
            trusted_html=True,
            workspace_root=self.workspace,
        )
        self.assertTrue(res_trusted_data["ok"], res_trusted_data)
        self.assertEqual(res_trusted_data["result"]["policy_receipt"]["verdict"], "ALLOW")

        # Design file mutation during host_render_artifact -> DENY receipt + retained partial files
        custom_design = self.workspace / "docs" / "custom.DESIGN.md"
        custom_design.write_bytes((REPO_ROOT / "ste_promax" / "designs" / "ste.DESIGN.md").read_bytes())
        orig_design_bytes = custom_design.read_bytes()
        drift_design_dir = self.workspace / "artifacts" / "triple-design-drift"
        orig_render_fn = render.render_artifact

        def _mutating_design_render(
            input_data: dict[str, Any],
            design_path: Path | None = None,
            output_dir: Path | None = None,
            *,
            trusted_html: bool = False,
        ):
            out = orig_render_fn(
                input_data,
                design_path=design_path,
                output_dir=output_dir,
                trusted_html=trusted_html,
            )
            custom_design.write_bytes(orig_design_bytes + b"\n<!-- mutated -->\n")
            return out

        before_drift_runs = self._run_dirs()
        try:
            with patch.object(render, "render_artifact", side_effect=_mutating_design_render):
                res_drift = host_render_artifact(
                    output_dir=str(drift_design_dir),
                    input_path=str(src_md),
                    design_path=str(custom_design),
                    workspace_root=self.workspace,
                )
            self.assertFalse(res_drift["ok"])
            self.assertEqual(res_drift["error"]["code"], "postcondition_failure")
            self.assertEqual(res_drift["error"].get("receipt", {}).get("verdict"), "DENY")
            self.assertTrue(list(drift_design_dir.glob("*.html")))
            drift_runs = self._run_dirs() - before_drift_runs
            self.assertEqual(len(drift_runs), 1)
            drift_rec = json.loads((next(iter(drift_runs)) / ".skillc" / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(drift_rec["verdict"], "DENY")
        finally:
            custom_design.write_bytes(orig_design_bytes)

        # 2. host_regenerate_gallery: outer guard + expected_before + unowned gallery refusal
        before_gal_runs = self._run_dirs()
        res_gal1 = host_regenerate_gallery(
            artifact_dir=str(triple_dir),
            workspace_root=self.workspace,
        )
        self.assertTrue(res_gal1["ok"], res_gal1)
        gal_runs = self._run_dirs() - before_gal_runs
        self.assertEqual(len(gal_runs), 1)
        gal_rec = json.loads((next(iter(gal_runs)) / ".skillc" / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(gal_rec["verdict"], "ALLOW")
        self.assertEqual(gal_rec["op"], "ste.regenerate_gallery")
        self.assertEqual(len(gal_rec.get("nested_operations", [])), 1)

        # Updating owned gallery.html succeeds via expected_before hash binding
        res_gal2 = host_regenerate_gallery(
            artifact_dir=str(triple_dir),
            workspace_root=self.workspace,
        )
        self.assertTrue(res_gal2["ok"], res_gal2)

        # Unowned gallery.html is refused before overwrite
        unowned_gal_dir = self.workspace / "artifacts" / "unowned-gal"
        unowned_gal_dir.mkdir(parents=True, exist_ok=True)
        unowned_gal_file = unowned_gal_dir / "gallery.html"
        unowned_gal_file.write_text("<html><body>User handwritten file</body></html>\n", encoding="utf-8")
        res_unowned = host_regenerate_gallery(
            artifact_dir=str(unowned_gal_dir),
            workspace_root=self.workspace,
        )
        self.assertFalse(res_unowned["ok"])
        self.assertEqual(res_unowned["error"]["code"], "policy_refusal")
        self.assertIn("User handwritten file", unowned_gal_file.read_text(encoding="utf-8"))

        # 3. host_synthesize_wav: outer guard + expected_before=None refuses existing WAV before callback
        cue_txt = self.workspace / "docs" / "cue.txt"
        cue_txt.write_text("Verify inlet pressure is zero.\n", encoding="utf-8")
        wav_target = self.workspace / "artifacts" / "audio" / "cue.wav"
        wav_target.parent.mkdir(parents=True, exist_ok=True)

        def _fake_ps(cmd: list[str], *args: Any, **kwargs: Any):
            idx = cmd.index("-OutputPath") + 1
            Path(cmd[idx]).write_bytes(_valid_pcm_wav_bytes())
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            patch.object(media.shutil, "which", return_value="powershell.exe"),
            patch.object(media.subprocess, "run", side_effect=_fake_ps) as ps_mock,
        ):
            before_synth_runs = self._run_dirs()
            res_synth = host_synthesize_wav(
                text_path=str(cue_txt),
                audio_path=str(wav_target),
                workspace_root=self.workspace,
            )
            self.assertTrue(res_synth["ok"], res_synth)
            self.assertEqual(ps_mock.call_count, 1)
            synth_runs = self._run_dirs() - before_synth_runs
            self.assertEqual(len(synth_runs), 1)
            synth_rec = json.loads((next(iter(synth_runs)) / ".skillc" / "receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(synth_rec["verdict"], "ALLOW")
            self.assertEqual(synth_rec["op"], "ste.synthesize_wav")
            self.assertEqual(len(synth_rec.get("nested_operations", [])), 1)

            # Second call to existing wav_target is refused by expected_before=None BEFORE subprocess.run
            res_synth_dup = host_synthesize_wav(
                text_path=str(cue_txt),
                audio_path=str(wav_target),
                workspace_root=self.workspace,
            )
            self.assertFalse(res_synth_dup["ok"])
            self.assertEqual(res_synth_dup["error"]["code"], "policy_refusal")
            self.assertEqual(ps_mock.call_count, 1)

        # 4. host_prepare_story_media: outer guard carries audio_dir/voice and local origins (single persisted ALLOW)
        story_ok_dict = _make_story_dict("pressure-log.txt")
        story_ok_file = self.workspace / "docs" / "story-ok.json"
        story_ok_file.write_text(json.dumps(story_ok_dict, indent=2) + "\n", encoding="utf-8")
        story_audio_dir = self.workspace / "docs" / "story-audio"
        story_audio_dir.mkdir(parents=True, exist_ok=True)
        (story_audio_dir / "beat-1.wav").write_bytes(_valid_pcm_wav_bytes())
        media_out_dir = self.workspace / "artifacts" / "media-outer-01"
        before_media_runs = self._run_dirs()
        res_media = host_prepare_story_media(
            input_path=str(story_ok_file),
            output_dir=str(media_out_dir),
            audio_dir=str(story_audio_dir),
            workspace_root=self.workspace,
        )
        self.assertTrue(res_media["ok"], res_media)
        media_runs = self._run_dirs() - before_media_runs
        self.assertEqual(len(media_runs), 1)
        media_rec = json.loads((next(iter(media_runs)) / ".skillc" / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(media_rec["verdict"], "ALLOW")
        self.assertEqual(media_rec["op"], "ste.prepare_story_media")
        self.assertEqual(len(media_rec.get("nested_operations", [])), 1)

        # 5. host_export_bundle: outer preflight rejects manifest with outside origin before native helper
        bundle_dir = self.workspace / "artifacts" / "bundle-valid"
        res_bundle = host_render_bundle(
            input_path=str(src_md),
            output_dir=str(bundle_dir),
            evidence=[str(ev_file)],
            workspace_root=self.workspace,
        )
        self.assertTrue(res_bundle["ok"], res_bundle)

        export_dir = self.workspace / "artifacts" / "bundle-exported"
        before_exp_runs = self._run_dirs()
        res_export = host_export_bundle(
            input_dir=str(bundle_dir),
            output_dir=str(export_dir),
            workspace_root=self.workspace,
        )
        self.assertTrue(res_export["ok"], res_export)
        exp_runs = self._run_dirs() - before_exp_runs
        self.assertEqual(len(exp_runs), 1)
        exp_rec = json.loads((next(iter(exp_runs)) / ".skillc" / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(exp_rec["verdict"], "ALLOW")
        self.assertEqual(exp_rec["op"], "ste.export_bundle")
        self.assertEqual(len(exp_rec.get("nested_operations", [])), 1)

        # Tamper manifest source_path to point to a file outside workspace (e.g. REPO_ROOT/README.md)
        manifest_path = bundle_dir / "manifest.json"
        orig_manifest_bytes = manifest_path.read_bytes()
        try:
            tampered_manifest = json.loads(orig_manifest_bytes.decode("utf-8"))
            tampered_manifest["source_path"] = str(REPO_ROOT / "README.md")
            manifest_path.write_text(json.dumps(tampered_manifest, indent=2) + "\n", encoding="utf-8")
            with patch.object(gate, "export_bundle") as mock_native_export:
                bad_exp = host_export_bundle(
                    input_dir=str(bundle_dir),
                    output_dir=str(self.workspace / "artifacts" / "bundle-exported-bad"),
                    workspace_root=self.workspace,
                )
                self.assertFalse(bad_exp["ok"])
                self.assertEqual(bad_exp["error"]["code"], "policy_refusal")
                self.assertEqual(mock_native_export.call_count, 0)
        finally:
            manifest_path.write_bytes(orig_manifest_bytes)

    def test_fix3_owned_fake_sensitive_story_locators_and_origins_refused(self) -> None:
        # Create owned fake sensitive files inside the temporary test workspace (never real user credentials)
        fake_env = self.workspace / "docs" / ".env"
        fake_env.parent.mkdir(parents=True, exist_ok=True)
        fake_env.write_text("FAKE_TEST_TOKEN=owned-test-only\n", encoding="utf-8")

        fake_creds = self.workspace / "docs" / "credentials.json"
        fake_creds.write_text('{"fake": "owned-test-credential"}\n', encoding="utf-8")

        fake_copilot_cfg = self.workspace / "docs" / ".copilot" / "config.json"
        fake_copilot_cfg.parent.mkdir(parents=True, exist_ok=True)
        fake_copilot_cfg.write_text('{"fake_copilot": true}\n', encoding="utf-8")

        fake_runtime = self.workspace / "docs" / "runtime.json"
        fake_runtime.write_text('{"fake_runtime": true}\n', encoding="utf-8")

        sensitive_locators = [
            (".env", fake_env),
            ("credentials.json", fake_creds),
            (".copilot/config.json", fake_copilot_cfg),
            ("runtime.json", fake_runtime),
        ]

        audio_dir = self.workspace / "docs" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "beat-1.wav").write_bytes(_valid_pcm_wav_bytes())

        orig_read_bytes = Path.read_bytes
        sensitive_resolved = {p.resolve() for _, p in sensitive_locators}
        read_sensitive_hits: list[Path] = []

        def _spy_read_bytes(path_self: Path) -> bytes:
            res_p = path_self.resolve()
            if res_p in sensitive_resolved:
                read_sensitive_hits.append(res_p)
            return orig_read_bytes(path_self)

        with patch.object(Path, "read_bytes", _spy_read_bytes):
            for idx, (loc_str, fake_path) in enumerate(sensitive_locators):
                story_dict = _make_story_dict(loc_str)
                story_file = self.workspace / "docs" / f"story-sens-{idx}.json"
                story_file.write_text(json.dumps(story_dict, indent=2) + "\n", encoding="utf-8")

                # 1. host_render_bundle must refuse before reading/copying the sensitive locator or creating output_dir
                bundle_out = self.workspace / "artifacts" / f"sens-bundle-{idx}"
                res_b = host_render_bundle(
                    input_path=str(story_file),
                    output_dir=str(bundle_out),
                    workspace_root=self.workspace,
                )
                self.assertFalse(res_b["ok"], f"Expected render_bundle refusal for locator {loc_str!r}")
                self.assertEqual(res_b["error"]["code"], "policy_refusal")
                self.assertFalse(bundle_out.exists(), f"Output dir must not be created for {loc_str!r}")
                self.assertIsNone(gate.get_last_receipt())

                # 2. host_render_artifact (both input_path and input_data) must refuse before creating output_dir
                triple_out1 = self.workspace / "artifacts" / f"sens-triple-file-{idx}"
                res_t1 = host_render_artifact(
                    output_dir=str(triple_out1),
                    input_path=str(story_file),
                    workspace_root=self.workspace,
                )
                self.assertFalse(res_t1["ok"], f"Expected render_artifact refusal for locator {loc_str!r}")
                self.assertEqual(res_t1["error"]["code"], "policy_refusal")
                self.assertFalse(triple_out1.exists())
                self.assertIsNone(gate.get_last_receipt())

                triple_out2 = self.workspace / "artifacts" / f"sens-triple-data-{idx}"
                res_t2 = host_render_artifact(
                    output_dir=str(triple_out2),
                    input_data=story_dict,
                    workspace_root=self.workspace,
                )
                self.assertFalse(res_t2["ok"], f"Expected render_artifact data refusal for locator {loc_str!r}")
                self.assertEqual(res_t2["error"]["code"], "policy_refusal")
                self.assertFalse(triple_out2.exists())
                self.assertIsNone(gate.get_last_receipt())

                # 3. host_prepare_story_media must refuse before reading sensitive locator or creating output_dir
                media_out = self.workspace / "artifacts" / f"sens-media-{idx}"
                res_m = host_prepare_story_media(
                    input_path=str(story_file),
                    output_dir=str(media_out),
                    audio_dir=str(audio_dir),
                    workspace_root=self.workspace,
                )
                self.assertFalse(res_m["ok"], f"Expected prepare_story_media refusal for locator {loc_str!r}")
                self.assertEqual(res_m["error"]["code"], "policy_refusal")
                self.assertFalse(media_out.exists())
                self.assertIsNone(gate.get_last_receipt())

                # 4. Direct _resolve_host_read_path refusal via shared check_sensitive_read_path
                with self.assertRaises(policy_runtime.PolicyError) as ctx_direct:
                    mcp_ops._resolve_host_read_path(fake_path, self.workspace, "sensitive_origin")
                self.assertEqual(ctx_direct.exception.code, "policy_refusal")

        self.assertEqual(read_sensitive_hits, [], f"Sensitive files must never be read: {read_sensitive_hits}")


if __name__ == "__main__":
    unittest.main()
