"""Manifest trust-boundary checks for the optional external suite."""
import copy
import contextlib
import hashlib
import io
import json
import os
import posixpath
import tempfile
from types import SimpleNamespace
from unittest import mock

import test_fit_explorer_external as ext


def digest(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def expect_fail(fn, text):
    try:
        fn()
    except AssertionError as exc:
        assert text in str(exc), (text, exc)
    else:
        raise AssertionError(f"expected failure containing {text!r}")


def main():
    with tempfile.TemporaryDirectory() as td:
        paths = {}
        for name in ("legacy", "alpha", "wave", "ref"):
            path = os.path.join(td, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(name)
            paths[name] = path
        deps = [{"id": name, "role": {"legacy": "legacy_fitset", "alpha": "alpha",
                 "wave": "wavecal", "ref": "reference"}[name],
                 "path": path, "sha256": digest(path)} for name, path in paths.items()]
        case = {"id": "case", "evidence_role": "low_residual_candidate",
                "source_fitset_id": "legacy", "alpha_id": "alpha",
                "wavecal_id": "wave", "reference_ids": ["ref"],
                "expected_references": [{"dependency_id": "ref", "name": "NO2", "mult": 0}],
                "expected_gas_order": ["NO2"], "channel_id": "1", "row_index": 0,
                "allow_negative_gas": True, "fixed_shift": -6.0}
        high_case = copy.deepcopy(case)
        high_case.update(id="high", evidence_role="high_residual_candidate",
                         allow_negative_gas=False)
        assertion = {"id": "contrast", "type": "paired_branch_contrast",
                     "high_case_id": "high", "low_case_id": "case", "source": "test",
                     "strictly_greater": ["conc", "rms_sig", "abs_ac1"]}
        manifest = {"schema_version": 3, "suite_version": "1.2",
                    "dependencies": deps, "cases": [high_case, case], "assertions": [assertion],
                    "measurements": [],
                    "assertion_scope": ext.ASSERTION_SCOPE}
        validated = ext.validate_manifest(manifest, td)
        ext.verify_dependencies(validated)
        private = copy.deepcopy(validated["legacy"])
        private_paths = (r"C:\Users\Private Person\secret\legacy.json",
                         "/home/private-person/secret/legacy.json",
                         r"C:\Users/Private Person\secret/legacy.json",
                         r"\\server\Private Person\secret\legacy.json")
        with mock.patch.object(ext.os.path, "basename", side_effect=posixpath.basename):
            for private_path in private_paths:
                assert ext.portable_basename(private_path) == "legacy.json"
                private["resolved_path"] = private_path
                public = ext.public_dependency(private)
                encoded = json.dumps(public)
                assert public["name"] == "legacy.json"
                assert "Private Person" not in encoded and "private-person" not in encoded
                assert "secret" not in encoded and "server" not in encoded

            missing = copy.deepcopy(validated)
            missing["legacy"]["resolved_path"] = private_paths[0]
            try:
                ext.verify_dependencies(missing)
            except AssertionError as exc:
                assert str(exc) == "required file missing: legacy (legacy.json)"
            else:
                raise AssertionError("foreign-style missing dependency must fail")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                assert ext.main(["--manifest", private_paths[0]]) == 1
            error = stderr.getvalue()
            assert "manifest not found: legacy.json" in error
            assert "Private Person" not in error and "secret" not in error

        portable = copy.deepcopy(manifest)
        for dep in portable["dependencies"]:
            dep["path"] = os.path.basename(dep["path"])
        rooted = ext.validate_manifest(portable, "ignored", td)
        assert rooted["alpha"]["resolved_path"] == paths["alpha"]
        bad = copy.deepcopy(portable); bad["dependencies"][0]["path"] = paths["legacy"]
        expect_fail(lambda: ext.validate_manifest(bad, "ignored", td), "must be relative")
        bad = copy.deepcopy(portable); bad["dependencies"][0]["path"] = "../escape"
        expect_fail(lambda: ext.validate_manifest(bad, "ignored", td), "leaves data root")

        bad = copy.deepcopy(manifest); bad["schema_version"] = 1
        expect_fail(lambda: ext.validate_manifest(bad, td), "schema_version")
        bad = copy.deepcopy(manifest); bad["cases"][0]["allow_negative_gas"] = 1
        expect_fail(lambda: ext.validate_manifest(bad, td), "exact bool")
        bad = copy.deepcopy(manifest); bad["assertions"][0]["strictly_greater"] = ["conc"]
        expect_fail(lambda: ext.validate_manifest(bad, td), "must order exactly")
        bad = copy.deepcopy(manifest); bad["assertions"][0]["thresholds"] = {"min_ratio": 2}
        expect_fail(lambda: ext.validate_manifest(bad, td), "unsupported fields")
        bad = copy.deepcopy(manifest); bad["assertion_scope"] = "numeric tolerance"
        expect_fail(lambda: ext.validate_manifest(bad, td), "assertion_scope")
        bad = copy.deepcopy(manifest); bad["assertions"][0]["low_case_id"] = "high"
        expect_fail(lambda: ext.validate_manifest(bad, td), "two distinct cases")
        bad = copy.deepcopy(manifest); bad["cases"].append(copy.deepcopy(case))
        expect_fail(lambda: ext.validate_manifest(bad, td), "duplicate")
        bad = copy.deepcopy(manifest); bad["measurements"] = [{
            "id": "path", "type": "shift_path", "source_case_id": "case",
            "shift_mode": "Free", "shift_value": "-1,1"}]
        expect_fail(lambda: ext.validate_manifest(bad, td), "Limit/Center")
        base_path = {"id": "path", "type": "shift_path", "source_case_id": "case",
                     "shift_mode": "Limit", "shift_value": "-1,1",
                     "seed_range": 15.0, "seed_step": .25}
        for value in ("-1", "-1,1,2", "nan,1"):
            bad = copy.deepcopy(manifest); bad["measurements"] = [{**base_path, "shift_value": value}]
            expect_fail(lambda bad=bad: ext.validate_manifest(bad, td), "exactly two finite")
        bad = copy.deepcopy(manifest); bad["measurements"] = [{**base_path, "shift_value": "1,-1"}]
        expect_fail(lambda: ext.validate_manifest(bad, td), "lower bound")
        bad = copy.deepcopy(manifest); bad["measurements"] = [{**base_path, "seed_step": 0}]
        expect_fail(lambda: ext.validate_manifest(bad, td), "seed_step")
        bad = copy.deepcopy(manifest); bad["measurements"] = [{**base_path,
            "shift_value": "20,21", "seed_range": 15.0}]
        expect_fail(lambda: ext.validate_manifest(bad, td), "must overlap")
        bad = copy.deepcopy(manifest); bad["measurements"] = [{**base_path,
            "shift_mode": "Center", "shift_value": "-5,0"}]
        expect_fail(lambda: ext.validate_manifest(bad, td), "halfwidth")
        grid = {"id": "grid", "type": "fixed_shift_grid", "source_case_id": "case",
                "shift_values": [-1.0, 0.0], "fixed_squeeze": 1.0}
        bad = copy.deepcopy(manifest); bad["measurements"] = [{**grid,
            "shift_values": [0.0, -1.0]}]
        expect_fail(lambda: ext.validate_manifest(bad, td), "strictly increasing")
        bad = copy.deepcopy(manifest); bad["measurements"] = [{**grid,
            "fixed_squeeze": float("inf")}]
        expect_fail(lambda: ext.validate_manifest(bad, td), "fixed_squeeze")
        bad = copy.deepcopy(manifest); bad["dependencies"].append(
            {"id": "extra", "role": "alpha", "path": paths["alpha"], "sha256": digest(paths["alpha"])})
        expect_fail(lambda: ext.validate_manifest(bad, td), "extra dependencies")
        bad = copy.deepcopy(validated); bad["alpha"]["resolved_path"] = os.path.join(td, "absent")
        expect_fail(lambda: ext.verify_dependencies(bad), "required file missing")
        bad = copy.deepcopy(validated); bad["alpha"]["sha256"] = "0" * 64
        expect_fail(lambda: ext.verify_dependencies(bad), "hash mismatch")
        bad = copy.deepcopy(manifest); bad["cases"][0]["reference_ids"] = []
        expect_fail(lambda: ext.validate_manifest(bad, td), "ordered references")
        missing_manifest = copy.deepcopy(manifest)
        for dep in missing_manifest["dependencies"]:
            dep["path"] = os.path.join(td, "missing", dep["id"])
        missing_path = os.path.join(td, "all-missing.json")
        with open(missing_path, "w", encoding="utf-8") as fh:
            json.dump(missing_manifest, fh)
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            result_path = os.path.join(td, "failure-result.json")
            assert ext.main(["--manifest", missing_path, "--result", result_path]) == 1
        assert "required file missing" in stderr.getvalue()
        result_text = open(result_path, encoding="utf-8").read()
        assert td not in result_text and "missing\\legacy" not in result_text

        # Embedded personal paths are never used: manifest-resolved paths replace them.
        scenario = {"channels": {"1": {"wl_path": "X:/private/wave",
                    "f_min": 0, "f_max": 1, "poly_deg": 1, "step_limit": .5,
                    "refs": [{"name": "NO2", "mult": 0, "path": "X:/private/ref"}],
                    "ref_props": {"NO2": {}}}}}
        with open(paths["legacy"], "w", encoding="utf-8") as fh:
            json.dump(scenario, fh)
        validated["legacy"]["sha256"] = digest(paths["legacy"])
        captured = {}
        old_build, old_load, old_fit, old_fitter = (ext.build_engine_from_config,
                                                     ext.DataIO.load_alpha_trace_row_mapped,
                                                     ext.PO.fit_scan, ext.DoasFitter)
        try:
            def fake_build(cfg):
                captured.update(cfg)
                return SimpleNamespace(gas_list=["NO2"], multipliers={"NO2": 1.0},
                                       scaling_factors={"NO2": 2.0})
            ext.build_engine_from_config = fake_build
            ext.DataIO.load_alpha_trace_row_mapped = lambda *_: ([1, 2], [1, 2], 20, 1000, 0)
            old_identity = ext.alpha_row_identity
            ext.alpha_row_identity = lambda *_: {"row_index": 0}
            ext.DoasFitter = lambda engine: object()
            ext.PO.fit_scan = lambda *_a, **_k: {
                "conc": 3.5, "rms_sig": .1, "autocorr1": -.2, "etalon_frequency": .1,
                "nonlinear_initialization": {"active": [], "theta0": [], "lower": [], "upper": []}}
            row = ext.run_case(case, validated)
            assert captured["wl_path"] == paths["wave"]
            assert captured["refs"][0]["path"] == paths["ref"]
            assert row["metrics"]["abs_ac1"] == .2
            passed = ext.evaluate_assertions([assertion], [
                {"id": "high", "metrics": {"conc": 40, "rms_sig": .4, "abs_ac1": .9}},
                {"id": "case", "metrics": {"conc": 3, "rms_sig": .1, "abs_ac1": .2}}])
            assert passed[0]["status"] == "PASS"
            expect_fail(lambda: ext.evaluate_assertions([assertion], [
                {"id": "high", "metrics": {"conc": 2, "rms_sig": .4, "abs_ac1": .9}},
                {"id": "case", "metrics": {"conc": 3, "rms_sig": .1, "abs_ac1": .2}}]),
                        "relational assertion failed")
            changed = copy.deepcopy(case)
            changed["expected_references"][0]["name"] = "H2O"
            expect_fail(lambda: ext.run_case(changed, validated), "order/mults changed")
        finally:
            ext.build_engine_from_config, ext.DataIO.load_alpha_trace_row_mapped = old_build, old_load
            ext.PO.fit_scan, ext.DoasFitter = old_fit, old_fitter
            ext.alpha_row_identity = old_identity
    print("test_fit_explorer_external_contract: PASS")


if __name__ == "__main__":
    main()
