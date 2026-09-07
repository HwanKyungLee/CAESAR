"""Static consistency and privacy checks for committed ROI1 evidence."""
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer as FE


EVIDENCE = os.path.join(ROOT, "diagnostics", "fit_explorer")


def main():
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "init", "-q"], cwd=td, check=True)
        tracked = os.path.join(td, "tracked.txt")
        with open(tracked, "w", encoding="utf-8") as fh:
            fh.write("tracked")
        subprocess.run(["git", "add", "tracked.txt"], cwd=td, check=True)
        subprocess.run(["git", "-c", "user.name=test", "-c",
                        "user.email=test@example.invalid", "commit", "-qm", "initial"],
                       cwd=td, check=True)
        name = "한글 파일.txt"
        path = os.path.join(td, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("portable")
        provenance = FE.git_provenance(td)
        assert provenance["untracked"] == [{"path": name, "sha256": FE.sha256_file(path)}]

    manifest_path = os.path.join(EVIDENCE, "roi1_manifest_v1.json")
    result_path = os.path.join(EVIDENCE, "roi1_result_v1.json")
    manifest_bytes = open(manifest_path, "rb").read()
    manifest = json.loads(manifest_bytes)
    manifest_text = manifest_bytes.decode("utf-8")
    result_text = open(result_path, encoding="utf-8").read()
    result = json.loads(result_text)
    assert result["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert manifest["schema_version"] == result["schema_version"] == 3
    assert len(manifest["cases"]) == len(result["performed"]) == 2
    assert not result["failed"] and not result["skipped"]
    assert {row["id"] for row in result["performed"]} == {case["id"] for case in manifest["cases"]}
    for dep in manifest["dependencies"]:
        assert not os.path.isabs(dep["path"]) and ".." not in dep["path"].split("/")
    private_markers = ("C:\\", "C:/", "Users/", "Users\\", "Doasis_Work")
    assert not any(marker in manifest_text + result_text for marker in private_markers)
    expected_dependencies = {(dep["id"], dep["role"], dep["sha256"].lower())
                             for dep in manifest["dependencies"]}
    actual_dependencies = {(dep["id"], dep["role"], dep["sha256"].lower())
                           for dep in result["dependencies"]}
    assert actual_dependencies == expected_dependencies
    for row in result["performed"]:
        assert set(row["metrics"]) == {"conc", "rms_sig", "abs_ac1"}
        assert row["status"] == "PERFORMED"
        assert row["sample_identity"]["datetime"] and row["sample_identity"]["state"]
        fit = row["config_identity"]["fit"]
        assert fit["fit_sign"] == 1.0 and fit["W"] == "identity"
        assert fit["seed_grid"]["state"] == "N/A"
        assert fit["shift"]["mode"] == fit["squeeze"]["mode"] == "Fix"
        assert set(row["engine_identity"]) == {"gas_order", "multipliers", "scaling_factors"}
        assert row["t2"]["state"] == "UNAVAILABLE"
        assert len(row["config_sha256"]) == 64
    assert result["assertions"] and all(a["status"] == "PASS" for a in result["assertions"])
    assert result["assertion_scope"] == manifest["assertion_scope"]
    assert "not cross-platform numeric equivalence" in result["assertion_scope"]
    assert all("thresholds" not in assertion for assertion in manifest["assertions"])
    assert set(result["runtime"]) == {"python", "platform", "numpy", "scipy"}
    assert result["generation"]["artifact_self_excluded"] is True
    measurements = {row["id"]: row for row in result["measurements"]}
    assert set(measurements) == {spec["id"] for spec in manifest["measurements"]}
    grid = measurements["roi1_signed_fixed_shift_grid"]
    assert grid["execution_scope"].endswith("not worker end-to-end")
    assert [row["fitted_shift"] for row in grid["observations"]] == grid["policy"]["shift_values"]
    assert all(row["initialization"]["active"] == [] for row in grid["observations"])
    limit = measurements["roi1_signed_default_limit_path"]
    assert limit["policy"]["seed_grid"] == {
        "range": 15.0, "step": 0.25,
        "effective_interval": [-10.0, 0.5],
        "selection": "minimum linear-fit RMS before final VarPro"}
    center = measurements["roi1_signed_center_path"]
    assert center["policy"]["seed_grid"]["state"] == "N/A"
    assert center["initialization_scope"].startswith("Center-anchored bounds")
    center_init = center["observations"][0]["initialization"]
    shift_i = center_init["active"].index("NO2_sh")
    # fit_scan supplies current shift 0; setup clamps it just inside the upper bound.
    assert center_init["theta0"][shift_i] == center_init["upper"][shift_i] - 1e-5
    assert center_init["theta0"][shift_i] != -5.25
    for row in measurements.values():
        assert row["status"] == "OBSERVED" and row["t2"]["state"] == "UNAVAILABLE"
        assert row["fit_context"]["fit_sign"] == 1.0
        assert row["fit_context"]["W"] == "identity"
        assert row["fit_context"]["sample"]["datetime"]
        for observation in row["observations"]:
            assert all(math.isfinite(value) for value in observation["metrics"].values())
            assert math.isfinite(observation["fitted_shift"])
            assert math.isfinite(observation["fitted_squeeze"])
            init = observation["initialization"]
            assert len(init["active"]) == len(init["theta0"]) == len(init["lower"]) == len(init["upper"])
            assert all(math.isfinite(value) for values in
                       (init["theta0"], init["lower"], init["upper"]) for value in values)
            assert all(lower < value < upper for lower, value, upper in
                       zip(init["lower"], init["theta0"], init["upper"]))
    assert result["git"]["excluded_paths"] == ["diagnostics/fit_explorer/roi1_result_v1.json"]
    # An already-existing output cannot perturb provenance between reruns.
    fd, rerun_path = tempfile.mkstemp(prefix=".portable-rerun-", suffix=".json", dir=EVIDENCE)
    try:
        os.write(fd, b"first")
        os.close(fd)
        before = FE.git_provenance(ROOT, [rerun_path])
        with open(rerun_path, "wb") as fh:
            fh.write(b"second, different bytes")
        after = FE.git_provenance(ROOT, [rerun_path])
        assert before == after and before["excluded_paths"] == [
            os.path.relpath(rerun_path, ROOT).replace("\\", "/")]
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        if os.path.exists(rerun_path):
            os.unlink(rerun_path)
    print("test_fit_explorer_portable_evidence: PASS")


if __name__ == "__main__":
    main()
