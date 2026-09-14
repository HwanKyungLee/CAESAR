"""Static contract for the committed cold/O4 portable evidence."""
import hashlib, json, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVIDENCE = os.path.join(ROOT, "diagnostics", "fit_explorer")


def main():
    manifest_bytes = open(os.path.join(EVIDENCE, "cold_o4_manifest_v1.json"), "rb").read()
    manifest = json.loads(manifest_bytes)
    result = json.load(open(os.path.join(EVIDENCE, "cold_o4_result_v1.json"), encoding="utf-8"))
    assert result["manifest_sha256"] == hashlib.sha256(manifest_bytes).hexdigest()
    assert result["status"] == "HISTORICAL_INVALIDATED_FOR_NUMERIC_USE"
    assert result["superseded_by"] == "diagnostics/fit_explorer/o4_ab_result_v1.json"
    assert result["claim_scope"].startswith("historical pre-normalization ")
    states = result["t2"]["states"]
    assert {name: row["state"] for name, row in states.items()} == manifest["expected_t2_states"]
    nonnegative, signed = states["nonnegative"]["observed"], states["signed"]["observed"]
    assert nonnegative["exclude"] is True and nonnegative["impossible"] is True
    assert nonnegative["abs_ratio"] > 3 and nonnegative["n"] == len(manifest["sample_ids"]) == 15
    assert signed["exclude"] is True and signed["impossible"] is False
    assert signed["candidate_cv"] > signed["target_cv"]
    for policy in states.values():
        audit = policy["per_scan_audit"]
        assert len(audit) == len(manifest["sample_ids"])
        assert all(row["fit_success"] is True for row in audit)
        assert all(set(row["O4"]) == {"coefficient", "retrieved_amount",
                                      "theoretical_amount", "abs_ratio"} for row in audit)
        assert all(isinstance(row["NO2_coefficient"], float) for row in audit)
        assert all(row["deterministic_seed"]["source"] == "deterministic_grid" for row in audit)
        assert all(set(row["effective_target"]) == {"theta0", "lower", "upper", "final"}
                   for row in audit)
        o4 = np.asarray([row["O4"]["coefficient"] for row in audit])
        no2 = np.asarray([row["NO2_coefficient"] for row in audit])
        observed = policy["observed"]
        cv = lambda values: float(np.std(values) / (abs(np.mean(values)) + 1e-30))
        assert np.isclose(cv(o4), observed["candidate_cv"])
        assert np.isclose(cv(no2), observed["target_cv"])
        assert np.isclose(np.corrcoef(o4, no2)[0, 1], observed["corr_with_target"])
    assert set(result["runtime"]) == {"python", "platform", "numpy", "scipy"}
    assert result["physical_anchor"]["formula"] == "(0.2095 * n_air)^2"
    assert result["physical_anchor"]["air_number_density_formula"] == (
        "N_LOSCHMIDT * (P_mbar / 1013.25) * (273.15 / (T_C + 273.15)); N_LOSCHMIDT = 101325/(1.380649e-23*273.15)*1e-6 = 2.686780111e19 (CODATA 2018)")
    assert result["physical_anchor"]["source"] == (
        "core.fit_physics.air_number_density/theoretical_amount")
    assert result["fit"]["gas_order"] == ["CHOCHO", "H2O", "NO2", "O4"]
    assert set(result["fit"]["ref_props"]) == {"CHOCHO", "H2O", "NO2", "O4"}
    assert result["fit"]["gas_temperature_override_C"] == 0.0
    assert set(result["sampling"]) >= {"population_glob", "population_filter", "population_order",
                                       "selected_zero_based_indices", "samples"}
    assert result["sampling"]["selected_zero_based_indices"] == list(range(0, 421, 30))
    assert all(set(row) >= {"id", "row_idx", "datetime", "T_C", "P_mbar"}
               for row in result["sampling"]["samples"])
    assert all(row["I0_mode"] == "PCHIP" and row["ZA_count"] == 749
               and row["ambient_avg_sec"] == 60 and row["RL_factor"] == 1.0
               and row["d_cm"] == 51.8 and row["channel"] == "1" and row["label"] == "cold"
               and row["state"] == "ambient_60s_average"
               for row in result["sampling"]["samples"])
    frequencies = result["fit"]["etalon"]["detected_frequency_rad_per_px_by_policy"]
    search = result["fit"]["etalon"]
    assert search["frequency_search_cycles_per_px"] == [0.02, 0.4]
    assert np.allclose(search["frequency_search_rad_per_px"], 2*np.pi*np.asarray([0.02, 0.4]))
    assert set(frequencies) == {"nonnegative", "signed"}
    lo, hi = search["frequency_search_rad_per_px"]
    assert all(len(values) == 15 and all(np.isfinite(value) and lo < value < hi
                                        for value in values) for values in frequencies.values())
    assert result["fit"]["target_shift"]["effective_seed_range"] == [-1.0, 1.0]
    assert result["fit"]["target_shift"]["seed_step"] == 0.25
    assert result["fit"]["target_squeeze"]["effective_seed_range"] == [0.99, 1.01]
    assert result["fit"]["target_squeeze"]["seed_step"] == 0.001
    assert result["execution"]["elapsed_seconds"] > 0
    assert result["selection"]["pruning"]["state"] == "N/A"
    assert result["selection"]["closure"]["state"] == "N/A"
    for policy in states.values():
        gates = policy["gates"]
        assert set(gates) == {"magnitude", "constant_species", "collinearity", "trade_off"}
        assert all(gate["state"] in {"PASS", "FAIL", "UNAVAILABLE"}
                   and isinstance(gate["tolerance"], (int, float)) and gate["source"]
                   for gate in gates.values())
    exclusions = result["git"]["excluded_paths"]
    assert "diagnostics/fit_explorer/cold_o4_result_v1.json" in exclusions
    assert "Claude outputs" in exclusions
    assert "diagnostics/varpro_speed_2026-09" in exclusions
    assert "diagnostics/parallel_shift_bench/bench.py" in exclusions
    assert "diagnostics/parallel_shift_bench/validate_chunk.py" in exclusions
    assert all(not row["path"].startswith(("Claude outputs/", "diagnostics/varpro_speed_2026-09/"))
               for row in result["git"]["untracked"])
    text = manifest_bytes.decode() + json.dumps(result)
    assert "C:\\Doasis_Work" not in text and "C:/Doasis_Work" not in text
    print("test_fit_explorer_cold_o4_evidence: PASS")


if __name__ == "__main__":
    main()
