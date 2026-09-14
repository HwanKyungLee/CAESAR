"""Small contract checks for the FitSet-free V2 mission planner."""
from __future__ import annotations

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer_v2 as V2


def _hash(char):
    return char * 64


def _mission():
    return {"schema": V2.MISSION_SCHEMA, "mission_id": "opaque-mission",
            "channels": [{"channel_id": "detector-blue-x", "alpha_inputs": [
                {"observation_id": "o-1", "content_hash": _hash("a")},
                {"observation_id": "o-2", "content_hash": _hash("b")}],
                "wavelength": {"unit": "nm", "values": [430., 431., 432., 433., 434., 435., 436., 437.]},
                "references": [
                    {"species_id": "Species_A", "wavelength_nm": [429., 432., 435., 438.],
                     "values": [1., 2., 3., 4.], "cross_section_unit": "arb", "ils_state": "ALREADY_CONVOLVED"},
                    {"species_id": "Species_B", "wavelength_nm": [429., 432., 435., 438.],
                     "values": [4., 3., 2., 1.], "cross_section_unit": "arb", "ils_state": "NEEDS_RUNTIME_CONVOLUTION"}]}],
            "search_policy": {"windows_nm": [[431., 436.]], "poly_degrees": [1, 2],
                "registration_policies": [{"driver_species": "Species_A",
                    "shift": {"mode": "Limit", "lower": -1., "upper": 1.},
                    "squeeze": {"mode": "Limit", "lower": .9999, "upper": 1.0001}}],
                "split": {"discovery": ["o-1"], "validation": [], "holdout": ["o-2"]},
                "budget": {"max_fit_attempts": 20, "closure_max_attempts": 4}}}


def test_mission_plan_is_generic_stable_and_input_bound():
    mission = _mission()
    first, second = V2.build_mission_plan(mission), V2.build_mission_plan(copy.deepcopy(mission))
    assert first["plan_hash"] == second["plan_hash"] and first["candidates"]
    assert {row["channel_id"] for row in first["candidates"]} == {"detector-blue-x"}
    assert {row["registration"]["driver_species"] for row in first["candidates"]} == {"Species_A"}
    assert first["candidates"][0]["runtime_spec"]["reference_order"] == ["Species_A", "Species_B"]
    changed = copy.deepcopy(mission); changed["channels"][0]["alpha_inputs"][0]["content_hash"] = _hash("c")
    changed_plan = V2.build_mission_plan(changed)
    assert changed_plan["plan_hash"] != first["plan_hash"]
    assert changed_plan["candidates"][0]["candidate_id"] != first["candidates"][0]["candidate_id"]


def test_mission_plan_rejects_unknown_units_and_holdout_overlap():
    bad = _mission(); bad["channels"][0]["wavelength"]["unit"] = "unknown"
    try:
        V2.build_mission_plan(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown wavelength unit was accepted")
    bad = _mission(); bad["search_policy"]["split"]["holdout"] = ["o-1"]
    try:
        V2.build_mission_plan(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("holdout overlap was accepted")
    bad = _mission(); bad["search_policy"]["registration_policies"][0]["driver_species"] = "Species_B"
    bad["channels"][0]["references"] = bad["channels"][0]["references"][:1]
    try:
        V2.build_mission_plan(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("missing registration driver was accepted")


def main():
    test_mission_plan_is_generic_stable_and_input_bound()
    test_mission_plan_rejects_unknown_units_and_holdout_overlap()
    test_geometry_metadata_and_vectors()
    print("test_fit_explorer_v2: PASS")


def test_geometry_metadata_and_vectors():
    mission = _mission()
    mission["search_policy"]["windows_nm"] = [[430., 437.], [431., 437.], [431.1, 437.], [432., 437.]]
    mission["search_policy"]["poly_degrees"] = [0, 1, 2]
    mission["channels"][0]["alpha_inputs"][0].update(block_id="day1", date="2026-06-01", previously_used=True)
    plan = V2.build_mission_plan(mission)
    assert len({row["candidate_id"] for row in plan["candidates"]}) == len(plan["candidates"])
    assert all(row["planned_fit_attempts"] == 2 for row in plan["candidates"])
    assert plan["edges"] and {edge["kind"] for edge in plan["edges"]} == {"poly", "window_px_min"}
    by_id = {row["candidate_id"]: row for row in plan["candidates"]}
    assert all(abs(by_id[edge["left_candidate_id"]]["px_min"] - by_id[edge["right_candidate_id"]]["px_min"]) <= 1 for edge in plan["edges"])
    other = copy.deepcopy(mission["channels"][0]); other["channel_id"] = "other"
    other["alpha_inputs"] = [{"observation_id": "other1", "content_hash": _hash("d")}]
    other["references"] = other["references"][1:]
    mission["channels"].append(other)
    registration = copy.deepcopy(mission["search_policy"]["registration_policies"][0]); registration["driver_species"] = "Species_B"
    mission["search_policy"]["registration_policies"].append(registration)
    plan = V2.build_mission_plan(mission)
    assert {row["channel_id"] for row in plan["candidates"]} == {"detector-blue-x", "other"}
    assert not any(edge["kind"] == "registration_explicit" for edge in plan["edges"])
    mission["channels"][0]["wavelength"]["values"] = [[430., 431.], [432., 433.]]
    try:
        V2.build_mission_plan(mission)
    except ValueError:
        pass
    else:
        raise AssertionError("multidimensional wavelength silently flattened")


if __name__ == "__main__":
    main()
