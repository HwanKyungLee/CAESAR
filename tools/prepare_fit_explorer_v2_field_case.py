"""Prepare a bounded Yeosu operational fixture, not a scientific recommendation.

The legacy config supplies only wavelength/reference filenames and reference scale.
Its fitted window, polynomial degree, and registration values are never copied.
All dates have previously been reviewed: the held-out date is disjoint for this
execution, but cannot honestly be called a fresh independent validation dataset.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.data_io import DataIO
from core.fit_explorer import sha256_file


def _write_new_or_identical(path, value):
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != value:
            raise ValueError("existing fixture differs; choose a new output directory")
        return
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)


def prepare(config_path, channel_key, alpha_root, output_directory):
    config_path, alpha_root = Path(config_path).resolve(), Path(alpha_root).resolve()
    cfg = json.loads(config_path.read_text(encoding="utf-8"))["channels"][channel_key]
    wave_path = Path(cfg["wl_path"])
    wave = np.loadtxt(wave_path)
    if wave.ndim != 1:
        raise ValueError("fixture expects a one-column wavelength file")
    references, sources = [], []
    for entry in cfg["refs"]:
        path = Path(entry["path"])
        header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:3])
        if "Dynamic-ILS-Applied" not in header:
            raise ValueError("reference convolution provenance not verified")
        values = np.loadtxt(path)
        if values.shape != wave.shape:
            raise ValueError("reference/wavelength shape mismatch")
        scale = 10.0 ** entry["mult"]
        references.append({"species_id": entry["name"], "wavelength_nm": wave.tolist(),
                           "values": (values * scale).tolist(), "cross_section_unit": "arb",
                           "ils_state": "ALREADY_CONVOLVED"})
        sources.append({"species_id": entry["name"], "path": str(path),
                        "sha256": sha256_file(str(path)), "legacy_scale_exponent": entry["mult"],
                        "applied_scale": scale, "unit_status": "UNVERIFIED_DIAGNOSTIC_ARB",
                        "ils_source": header})
    dates = ["2026-05-26", "2026-05-30", "2026-06-04", "2026-06-09"]
    split = {"discovery": [], "validation": [], "holdout": []}
    alpha_inputs, bindings, observations = [], {}, []
    for index, date in enumerate(dates):
        files = sorted((alpha_root / date).glob("*.dat"))
        if len(files) != 1:
            raise ValueError("expected exactly one source alpha per declared date")
        path = files[0].resolve()
        rows = DataIO.expand_to_scan_list(str(path))
        if len(rows) < 2:
            raise ValueError("need at least two observations per date")
        role = "discovery" if index < 2 else "validation" if index == 2 else "holdout"
        digest = sha256_file(str(path))
        for row_index in (0, len(rows) - 1):
            obs_id = f"detector2_{date}_row{row_index}"
            local_wave, alpha, temperature, pressure, pixel_start = DataIO.load_alpha_trace_row_mapped(str(path), row_index)
            if not (np.isfinite(alpha).all() and local_wave[0] < 445 and local_wave[-1] > 469):
                raise ValueError("alpha does not cover declared fixture windows")
            alpha_inputs.append({"observation_id": obs_id, "content_hash": digest,
                                 "date": date, "block_id": date, "previously_used": True})
            bindings[obs_id] = {"path": str(path), "row_index": row_index}
            split[role].append(obs_id)
            observations.append({"observation_id": obs_id, "role": role, "source_row_count": len(rows),
                                 "T_C": temperature, "P_mbar": pressure, "pixel_start": pixel_start,
                                 "coverage_nm": [float(local_wave[0]), float(local_wave[-1])],
                                 "previously_used": True})
    mission = {"schema": "explorer-mission-v2", "mission_id": "yeosu-pns-v2-operational-reused-dates",
               "channels": [{"channel_id": "detector2", "alpha_inputs": alpha_inputs,
                             "wavelength": {"unit": "nm", "values": wave.tolist()},
                             "references": references}],
               "search_policy": {"windows_nm": [[445., 469.], [446., 469.]], "poly_degrees": [2, 3, 4],
                                 "registration_policies": [{"driver_species": "NO2",
                                     "shift": {"mode": "Limit", "lower": -5., "upper": 5.},
                                     "squeeze": {"mode": "Limit", "lower": .9999, "upper": 1.0001}}],
                                 "split": split, "budget": {"max_fit_attempts": 96, "closure_max_attempts": 0}}}
    provenance = {"scope": "BOUNDED_OPERATIONAL_CASE_NOT_ZERO_BASE_DOMAIN_OPTIMUM",
                  "source_config_path": str(config_path), "source_config_hash": sha256_file(str(config_path)),
                  "source_config_usage": "Only wavelength/ref paths and ref mult; no fitted parameters copied",
                  "wavelength_path": str(wave_path), "wavelength_hash": sha256_file(str(wave_path)),
                  "references": sources, "observations": observations,
                  "limitations": ["All reference headers omit absolute cross-section units; coefficient units are arb",
                                  "Same measurement cannot be converted into independent evidence by declaring a new split",
                                  "Declared narrow finite windows and bounds test runtime; not universal search bounds",
                                  "No sensitivity threshold invented; criteria intentionally absent",
                                  "Registration driver NO2 is explicit test policy, not mandatory target input"]}
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("mission.json", mission), ("bindings.json", bindings), ("provenance.json", provenance)):
        _write_new_or_identical(output / name, value)
    return {"output_directory": str(output), "candidates": 6, "discovery_attempts": 48,
            "validation_attempts": 24, "maximum_holdout_attempts": 24, "independent_holdout": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-config", required=True)
    parser.add_argument("--channel-key", required=True)
    parser.add_argument("--alpha-root", required=True)
    parser.add_argument("--output-directory", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.metadata_config, args.channel_key, args.alpha_root, args.output_directory)))
