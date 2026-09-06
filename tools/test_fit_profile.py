import os
import sys
import tempfile

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.fit_profile import grid_cells, run_profile


def test_deterministic_grid_and_diagnostic_schema():
    seen = []
    def fit(shift, squeeze, mode):
        seen.append((shift, squeeze, mode))
        return {"shift": shift, "squeeze": squeeze,
                "rms_sig": float((shift - 1) ** 2 + (squeeze - 1) ** 2),
                "conc": 1.0}
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(b"fixture")
        path = fh.name
    try:
        report = run_profile(scan_identity={"file": "scan.dat", "row_index": 44},
                             starts=[(-1, .99), (1, 1.01)],
                             shift_grid=[1, -1], squeeze_grid=[1.01, .99],
                             bounds={"shift": [-2, 2], "squeeze": [.98, 1.02]},
                             fit_callback=fit, fixed_fit_callback=fit, allow_negative_gas=True,
                             source_files=[path], provenance_root=ROOT)
    finally:
        os.unlink(path)
    assert report["status"] == "DIAGNOSTIC_ONLY"
    assert [c["cell_id"] for c in report["fixed_grid"]] == ["s0_q0", "s1_q0", "s0_q1", "s1_q1"]
    assert len(report["multi_start"]) == 2 and len(seen) == 6
    assert "No Apply" in report["limitations"]


if __name__ == "__main__":
    test_deterministic_grid_and_diagnostic_schema()
    print("test_fit_profile: PASS")
