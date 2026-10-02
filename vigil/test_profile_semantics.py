# -*- coding: utf-8 -*-
"""vigil/test_profile_semantics.py — profile meaning checks + same-column-count ambiguity (2026-10-03).

Before: an hk rel past the row width raised IndexError every tick (rows lost), reversed bands /
ROIs and unknown HK keys loaded silently, and two profiles matching the same files were resolved
by alphabetical order without a word (audit 2026-10-02 V2 §6).

    python vigil/test_profile_semantics.py
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.profile import DEFAULT_PROFILE_DIR, Profile, ProfileError, ProfileSet, load_profiles


def main():
    with open(os.path.join(DEFAULT_PROFILE_DIR, "base_hot_6181.json"), encoding="utf-8") as fh:
        base = json.load(fh)
    assert Profile.from_dict(base).semantic_problems() == []
    for p in ProfileSet.load().profiles:                       # shipped profiles stay valid
        assert p.semantic_problems() == [], (p.profile_id, p.semantic_problems())

    bad = copy.deepcopy(base)
    bad["hk"]["fields"][0]["rel"] = 999
    f1 = next(f for f in bad["hk"]["fields"] if f.get("alert", {}).get("warn"))
    lo, hi = f1["alert"]["warn"]
    f1["alert"]["warn"] = [hi, lo]
    bad["channels"][1]["cavity"] = {"pressure_hk": ["p_typo"]}
    bad["channels"].append(copy.deepcopy(bad["channels"][0]))
    probs = Profile.from_dict(bad).semantic_problems()
    joined = " | ".join(probs)
    for want in ("outside the row", "band reversed", "unknown hk key 'p_typo'", "defined twice"):
        assert want in joined, (want, probs)

    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "bad.json"), "w", encoding="utf-8") as fh:
            json.dump(bad, fh)
        try:
            load_profiles(d)
            raise AssertionError("bad profile loaded")
        except ProfileError as e:
            assert "outside the row" in str(e)

        os.remove(os.path.join(d, "bad.json"))
        for name in ("a", "b"):
            twin = copy.deepcopy(base)
            twin["profile_id"] = f"twin_{name}"
            with open(os.path.join(d, f"{name}.json"), "w", encoding="utf-8") as fh:
                json.dump(twin, fh)
        assert ProfileSet(load_profiles(d)).ambiguous_groups() == [["twin_a", "twin_b"]]
        assert ProfileSet.load().ambiguous_groups() == []
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("test_profile_semantics: OK")


if __name__ == "__main__":
    main()
