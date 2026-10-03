"""Quickstart safety and orchestration; installation is always mocked."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import quickstart


ROOT = Path(__file__).resolve().parents[1]


class QuickstartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ste quickstart ")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.environment = self.workspace / quickstart.ENV_NAME
        self.python = quickstart.env_python(self.environment)
        self.cwd = patch("quickstart.Path.cwd", return_value=self.workspace)
        self.cwd.start()
        self.addCleanup(self.cwd.stop)

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()) as out, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            code = quickstart.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def owned_environment(self):
        self.python.parent.mkdir(parents=True)
        self.python.write_bytes(b"test interpreter placeholder")
        (self.environment / "pyvenv.cfg").write_text(
            "include-system-site-packages = false\n", encoding="utf-8")
        (self.environment / quickstart.MARKER_NAME).write_text(quickstart.MARKER, encoding="utf-8")

    def snapshot(self):
        return {str(p.relative_to(self.workspace)): p.read_bytes()
                for p in self.workspace.rglob("*") if p.is_file()}

    def test_ready_current_interpreter_skips_install_and_env(self):
        with patch("quickstart.current_ready", return_value=True), \
             patch("quickstart.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            code, out, err = self.invoke("--no-install")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertIn("Ready.", err)
        self.assertFalse(self.environment.exists())
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], [sys.executable, "-I", "-B", str(ROOT), "start"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.workspace)
        self.assertIs(run.call_args.kwargs["shell"], False)
        self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_nonready_no_install_is_actionable_and_nonmutating(self):
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run") as run:
            code, out, err = self.invoke("--no-install", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("without --no-install", err)
        self.assertIn("Nothing was installed", err)
        self.assertFalse(self.environment.exists())
        run.assert_not_called()

    def test_valid_owned_environment_reused_without_writes_or_pip(self):
        self.owned_environment()
        before = self.snapshot()
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            code, _, err = self.invoke("--no-install", "--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][:4], [str(self.python), "-I", "-B", "-c"])
        self.assertEqual(run.call_args_list[1].args[0],
                         [str(self.python), "-I", "-B", str(ROOT), "start", "--json"])
        self.assertTrue(all("pip" not in call.args[0] for call in run.call_args_list))
        self.assertTrue(all(call.kwargs["timeout"] > 0 for call in run.call_args_list))

    def test_unowned_environment_refused_even_if_it_looks_ready(self):
        self.environment.mkdir()
        sentinel = self.environment / "user-file"
        sentinel.write_bytes(b"leave untouched")
        before = self.snapshot()
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run") as run:
            code, out, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("unowned", err)
        self.assertEqual(self.snapshot(), before)
        run.assert_not_called()

    def test_owned_but_broken_environment_is_not_repaired(self):
        self.owned_environment()
        before = self.snapshot()
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run", return_value=SimpleNamespace(returncode=1)) as run:
            code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn("not ready", err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(run.call_count, 1)

    def test_owned_environment_with_missing_interpreter_is_actionable(self):
        self.owned_environment()
        self.python.unlink()
        before = self.snapshot()
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run") as run:
            code, _, err = self.invoke("--no-install")
        self.assertEqual(code, 2)
        self.assertIn("different clean workspace", err)
        self.assertEqual(self.snapshot(), before)
        run.assert_not_called()

    def test_environment_exposing_global_packages_is_refused(self):
        self.owned_environment()
        (self.environment / "pyvenv.cfg").write_text("include-system-site-packages = true\n")
        before = self.snapshot()
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run") as run:
            code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn("not ready", err)
        self.assertEqual(self.snapshot(), before)
        run.assert_not_called()

    def test_version_bounds_match_declared_package_constraints(self):
        declared = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
        for _, distribution, minimum, major in quickstart.REQUIREMENTS:
            version = ".".join(map(str, minimum))
            self.assertIn(f"{distribution.lower()}>={version},<{major}", declared)

    def test_dependency_check_imports_both_at_compatible_versions(self):
        for versions in (["3.1.6", "6.0.3"], ["3.2", "6.1.0"]):
            with self.subTest(versions=versions), \
                 patch("quickstart.metadata.version", side_effect=versions), \
                 patch("quickstart.importlib.import_module") as load:
                self.assertTrue(quickstart.dependencies_ready())
                self.assertEqual([call.args[0] for call in load.call_args_list], ["jinja2", "yaml"])

    def test_dependency_check_rejects_old_major_future_major_and_prerelease(self):
        for versions in (["3.1.5"], ["4.0.0"], ["3.1.6rc1"], ["3.1.6", "6.0.2"],
                         ["3.1.6", "7.0.0"], ["3.1.6", "not a version"]):
            with self.subTest(versions=versions), \
                 patch("quickstart.metadata.version", side_effect=versions), \
                 patch("quickstart.importlib.import_module"):
                self.assertFalse(quickstart.dependencies_ready())

    def test_dependency_check_requires_successful_import_and_restores_bytecode_flag(self):
        previous = sys.dont_write_bytecode
        with patch("quickstart.metadata.version", return_value="3.1.6"), \
             patch("quickstart.importlib.import_module", side_effect=ImportError("broken")):
            self.assertFalse(quickstart.dependencies_ready())
        self.assertEqual(sys.dont_write_bytecode, previous)
        with patch("quickstart.metadata.version", side_effect=quickstart.metadata.PackageNotFoundError):
            self.assertFalse(quickstart.dependencies_ready())

    def test_paths_with_spaces_and_metacharacters_are_single_argv_items(self):
        source = self.workspace / "notes & report.md"
        source.write_text("# Notes\n")
        output = self.workspace / "output with spaces & x"
        with patch("quickstart.current_ready", return_value=True), \
             patch("quickstart.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            code, _, err = self.invoke(str(source), "--open", "--json", "--output-dir", str(output))
        self.assertEqual(code, 0, err)
        self.assertEqual(run.call_args.args[0], [
            sys.executable, "-I", "-B", str(ROOT), "start", str(source), "--open", "--json",
            "--output-dir", str(output),
        ])
        self.assertIs(run.call_args.kwargs["shell"], False)

    def test_no_open_overrides_open_in_either_order(self):
        for flags in (["--open", "--no-open"], ["--no-open", "--open"]):
            with self.subTest(flags=flags), \
                 patch("quickstart.current_ready", return_value=True), \
                 patch("quickstart.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
                self.assertEqual(self.invoke(*flags)[0], 0)
                self.assertNotIn("--open", run.call_args.args[0])

    def test_option_shaped_source_cannot_enable_browser_open(self):
        source = self.workspace / "--open"
        source.write_text("# Not a browser flag")
        with patch("quickstart.current_ready", return_value=True), \
             patch("quickstart.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run:
            code, _, err = self.invoke("--", "--open")
        self.assertEqual(code, 2, err)
        run.assert_not_called()

    def test_explicit_blank_arguments_fail_before_runtime_or_install(self):
        for value in ("", " ", "\t\n"):
            for args in ([value], ["--output-dir", value]):
                with self.subTest(args=args), patch("quickstart.runtime") as runtime, \
                     patch("quickstart.subprocess.run") as run:
                    code, out, err = self.invoke(*args)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertIn("must not be blank", err)
                self.assertFalse(self.environment.exists())
                runtime.assert_not_called()
                run.assert_not_called()

    def test_invalid_source_fails_before_runtime_or_install(self):
        cases = [("raw.html", "<h1>untrusted</h1>"), ("notes.txt", "text"), ("empty.md", "  \n"),
                 ("invalid.json", "{bad"), ("array.json", "[]"), ("number.json", '{"title":42}'),
                 ("raw.json", '{"body_html":"<b>untrusted</b>"}'),
                 ("story.json", '{"kind":"story"}'), ("chart.json", '{"kind":"chart"}'),
                 ("diagram.json", '{"kind":"diagram"}'),
                 ("section.json", '{"sections":[{"kind":"not-a-section"}]}'),
                 ("nested.json", '{"sections":[{"kind":"sec","body":[{"kind":"not-a-section"}]}]}'),
                 ("row.json", '{"rows":[{"one":1},{"two":2}]}'),
                 ("duplicate.json", '{"title":"one","title":"two"}'),
                 ("nan.json", '{"value":NaN}')]
        for name, content in cases:
            source = self.workspace / name
            source.write_text(content)
            with self.subTest(name=name), patch("quickstart.runtime") as runtime, \
                 patch("quickstart.subprocess.run") as run:
                code, out, err = self.invoke(str(source))
            self.assertEqual(code, 2, err)
            self.assertEqual(out, "")
            self.assertFalse(self.environment.exists())
            runtime.assert_not_called()
            run.assert_not_called()

    def test_json_stdout_is_pristine_and_native_exit_is_preserved(self):
        payload = '{"status":"native-result"}\n'
        for status in (0, 1, 17):
            def native(*args, **kwargs):
                print(payload, end="")
                return SimpleNamespace(returncode=status)
            with self.subTest(status=status), patch("quickstart.current_ready", return_value=True), \
                 patch("quickstart.subprocess.run", side_effect=native):
                code, out, err = self.invoke("--json")
            self.assertEqual(code, status)
            self.assertEqual(out, payload)
            self.assertEqual(err, "")

    def test_traversal_missing_source_and_output_collisions_fail_before_setup(self):
        source = self.workspace / "source.md"
        source.write_text("# Source")
        existing = self.workspace / "existing"
        existing.mkdir()
        cases = [
            ["../outside.md"], [str(self.workspace / "missing.md")],
            ["--output-dir", str(self.workspace / "nested" / ".." / "escape")],
            ["--output-dir", str(source)], ["--output-dir", str(source / "child")],
            ["--output-dir", str(existing)], ["--output-dir", str(self.environment / "output")],
        ]
        before = self.snapshot()
        for args in cases:
            with self.subTest(args=args), patch("quickstart.subprocess.run") as run:
                code, out, err = self.invoke(*args)
                self.assertEqual(code, 2, err)
                self.assertEqual(out, "")
                run.assert_not_called()
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.environment.exists())

    def test_environment_file_collision_is_nonmutating(self):
        self.environment.write_bytes(b"user file")
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run") as run:
            code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn("collision", err)
        self.assertEqual(self.environment.read_bytes(), b"user file")
        run.assert_not_called()

    def test_simulated_reparse_and_symlink_ancestors_are_refused(self):
        original = Path.lstat
        for mode, attributes in ((stat.S_IFDIR, 0x400), (stat.S_IFLNK, 0)):
            for target in (self.workspace, ROOT, ROOT / "ste_promax", self.environment):
                def redirected(path, *args, **kwargs):
                    if path == target:
                        return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                    return original(path, *args, **kwargs)
                with self.subTest(mode=mode, target=target), \
                     patch.object(Path, "lstat", redirected), \
                     patch("quickstart.current_ready", return_value=False), \
                     patch("quickstart.subprocess.run") as run:
                    code, _, err = self.invoke()
                    self.assertEqual(code, 2, err)
                    self.assertIn("reparse", err)
                    run.assert_not_called()

    def test_bundle_file_and_bytecode_directory_reparse_points_are_refused(self):
        original = Path.lstat
        for target in (ROOT / "pyproject.toml", ROOT / "ste_promax" / "cli.py",
                       ROOT / "ste_promax" / "__pycache__"):
            if not target.exists():
                continue
            def redirected(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == target:
                    return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
                return info
            with self.subTest(target=target), patch.object(Path, "lstat", redirected), \
                 patch("quickstart.subprocess.run") as run:
                code, _, err = self.invoke("--no-install")
            self.assertEqual(code, 2)
            self.assertIn("reparse", err)
            run.assert_not_called()

    def test_real_symlink_source_is_refused_where_supported(self):
        source = self.workspace / "source.md"
        source.write_text("# source")
        link = self.workspace / "linked.md"
        try:
            link.symlink_to(source)
        except OSError:
            self.skipTest("Symlink creation not available to this account")
        with patch("quickstart.subprocess.run") as run:
            code, _, err = self.invoke(str(link))
        self.assertEqual(code, 2)
        self.assertIn("Symbolic links", err)
        run.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32", "Windows path syntax")
    def test_drive_relative_paths_refused(self):
        with self.assertRaisesRegex(ValueError, "drive-relative"):
            quickstart.safe_path(Path("C:relative"))

    def test_exclusive_creation_refuses_concurrent_directory(self):
        original = Path.mkdir
        def raced(path, *args, **kwargs):
            if path == self.environment:
                original(path)
                (path / "other-owner").write_bytes(b"preserve")
            return original(path, *args, **kwargs)
        with patch("quickstart.current_ready", return_value=False), \
             patch.object(Path, "mkdir", raced), patch("quickstart.subprocess.run") as run:
            code, _, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual((self.environment / "other-owner").read_bytes(), b"preserve")
        run.assert_not_called()

    def fake_setup(self, pip_exit=0, venv_exit=0):
        def run(command, **kwargs):
            self.assertIs(kwargs["shell"], False)
            self.assertEqual(kwargs["cwd"], self.workspace)
            self.assertGreater(kwargs["timeout"], 0)
            if "venv" in command:
                self.assertIn("--copies", command)
                self.python.parent.mkdir(parents=True)
                self.python.write_bytes(b"private interpreter")
                (self.environment / "pyvenv.cfg").write_text("include-system-site-packages = false\n")
                return SimpleNamespace(returncode=venv_exit, stdout="venv diagnostic\n")
            if "pip" in command:
                self.assertEqual(command[0], str(self.python))
                for flag in ("-I", "--isolated", "--require-virtualenv", "--no-cache-dir", "--no-input"):
                    self.assertIn(flag, command)
                self.assertIn("--only-binary=:all:", command)
                self.assertEqual(command[-2:], ["Jinja2>=3.1.6,<4", "PyYAML>=6.0.3,<7"])
                self.assertFalse((self.environment / "bundle-source").exists())
                return SimpleNamespace(returncode=pip_exit, stdout="pip diagnostic\n")
            self.assertEqual(command[0], str(self.python))
            return SimpleNamespace(returncode=0)
        return run

    def test_setup_ignores_global_pip_config_and_target_without_changing_host_env(self):
        with patch.dict(os.environ, {"PIP_TARGET": "must-not-write", "PIP_CONFIG_FILE": "host-config"}), \
             patch("quickstart.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="")) as run:
            quickstart.setup_command(["python", "-m", "pip"], self.workspace, 10)
            child = run.call_args.kwargs["env"]
            self.assertNotIn("PIP_TARGET", child)
            self.assertEqual(child["PIP_CONFIG_FILE"], os.devnull)
            self.assertEqual(os.environ["PIP_TARGET"], "must-not-write")
            self.assertEqual(os.environ["PIP_CONFIG_FILE"], "host-config")

    def test_install_is_runtime_only_then_uses_exact_venv_runtime(self):
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.env_ready", side_effect=[False, True]), \
             patch("quickstart.subprocess.run", side_effect=self.fake_setup()) as run:
            code, out, err = self.invoke("--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "")
        self.assertIn("pip diagnostic", err)
        self.assertEqual((self.environment / quickstart.MARKER_NAME).read_text(), quickstart.MARKER)
        self.assertEqual(len(run.call_args_list), 3)
        self.assertEqual(run.call_args.args[0], [str(self.python), "-I", "-B", str(ROOT), "start", "--json"])

    def test_fresh_ready_venv_needs_no_pip(self):
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.env_ready", return_value=True), \
             patch("quickstart.subprocess.run", side_effect=self.fake_setup()) as run:
            code, _, err = self.invoke()
        self.assertEqual(code, 0, err)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all("pip" not in call.args[0] for call in run.call_args_list))

    def test_venv_and_pip_failures_preserve_partial_environment(self):
        for venv_exit, pip_exit in ((7, 0), (0, 8)):
            with tempfile.TemporaryDirectory(dir=self.workspace) as directory:
                workspace = Path(directory)
                old_environment, old_python, old_workspace = self.environment, self.python, self.workspace
                self.workspace = workspace
                self.environment = workspace / quickstart.ENV_NAME
                self.python = quickstart.env_python(self.environment)
                try:
                    with self.subTest(venv_exit=venv_exit), \
                         patch("quickstart.Path.cwd", return_value=workspace), \
                         patch("quickstart.current_ready", return_value=False), \
                         patch("quickstart.env_ready", return_value=False), \
                         patch("quickstart.subprocess.run",
                               side_effect=self.fake_setup(pip_exit=pip_exit, venv_exit=venv_exit)):
                        code, out, err = self.invoke("--json")
                    self.assertEqual(code, 2)
                    self.assertEqual(out, "")
                    self.assertIn("Partial environment preserved", err)
                    self.assertIn(f"exit {venv_exit or pip_exit}", err)
                    self.assertTrue(self.python.exists())
                    self.assertFalse((self.environment / quickstart.MARKER_NAME).exists())
                finally:
                    self.environment, self.python, self.workspace = old_environment, old_python, old_workspace

    def test_post_install_probe_failure_is_not_marked_owned(self):
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.env_ready", return_value=False), \
             patch("quickstart.subprocess.run", side_effect=self.fake_setup()):
            code, _, err = self.invoke()
        self.assertEqual(code, 2)
        self.assertIn("still cannot import", err)
        self.assertFalse((self.environment / quickstart.MARKER_NAME).exists())

    def test_setup_timeout_preserves_partial_state(self):
        with patch("quickstart.current_ready", return_value=False), \
             patch("quickstart.subprocess.run", side_effect=subprocess.TimeoutExpired(["venv"], 120)):
            code, out, err = self.invoke("--json")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("Partial environment preserved", err)
        self.assertTrue(self.environment.is_dir())

    def test_native_timeout_is_bounded_failure(self):
        with patch("quickstart.current_ready", return_value=True), \
             patch("quickstart.subprocess.run", side_effect=subprocess.TimeoutExpired(["start"], 120)):
            code, out, err = self.invoke("--json")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("timed out", err)
        self.assertFalse(self.environment.exists())

    def test_real_current_environment_from_unrelated_workspace(self):
        if not quickstart.dependencies_ready():
            self.skipTest("Current interpreter lacks declared render dependencies")
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "quickstart.py"), "--no-install", "--no-open", "--json"],
            cwd=self.workspace, capture_output=True, text=True, check=False, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "complete")
        html = Path(report["files"]["html"]["path"])
        self.assertTrue(html.is_relative_to(self.workspace / "artifacts"))
        for name in ("html", "gallery", "source", "input"):
            self.assertTrue(Path(report["files"][name]["path"]).is_file())
        self.assertFalse(self.environment.exists())
        self.assertEqual(result.stderr, "")

    def test_real_isolated_probe_and_start_ignore_pythonpath_shadow_packages(self):
        if not quickstart.dependencies_ready():
            self.skipTest("Current interpreter lacks declared render dependencies")
        shadow = self.workspace / "shadow"
        shadow.mkdir()
        for name in ("jinja2.py", "yaml.py", "ste_promax.py"):
            (shadow / name).write_text("print('SHADOW STDOUT'); raise RuntimeError('shadow imported')\n")
        source = self.workspace / "source.md"
        source.write_text("# Genuine input\n\nNo hidden provider calls.\n")
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "quickstart.py"), str(source),
             "--no-install", "--no-open", "--json"],
            cwd=self.workspace, capture_output=True, text=True, check=False, timeout=120,
            env={**os.environ, "PYTHONPATH": str(shadow)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "complete")
        self.assertNotIn("SHADOW", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertFalse(self.environment.exists())


if __name__ == "__main__":
    unittest.main()
