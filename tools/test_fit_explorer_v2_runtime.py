"""Real production-engine run and resume, without a manual FitSet or mocks."""
import json
import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import fit_explorer as FE
from core.fit_explorer_v2_runtime import run_mission


def main():
    with tempfile.TemporaryDirectory() as root:
        wave = np.linspace(430., 460., 121)
        ref = 1e-19 * (2 + np.sin(np.arange(121) * .37))
        alpha = 1e-7 + ref * 1e11
        path = os.path.join(root, "alpha.dat")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# wavelength_nm: " + "\t".join(map(str, wave)) + "\n")
            f.write("row_idx\tT_C\tP_mbar\t" + "\t".join(f"px{i}" for i in range(121)) + "\n")
            f.write("0\t25\t1013.25\t" + "\t".join(map(str, alpha)) + "\n")
        mission = {"schema": "explorer-mission-v2", "mission_id": "synthetic-runtime",
                   "channels": [{"channel_id": "opaque-detector", "alpha_inputs": [
                       {"observation_id": "obs", "content_hash": FE.sha256_file(path)}],
                       "wavelength": {"unit": "nm", "values": wave.tolist()},
                       "references": [{"species_id": "Species_X", "wavelength_nm": wave.tolist(),
                           "values": ref.tolist(), "cross_section_unit": "cm2/molecule",
                           "ils_state": "ALREADY_CONVOLVED"}]}],
                   "search_policy": {"windows_nm": [[432., 457.]], "poly_degrees": [2],
                       "registration_policies": [{"driver_species": "Species_X",
                           "shift": {"mode": "Limit", "lower": -.5, "upper": .5},
                           "squeeze": {"mode": "Fix", "value": 1.}}],
                       "split": {"discovery": ["obs"], "validation": [], "holdout": []},
                       "budget": {"max_fit_attempts": 2, "closure_max_attempts": 0}}}
        bindings = {"obs": {"path": path, "row_index": 0}}
        result = run_mission(mission, bindings, root)
        assert result["consumed_fit_attempts"] == 2
        attempts = result["reports"][0]["attempts"]
        assert all(row["status"] == "OK" for row in attempts), attempts
        assert all("Species_X" in row["coeffs"] for row in attempts)
        assert result == run_mission(mission, bindings, root)
        assert result["status"] == "DIAGNOSTIC_ONLY"
        directory = os.path.join(root, result["execution_hash"])
        attempt_path = next(os.path.join(directory, name) for name in os.listdir(directory)
                            if name.endswith(".json") and name not in {"plan.json", "result.json"})
        with open(attempt_path, encoding="utf-8") as handle:
            saved = json.load(handle)
        saved["attempt"]["scan_id"] = "forged"
        with open(attempt_path, "w", encoding="utf-8") as handle:
            json.dump(saved, handle)
        try:
            run_mission(mission, bindings, root)
        except ValueError as exc:
            assert "integrity mismatch" in str(exc)
        else:
            raise AssertionError("tampered cached attempt accepted")
        print("test_fit_explorer_v2_runtime: PASS (real VARPRO, 2 starts, resume)")


if __name__ == "__main__":
    main()
