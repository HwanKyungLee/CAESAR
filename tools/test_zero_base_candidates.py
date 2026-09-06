import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import fit_explorer as FE


def test_zero_base_grid_is_explicit_and_deterministic():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4}
    wave = np.linspace(430.0, 480.0, 401)
    a = FE.zero_base_policy_candidates(cfg, wave)
    b = FE.zero_base_policy_candidates(cfg, wave)
    assert len(a) == 315
    assert [x["id"] for x in a] == [x["id"] for x in b]
    assert all(x["refs_source"] == "FitSet.cfg.refs" for x in a)
    assert all(x["policy_stage"] == "STAGE0_METADATA_ONLY" for x in a)
    assert {x["window_offset_nm"] for x in a} == {-1.0, 0.0, 1.0}
    assert {x["policy"]["shift"]["mode"] for x in a} == {"Fix", "Limit"}


def test_zero_base_rejects_collapsed_nm_offsets():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4}
    wave = np.linspace(430.0, 480.0, 401)
    try:
        FE.zero_base_policy_candidates(cfg, wave, window_offsets_nm=(-0.01, 0.0, 0.01))
    except ValueError as exc:
        assert "duplicate pixel deltas" in str(exc)
    else:
        raise AssertionError("collapsed offsets must fail closed")


def test_zero_base_stage0_is_fit_free_and_counts(monkeypatch):
    class Engine:
        _wave_axis = np.arange(300.0)
        gas_list = ["NO2"]
        raw_references = {"NO2": np.ones(300)}

    monkeypatch.setattr(FE.FP, "differential_collinearity",
                        lambda *a, **k: {"multiple_R": {"NO2": 0.1}})
    candidates = [{"id": "pass", "px_min": 100, "px_max": 200, "poly": 2},
                  {"id": "bad", "px_min": 100, "px_max": 999, "poly": 2}]
    report = FE.stage0_candidate_grid(Engine(), candidates)
    assert report["fit_executed"] is False
    assert report["counts"] == {"PASS": 1, "FAIL": 1, "UNAVAILABLE": 0}
    assert report["candidates"][1]["stage0_preflight"]["state"] == "FAIL"


if __name__ == "__main__":
    test_zero_base_grid_is_explicit_and_deterministic()
