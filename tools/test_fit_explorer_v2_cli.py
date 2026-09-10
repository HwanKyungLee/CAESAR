"""End-to-end file-contract smoke test for the V2 GUI bridge."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _hash(char): return char * 64


def _mission():
    return {"schema": "explorer-mission-v2", "mission_id": "opaque",
        "channels": [{"channel_id": "opaque-channel", "alpha_inputs": [
            {"observation_id": "d", "content_hash": _hash("a")}],
            "wavelength": {"unit": "nm", "values": [430., 431., 432., 433., 434., 435., 436., 437.]},
            "references": [{"species_id": "Species_A", "wavelength_nm": [429., 432., 435., 438.],
                "values": [1., 2., 3., 4.], "cross_section_unit": "arb", "ils_state": "ALREADY_CONVOLVED"}]}],
        "search_policy": {"windows_nm": [[431., 436.]], "poly_degrees": [1],
            "registration_policies": [{"driver_species": "Species_A",
                "shift": {"mode": "Limit", "lower": -1., "upper": 1.},
                "squeeze": {"mode": "Limit", "lower": .9999, "upper": 1.0001}}],
            "split": {"discovery": ["d"], "validation": [], "holdout": []},
            "budget": {"max_fit_attempts": 4, "closure_max_attempts": 1}}}


def main():
    with tempfile.TemporaryDirectory() as root:
        mission, plan = os.path.join(root, "mission.json"), os.path.join(root, "plan.json")
        with open(mission, "w", encoding="utf-8") as fh: json.dump(_mission(), fh)
        command = [sys.executable, os.path.join(ROOT, "tools", "run_fit_explorer_v2.py"),
                   "plan", "--mission", mission, "--output", plan]
        first = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        second = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        assert first.returncode == second.returncode == 0 and json.load(open(plan))["schema"] == "explorer-plan-v2"
        assert json.loads(second.stdout)["state"] == "REUSED"
    print("test_fit_explorer_v2_cli: PASS")


if __name__ == "__main__":
    main()
