"""Focused unittest suite for automatic STE-Pro-Max + SkillC rendering and export."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ste_promax import cli, gate
from ste_promax.policy_runtime import (
    ERROR_POSTCONDITION_FAILURE,
    PolicyBackendError,
    PolicyError,
    has_inprocess_skillc,
    load_runtime_config,
    resolve_worker_backend,
)
from ste_promax.stories import STORY_SCHEMA

ROOT = Path(__file__).resolve().parents[1]


def _skillc_backend_configured() -> bool:
    """True when automatic policy API is present and SkillC backend is available/configured."""
    if not hasattr(gate, "run_guarded_operation") or not hasattr(gate, "export_bundle"):
        return False
    if has_inprocess_skillc():
        return True
    if os.environ.get("STE_SKILLC_PYTHON", "").strip() or os.environ.get("STE_SKILLC_ROOT", "").strip():
        return True
    try:
        return load_runtime_config() is not None
    except PolicyError:
        return True


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _passthrough_guard(op, inputs, effect_fn, *, validate_result=None):
    result = effect_fn()
    if validate_result is not None:
        validate_result(result)
    return result


class GateAlwaysRunBoundaryTests(unittest.TestCase):
    """Always-run boundary and wiring checks that do not require an installed SkillC runtime."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.md_source = self.root / "note.md"
        self.md_bytes = b"# Boundary Check\r\n\r\nKeep local checks fast.\r\n"
        self.md_source.write_bytes(self.md_bytes)

        self.evidence_dir = self.root / "sources"
        self.evidence_dir.mkdir()
        self.evidence_file = self.evidence_dir / "observation-log.json"
        self.evidence_payload = {
            "id": "obs-log",
            "title": "Local observation log",
            "scope": "Single local workstation run; not multi-host certification.",
            "qualification": "Manual semantic review remains required before relying on findings.",
        }
        self.evidence_file.write_text(json.dumps(self.evidence_payload, indent=2) + "\n", encoding="utf-8")

        self.story_source = self.root / "evidence-story.json"
        self.story_data = copy.deepcopy(STORY_SCHEMA["example"])
        self.story_data["sources"] = [
            {
                "id": "notes",
                "title": "Local observation log",
                "locator": "sources/observation-log.json",
                "note": "Primary local evidence file bound under evidence root.",
            }
        ]
        self.story_source.write_text(
            json.dumps(self.story_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_cli(self, *args: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_manual_stage_approve_and_legacy_export_flags_are_removed(self):
        out_dir = self.root / "out"
        exp_dir = self.root / "export"
        fp = "a" * 64
        removed_invocations = (
            ["stage", str(self.md_source), "--output-dir", str(out_dir), "--export-dir", str(exp_dir)],
            ["approve", "--stage-dir", str(out_dir), "--fingerprint", fp, "--export-dir", str(exp_dir)],
            ["export", "--stage-dir", str(out_dir), "--export-dir", str(exp_dir)],
            ["export", "--input-dir", str(out_dir), "--output-dir", str(exp_dir), "--fingerprint", fp],
            ["export", "--input-dir", str(out_dir), "--output-dir", str(exp_dir), "--yes"],
            ["export", "--input-dir", str(out_dir), "--output-dir", str(exp_dir), "--approved"],
            ["export", "--input-dir", str(out_dir), "--output-dir", str(exp_dir), "--approver", "user"],
            ["export", "--input-dir", str(out_dir), "--output-dir", str(exp_dir), "--approval-file", "tok.json"],
        )
        for argv in removed_invocations:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    cli.main(argv)
                self.assertEqual(raised.exception.code, 2)
        self.assertFalse(out_dir.exists())
        self.assertFalse(exp_dir.exists())

    def test_non_boolean_trusted_html_and_evidence_preflight_rejected_before_controller(self):
        out_dir = self.root / "out-invalid"
        for bad_trusted in ("false", 1, None):
            with self.subTest(bad_trusted=bad_trusted):
                with self.assertRaisesRegex(ValueError, "trusted_html must be a boolean"):
                    cli.normalized_input(self.md_source, trusted_html=bad_trusted)  # type: ignore[arg-type]

        with patch("ste_promax.gate.run_guarded_operation", side_effect=AssertionError("Must not enter controller"), create=True):
            # Absent --evidence file
            code, _, err = self.run_cli(
                "render",
                str(self.md_source),
                "--output-dir",
                str(out_dir),
                "--evidence",
                str(self.root / "missing-evidence.json"),
            )
            self.assertEqual(code, 2)
            self.assertIn("does not exist", err)
            self.assertFalse(out_dir.exists())

            # Duplicate --evidence file
            code, _, err = self.run_cli(
                "render",
                str(self.md_source),
                "--output-dir",
                str(out_dir),
                "--evidence",
                str(self.evidence_file),
                "--evidence",
                str(self.evidence_file),
            )
            self.assertEqual(code, 2)
            self.assertIn("Duplicate evidence dependency", err)
            self.assertFalse(out_dir.exists())

            # Ambiguous --evidence basenames
            other_root = self.root / "other-root"
            (other_root / "a").mkdir(parents=True)
            (other_root / "b").mkdir(parents=True)
            ev_a = other_root / "a" / "shared.json"
            ev_b = other_root / "b" / "shared.json"
            ev_a.write_text('{"part": "a"}\n', encoding="utf-8")
            ev_b.write_text('{"part": "b"}\n', encoding="utf-8")
            code, _, err = self.run_cli(
                "render",
                str(self.md_source),
                "--output-dir",
                str(out_dir),
                "--evidence",
                str(ev_a),
                "--evidence",
                str(ev_b),
            )
            self.assertEqual(code, 2)
            self.assertIn("Duplicate or ambiguous evidence basename", err)
            self.assertFalse(out_dir.exists())

            # Invalid story locators
            for bad_locator in (
                "../outside.json",
                "/abs/outside.json",
                "https://example.org/remote.json",
                "sources\\observation-log.json",
                "sources/does-not-exist.json",
            ):
                with self.subTest(bad_locator=bad_locator):
                    bad_story = copy.deepcopy(self.story_data)
                    bad_story["sources"][0]["locator"] = bad_locator
                    bad_story_path = self.root / "bad-story.json"
                    bad_story_path.write_text(json.dumps(bad_story), encoding="utf-8")
                    code, _, err = self.run_cli(
                        "render",
                        str(bad_story_path),
                        "--output-dir",
                        str(out_dir),
                        "--evidence-root",
                        str(self.root),
                    )
                    self.assertEqual(code, 2)
                    self.assertFalse(out_dir.exists())

            # Reparse point on evidence file
            original_lstat = Path.lstat

            def fake_reparse_lstat(path_obj: Path):
                info = original_lstat(path_obj)
                if path_obj == self.evidence_file:
                    return SimpleNamespace(
                        st_mode=info.st_mode,
                        st_size=info.st_size,
                        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
                    )
                return info

            with patch.object(Path, "lstat", fake_reparse_lstat):
                code, _, err = self.run_cli(
                    "render",
                    str(self.md_source),
                    "--output-dir",
                    str(out_dir),
                    "--evidence",
                    str(self.evidence_file),
                )
            self.assertEqual(code, 2)
            self.assertIn("reparse", err)
            self.assertFalse(out_dir.exists())

    def test_bundled_catalog_examples_and_contract_inputs_wired_before_filesystem_effects(self):
        calls = []

        def recording_guard(op, inputs, effect_fn, *, validate_result=None):
            if op == "ste.render_bundle":
                self.assertFalse(Path(inputs["output_root"]).exists())
            result = effect_fn()
            obs = validate_result(result) if validate_result is not None else None
            calls.append((op, inputs, obs))
            return result

        suite_story = ROOT / "examples" / "suite" / "retry-explanation.json"
        out_dir = self.root / "suite-rendered"
        with patch("ste_promax.gate.run_guarded_operation", side_effect=recording_guard, create=True):
            code, out, err = self.run_cli("render", str(suite_story), "--output-dir", str(out_dir))
        self.assertEqual(code, 0, err)
        manifest = json.loads(out)
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual([c[0] for c in calls], ["ste.render_artifact", "ste.regenerate_gallery", "ste.render_bundle"])
        bundle_inputs = calls[-1][1]
        bundle_obs = calls[-1][2]
        expected_keys = {
            "caller_kind",
            "workspace_root",
            "output_root",
            "target_paths",
            "source_paths",
            "source_digest",
            "source_kind",
            "trusted_html",
            "evidence_root",
            "evidence_paths",
            "evidence_locators",
            "availability",
            "proposed_contents",
            "expected_before",
        }
        self.assertEqual(set(bundle_inputs.keys()), expected_keys)
        self.assertEqual(bundle_inputs["caller_kind"], "native")
        self.assertEqual(bundle_inputs["source_kind"], "story")
        self.assertEqual(bundle_inputs["evidence_root"], str(ROOT.resolve()))
        self.assertEqual(bundle_inputs["evidence_locators"], ["examples/suite/sources/retry-trace.json"])
        self.assertEqual(
            bundle_inputs["evidence_paths"],
            [str((ROOT / "examples" / "suite" / "sources" / "retry-trace.json").resolve())],
        )
        self.assertFalse((out_dir / "index.html").exists())
        self.assertIn(str((out_dir / "manifest.json").resolve()), bundle_obs["outputs"])
        for rec in manifest["files"].values():
            p = str(Path(rec["path"]).resolve())
            self.assertIn(p, bundle_obs["outputs"])
            self.assertEqual(bundle_obs["outputs"][p]["sha256"], rec["sha256"])

    def test_validate_result_rejects_source_or_evidence_drift_and_false_success(self):
        # 1. Source mutation during render is rejected by validate_result
        race_out = self.root / "race-source"

        def mutating_source_guard(op, inputs, effect_fn, *, validate_result=None):
            result = effect_fn()
            if op == "ste.render_bundle":
                self.md_source.write_bytes(self.md_bytes + b"\nMutated during render.\r\n")
            if validate_result is not None:
                validate_result(result)
            return result

        try:
            with patch("ste_promax.gate.run_guarded_operation", side_effect=mutating_source_guard, create=True):
                code, out, err = self.run_cli(
                    "render",
                    str(self.md_source),
                    "--output-dir",
                    str(race_out),
                    "--evidence",
                    str(self.evidence_file),
                )
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertIn("Original source file changed", err)
        finally:
            self.md_source.write_bytes(self.md_bytes)

        # 2. Evidence mutation during render is rejected by validate_result
        race_ev_out = self.root / "race-ev"
        original_ev = self.evidence_file.read_bytes()

        def mutating_ev_guard(op, inputs, effect_fn, *, validate_result=None):
            result = effect_fn()
            if op == "ste.render_bundle":
                self.evidence_file.write_bytes(original_ev + b"\n")
            if validate_result is not None:
                validate_result(result)
            return result

        try:
            with patch("ste_promax.gate.run_guarded_operation", side_effect=mutating_ev_guard, create=True):
                code, out, err = self.run_cli(
                    "render",
                    str(self.story_source),
                    "--output-dir",
                    str(race_ev_out),
                    "--evidence-root",
                    str(self.root),
                )
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertIn("Evidence source file changed", err)
        finally:
            self.evidence_file.write_bytes(original_ev)

        # 3. Renderer failure triggers PolicyError(code=ERROR_POSTCONDITION_FAILURE) in validate_result
        # while still returning the truthful failed manifest to CLI callers.
        fail_out = self.root / "fail-render"
        observed_post_errors = []

        def catching_guard(op, inputs, effect_fn, *, validate_result=None):
            result = effect_fn()
            if validate_result is not None:
                try:
                    validate_result(result)
                except PolicyError as exc:
                    observed_post_errors.append((op, exc.code))
                    raise
            return result

        with patch("ste_promax.gate.run_guarded_operation", side_effect=catching_guard, create=True), \
             patch("ste_promax.render.render_artifact", side_effect=RuntimeError("boom")):
            code, out, _ = self.run_cli("render", str(self.md_source), "--output-dir", str(fail_out))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["status"], "failed")
        self.assertEqual(observed_post_errors, [("ste.render_bundle", ERROR_POSTCONDITION_FAILURE)])

    def test_non_effectful_commands_usable_without_backend_while_writes_fail_closed(self):
        out_dir = self.root / "blocked-out"
        with patch(
            "ste_promax.gate.run_guarded_operation",
            side_effect=PolicyBackendError("SkillC backend is unavailable"),
            create=True,
        ), patch(
            "ste_promax.gate.export_bundle",
            side_effect=PolicyBackendError("SkillC backend is unavailable"),
            create=True,
        ):
            for cmd in (
                ["render", str(self.md_source), "--output-dir", str(out_dir)],
                ["start", str(self.md_source), "--output-dir", str(out_dir)],
                ["export", "--input-dir", str(self.root), "--output-dir", str(out_dir)],
            ):
                with self.subTest(cmd=cmd[0]):
                    code, _, err = self.run_cli(*cmd)
                    self.assertEqual(code, 2)
                    self.assertIn("SkillC backend is unavailable", err)
                    self.assertFalse(out_dir.exists())

            from ste_promax.gallery import regenerate_gallery
            from ste_promax.render import render_artifact

            with self.assertRaises(PolicyBackendError):
                render_artifact({"title": "Blocked", "body_md": "# Blocked"}, output_dir=out_dir)
            self.assertFalse(out_dir.exists())

            with self.assertRaises(PolicyBackendError):
                regenerate_gallery(out_dir)
            self.assertFalse(out_dir.exists())

            # Non-effectful commands remain usable without backend
            check_code, check_out, check_err = self.run_cli("check", str(self.md_source), "--json")
            self.assertEqual(check_code, 0, check_err)
            self.assertIn("word_count", json.loads(check_out))

            schema_code, schema_out, schema_err = self.run_cli("schema", "story")
            self.assertEqual(schema_code, 0, schema_err)
            self.assertIn("fields", json.loads(schema_out))

            doc_code, doc_out, doc_err = self.run_cli("doctor", "--json")
            self.assertIn(doc_code, (0, 2), doc_err)
            self.assertIn("required_render", json.loads(doc_out))

            help_code, help_out, _ = self.run_cli()
            self.assertEqual(help_code, 0)
            self.assertIn("First result: start", help_out)

    def test_trusted_env_symlink_resolution_in_policy_runtime(self):
        real_py = self.root / "real-python.bin"
        real_py.write_bytes(b"#!/bin/sh\n")
        fake_root = self.root / "skillc-root"
        (fake_root / "src" / "skillc").mkdir(parents=True)
        (fake_root / "src" / "skillc" / "__init__.py").write_text("__version__ = '0.3.0'\n", encoding="utf-8")
        linked_py = self.root / "venv-python"
        try:
            linked_py.symlink_to(real_py)
        except OSError:
            linked_py = real_py
        with patch.dict(
            os.environ,
            {"STE_SKILLC_PYTHON": str(linked_py), "STE_SKILLC_ROOT": str(fake_root)},
            clear=False,
        ):
            resolved_py, resolved_src = resolve_worker_backend()
            self.assertEqual(resolved_py, linked_py.absolute())
            self.assertEqual(resolved_src, (fake_root / "src").resolve())


@unittest.skipUnless(
    _skillc_backend_configured(),
    "Automatic SkillC backend is not yet configured (waiting on gate.run_guarded_operation / runtime.json).",
)
class GateCliWorkflowTests(unittest.TestCase):
    """End-to-end automatic SkillC controller workflow checks for render, start, gallery, and export."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

        self.md_source = self.root / "research-note.md"
        self.md_bytes = (
            b"# Local Automatic Policy Verification Note\r\n\r\n"
            b"Verify bundles automatically without human prompts. "
            b"Keep every qualification intact.\r\n"
        )
        self.md_source.write_bytes(self.md_bytes)

        self.evidence_dir = self.root / "sources"
        self.evidence_dir.mkdir()
        self.evidence_file = self.evidence_dir / "observation-log.json"
        self.evidence_payload = {
            "id": "obs-log",
            "title": "Local observation log",
            "scope": "Single local workstation run; not multi-host certification.",
            "qualification": "Manual semantic review remains required before relying on findings.",
        }
        self.evidence_file.write_text(
            json.dumps(self.evidence_payload, indent=2) + "\n",
            encoding="utf-8",
        )

        self.story_source = self.root / "evidence-story.json"
        self.story_data = copy.deepcopy(STORY_SCHEMA["example"])
        self.story_data["sources"] = [
            {
                "id": "notes",
                "title": "Local observation log",
                "locator": "sources/observation-log.json",
                "note": "Primary local evidence file bound under evidence root.",
            }
        ]
        self.story_source.write_text(
            json.dumps(self.story_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def run_cli(self, *args: str):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def test_automatic_render_and_start_produce_verified_bundles_and_receipts(self):
        md_out = self.root / "rendered-md"
        code, out, err = self.run_cli(
            "render",
            str(self.md_source),
            "--output-dir",
            str(md_out),
            "--evidence",
            str(self.evidence_file),
            "--title",
            "Automatic Markdown Brief",
        )
        self.assertEqual(code, 0, err + out)
        manifest = json.loads(out)
        self.assertEqual(manifest["status"], "complete")
        self.assertTrue(manifest["lint_passed"])
        self.assertFalse((md_out / ".skillc").exists())
        self.assertFalse((md_out / "index.html").exists())
        receipt = gate.get_last_receipt()
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt.get("verdict"), "ALLOW")
        self.assertEqual(receipt.get("authority_model"), "automatic-local-policy")

        story_out = self.root / "rendered-story"
        code, out, err = self.run_cli(
            "render",
            str(self.story_source),
            "--output-dir",
            str(story_out),
            "--evidence-root",
            str(self.root),
        )
        self.assertEqual(code, 0, err + out)
        story_manifest = json.loads(out)
        self.assertEqual(story_manifest["status"], "complete")
        self.assertTrue((story_out / "evidence.json").is_file())

        start_out = self.root / "started-story"
        code, out, err = self.run_cli(
            "start",
            str(self.story_source),
            "--output-dir",
            str(start_out),
            "--evidence-root",
            str(self.root),
            "--json",
        )
        self.assertEqual(code, 0, err + out)
        self.assertEqual(json.loads(out)["status"], "complete")

    def test_direct_render_artifact_and_regenerate_gallery_under_automatic_policy(self):
        from ste_promax.gallery import regenerate_gallery
        from ste_promax.render import render_artifact

        direct_out = self.root / "direct-triple"
        triple = render_artifact({"title": "Direct Triple", "body_md": "# Direct"}, output_dir=direct_out)
        self.assertEqual(set(triple), {"html_path", "design_path", "meta_path", "slug"})
        for key in ("html_path", "design_path", "meta_path"):
            self.assertTrue(Path(triple[key]).is_file())
        gallery = regenerate_gallery(direct_out)
        self.assertEqual(gallery, direct_out / "gallery.html")
        self.assertTrue(gallery.is_file())

    def test_automatic_export_verifies_and_copies_fresh_bundle_without_approval(self):
        bundle_dir = self.root / "fresh-bundle"
        export_dir = self.root / "exported-bundle"
        code, out, err = self.run_cli(
            "render",
            str(self.story_source),
            "--output-dir",
            str(bundle_dir),
            "--evidence-root",
            str(self.root),
        )
        self.assertEqual(code, 0, err + out)
        manifest = json.loads(out)
        self.assertTrue((bundle_dir / "evidence" / "observation-log.json").is_file())
        self.assertEqual(len(manifest.get("evidence_files", [])), 1)
        self.assertEqual(
            manifest["evidence_files"][0]["sha256"],
            _sha256_file(self.evidence_file),
        )

        code, exp_out, exp_err = self.run_cli(
            "export",
            "--input-dir",
            str(bundle_dir),
            "--output-dir",
            str(export_dir),
        )
        self.assertEqual(code, 0, exp_err + exp_out)
        for rec in manifest["files"].values():
            rel_name = Path(rec["path"]).name
            exported_file = export_dir / rel_name
            self.assertTrue(exported_file.is_file(), f"Missing exported file: {rel_name}")
            self.assertEqual(_sha256_file(exported_file), rec["sha256"])
        self.assertEqual(
            _sha256_file(export_dir / "evidence" / "observation-log.json"),
            _sha256_file(self.evidence_file),
        )

        # Reject legacy manual stage directory
        legacy_stage = self.root / "legacy-stage"
        (legacy_stage / ".skillc").mkdir(parents=True)
        (legacy_stage / ".skillc" / "stage.json").write_text('{"status": "pending_approval"}\n', encoding="utf-8")
        legacy_out = self.root / "legacy-export"
        code, _, legacy_err = self.run_cli(
            "export",
            "--input-dir",
            str(legacy_stage),
            "--output-dir",
            str(legacy_out),
        )
        self.assertEqual(code, 2)
        self.assertFalse(legacy_out.exists())


if __name__ == "__main__":
    unittest.main()
