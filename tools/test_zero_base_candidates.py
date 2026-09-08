import os
import sys
import copy
import json
import tempfile
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import fit_explorer as FE
from core.data_io import DataIO
from core.doas_fit import (DoasFitter, _aggregate_solver_termination,
                           _endpoint_objectives)
from tools.run_zero_base_stage1 import (alpha_header_channel, alpha_stage2_metadata,
                                        alpha_time_source, load_selected_scans,
                                        main as run_stage_main, report_sampling,
                                        reuse_stage2_samples, select_candidate,
                                        stage1_paths_in_date_range)


def test_zero_base_grid_is_explicit_and_deterministic():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4}
    wave = np.linspace(430.0, 480.0, 401)
    a = FE.zero_base_policy_candidates(cfg, wave)
    b = FE.zero_base_policy_candidates(cfg, wave)
    assert len(a) == 360
    assert [x["id"] for x in a] == [x["id"] for x in b]
    assert all(x["refs_source"] == "FitSet.cfg.refs" for x in a)
    assert all(x["policy_stage"] == "STAGE0_METADATA_ONLY" for x in a)
    assert {x["window_offset_nm"] for x in a} == {-1.0, 0.0, 1.0}
    assert {x["policy"]["shift"]["mode"] for x in a} == {"Fix", "Limit"}


def test_stage1_cli_candidate_selector_uses_explicit_policy():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4,
           "refs": [{"name": "NO2"}]}
    candidates = FE.zero_base_policy_candidates(
        cfg, np.linspace(430.0, 480.0, 401))
    selected = select_candidate(
        candidates, cfg, shift_limit=(-10.0, .5),
        squeeze_limit=(.995, 1.005))
    assert selected["policy"] == {
        "shift": {"mode": "Limit", "lower": -10.0, "upper": .5},
        "squeeze": {"mode": "Limit", "lower": .995, "upper": 1.005}}
    fixed = select_candidate(
        candidates, cfg, shift_fix=-.5, squeeze_fix=1.0)
    assert fixed["policy"] == {
        "shift": {"mode": "Fix", "value": -.5},
        "squeeze": {"mode": "Fix", "value": 1.0}}
    try:
        select_candidate(candidates, cfg, shift_limit=(-3.0, 3.0),
                         squeeze_fix=1.0)
    except StopIteration:
        pass
    else:
        raise AssertionError("policy outside the zero-base grid was accepted")


def test_zero_base_rejects_collapsed_nm_offsets():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4}
    wave = np.linspace(430.0, 480.0, 401)
    try:
        FE.zero_base_policy_candidates(cfg, wave, window_offsets_nm=(-0.01, 0.0, 0.01))
    except ValueError as exc:
        assert "duplicate pixel deltas" in str(exc)
    else:
        raise AssertionError("collapsed offsets must fail closed")


def test_zero_base_stage0_is_fit_free_and_counts():
    class Engine:
        _wave_axis = np.arange(300.0)
        gas_list = ["NO2"]
        raw_references = {"NO2": np.ones(300)}

    candidates = [{"id": "pass", "px_min": 100, "px_max": 200, "poly": 2},
                  {"id": "bad", "px_min": 100, "px_max": 999, "poly": 2}]
    with patch.object(FE.FP, "differential_collinearity",
                      return_value={"multiple_R": {"NO2": 0.1}}):
        report = FE.stage0_candidate_grid(Engine(), candidates)
    assert report["fit_executed"] is False
    assert report["counts"] == {"PASS": 1, "FAIL": 1, "UNAVAILABLE": 0}
    assert report["candidates"][1]["stage0_preflight"]["state"] == "FAIL"


def _translation_fixture():
    cfg = {"f_min": 100, "f_max": 200, "poly_deg": 4,
           "refs": [{"name": "H2O"}, {"name": "NO2"}]}
    props = {
        "H2O": {"sh_mode": "Link", "sh_val": "NO2",
                "sq_mode": "Link", "sq_val": "NO2", "mult": -12},
        "NO2": {"sh_mode": "Center", "sh_val": "-2, 3",
                "sq_mode": "Fix", "sq_val": "1.0", "mult": 0},
    }
    wave = np.linspace(430.0, 480.0, 401)
    candidates = FE.zero_base_policy_candidates(cfg, wave)
    unique = {}
    for candidate in candidates:
        key = repr(candidate["policy"])
        unique.setdefault(key, candidate)
    assert len(unique) == 40
    return cfg, props, list(unique.values())


def test_policy_translation_all_35_round_trip_through_worker():
    cfg, props, candidates = _translation_fixture()
    original_cfg, original_props = copy.deepcopy(cfg), copy.deepcopy(props)
    fake = SimpleNamespace(engine=SimpleNamespace(gas_list=["H2O", "NO2"]))
    for candidate in candidates:
        original_candidate = copy.deepcopy(candidate)
        translated = FE.translate_zero_base_policy(cfg, props, candidate)
        derived = translated["ref_props"]
        assert derived["H2O"] == props["H2O"]
        active, fixed, linked, _, lower, upper = DoasFitter.setup_fit_parameters(
            fake, derived, 0.0, [0.0, 1.0], 1e6)
        policy = candidate["policy"]
        shift = policy["shift"]
        squeeze = policy["squeeze"]
        if shift["mode"] == "Fix":
            assert fixed["NO2_sh"] == shift["value"]
        else:
            index = active.index("NO2_sh")
            assert (lower[index], upper[index]) == (shift["lower"], shift["upper"])
        if squeeze["mode"] == "Fix":
            assert fixed["NO2_sq"] == squeeze["value"]
            assert derived["NO2"]["sq_val"] == "0.0"
        else:
            index = active.index("NO2_sq")
            assert np.allclose((lower[index], upper[index]),
                               (squeeze["lower"], squeeze["upper"]),
                               rtol=0.0, atol=1e-15)
        assert linked["H2O_sh"] == "NO2_sh"
        assert linked["H2O_sq"] == "NO2_sq"
        assert translated["provenance"]["fit_executed"] is False
        assert candidate == original_candidate
    assert cfg == original_cfg
    assert props == original_props


def test_policy_translation_malformed_fails_closed():
    cfg, props, candidates = _translation_fixture()
    base = candidates[0]
    malformed = []
    wrong_stage = copy.deepcopy(base)
    wrong_stage["policy_stage"] = "STAGE1"
    malformed.append(wrong_stage)
    extra = copy.deepcopy(base)
    extra["policy"]["shift"]["extra"] = 1
    malformed.append(extra)
    nan_value = copy.deepcopy(base)
    nan_value["policy"]["shift"] = {"mode": "Fix", "value": float("nan")}
    malformed.append(nan_value)
    reversed_bounds = copy.deepcopy(base)
    reversed_bounds["policy"]["squeeze"] = {"mode": "Limit", "lower": 1.1, "upper": 0.9}
    malformed.append(reversed_bounds)
    bad_fix = copy.deepcopy(base)
    bad_fix["policy"]["squeeze"] = {"mode": "Fix", "value": 1.1}
    malformed.append(bad_fix)
    string_value = copy.deepcopy(base)
    string_value["policy"]["shift"] = {"mode": "Fix", "value": "0.0"}
    malformed.append(string_value)
    missing_id = copy.deepcopy(base)
    del missing_id["id"]
    malformed.append(missing_id)
    for candidate in malformed:
        try:
            FE.translate_zero_base_policy(cfg, props, candidate)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed policy must fail closed")

    missing_target = copy.deepcopy(cfg)
    missing_target["refs"] = [{"name": "H2O"}]
    try:
        FE.translate_zero_base_policy(missing_target, props, base)
    except ValueError as exc:
        assert "target" in str(exc)
    else:
        raise AssertionError("missing target must fail closed")


def test_stage1_one_candidate_budget_and_worker_contract():
    cfg, props, candidates = _translation_fixture()
    original_cfg, original_props = copy.deepcopy(cfg), copy.deepcopy(props)
    scans = [{"id": f"scan{i}"} for i in range(4)]

    def worker(candidate, scan, start, *, ref_props, policy_bounds,
               allow_negative_gas):
        assert allow_negative_gas is True
        assert ref_props["H2O"] == props["H2O"]
        assert ref_props["NO2"]["sh_mode"] == candidate["policy"]["shift"]["mode"]
        assert set(policy_bounds) == {"shift", "squeeze"}
        return {"initial_shift": start["shift"],
                "initial_squeeze": start["squeeze"],
                "final_shift": start["shift"],
                "final_squeeze": start["squeeze"],
                "objective_initial": 10.0, "objective_final": 8.0,
                "solver_termination": {"status": "CONVERGED", "success": True,
                                       "nfev": 3},
                "boundary_hits": []}

    fixed = next(c for c in candidates
                 if c["policy"]["shift"]["mode"] == "Fix"
                 and c["policy"]["squeeze"]["mode"] == "Fix")
    fixed_report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, worker, allow_negative_gas=True)
    assert fixed_report["status"] == "COMPLETE"
    assert fixed_report["planned_attempts"] == 4
    assert fixed_report["budget"]["attempts_per_scan"] == 1
    assert fixed_report["budget"]["seed_stability"] == "NOT_APPLICABLE"
    assert fixed_report["translation"]["scope"] == "TRANSLATION_ONLY_NO_FIT_CLAIM"
    assert fixed_report["translation"]["details"]["fit_executed"] is False
    assert all(row["objective_change"] == -2.0 for row in fixed_report["attempts"])

    modes = (("Limit", "Fix"), ("Fix", "Limit"), ("Limit", "Limit"))
    for sh_mode, sq_mode in modes:
        active = next(c for c in candidates
                      if c["policy"]["shift"]["mode"] == sh_mode
                      and c["policy"]["squeeze"]["mode"] == sq_mode)
        active_report = FE.run_stage1_vertical_slice(
            cfg, props, active, scans, worker, allow_negative_gas=True)
        assert active_report["status"] == "COMPLETE"
        assert active_report["planned_attempts"] == 8
        assert active_report["budget"]["attempts_per_scan"] == 2
        assert active_report["budget"]["seed_stability"] == "PENDING"
        starts = active_report["budget"]["starts"]
        assert len({(s["shift"], s["squeeze"]) for s in starts}) == 2
        assert len({(r["scan_id"], r["start_id"])
                    for r in active_report["attempts"]}) == 8

    active = next(c for c in candidates
                  if c["policy"]["shift"]["mode"] == "Limit"
                  and c["policy"]["squeeze"]["mode"] == "Limit")

    incomplete = FE.run_stage1_vertical_slice(
        cfg, props, active, scans, lambda *a, **k: {}, allow_negative_gas=True)
    assert incomplete["status"] == "ABSTAIN_INCOMPLETE"
    assert incomplete["successful_attempts"] == 0
    assert all(row["exception_class"] == "ValueError" for row in incomplete["attempts"])
    try:
        FE.run_stage1_vertical_slice(cfg, props, active, scans, worker,
                                     allow_negative_gas=False)
    except ValueError as exc:
        assert "explicit" in str(exc)
    else:
        raise AssertionError("implicit/nonnegative Stage 1 policy was accepted")
    assert cfg == original_cfg and props == original_props


def test_stage2_date_distributed_sampling_and_budget_contract():
    cfg, props, candidates = _translation_fixture()
    active = next(c for c in candidates
                  if c["policy"]["shift"]["mode"] == "Limit"
                  and c["policy"]["squeeze"]["mode"] == "Limit")
    with tempfile.TemporaryDirectory() as root:
        records = []
        for index in range(24):
            day = f"2026-06-{1 + index // 4:02d}"
            path = os.path.join(root, f"{day}-{index:02d}.dat")
            open(path, "wb").close()
            timestamp = f"{day} 12:{index:02d}:00"
            records.append({"path": path, "row_index": 0, "date": day,
                            "timestamp": timestamp, "observation_key": timestamp,
                            "time_source": "alpha_header_datetime",
                            "channel": "ANs",
                            "channel_source": "alpha_header_label"})
        selected_a, provenance_a = FE.select_stage2_rows(
            records, "2026-06-01", "2026-06-06", "ANs")
        selected_b, provenance_b = FE.select_stage2_rows(
            list(reversed(records)), "2026-06-01", "2026-06-06", "ANs")
        assert selected_a == selected_b and provenance_a == provenance_b
        assert len(selected_a) == 12
        assert provenance_a["date_range"] == ["2026-06-01", "2026-06-06"]
        assert len({sample["date"] for sample in provenance_a["samples"]}) == 6
        assert provenance_a["state_stratification"] == "NOT_AVAILABLE_NOT_STRATIFIED"
        assert not any(os.path.isabs(sample.get("file", ""))
                       or "path" in sample for sample in provenance_a["samples"])
        assert set(provenance_a["eligible_per_date"]) == {
            f"2026-06-{day:02d}" for day in range(1, 7)}
        assert sum(provenance_a["selected_per_date"].values()) == 12
        assert max(provenance_a["selected_per_date"].values()) <= 3
        shared_file_records = []
        for day_number in range(1, 5):
            shared_path = os.path.join(root, f"shared-{day_number}.dat")
            open(shared_path, "wb").close()
            for row_index in range(3):
                day = f"2026-08-{day_number:02d}"
                timestamp = f"{day} 12:{row_index:02d}:00"
                shared_file_records.append({"path": shared_path,
                    "row_index": row_index, "date": day,
                    "timestamp": timestamp, "observation_key": timestamp,
                    "time_source": "alpha_header_datetime", "channel": "ANs",
                    "channel_source": "alpha_header_label"})
        with patch.object(FE, "sha256_file", wraps=FE.sha256_file) as hashes:
            FE.select_stage2_rows(
                shared_file_records, "2026-08-01", "2026-08-04", "ANs")
        assert hashes.call_count == 4
        pns_records = []
        for index, record in enumerate(records):
            path = os.path.join(root, f"pns-{index:02d}.dat")
            open(path, "wb").close()
            pns_records.append({**record, "path":path, "channel":"PNs"})
        _, pns_provenance = FE.select_stage2_rows(
            pns_records, "2026-06-01", "2026-06-06", "PNs")
        assert ([sample["observation_key"] for sample in pns_provenance["samples"]]
                == [sample["observation_key"] for sample in provenance_a["samples"]])
        cli_scans = [{"id": sample["id"]} for sample in provenance_a["samples"]]
        cli_sampling = report_sampling(provenance_a, cli_scans, "2")
        assert cli_sampling["expected_channel"] == "ANs"
        assert cli_sampling["samples"] == provenance_a["samples"]
        try:
            report_sampling(provenance_a, list(reversed(cli_scans)), "2")
        except ValueError:
            pass
        else:
            raise AssertionError("CLI accepted mismatched Stage 2 provenance")

        many_dates = []
        for index in range(15):
            day = f"2026-07-{index + 1:02d}"
            path = os.path.join(root, f"many-{index:02d}.dat")
            open(path, "wb").close()
            timestamp = f"{day} 00:00:00"
            many_dates.append({"path":path,"row_index":0,"date":day,
                "timestamp":timestamp,"observation_key":timestamp,"channel":"ANs",
                "time_source":"alpha_header_datetime",
                "channel_source":"alpha_header_label"})
        _, many_provenance = FE.select_stage2_rows(
            many_dates, "2026-07-01", "2026-07-15", "ANs")
        assert len([n for n in many_provenance["selected_per_date"].values() if n]) == 12
        assert sum(n == 0 for n in many_provenance["selected_per_date"].values()) == 3
        scans = [{"id": f"scan{i}"} for i in range(12)]

        def worker(candidate, scan, start, **kwargs):
            assert kwargs["allow_negative_gas"] is True
            return {"initial_shift": start["shift"],
                    "initial_squeeze": start["squeeze"],
                    "final_shift": start["shift"],
                    "final_squeeze": start["squeeze"],
                    "objective_initial": 2.0, "objective_final": 1.0,
                    "solver_termination": {"status": "CONVERGED", "success": True,
                                           "nfev": 1}, "boundary_hits": []}
        report = FE.run_stage2_vertical_slice(
            cfg, props, active, scans, worker, allow_negative_gas=True)
        assert report["schema"] == FE.STAGE2_VERTICAL_SLICE_SCHEMA
        assert report["planned_attempts"] == report["executed_attempts"] == 24
        assert FE.run_stage1_vertical_slice(
            cfg, props, active, scans[:4], worker,
            allow_negative_gas=True)["planned_attempts"] == 8
        for bad_scans in (scans[:11], scans + [{"id": "scan12"}]):
            try:
                FE.run_stage2_vertical_slice(
                    cfg, props, active, bad_scans, worker,
                    allow_negative_gas=True)
            except ValueError:
                pass
            else:
                raise AssertionError("non-12 Stage 2 budget was accepted")

        bad_cases = (records[:11],
                     [{**record, "date": ""} for record in records],
                     [{**record, "channel": "PNs"} for record in records],
                     [{**record, "channel_source": "cli"} for record in records],
                     [{**record, "observation_key": "made-up"} for record in records],
                     [{**record, "timestamp": "not-a-time",
                       "observation_key": "not-a-time"} for record in records],
                     [record for record in records if record["date"] < "2026-06-04"])
        for bad in bad_cases:
            try:
                FE.select_stage2_rows(bad, "2026-06-01", "2026-06-06", "ANs")
            except ValueError:
                pass
            else:
                raise AssertionError("invalid Stage 2 population was accepted")
        alias = os.path.join(root, "alias.dat")
        os.link(records[0]["path"], alias)
        try:
            FE.select_stage2_rows(
                records + [{**records[0], "path": alias}],
                "2026-06-01", "2026-06-06", "ANs")
        except ValueError as exc:
            assert "alias" in str(exc)
        else:
            raise AssertionError("physical alias was accepted")

        header_path = os.path.join(root, "header.dat")
        with open(header_path, "w", encoding="utf-8") as fh:
            fh.write("# channel=2  label=pNs\nrow_idx\tdatetime\n")
        assert alpha_header_channel(header_path) == {
            "index": 2, "label": "PNs", "source": "alpha_header_label"}
        assert alpha_time_source(header_path) == "alpha_header_datetime"

        mixed_case = [{**record, "channel": "aNs"} for record in records]
        _, mixed_provenance = FE.select_stage2_rows(
            mixed_case, "2026-06-01", "2026-06-06", "ANs")
        assert mixed_provenance["expected_channel"] == "ANs"
        try:
            FE.select_stage2_rows(
                mixed_case, "2026-06-01", "2026-06-06", "PNs")
        except ValueError as exc:
            assert "does not match" in str(exc)
        else:
            raise AssertionError("mismatched canonical channel was accepted")

        for unknown_expected in ("mystery", "ANs-extra", ""):
            try:
                FE.select_stage2_rows(
                    records, "2026-06-01", "2026-06-06", unknown_expected)
            except ValueError:
                pass
            else:
                raise AssertionError("unknown expected channel was accepted")
        unknown_records = [{**record, "channel": "mystery"}
                           for record in records]
        try:
            FE.select_stage2_rows(
                unknown_records, "2026-06-01", "2026-06-06", "mystery")
        except ValueError:
            pass
        else:
            raise AssertionError("unknown record channel was accepted")

        lopsided = records[:4] + [
            {**records[4], "path": os.path.join(root, f"lopsided-{index}.dat"),
             "row_index": index, "timestamp": f"2026-06-02 15:{index:02d}:00",
             "observation_key": f"2026-06-02 15:{index:02d}:00"}
            for index in range(20)] + records[8:12] + records[12:16]
        for record in lopsided[4:24]:
            open(record["path"], "wb").close()
        _, lopsided_provenance = FE.select_stage2_rows(
            lopsided, "2026-06-01", "2026-06-04", "ANs")
        assert set(lopsided_provenance["selected_per_date"].values()) == {3}
        capped_short = records[:3] + lopsided[4:24] + records[8:11] + records[12:14]
        try:
            FE.select_stage2_rows(capped_short, "2026-06-01", "2026-06-04", "ANs")
        except ValueError as exc:
            assert "cap" in str(exc)
        else:
            raise AssertionError("population below capped budget was accepted")

        duplicate = list(records)
        duplicate[1] = {**duplicate[1],
                        "timestamp": duplicate[0]["timestamp"],
                        "observation_key": duplicate[0]["observation_key"]}
        try:
            FE.select_stage2_rows(duplicate, "2026-06-01", "2026-06-06", "ANs")
        except ValueError as exc:
            assert "duplicated" in str(exc)
        else:
            raise AssertionError("duplicate timestamp was accepted")

        fallback_path = os.path.join(root, "alpha_2026-06-01_fallback.dat")
        with open(fallback_path, "w", encoding="utf-8") as fh:
            fh.write("# channel=1 label=ANs\n")
            fh.write("row_idx\tdoy\tdatetime\tT_C\tP_mbar\tpx0\n")
            fh.write("0\t152.5\tnot-a-time\t25\t1000\t1\n")
        real_open = open
        with patch("builtins.open", side_effect=real_open) as mocked_open:
            fallback_channel, fallback_rows = alpha_stage2_metadata(fallback_path)
        assert sum(call.args and call.args[0] == fallback_path
                   for call in mocked_open.call_args_list) == 1
        assert fallback_channel["label"] == "ANs"
        assert fallback_rows[0][2] == "alpha_header_doy_with_filename_year"
        assert fallback_rows[0][1] == datetime(2026, 6, 1, 12)

        duplicate_header = os.path.join(root, "duplicate-header.dat")
        with open(duplicate_header, "w", encoding="utf-8") as fh:
            fh.write("# channel=1 label=ANs\n# channel=1 label=ANs\n")
            fh.write("row_idx\tdatetime\n0\t2026-06-01 12:00:00\n")
        try:
            alpha_stage2_metadata(duplicate_header)
        except ValueError as exc:
            assert "duplicated" in str(exc)
        else:
            raise AssertionError("duplicate channel headers were accepted")

        conflicting_header = os.path.join(root, "conflicting-header.dat")
        with open(conflicting_header, "w", encoding="utf-8") as fh:
            fh.write("# channel=1 label=ANs\n# channel=2 label=PNs\n")
            fh.write("row_idx\tdatetime\n0\t2026-06-01 12:00:00\n")
        try:
            alpha_stage2_metadata(conflicting_header)
        except ValueError as exc:
            assert "duplicated" in str(exc)
        else:
            raise AssertionError("conflicting channel headers were accepted")

        dated_paths = []
        for day in ("2026-05-31", "2026-06-01", "2026-06-02", "2026-06-03"):
            folder = os.path.join(root, day)
            os.makedirs(folder)
            path = os.path.join(folder, "alpha.dat")
            open(path, "wb").close()
            dated_paths.append(path)
        in_range = stage1_paths_in_date_range(
            dated_paths, datetime(2026, 6, 1).date(), datetime(2026, 6, 2).date())
        assert in_range == dated_paths[1:3]
        stage1_rows = [(path, row) for path in in_range for row in range(2)]
        selected_stage1, _ = FE.select_representative_rows(stage1_rows, 4)
        assert all(os.path.basename(os.path.dirname(path)) in {"2026-06-01", "2026-06-02"}
                   for path, _ in selected_stage1)

        with patch.object(FE, "sha256_file", wraps=FE.sha256_file) as hashes:
            selected_stage2, sampling_stage2 = FE.select_stage2_rows(
                shared_file_records, "2026-08-01", "2026-08-04", "ANs")
            with patch.object(DataIO, "load_alpha_trace_row_mapped",
                              return_value=([1.0], [2.0], 25.0, 1000.0, 0)):
                cli_scans = load_selected_scans(selected_stage2, sampling_stage2)
        assert hashes.call_count == 4
        assert [scan["id"] for scan in cli_scans] == [
            sample["id"] for sample in sampling_stage2["samples"]]


def test_stage2_manifest_reuse_revalidates_selected_rows_only():
    with tempfile.TemporaryDirectory() as root:
        paths, samples = [], []
        for index in range(12):
            day = f"2026-06-{1 + index // 3:02d}"
            timestamp = f"{day} 12:{index:02d}:00.123000"
            path = os.path.join(root, f"sample-{index:02d}.dat")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("# channel=1 label=ANs\nrow_idx\tdatetime\n")
                fh.write(f"0\t{timestamp}\n")
            digest = FE.sha256_file(path)
            name = os.path.basename(path)
            samples.append({"id":f"{name}#sha256={digest[:12]}#row=0",
                "file":name,"sha256":digest,"row_index":0,"date":day,
                "timestamp":timestamp,"observation_key":timestamp,
                "time_source":"alpha_header_datetime","channel":"ANs",
                "channel_source":"alpha_header_label"})
            paths.append(path)
        sampling = {"contract":FE.STAGE2_SAMPLE_CONTRACT,"requested_scans":12,
            "date_range":["2026-06-01","2026-06-04"],"expected_channel":"ANs",
            "selected_per_date":{f"2026-06-{n:02d}":3 for n in range(1,5)},
            "samples":samples}
        manifest = os.path.join(root, "prior-stage2.json")
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump({"sampling":sampling}, fh)
        unrelated = os.path.join(root, "unrelated.dat")
        os.link(paths[0], unrelated)
        selected, reused = reuse_stage2_samples(
            manifest, list(reversed(paths)) + [unrelated],
            date(2026,6,1), date(2026,6,4), "aNs")
        assert selected == [(path, 0) for path in paths]
        assert reused["samples"] == samples
        assert reused["manifest_reuse"] == {"status":"REVALIDATED",
            "sample_order":"PRESERVED","file":"prior-stage2.json",
            "sha256":FE.sha256_file(manifest)}
        assert not any(os.path.isabs(value) for value in reused["manifest_reuse"].values()
                       if isinstance(value, str))

        for field, value in (("sha256", "0" * 64), ("row_index", 1),
                             ("timestamp", "2026-06-01 00:00:00"),
                             ("observation_key", "2026-06-01 00:00:00"),
                             ("channel", "PNs"), ("date", "2026-06-02")):
            bad = copy.deepcopy(sampling)
            bad["samples"][0][field] = value
            bad_manifest = os.path.join(root, f"bad-{field}.json")
            with open(bad_manifest, "w", encoding="utf-8") as fh:
                json.dump({"sampling":bad}, fh)
            try:
                reuse_stage2_samples(bad_manifest, paths, date(2026,6,1),
                                     date(2026,6,4), "ANs")
            except ValueError:
                pass
            else:
                raise AssertionError(f"tampered manifest {field} was accepted")

        duplicate = copy.deepcopy(sampling)
        duplicate["samples"][1] = copy.deepcopy(duplicate["samples"][0])
        duplicate_manifest = os.path.join(root, "duplicate.json")
        with open(duplicate_manifest, "w", encoding="utf-8") as fh:
            json.dump({"sampling":duplicate}, fh)
        aliased = copy.deepcopy(sampling)
        aliased["samples"][1] = {**copy.deepcopy(aliased["samples"][0]),
            "file":"unrelated.dat",
            "id":f"unrelated.dat#sha256={samples[0]['sha256'][:12]}#row=0"}
        alias_manifest = os.path.join(root, "alias.json")
        with open(alias_manifest, "w", encoding="utf-8") as fh:
            json.dump({"sampling":aliased}, fh)
        try:
            reuse_stage2_samples(alias_manifest, paths + [unrelated],
                                 date(2026,6,1), date(2026,6,4), "ANs")
        except ValueError as exc:
            assert "alias" in str(exc)
        else:
            raise AssertionError("physical alias was accepted")
        ambiguous_paths = paths + [os.path.join(root, "copy", samples[0]["file"])]
        for target_manifest, current_paths in ((duplicate_manifest, paths),
                                                (manifest, paths[1:]),
                                                (manifest, ambiguous_paths)):
            if current_paths is ambiguous_paths:
                os.makedirs(os.path.dirname(current_paths[-1]))
                with open(paths[0], "rb") as source, open(current_paths[-1], "wb") as dest:
                    dest.write(source.read())
            try:
                reuse_stage2_samples(target_manifest, current_paths,
                                     date(2026,6,1), date(2026,6,4), "ANs")
            except ValueError:
                pass
            else:
                raise AssertionError("missing, duplicated, or ambiguous sample was accepted")
        try:
            run_stage_main(["--fitset","x","--alpha-glob","x","--output","x",
                            "--date-from","2026-06-01","--date-to","2026-06-04",
                            "--stage","1","--sample-manifest",manifest])
        except SystemExit as exc:
            assert "requires --stage 2" in str(exc)
        else:
            raise AssertionError("Stage 1 accepted a Stage 2 sample manifest")


def test_stage1_worker_output_cannot_override_or_leak():
    cfg, props, candidates = _translation_fixture()
    scans = [{"id": f"scan{i}"} for i in range(4)]
    fixed = next(c for c in candidates
                 if c["policy"]["shift"]["mode"] == "Fix"
                 and c["policy"]["squeeze"]["mode"] == "Fix")

    def bad_extra(candidate, scan, start, **kwargs):
        return {"initial_shift": start["shift"], "initial_squeeze": start["squeeze"],
                "final_shift": start["shift"], "final_squeeze": start["squeeze"],
                "objective_initial": 2.0, "objective_final": 1.0,
                "solver_termination": {"status": "OK", "success": True, "nfev": 1},
                "boundary_hits": [], "status": "OK", "path": "C:\\secret\\raw.txt"}

    report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, bad_extra, allow_negative_gas=True)
    assert report["status"] == "ABSTAIN_INCOMPLETE"
    assert all("path" not in row and row["status"] == "UNAVAILABLE"
               for row in report["attempts"])

    def changed_fixed(candidate, scan, start, **kwargs):
        row = bad_extra(candidate, scan, start, **kwargs)
        row.pop("status"); row.pop("path")
        row["final_shift"] += 1e-6
        return row

    report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, changed_fixed, allow_negative_gas=True)
    assert report["status"] == "ABSTAIN_INCOMPLETE"
    assert all(row["exception_class"] == "ValueError" for row in report["attempts"])

    def sensitive_termination(candidate, scan, start, **kwargs):
        row = changed_fixed(candidate, scan, start, **kwargs)
        row["final_shift"] = start["shift"]
        row["solver_termination"] = {"status": "C:\\secret\\solver.log",
                                     "success": True, "nfev": 1}
        return row

    report = FE.run_stage1_vertical_slice(
        cfg, props, fixed, scans, sensitive_termination, allow_negative_gas=True)
    assert report["status"] == "ABSTAIN_INCOMPLETE"
    assert "secret" not in repr(report)


def test_production_adapter_maps_real_engine_contract():
    cfg, props, candidates = _translation_fixture()
    candidate = next(c for c in candidates
                     if c["policy"]["shift"]["mode"] == "Limit"
                     and c["policy"]["squeeze"]["mode"] == "Limit")
    scan = {"id": "s0", "wave": np.arange(300.), "alpha": np.ones(300),
            "temperature_C": 25., "pressure_mbar": 1013., "px_start": 0}
    class Fitter:
        pass
    engine = SimpleNamespace(gas_list=["H2O", "NO2"])
    translated = FE.translate_zero_base_policy(cfg, props, candidate)["ref_props"]
    with patch.object(FE.PO, "fit_scan") as mocked:
        mocked.return_value = {
            "shifts": {"NO2": candidate["policy"]["shift"]["lower"]},
            "squeezes": {"NO2": 1.0},
            "solver_diagnostics": {"objective_initial": 4.0,
                                   "objective_final": 1.0,
                                   "solver_termination": {
                                       "status": "CONVERGED", "success": True,
                                       "nfev": 7}}}
        callback = FE.production_stage1_callback(engine, Fitter(), cfg)
        start = FE.stage1_policy_starts(candidate)["starts"][0]
        bounds = {"shift": {"mode": "INTERVAL", **{
                      "lower": candidate["policy"]["shift"]["lower"],
                      "upper": candidate["policy"]["shift"]["upper"]}},
                  "squeeze": {"mode": "INTERVAL", **{
                      "lower": candidate["policy"]["squeeze"]["lower"],
                      "upper": candidate["policy"]["squeeze"]["upper"]}}}
        out = callback(candidate, scan, start, ref_props=translated,
                       policy_bounds=bounds, allow_negative_gas=True)
    assert out["solver_termination"]["nfev"] == 7
    assert out["boundary_hits"] == [{"parameter": "shift", "side": "lower",
                                     "value": bounds["shift"]["lower"],
                                     "bound": bounds["shift"]["lower"]}]
    assert mocked.call_args.kwargs["return_solver_diagnostics"] is True
    assert mocked.call_args.kwargs["allow_negative_gas"] is True


def test_solver_diagnostics_are_comparable_and_max_nfev_reachable():
    termination = _aggregate_solver_termination([
        {"status": 1, "success": True, "nfev": 3},
        {"status": 0, "success": False, "nfev": 9}])
    assert termination == {"status": "MAX_NFEV", "success": False, "nfev": 12}
    final_irls_weight = 3.0
    calls = []
    def final_objective(theta):
        calls.append(float(theta[0]))
        return np.array([final_irls_weight * (theta[0] - 2.0)])
    initial, final = _endpoint_objectives(final_objective, [0.0], [1.0])
    assert calls == [0.0, 1.0]
    assert initial == 36.0 and final == 9.0


if __name__ == "__main__":
    test_zero_base_grid_is_explicit_and_deterministic()
    test_stage1_cli_candidate_selector_uses_explicit_policy()
    test_zero_base_rejects_collapsed_nm_offsets()
    test_zero_base_stage0_is_fit_free_and_counts()
    test_policy_translation_all_35_round_trip_through_worker()
    test_policy_translation_malformed_fails_closed()
    test_stage1_one_candidate_budget_and_worker_contract()
    test_stage2_date_distributed_sampling_and_budget_contract()
    test_stage2_manifest_reuse_revalidates_selected_rows_only()
    test_stage1_worker_output_cannot_override_or_leak()
    test_production_adapter_maps_real_engine_contract()
    test_solver_diagnostics_are_comparable_and_max_nfev_reachable()
    print("test_zero_base_candidates: PASS")
