"""Manifest trust-boundary checks for the optional external suite."""
import copy
import contextlib
import hashlib
import io
import json
import os
import tempfile
from types import SimpleNamespace

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
        manifest = {"schema_version": 2, "suite_version": "1.1",
                    "dependencies": deps, "cases": [high_case, case], "assertions": [assertion],
                    "assertion_scope": ext.ASSERTION_SCOPE}
        validated = ext.validate_manifest(manifest, td)
        ext.verify_dependencies(validated)
        private = copy.deepcopy(validated["legacy"])
        private["resolved_path"] = r"C:\Users\Private Person\secret\legacy.json"
        encoded = json.dumps(ext.public_dependency(private))
        assert "Private Person" not in encoded and "secret" not in encoded
        assert "legacy.json" in encoded

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
