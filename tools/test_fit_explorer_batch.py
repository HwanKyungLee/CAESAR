"""Contract tests for mission-agnostic batch execution and resume."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import fit_explorer_batch as FB
from tools.run_fit_explorer_batch import (code_hash, reject_cross_channel_alpha_aliases,
                                          validate_stage1_selected_channels)


def _policy(lo=-1.0, hi=1.0):
    return {"shift": {"mode": "Limit", "lower": lo, "upper": hi},
            "squeeze": {"mode": "Limit", "lower": .9999, "upper": 1.0001}}


def _config(root, stage=1):
    channels = []
    for label in ("ANs", "PNs", "cold"):
        entry = {"label": label, "fitset": os.path.join(root, "fitset.json"),
                 "alpha_glob": os.path.join(root, label, "*.dat"),
                 "candidates": [{"id": "candidate-a", "policy": _policy()}]}
        if stage == 2:
            entry["sample_manifest"] = os.path.join(root, label + "-samples.json")
        channels.append(entry)
    return {"schema": FB.SCHEMA, "mission": "opaque-fixture", "stage": stage,
            "allow_negative_gas": True, "output_root": os.path.join(root, "out"),
            "date_range": ["2026-05-01", "2026-06-30"], "channels": channels}


def _prepared(config, suffix="a"):
    out = {}
    for channel in config["channels"]:
        declaration = channel["candidates"][0]
        out[channel["label"]] = {"input_hash": (suffix * 64)[:64],
            "candidates": {declaration["id"]: {"id": declaration["id"],
                                               "policy": declaration["policy"]}},
            "context": {"private_path": r"C:\secret\mission\alpha.dat"}}
    return out


def _result(candidate_id, stage=1):
    return {"schema": f"stage{stage}-one-candidate-v1", "candidate_id": candidate_id,
        "status": "COMPLETE", "policy": {"allow_negative_gas": True},
        "budget": {}, "translation": {}, "policy_bounds": {},
        "planned_attempts": 0, "executed_attempts": 0, "successful_attempts": 0,
        "objective_change_convention": "final_minus_initial", "attempts": [],
        "limitations": ["No T2 verdict"], "sampling": {}, "source": {}}


def test_public_result_allows_iso_date_sampling_maps_but_rejects_bad_keys():
    good = _result("candidate-a", stage=2)
    good["sampling"] = {"selected_per_date": {"2026-05-26": 1},
                        "eligible_per_date": {"2026-05-26": 3}}
    assert FB.validate_public_result(good, stage=2,
                                     candidate_id="candidate-a")["sampling"] == good["sampling"]
    for bad_key in ("2026/05/26", r"C:\\secret\\alpha.dat", "not-a-date"):
        bad = _result("candidate-a", stage=2)
        bad["sampling"] = {"selected_per_date": {bad_key: 1}}
        try:
            FB.validate_public_result(bad, stage=2, candidate_id="candidate-a")
        except ValueError:
            pass
        else:
            raise AssertionError("malformed per-date sampling key was accepted")
    for bad_count in (-1, True, 1.5):
        bad = _result("candidate-a", stage=2)
        bad["sampling"] = {"selected_per_date": {"2026-05-26": bad_count}}
        try:
            FB.validate_public_result(bad, stage=2, candidate_id="candidate-a")
        except ValueError:
            pass
        else:
            raise AssertionError("malformed per-date sampling count was accepted")


def test_public_result_allows_slashes_in_prose_but_rejects_absolute_paths():
    good = _result("candidate-a", stage=2)
    good["sampling"] = {"independence_note": "Rows within one file/date are repeated"}
    FB.validate_public_result(good, stage=2, candidate_id="candidate-a")
    bad = _result("candidate-a", stage=2)
    bad["sampling"] = {"independence_note": "C:/private/input.dat"}
    try:
        FB.validate_public_result(bad, stage=2, candidate_id="candidate-a")
    except ValueError:
        pass
    else:
        raise AssertionError("absolute path-like prose was accepted")


def test_validation_is_fail_closed():
    with tempfile.TemporaryDirectory() as root:
        good = _config(root)
        FB.validate_config(good)
        variants = []
        bad = json.loads(json.dumps(good)); bad["allow_negative_gas"] = False; variants.append(bad)
        bad = json.loads(json.dumps(good)); bad["channels"][0]["label"] = "mystery"; variants.append(bad)
        bad = json.loads(json.dumps(good)); bad["channels"][1]["alpha_glob"] = bad["channels"][0]["alpha_glob"]; variants.append(bad)
        bad = json.loads(json.dumps(good)); bad["channels"][0]["candidates"] *= 2; variants.append(bad)
        bad = json.loads(json.dumps(good)); bad["channels"][0]["candidates"] = [
            {"id": "Case", "policy": _policy()}, {"id": "case", "policy": _policy()}]; variants.append(bad)
        bad = json.loads(json.dumps(good)); bad["channels"][0]["candidates"] = [
            {"id": "trail", "policy": _policy()}, {"id": "trail.", "policy": _policy()}]; variants.append(bad)
        bad = json.loads(json.dumps(good)); bad["channels"][0]["candidates"][0]["id"] = "CON.txt"; variants.append(bad)
        bad = _config(root, stage=2); del bad["channels"][0]["sample_manifest"]; variants.append(bad)
        for document in variants:
            try:
                FB.validate_config(document)
            except ValueError:
                pass
            else:
                raise AssertionError("invalid batch config was accepted")


def test_three_channels_resume_stale_and_failure_isolation():
    with tempfile.TemporaryDirectory() as root:
        config = _config(root)
        prepared = _prepared(config)
        calls = []
        def executor(label, candidate, context):
            calls.append((label, candidate["id"]))
            if label == "PNs":
                raise RuntimeError(r"private C:\secret\mission\alpha.dat")
            return _result(candidate["id"])
        first = FB.run_prepared_batch(config, prepared, executor, code_hash="1" * 64)
        assert first["counts"] == {"COMPLETE": 2, "INCOMPLETE": 1, "PLANNED": 0}
        assert len(calls) == 3
        second = FB.run_prepared_batch(config, prepared, executor, code_hash="1" * 64)
        assert len(calls) == 4 and calls[-1][0] == "PNs"
        assert sum(row["action"] == "SKIPPED_VALID" for row in second["candidates"]) == 2
        # A new code hash gets a new evidence directory and preserves old reports.
        FB.run_prepared_batch(config, prepared, lambda _l, c, _x: _result(c["id"]),
                              code_hash="2" * 64)
        reports = []
        for base, _, files in os.walk(config["output_root"]):
            reports.extend(os.path.join(base, name) for name in files if name == "report.json")
        assert len(reports) == 5
        text = "\n".join(open(path, encoding="utf-8").read() for path in reports)
        assert "secret" not in text and "alpha.dat" not in text
        # Mutable failure checkpoint also records only the exception type.
        checkpoints = []
        for base, _, files in os.walk(config["output_root"]):
            checkpoints.extend(os.path.join(base, name) for name in files if name == "checkpoint.json")
        assert "private" not in "\n".join(open(path, encoding="utf-8").read()
                                             for path in checkpoints)


def test_dry_run_writes_nothing_and_prepared_contract_precedes_execution():
    with tempfile.TemporaryDirectory() as root:
        config = _config(root)
        prepared = _prepared(config)
        called = []
        report = FB.run_prepared_batch(config, prepared,
            lambda *args: called.append(args), code_hash="3" * 64, dry_run=True)
        assert report["counts"]["PLANNED"] == 3 and not called
        assert not os.path.exists(config["output_root"])
        broken = dict(prepared); del broken["cold"]
        try:
            FB.run_prepared_batch(config, broken, lambda *args: called.append(args),
                                  code_hash="3" * 64)
        except ValueError:
            pass
        else:
            raise AssertionError("partial preparation was accepted")
        assert not called


def test_immutable_atomic_write_rejects_collision():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "report.json")
        FB.atomic_write_json(path, {"a": 1}, immutable=True)
        FB.atomic_write_json(path, {"a": 1}, immutable=True)
        try:
            FB.atomic_write_json(path, {"a": 2}, immutable=True)
        except FileExistsError:
            pass
        else:
            raise AssertionError("immutable evidence was overwritten")


def test_public_payload_privacy_and_resume_integrity():
    with tempfile.TemporaryDirectory() as root:
        config = _config(root); prepared = _prepared(config)
        calls = []
        first = FB.run_prepared_batch(config, prepared,
            lambda _l, c, _x: calls.append(c["id"]) or _result(c["id"]),
            code_hash="4" * 64)
        assert len(calls) == 3 and "config_hash" in first
        reports = []
        for base, _, files in os.walk(config["output_root"]):
            reports += [os.path.join(base, name) for name in files if name == "report.json"]
        report_path = reports[0]
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
        candidate_root = os.path.dirname(os.path.dirname(report_path))
        checkpoint_path = os.path.join(candidate_root, "checkpoint.json")
        os.remove(checkpoint_path)
        FB.run_prepared_batch(config, prepared,
            lambda _l, c, _x: calls.append(c["id"]) or _result(c["id"]),
            code_hash="4" * 64)
        assert len(calls) == 3
        with open(checkpoint_path, encoding="utf-8") as fh:
            assert json.load(fh)["state"] == "COMPLETE"
        with open(checkpoint_path, "w", encoding="utf-8") as fh:
            json.dump({"state": "RUNNING"}, fh)
        FB.run_prepared_batch(config, prepared,
            lambda _l, c, _x: calls.append(c["id"]) or _result(c["id"]),
            code_hash="4" * 64)
        assert len(calls) == 3
        with open(checkpoint_path, encoding="utf-8") as fh:
            assert json.load(fh)["state"] == "COMPLETE"
        # A torn immutable report is preserved and never sent to the expensive executor.
        report["result"]["status"] = "TAMPERED"
        with open(report_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh)
        before = open(report_path, "rb").read()
        rerun = FB.run_prepared_batch(config, prepared,
            lambda _l, c, _x: calls.append(c["id"]) or _result(c["id"]),
            code_hash="4" * 64)
        assert open(report_path, "rb").read() == before
        assert any(row["action"] == "COLLISION_PRESERVED" for row in rerun["candidates"])
        assert len(calls) == 3
        # Arbitrary/private executor output becomes an isolated failure, never evidence.
        other = _config(os.path.join(root, "private")); other_prepared = _prepared(other)
        outcome = FB.run_prepared_batch(other, other_prepared,
            lambda *_: {**_result("candidate-a"), "message": r"C:\\secret\\alpha.dat"},
            code_hash="5" * 64)
        assert outcome["counts"]["INCOMPLETE"] == 3
        text = ""
        for base, _, files in os.walk(other["output_root"]):
            for name in files:
                text += open(os.path.join(base, name), encoding="utf-8").read()
        assert "secret" not in text and "alpha.dat" not in text


def test_multiple_candidates_versioned_summaries_and_dependency_hash():
    with tempfile.TemporaryDirectory() as root:
        config = _config(root)
        for channel in config["channels"]:
            channel["candidates"].append({"id": "candidate-b", "policy": _policy(-5, 5)})
        prepared = {}
        for channel in config["channels"]:
            prepared[channel["label"]] = {"input_hash": "a" * 64,
                "candidates": {entry["id"]: {"id": entry["id"], "policy": entry["policy"]}
                               for entry in channel["candidates"]}, "context": {}}
        result = FB.run_prepared_batch(config, prepared,
            lambda _l, c, _x: _result(c["id"]), code_hash="6" * 64)
        assert result["counts"]["COMPLETE"] == 6
        summaries = []
        for base, _, files in os.walk(config["output_root"]):
            summaries += [name for name in files if name.startswith("summary-")]
        assert len(summaries) == 1 and not any(name == "summary.json" for name in summaries)
        os.makedirs(os.path.join(root, "core")); os.makedirs(os.path.join(root, "tools"))
        dep = os.path.join(root, "core", "dependency.py")
        with open(dep, "w", encoding="utf-8") as fh: fh.write("VALUE = 1\n")
        before = code_hash(root)
        with open(dep, "w", encoding="utf-8") as fh: fh.write("VALUE = 2\n")
        assert code_hash(root) != before


def test_cross_channel_physical_alias_is_rejected():
    with tempfile.TemporaryDirectory() as root:
        config = _config(root)
        first = os.path.join(root, "ANs", "one.dat")
        second = os.path.join(root, "PNs", "alias.dat")
        os.makedirs(os.path.dirname(first)); os.makedirs(os.path.dirname(second))
        with open(first, "w", encoding="utf-8") as fh:
            fh.write("fixture")
        try:
            os.link(first, second)
        except OSError:
            return
        try:
            reject_cross_channel_alpha_aliases(config)
        except ValueError:
            pass
        else:
            raise AssertionError("cross-channel hardlink alias was accepted")


def test_stage1_relabel_is_rejected_before_fit():
    with tempfile.TemporaryDirectory() as root:
        path = os.path.join(root, "alpha.dat")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# channel=1 label=PNs\nrow_idx\n")
        try:
            validate_stage1_selected_channels([(path, 0)], "ANs")
        except ValueError:
            pass
        else:
            raise AssertionError("Stage 1 relabelled alpha was accepted")


def test_cli_no_data_abstains_before_fit():
    with tempfile.TemporaryDirectory() as root:
        config = _config(root)
        path = os.path.join(root, "batch.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        run = subprocess.run([sys.executable, os.path.join(ROOT, "tools",
            "run_fit_explorer_batch.py"), "--config", path, "--dry-run"],
            cwd=ROOT, text=True, capture_output=True)
        assert run.returncode != 0 and run.stderr.strip().endswith("ABSTAIN: FileNotFoundError")
        assert not os.path.exists(config["output_root"])


def main():
    test_validation_is_fail_closed()
    test_three_channels_resume_stale_and_failure_isolation()
    test_dry_run_writes_nothing_and_prepared_contract_precedes_execution()
    test_immutable_atomic_write_rejects_collision()
    test_public_payload_privacy_and_resume_integrity()
    test_multiple_candidates_versioned_summaries_and_dependency_hash()
    test_cross_channel_physical_alias_is_rejected()
    test_stage1_relabel_is_rejected_before_fit()
    test_cli_no_data_abstains_before_fit()
    print("test_fit_explorer_batch: PASS")


if __name__ == "__main__":
    main()
