"""External regression: alternate output must match the canonical semantic report."""
import argparse, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools import test_fit_explorer_cold_o4_external as cold

EVIDENCE = os.path.join(ROOT, "diagnostics", "fit_explorer")


def contract(report):
    states = report["t2"]["states"]
    return {
        "manifest_sha256": report["manifest_sha256"],
        "claim_scope": report["claim_scope"],
        "dependencies": report["dependencies"],
        "sampling": report["sampling"],
        "fit": report["fit"],
        "physical_anchor": report["physical_anchor"],
        "t2_states": {name: row["state"] for name, row in states.items()},
        "nonnegative_impossible": states["nonnegative"]["observed"]["impossible"] is True,
        "nonnegative_over_bound": states["nonnegative"]["observed"]["abs_ratio"] > 3.0,
        "signed_not_over_bound": states["signed"]["observed"]["impossible"] is False,
        "signed_constant_violation": (states["signed"]["observed"]["candidate_cv"]
                                      > states["signed"]["observed"]["target_cv"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()
    fd, alternate = tempfile.mkstemp(prefix=".cold-o4-rerun-", suffix=".json", dir=EVIDENCE)
    os.close(fd)
    try:
        assert cold.main(["--manifest", os.path.join(EVIDENCE, "cold_o4_manifest_v1.json"),
                          "--data-root", args.data_root, "--result", alternate]) == 0
        canonical = json.load(open(os.path.join(EVIDENCE, "cold_o4_result_v1.json"), encoding="utf-8"))
        rerun = json.load(open(alternate, encoding="utf-8"))
        assert contract(rerun) == contract(canonical)
    finally:
        os.unlink(alternate)
    print("test_fit_explorer_cold_o4_rerun: PASS")


if __name__ == "__main__":
    main()
