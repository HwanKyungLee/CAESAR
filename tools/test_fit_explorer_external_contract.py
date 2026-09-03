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
        for name in ("legacy", "migrated", "alpha", "wave", "ref"):
            path = os.path.join(td, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(name)
            paths[name] = path
        deps = [{"id": name, "role": {"legacy": "legacy_fitset", "migrated": "migrated_fitset",
                 "alpha": "alpha", "wave": "wavecal", "ref": "reference"}[name],
                 "path": path, "sha256": digest(path)} for name, path in paths.items()]
        case = {"id": "case", "evidence_role": "low_residual_candidate",
                "source_fitset_id": "legacy", "fitset_id": "migrated", "alpha_id": "alpha",
                "wavecal_id": "wave", "reference_ids": ["ref"],
                "expected_references": [{"dependency_id": "ref", "name": "NO2", "mult": 0}],
                "expected_gas_order": ["NO2"], "channel_id": "1", "row_index": 0,
                "allow_negative_gas": True, "fixed_shift": -6.0,
                "expected_ranges": {"conc": [3.0, 4.0], "rms_sig": [0.0, 1.0],
                                    "abs_ac1": [0.0, 1.0]}}
        manifest = {"schema_version": 1, "suite_version": "1.0",
                    "dependencies": deps, "cases": [case]}
        validated = ext.validate_manifest(manifest, td)
        ext.verify_dependencies(validated)
        private = copy.deepcopy(validated["legacy"])
        private["resolved_path"] = r"C:\Users\Private Person\secret\legacy.json"
        encoded = json.dumps(ext.public_dependency(private))
        assert "Private Person" not in encoded and "secret" not in encoded
        assert "legacy.json" in encoded

        bad = copy.deepcopy(manifest); bad["schema_version"] = 2
        expect_fail(lambda: ext.validate_manifest(bad, td), "schema_version")
        bad = copy.deepcopy(manifest); bad["cases"][0]["allow_negative_gas"] = 1
        expect_fail(lambda: ext.validate_manifest(bad, td), "exact bool")
        bad = copy.deepcopy(manifest); bad["cases"][0]["expected_ranges"]["conc"] = [4, 3]
        expect_fail(lambda: ext.validate_manifest(bad, td), "lo > hi")
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
        scenario = {"policy_migrations": [{"source_sha256": validated["legacy"]["sha256"]}],
                    "channels": {"1": {"allow_negative_gas": True, "wl_path": "X:/private/wave",
                    "f_min": 0, "f_max": 1, "poly_deg": 1, "step_limit": .5,
                    "refs": [{"name": "NO2", "mult": 0, "path": "X:/private/ref"}],
                    "ref_props": {"NO2": {}}}}}
        with open(paths["migrated"], "w", encoding="utf-8") as fh:
            json.dump(scenario, fh)
        validated["migrated"]["sha256"] = digest(paths["migrated"])
        captured = {}
        old_build, old_load, old_fit, old_fitter = (ext.build_engine_from_config,
                                                     ext.DataIO.load_alpha_trace_row_mapped,
                                                     ext.PO.fit_scan, ext.DoasFitter)
        try:
            def fake_build(cfg):
                captured.update(cfg)
                return SimpleNamespace(gas_list=["NO2"], multipliers={"NO2": 1.0})
            ext.build_engine_from_config = fake_build
            ext.DataIO.load_alpha_trace_row_mapped = lambda *_: ([1, 2], [1, 2], 20, 1000, 0)
            ext.DoasFitter = lambda engine: object()
            ext.PO.fit_scan = lambda *_a, **_k: {"conc": 3.5, "rms_sig": .1, "autocorr1": -.2}
            row = ext.run_case(case, validated)
            assert captured["wl_path"] == paths["wave"]
            assert captured["refs"][0]["path"] == paths["ref"]
            assert row["metrics"]["abs_ac1"] == .2
            changed = copy.deepcopy(case)
            changed["expected_references"][0]["name"] = "H2O"
            expect_fail(lambda: ext.run_case(changed, validated), "order/mults changed")
        finally:
            ext.build_engine_from_config, ext.DataIO.load_alpha_trace_row_mapped = old_build, old_load
            ext.PO.fit_scan, ext.DoasFitter = old_fit, old_fitter
    print("test_fit_explorer_external_contract: PASS")


if __name__ == "__main__":
    main()
