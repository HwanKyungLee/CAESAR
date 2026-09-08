"""Small regression contract for tools/analyze_injection_plateaus.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from analyze_injection_plateaus import find_plateaus


def main():
    # Two stable regions separated by an obvious ramp.  Overlapping sliding
    # windows must collapse to one representative per physical region.
    ans = {i: v for i, v in enumerate((10, 10.1, 10.0, 10.2, 20, 30, 40, 50,
                                        30, 30.1, 29.9, 30.2))}
    pns = {i: v / 1.25 for i, v in ans.items()}
    times = {i: f"2026-01-01 00:{i:02d}:00" for i in ans}
    found = find_plateaus(ans, pns, times, window_rows=4, max_relative_drift=0.05)
    assert [(x["row_start"], x["row_end"]) for x in found] == [(0, 3), (8, 11)], found
    print("test_injection_plateaus: PASS")


if __name__ == "__main__":
    main()
