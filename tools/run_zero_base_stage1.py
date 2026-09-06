"""Run one explicit zero-base candidate on four representative alpha rows."""
from __future__ import annotations
import argparse, glob, json, os, sys
from datetime import date
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.data_io import DataIO
from core.doas_fit import DoasFitter
from core import fit_explorer as FE
from tools import optimize_params as OP

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fitset", required=True); p.add_argument("--key", default="cold")
    p.add_argument("--alpha-glob", required=True); p.add_argument("--output", required=True)
    p.add_argument("--date-from", required=True); p.add_argument("--date-to", required=True)
    a = p.parse_args(argv)
    if os.path.exists(a.output): raise SystemExit("ABSTAIN: output exists")
    with open(a.fitset, encoding="utf-8") as fh: scenario = json.load(fh)
    cfg = OP.pick_channel(scenario, a.key)
    if cfg.get("allow_negative_gas") is not True:
        raise SystemExit("ABSTAIN: FitSet must explicitly allow negative gas")
    try:
        date_from, date_to = date.fromisoformat(a.date_from), date.fromisoformat(a.date_to)
    except ValueError:
        raise SystemExit("ABSTAIN: invalid ISO date range") from None
    if date_to < date_from: raise SystemExit("ABSTAIN: reversed date range")
    paths = []
    for path in sorted(glob.glob(a.alpha_glob)):
        try: day = date.fromisoformat(os.path.basename(os.path.dirname(path)))
        except ValueError: continue
        if date_from <= day <= date_to: paths.append(path)
    rows = [row for path in paths for row in DataIO.expand_to_scan_list(path)]
    try:
        selected, indices = FE.select_representative_rows(rows, 4)
        eng = OP.build_engine_from_config(cfg)
        if list(eng.gas_list) != [ref["name"] for ref in cfg["refs"]]:
            raise ValueError("engine reference order does not match FitSet")
        candidates = FE.zero_base_policy_candidates(cfg, eng._wave_axis)
        candidate = next(c for c in candidates if c["window_offset_nm"] == 0.0
                         and c["poly"] == int(cfg["poly_deg"])
                         and c["policy"]["shift"] == {"mode":"Limit","lower":-1.0,"upper":1.0}
                         and c["policy"]["squeeze"] == {"mode":"Limit","lower":.9999,"upper":1.0001})
        scans = []
        for path, row_index in selected:
            wave, alpha, temp, pressure, px_start = DataIO.load_alpha_trace_row_mapped(path, row_index)
            digest = FE.sha256_file(path)
            scans.append({"id":f"{os.path.basename(path)}#sha256={digest[:12]}#row={row_index}",
                          "wave":wave,"alpha":alpha,"temperature_C":float(temp),
                          "pressure_mbar":float(pressure),"px_start":int(px_start)})
        callback = FE.production_stage1_callback(eng, DoasFitter(eng), cfg)
        report = FE.run_stage1_vertical_slice(cfg, cfg["ref_props"], candidate, scans,
                    callback, allow_negative_gas=True)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, StopIteration) as exc:
        raise SystemExit("ABSTAIN: " + type(exc).__name__) from None
    report["sampling"] = {"contract":FE.STAGE1_SAMPLE_CONTRACT,"eligible_rows":len(rows),
        "selected_zero_based_indices":indices,"date_range":[a.date_from,a.date_to],
        "samples":[{"id":s["id"]} for s in scans]}
    report["source"] = {"fitset":{"name":os.path.basename(a.fitset),"sha256":FE.sha256_file(a.fitset)},
        "references":[{"name":r["name"],"file":os.path.basename(r["path"]),
                       "sha256":FE.sha256_file(r["path"])} for r in cfg["refs"]],
        "wavecal":{"file":os.path.basename(cfg["wl_path"]),"sha256":FE.sha256_file(cfg["wl_path"])},
        "gas_order":list(eng.gas_list)}
    report["git"] = FE.git_provenance(ROOT)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    tmp = a.output + ".tmp"
    with open(tmp,"w",encoding="utf-8") as fh:
        json.dump(report,fh,indent=2,sort_keys=True); fh.write("\n"); fh.flush(); os.fsync(fh.fileno())
    os.replace(tmp,a.output)
    print(json.dumps({"status":report["status"],"candidate_id":report["candidate_id"],
        "attempts":report["executed_attempts"],"successful":report["successful_attempts"],
        "output":os.path.abspath(a.output)},sort_keys=True))
    return 0
if __name__ == "__main__": raise SystemExit(main())
