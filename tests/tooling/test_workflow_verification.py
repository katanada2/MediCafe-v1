"""Stdlib-only static tooling tests: never import Django or run feature commands."""

import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = load_tool("select_verification")
runner = load_tool("run_modern_python")


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.catalog = selector.load_catalog(ROOT)

    def assert_invalid(self, change):
        change(self.catalog)
        with self.assertRaises(selector.CatalogError):
            selector.validate_catalog(self.catalog, ROOT)

    def test_real_catalog_links_concrete_calls_without_feature_execution(self):
        self.assertEqual(len(self.catalog["contracts"]), 6)
        f2 = self.catalog["contracts"][1]["feature_tests"][0]["helper_chain"]
        self.assertEqual(f2[-1]["symbol"], "assert_parse_boundary")
        self.assertEqual(self.catalog["contracts"][-1]["status"], "planned")
        self.assertEqual(self.catalog["contracts"][-1]["feature_tests"], [])

    def test_missing_schema_field_fails(self):
        self.assert_invalid(lambda c: c.pop("schema_version"))

    def test_unknown_top_level_field_fails(self):
        self.assert_invalid(lambda c: c.update(runtime_completed=True))

    def test_schema_boolean_or_new_version_fails(self):
        for version in (True, 2, "1"):
            with self.subTest(version=version):
                catalog = copy.deepcopy(self.catalog)
                catalog["schema_version"] = version
                with self.assertRaises(selector.CatalogError):
                    selector.validate_catalog(catalog, ROOT)

    def test_runtime_catalog_purpose_fails(self):
        self.assert_invalid(lambda c: c.update(purpose="runtime_evidence_registry"))

    def test_duplicate_contract_id_fails(self):
        self.assert_invalid(lambda c: c["contracts"].append(copy.deepcopy(c["contracts"][0])))

    def test_missing_boundary_meaning_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0].update(terminal_evidence=""))

    def test_invalid_list_or_contract_shape_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0].update(paths="src/*"))

    def test_unknown_contract_status_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0].update(status="complete"))

    def test_traversing_catalog_pattern_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0].update(paths=["../private/*"]))

    def test_unbounded_or_malformed_catalog_patterns_fail(self):
        for pattern in ("*", "src/*/other.py", "src/[abc", "src/?", "src/**"):
            with self.subTest(pattern=pattern):
                catalog = copy.deepcopy(self.catalog)
                catalog["contracts"][0]["paths"] = [pattern]
                with self.assertRaises(selector.CatalogError):
                    selector.validate_catalog(catalog, ROOT)

    def test_guidance_routes_must_be_exact_not_catch_all(self):
        self.assert_invalid(lambda c: c.update(governing_paths=["tools/*"]))

    def test_implemented_contract_without_concrete_tests_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0].update(feature_tests=[]))

    def test_planned_contract_cannot_claim_feature_tests(self):
        self.assert_invalid(lambda c: c["contracts"][-1].update(
            feature_tests=copy.deepcopy(c["contracts"][0]["feature_tests"])))

    def test_missing_concrete_test_file_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0]["feature_tests"][0].update(
            file="tests/f1/missing.py"))

    def test_missing_test_method_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0]["feature_tests"][0].update(
            test="ParseLifecycleTests.test_missing"))

    def test_test_that_does_not_call_helper_fails(self):
        self.assert_invalid(lambda c: c["contracts"][0]["feature_tests"][0].update(
            test="ParseLifecycleTests.test_newer_parser_failure_does_not_demote_older_success",
            helper_chain=[{"file": "tests/helpers/workflow_boundary_contract.py",
                           "symbol": "assert_archive_boundary"}]))

    def test_unrelated_helper_file_cannot_satisfy_link(self):
        self.assert_invalid(lambda c: c["contracts"][0]["feature_tests"][0].update(
            helper_chain=[{"file": "tests/helpers/f2_claim_boundary.py",
                           "symbol": "assert_parse_boundary"}]))

    def test_broken_transitive_helper_chain_fails(self):
        self.assert_invalid(lambda c: c["contracts"][1]["feature_tests"][0].update(
            helper_chain=c["contracts"][1]["feature_tests"][0]["helper_chain"][:1]))

    def test_duplicate_json_keys_fail(self):
        with self.assertRaises(selector.CatalogError):
            json.loads('{"status": "planned", "status": "implemented"}',
                       object_pairs_hook=selector.no_duplicates)

    def test_invalid_catalog_cli_fails_closed_json(self):
        with mock.patch.object(selector, "load_catalog", side_effect=selector.CatalogError("bad catalog")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(selector.main(["README.md", "--json"]), 2)
            result = json.loads(output.getvalue())
            self.assertTrue(result["boundary_scan_required"])
            self.assertEqual(result["status"], "review_required")


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = selector.load_catalog(ROOT)

    def select(self, *paths):
        return selector.select_paths(self.catalog, paths, ROOT)

    def test_docs_only_is_not_feature_execution(self):
        for path in ("docs/roadmap/TOOLING_IMPLEMENTATION_ADMISSION.md",
                     "tools/CODEX_SCAFFOLDING_COHERENCE_REVIEW.md"):
            with self.subTest(path=path):
                result = self.select(path)
                self.assertEqual(result["status"], "docs_only")
                self.assertTrue(result["governing_guidance_required"])
                self.assertEqual(result["commands"], [selector.TOOLING_COMMAND])
                self.assertIn("not_execution", result["evidence"])

    def test_ordinary_docs_only_has_explicit_empty_plan(self):
        result = self.select("README.md")
        self.assertEqual(result["status"], "docs_only")
        self.assertEqual(result["commands"], [])

    def test_tooling_code_is_not_labelled_docs_only(self):
        result = self.select("tools/select_verification.py")
        self.assertEqual(result["status"], "tooling")
        self.assertTrue(result["boundary_scan_required"])
        self.assertTrue(result["governing_guidance_required"])

    def test_governing_paths_all_select_coherence_lane(self):
        for path in self.catalog["governing_paths"]:
            with self.subTest(path=path):
                self.assertTrue(self.select(path)["governing_guidance_required"])

    def test_planned_o1_stays_planned_and_selects_no_feature_command(self):
        result = self.select("docs/roadmap/O1_OPERATOR_REVIEW_CARD.md")
        self.assertEqual(result["planned_contracts"], ["o1-operator-review"])
        self.assertEqual(result["feature_test_modules"], [])
        self.assertEqual(result["commands"], [])
        self.assertTrue(result["boundary_scan_required"])

    def test_deterministic_multicontract_selection_with_no_duplicate_suite(self):
        paths = ["src/medicafe_v1/claims/queries.py", "src/medicafe_v1/outcomes/queries.py"]
        result = self.select(*paths)
        self.assertEqual(result, self.select(*reversed(paths), paths[0]))
        self.assertEqual(result["feature_suites"], ["tests.f2", "tests.f3", "tests.f4"])
        self.assertEqual(len(result["commands"]), 1)

    def test_shared_code_selects_all_implemented_not_planned_contracts(self):
        result = self.select("src/medicafe_v1/settings.py")
        self.assertEqual(len(result["contracts"]), 5)
        self.assertEqual(result["planned_contracts"], [])
        self.assertEqual(result["feature_suites"], ["tests.f1", "tests.f2", "tests.f3", "tests.f4"])

    def test_cross_owner_archive_consumers_are_selected(self):
        for path in ("src/medicafe_v1/records/queries.py", "src/medicafe_v1/claims/queries.py",
                     "src/medicafe_v1/outcomes/queries.py"):
            with self.subTest(path=path):
                identifiers = {contract["id"] for contract in self.select(path)["contracts"]}
                self.assertIn("f4-archive", identifiers)

    def test_existing_f4_test_paths_all_route_without_invented_file_names(self):
        for file in sorted((ROOT / "tests/f4").glob("*.py")):
            with self.subTest(file=file.name):
                self.assertEqual(self.select(file.relative_to(ROOT).as_posix())["unknown_paths"], [])

    def test_unknown_code_fails_closed_without_guessing_lane(self):
        for path in ("src/medicafe_v1/new_owner.py", "tools/unknown.py", "tests/new_test.py"):
            with self.subTest(path=path):
                result = self.select(path)
                self.assertEqual(result["status"], "review_required")
                self.assertEqual(result["unknown_paths"], [path])
                self.assertTrue(result["boundary_scan_required"])

    def test_traversal_absolute_drives_globs_and_nul_rejected(self):
        for path in ("../private.py", "C:/private.py", "/private.py", "src/../private.py",
                     "src/*", "\\\\server\\share.py", "bad\x00.py"):
            with self.subTest(path=path), self.assertRaises(selector.CatalogError):
                self.select(path)

    def test_normalizes_windows_relative_path_without_traversal(self):
        self.assertEqual(self.select(".\\tools\\select_verification.py"),
                         self.select("tools/select_verification.py"))

    def test_cli_unknown_code_exit_and_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(selector.main(["tools/new.py", "--json"]), 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "review_required")

    def test_validate_only_and_missing_paths(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(selector.main(["--validate", "--json"]), 0)
            self.assertEqual(selector.main(["--json"]), 2)
            self.assertEqual(selector.main(["README.md", "--validate", "--json"]), 2)

    def test_no_subprocess_or_feature_execution_during_selection(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("must not execute")):
            result = self.select("src/medicafe_v1/claims/queries.py")
            self.assertIn("tests.f3", result["feature_suites"])

    def test_ci_has_one_tooling_step_and_once_only_foundation_suite(self):
        workflow = (ROOT / ".github/workflows/foundation.yml").read_text(encoding="utf-8")
        self.assertEqual(workflow.count("uv run python -m unittest discover -s tests/tooling"), 1)
        self.assertEqual(workflow.count("uv run python manage.py test tests.f1 tests.f2 tests.f3 tests.f4"), 1)


class RunnerTests(unittest.TestCase):
    def fake_run(self, version=b"[3, 13]", probe_code=0, child_code=0):
        return mock.Mock(side_effect=[subprocess.CompletedProcess([], probe_code, version, b""),
                                     subprocess.CompletedProcess([], child_code)])

    def test_verified_interpreter_child_args_and_failure_propagation(self):
        run = self.fake_run(child_code=7)
        result = runner.execute(["tools/select_verification.py", "README.md", "--json"],
                                executable="synthetic-python", run=run)
        self.assertEqual(result, 7)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][:2], ["synthetic-python", "-I"])
        self.assertEqual(run.call_args.kwargs["cwd"], str(ROOT))
        self.assertEqual(run.call_args.args[0][2:], ["README.md", "--json"])

    def test_wrong_version_invalid_probe_or_failed_probe_never_launches_child(self):
        for version, code in ((b"[3, 12]", 0), (b"[3, 14]", 0), (b"bad", 0),
                              (b"[3.0, 13]", 0), (b"[3, 13]", 1)):
            with self.subTest(version=version, code=code):
                run = self.fake_run(version, code)
                with self.assertRaises(ValueError):
                    runner.execute(["tools/select_verification.py"], run=run)
                self.assertEqual(run.call_count, 1)

    def test_script_escape_missing_or_recursive_target_refused_before_probe(self):
        for script in ("../private.py", "tools/missing.py", "tools/run_modern_python.py", "-c"):
            with self.subTest(script=script):
                run = self.fake_run()
                with self.assertRaises(ValueError):
                    runner.execute([script], run=run)
                run.assert_not_called()

    def test_probe_timeout_has_no_install_or_fallback(self):
        run = mock.Mock(side_effect=subprocess.TimeoutExpired("synthetic-python", 5))
        with self.assertRaises(subprocess.TimeoutExpired):
            runner.execute(["tools/select_verification.py"], run=run)
        self.assertEqual(run.call_count, 1)

    def test_missing_interpreter_error_propagates_without_fallback(self):
        run = mock.Mock(side_effect=FileNotFoundError("synthetic missing runtime"))
        with self.assertRaises(OSError):
            runner.execute(["tools/select_verification.py"], run=run)
        self.assertEqual(run.call_count, 1)

    def test_main_reports_invalid_runtime_and_preserves_no_mutation(self):
        with mock.patch.object(runner, "execute", side_effect=ValueError("wrong version")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(["--python", "synthetic-python", "tools/select_verification.py"]), 2)

    def test_real_current_interpreter_rejects_wrong_version_or_runs_valid_selection(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/run_modern_python.py"),
                                 "--python", sys.executable, "tools/select_verification.py",
                                 "README.md", "--json"], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0 if sys.version_info[:2] == (3, 13) else 2)
        if sys.version_info[:2] != (3, 13):
            self.assertIn(b"Python 3.13 is required", result.stderr)
        else:
            self.assertEqual(json.loads(result.stdout)["status"], "docs_only")

    @unittest.skipUnless(sys.version_info[:2] == (3, 13), "real project runner requires Python 3.13")
    def test_real_runner_selects_every_changed_governing_path_under_project_runtime(self):
        catalog = selector.load_catalog(ROOT)
        for path in catalog["governing_paths"]:
            with self.subTest(path=path):
                result = subprocess.run([sys.executable, str(ROOT / "tools/run_modern_python.py"),
                                         "tools/select_verification.py", path, "--json"],
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8"))
                selected = json.loads(result.stdout)
                self.assertTrue(selected["governing_guidance_required"])
                self.assertTrue(selected["boundary_scan_required"])
                self.assertIn("not_execution", selected["evidence"])


if __name__ == "__main__":
    unittest.main()
