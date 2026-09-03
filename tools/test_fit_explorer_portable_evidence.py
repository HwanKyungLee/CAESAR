"""Static consistency and privacy checks for committed ROI1 evidence."""
import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer as FE


EVIDENCE = os.path.join(ROOT, "diagnostics", "fit_explorer")


def main():
    manifest_path = os.path.join(EVIDENCE, "roi1_manifest_v1.json")
    result_path = os.path.join(EVIDENCE, "roi1_result_v1.json")
    manifest_bytes = open(manifest_path, "rb").read()
    manifest = json.loads(manifest_bytes)
    manifest_text = manifest_bytes.decode("utf-8")
    result_text = open(result_path, encoding="utf-8").read()
    result = json.loads(result_text)
    assert result["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert manifest["schema_version"] == result["schema_version"] == 2
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
