"""Static contract for the privacy-safe O4 A/B checkpoint."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "diagnostics" / "fit_explorer" / name).read_text(encoding="utf-8"))


def main() -> None:
    ab = load("o4_ab_result_v1.json")
    assert ab["status"] == "REPRODUCED_OBSERVATIONAL"
    assert ab["fit"]["n_fits"] == 60
    assert ab["observed_comparison"]["o4_physical_gate"] == {
        "state": "UNAVAILABLE",
        "reason_code": "O4_ANCHOR_NOT_ESTABLISHED_IN_WINDOW",
        "reason": "This A/B checkpoint does not establish an O4 physical anchor; no T2 pass/fail is asserted.",
    }
    assert ab["provenance"]["source_root_label"] == "<LOCAL_DATA_ROOT>"
    raw = (ROOT / "diagnostics" / "fit_explorer" / "o4_ab_result_v1.json").read_text(encoding="utf-8")
    assert "C:\\Users\\" not in raw and "C:/Users/" not in raw
    for name in ("roi1_result_v1.json", "cold_o4_result_v1.json"):
        old = load(name)
        assert old["status"] == "HISTORICAL_INVALIDATED_FOR_NUMERIC_USE"
        assert old["superseded_by"].endswith("o4_ab_result_v1.json")
    print("test_fit_explorer_o4_ab_schema: PASS")


if __name__ == "__main__":
    main()
