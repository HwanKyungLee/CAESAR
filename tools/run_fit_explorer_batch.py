"""Run a validated multi-channel Fit Explorer batch with checkpoint/resume."""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import fit_explorer as FE
from core import fit_explorer_batch as FB
from core.data_io import DataIO
from core.doas_fit import DoasFitter
from tools import optimize_params as OP
from tools.run_zero_base_stage1 import (load_selected_scans, report_sampling,
    reuse_stage2_samples, stage1_paths_in_date_range, alpha_header_channel)


def _resolve_paths(config, base):
    resolved = json.loads(json.dumps(config))
    resolved["output_root"] = os.path.abspath(os.path.join(base, config["output_root"]))
    for channel in resolved["channels"]:
        channel["fitset"] = os.path.abspath(os.path.join(base, channel["fitset"]))
        channel["alpha_glob"] = os.path.abspath(os.path.join(base, channel["alpha_glob"]))
        if "sample_manifest" in channel:
            channel["sample_manifest"] = os.path.abspath(
                os.path.join(base, channel["sample_manifest"]))
    return resolved


def _source_hash(cfg, fitset, sampling, selected):
    alpha_hashes = {}
    for path, _row_index in selected:
        if path not in alpha_hashes:
            alpha_hashes[path] = FE.sha256_file(path)
    source = {"fitset": FE.sha256_file(fitset),
        "wavecal": FE.sha256_file(cfg["wl_path"]),
        "references": [{"name": ref["name"], "sha256": FE.sha256_file(ref["path"])}
                       for ref in cfg["refs"]],
        "gas_order": [ref["name"] for ref in cfg["refs"]],
        "selected_alpha": [{"file": os.path.basename(path),
                            "sha256": alpha_hashes[path], "row_index": row_index}
                           for path, row_index in selected],
        "sampling": sampling}
    return FB.canonical_json_hash(source), source


def reject_cross_channel_alpha_aliases(config):
    """Fail before fitting if two configured channels resolve to one physical file."""
    owners = {}
    for channel in config["channels"]:
        for path in glob.glob(channel["alpha_glob"]):
            stat = os.stat(path)
            identity = ((int(stat.st_dev), int(stat.st_ino)) if stat.st_ino else
                        os.path.normcase(os.path.realpath(path)))
            prior = owners.get(identity)
            if prior is not None and prior != channel["label"]:
                raise ValueError("alpha files alias across configured channels")
            owners[identity] = channel["label"]


def validate_stage1_selected_channels(selected, expected_channel=None):
    if expected_channel is None:
        return
    expected_channel = FE.canonical_channel_label(expected_channel)
    for path in {path for path, _ in selected}:
        if alpha_header_channel(path)["label"] != expected_channel:
            raise ValueError("selected Stage 1 alpha channel does not match config")


def prepare_channel(channel, document):
    """Open and fully validate one channel, but execute no nonlinear fit."""
    with open(channel["fitset"], encoding="utf-8") as fh:
        scenario = json.load(fh)
    fitset_key = channel.get("fitset_channel_key", channel["label"])
    # Mission-specific FitSets may use opaque keys (e.g. "1", "blue").
    # Prefer an exact key match; retain the legacy ANs/PNs/cold resolver when
    # no explicit key was supplied.
    if fitset_key in scenario.get("channels", {}):
        cfg = scenario["channels"][fitset_key]
    else:
        cfg = OP.pick_channel(scenario, fitset_key)
    target = channel.get("target_species", "NO2")
    if cfg.get("allow_negative_gas") is not True:
        raise ValueError("FitSet must explicitly allow negative gas")
    reference_roles = FE.validate_reference_roles(cfg)
    paths = sorted(glob.glob(channel["alpha_glob"]))
    if not paths:
        raise ValueError("alpha glob matched no files")
    excluded = set(channel.get("exclude_alpha_basenames", []))
    paths = [path for path in paths if os.path.basename(path) not in excluded]
    if not paths:
        raise ValueError("all alpha files were excluded")
    date_from, date_to = document["date_range"]
    if document["stage"] == 2:
        selected, sampling = reuse_stage2_samples(
            channel["sample_manifest"], paths,
            __import__("datetime").date.fromisoformat(date_from),
            __import__("datetime").date.fromisoformat(date_to), channel["label"])
    else:
        selected_paths = stage1_paths_in_date_range(
            paths, __import__("datetime").date.fromisoformat(date_from),
            __import__("datetime").date.fromisoformat(date_to))
        # Do not let an obviously empty plain-trace file consume one of the
        # four representative slots. Headered alpha files are left untouched;
        # this filter only applies to the legacy one-spectrum-per-file format.
        nonempty = []
        for path in selected_paths:
            try:
                if DataIO._is_alpha_trace_format(path) or DataIO.is_araon_mega_matrix(path):
                    nonempty.append(path)
                else:
                    values = np.loadtxt(path, dtype=float)
                    if values.size and np.any(np.isfinite(values) & (values != 0.0)):
                        nonempty.append(path)
            except (OSError, ValueError, TypeError):
                continue
        selected_paths = nonempty
        rows = [row for path in selected_paths for row in DataIO.expand_to_scan_list(path)]
        selected, indices = FE.select_representative_rows(rows, 4)
        sampling = {"contract": FE.STAGE1_SAMPLE_CONTRACT, "eligible_rows": len(rows),
                    "selected_zero_based_indices": indices,
                    "date_range": [date_from, date_to]}
        validate_stage1_selected_channels(selected, channel.get("channel_header_key"))
    fallback_wave = None
    try:
        fallback_wave = __import__("numpy").loadtxt(cfg["wl_path"], dtype=float)
    except Exception:
        pass
    scans = load_selected_scans(selected, sampling if document["stage"] == 2 else None,
                                fallback_wave=fallback_wave)
    sampling = report_sampling(sampling, scans, str(document["stage"]))
    engine = OP.build_engine_from_config(cfg)
    if list(engine.gas_list) != [ref["name"] for ref in cfg["refs"]]:
        raise ValueError("engine reference order does not match FitSet")
    generated = FE.zero_base_policy_candidates(cfg, engine._wave_axis, target=target)
    by_id = {candidate["id"]: candidate for candidate in generated}
    chosen = {}
    for declaration in channel["candidates"]:
        candidate = by_id.get(declaration["id"])
        if candidate is None or candidate["policy"] != declaration["policy"]:
            raise ValueError("declared candidate is absent from the generated zero-base grid")
        chosen[candidate["id"]] = candidate
    input_hash, source = _source_hash(cfg, channel["fitset"], sampling, selected)
    return {"input_hash": input_hash, "candidates": chosen,
        "context": {"cfg": cfg, "scans": scans, "sampling": sampling,
                     "target": target, "reference_roles": reference_roles,
                    "source": source, "engine": engine,
                    "fitter": DoasFitter(engine), "stage": document["stage"]}}


def execute_candidate(_label, candidate, context):
    cfg = context["cfg"]
    target = context.get("target", "NO2")
    reference_roles = context.get("reference_roles")
    absolute_anchors = FE.absolute_anchor_species(context["engine"], reference_roles)
    callback = FE.production_stage1_callback(context["engine"], context["fitter"], cfg, target=target)
    runner = FE.run_stage1_vertical_slice if context["stage"] == 1 \
        else FE.run_stage2_vertical_slice
    report = runner(cfg, cfg["ref_props"], candidate, context["scans"], callback,
                    allow_negative_gas=True, target=target)
    report["sampling"] = context["sampling"]
    report["source"] = context["source"]
    report["t2_gate"] = FE.t2_from_attempts(
        context["engine"], candidate, report.get("attempts", []), target=target,
        absolute_anchors=absolute_anchors)
    report["t2_diagnostics"] = FE.t2_diagnostic_checks(
        context["engine"], candidate, report.get("attempts", []), target=target)
    report["reference_roles"] = (reference_roles if reference_roles is not None else
                                 {name: {"fit_role": "MODELED_REFERENCE",
                                         "registration_role": "NONE",
                                         "anchor_role": "UNSPECIFIED", "reason": None}
                                  for name in context["engine"].gas_list})
    report["reference_observability"] = FE.reference_observability(
        context["engine"], candidate, reference_roles)
    return report


def code_hash(root=ROOT):
    """Hash the full local Python implementation and numerical runtime identity."""
    paths = []
    for folder in ("core", "tools"):
        for base, dirs, files in os.walk(os.path.join(root, folder)):
            dirs[:] = [name for name in dirs if name != "__pycache__"]
            paths.extend(os.path.join(base, name) for name in files if name.endswith(".py"))
    import numpy, scipy
    identity = {"runtime": {"python": platform.python_version(),
                             "numpy": numpy.__version__, "scipy": scipy.__version__},
        "files": [{"file": os.path.relpath(path, root).replace("\\", "/"),
                   "sha256": FE.sha256_file(path)} for path in sorted(paths)]}
    return FB.canonical_json_hash(identity)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true",
                        help="validate inputs and list work without fitting or writing")
    args = parser.parse_args(argv)
    try:
        with open(args.config, encoding="utf-8") as fh:
            raw = json.load(fh)
        FB.validate_config(raw)
        config = _resolve_paths(raw, os.path.dirname(os.path.abspath(args.config)))
        FB.validate_config(config)
        reject_cross_channel_alpha_aliases(config)
        # Prepare every channel before the first fit: config/input failures are all-or-nothing.
        prepared = {channel["label"]: prepare_channel(channel, config)
                    for channel in config["channels"]}
        summary = FB.run_prepared_batch(config, prepared, execute_candidate,
                                        code_hash=code_hash(), dry_run=args.dry_run)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit("ABSTAIN: " + type(exc).__name__) from None
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
