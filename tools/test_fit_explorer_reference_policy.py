"""Window-specific reference policy contracts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.fit_explorer import validate_reference_policy


def main() -> None:
    cold = json.loads((ROOT / "scenarios" / "AutoFitSet_cold.json").read_text(encoding="utf-8"))
    assert [ref["name"] for ref in cold["refs"]] == ["CHOCHO", "H2O", "NO2"]
    policy = validate_reference_policy(cold)
    assert policy["excluded_species"] == ["O4"]
    assert policy["t2_o4_state"] == "UNAVAILABLE"

    with_o4 = dict(cold)
    with_o4["refs"] = [*cold["refs"], {"name": "O4", "path": "o4.dat", "mult": 0}]
    assert validate_reference_policy({k: v for k, v in with_o4.items() if k != "reference_policy"}) is None
    assert [r["name"] for r in with_o4["refs"]] == ["CHOCHO", "H2O", "NO2", "O4"]

    bad = dict(cold)
    bad["refs"] = [*cold["refs"], {"name": "O4", "path": "o4.dat", "mult": 0}]
    try:
        validate_reference_policy(bad)
    except ValueError as exc:
        assert "contradicts" in str(exc)
    else:
        raise AssertionError("contradictory reference policy was accepted")

    malformed = dict(cold)
    malformed["refs"] = ["O4"]
    try:
        validate_reference_policy(malformed)
    except ValueError as exc:
        assert "list of objects" in str(exc)
    else:
        raise AssertionError("malformed refs were accepted")
    print("test_fit_explorer_reference_policy: PASS")


if __name__ == "__main__":
    main()
