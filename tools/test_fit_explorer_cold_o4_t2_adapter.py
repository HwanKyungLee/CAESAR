"""Focused tri-state check for missing cold/O4 physical-anchor inputs."""
import os, sys, tempfile
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tools.test_fit_explorer_cold_o4_external import alpha_identity, evaluate_t2, verify_population
from core import fit_physics as FP


def main():
    scan = (np.arange(3.0), np.arange(3.0), float("nan"), 1013.25)
    result = evaluate_t2(None, [scan], None, None, 0, 2, 1, .5, True)
    assert result == {"state": "UNAVAILABLE",
                      "reason": "selected scan is missing finite temperature/pressure"}
    original = FP.judge_reference
    called = []
    finite = {"exclude": False, "n": 1, "abs_ratio": 1.0, "candidate_cv": .1,
              "target_cv": .2, "pair_collinearity": .1, "multiple_R": .2,
              "corr_with_target": .0}
    try:
        FP.judge_reference = lambda *a, **k: (called.append(True) or {**finite, "abs_ratio": float("nan")})
        class MissingAnchor:
            gas_list = ["NO2"]
            raw_references = {}
            scaling_factors = {}
            multipliers = {}
        result = evaluate_t2(MissingAnchor(), [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and called == []
        class Ready:
            gas_list = ["NO2", "O4"]
            raw_references = {"O4": np.ones(3)}
            scaling_factors = {"O4": 1.0}
            multipliers = {"O4": 1.0}
        ready = Ready()
        result = evaluate_t2(None, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             None, None, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and called == []
        ready.scaling_factors = {}
        result = evaluate_t2(ready, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {"O4": {}}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and "conversion" in result["reason"] and called == []
        ready.scaling_factors = {"O4": 1.0}
        original_anchor = FP.theoretical_amount
        FP.theoretical_amount = lambda *a: None
        result = evaluate_t2(ready, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {"O4": {}}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and "anchor" in result["reason"] and called == []
        FP.theoretical_amount = original_anchor
        result = evaluate_t2(ready, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {"O4": {}}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and "non-finite" in result["reason"]
        FP.judge_reference = lambda *a, **k: {key: value for key, value in finite.items()
                                              if key != "candidate_cv"}
        result = evaluate_t2(ready, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {"O4": {}}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and "non-finite" in result["reason"]
        FP.judge_reference = lambda *a, **k: {**finite, "n": 0}
        result = evaluate_t2(ready, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {"O4": {}}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and "every selected scan" in result["reason"]
        FP.judge_reference = lambda *a, **k: {**finite, "exclude": True, "n": 0}
        result = evaluate_t2(ready, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {"O4": {}}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and "every selected scan" in result["reason"]
        FP.judge_reference = lambda *a, **k: {**finite, "exclude": True,
                                              "candidate_cv": float("nan")}
        result = evaluate_t2(ready, [(np.arange(3.), np.arange(3.), 25., 1013.25)],
                             {}, {"O4": {}}, 0, 2, 1, .5, True)
        assert result["state"] == "UNAVAILABLE" and "non-finite" in result["reason"]
    finally:
        FP.theoretical_amount = original_anchor
        FP.judge_reference = original
    with tempfile.TemporaryDirectory() as root:
        paths = []
        for day, name in (("2026-05-26", "a.dat"), ("2026-05-27", "b.dat"),
                          ("2026-05-28", "c.dat")):
            directory = os.path.join(root, "Output", "alpha", "60s", "cold", day)
            os.makedirs(directory)
            path = os.path.join(directory, name)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("fixture")
            paths.append(path)
        manifest = {"population_glob": "Output/alpha/60s/cold/2026-*/*.dat",
                    "date_range": ["2026-05-26", "2026-05-28"], "source_population_n": 3,
                    "selected_zero_based_indices": [0, 2], "sample_ids": ["a", "c"]}
        verify_population(root, manifest, {"a": paths[0], "c": paths[2]})
        manifest["selected_zero_based_indices"] = [1, 2]
        try:
            verify_population(root, manifest, {"a": paths[0], "c": paths[2]})
            raise AssertionError("population/sample mismatch was accepted")
        except AssertionError as exc:
            assert "sample_ids" in str(exc)
        alpha = os.path.join(root, "alpha.dat")
        with open(alpha, "w", encoding="utf-8") as fh:
            fh.write("# I0_mode=PCHIP ZA_count=749\nrow_idx\tdatetime\tT_C\n0\tt\t25\n")
        try:
            alpha_identity(alpha, {"I0_mode": "PCHIP", "ZA_count": 749,
                                   "ambient_avg_sec": 60, "RL_factor": 1.0,
                                   "d_cm": 51.8, "channel": "1", "label": "cold"})
            raise AssertionError("missing P_mbar was accepted")
        except AssertionError as exc:
            assert "required columns" in str(exc)
        with open(alpha, "w", encoding="utf-8") as fh:
            fh.write("# channel=1 label=cold\n# RL_factor=1.0 d=51.8 cm\n"
                     "# I0_mode=PCHIP ZA_count=749\n# ambient_avg_sec=30\n"
                     "row_idx\tdatetime\tT_C\tP_mbar\n0\tt\t25\t1013.25\n")
        try:
            alpha_identity(alpha, {"I0_mode": "PCHIP", "ZA_count": 749,
                                   "ambient_avg_sec": 60, "RL_factor": 1.0,
                                   "d_cm": 51.8, "channel": "1", "label": "cold"})
            raise AssertionError("wrong ambient averaging was accepted")
        except AssertionError as exc:
            assert "provenance changed" in str(exc)
    print("test_fit_explorer_cold_o4_t2_adapter: PASS")


if __name__ == "__main__":
    main()
