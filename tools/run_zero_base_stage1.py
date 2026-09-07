"""Run one explicit zero-base candidate using a Stage 1 or Stage 2 budget."""
from __future__ import annotations
import argparse, glob, json, os, re, sys
from datetime import date, datetime, timedelta
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.data_io import DataIO
from core.doas_fit import DoasFitter
from core import fit_explorer as FE
from tools import optimize_params as OP

def select_candidate(candidates, cfg, *, shift_fix=None, shift_limit=None,
                     squeeze_fix=None, squeeze_limit=None):
    shift = ({"mode": "Fix", "value": float(shift_fix)} if shift_fix is not None
             else {"mode": "Limit", "lower": float(shift_limit[0]),
                   "upper": float(shift_limit[1])})
    squeeze = ({"mode": "Fix", "value": float(squeeze_fix)} if squeeze_fix is not None
               else {"mode": "Limit", "lower": float(squeeze_limit[0]),
                     "upper": float(squeeze_limit[1])})
    return next(c for c in candidates if c["window_offset_nm"] == 0.0
                and c["poly"] == int(cfg["poly_deg"])
                and c["policy"] == {"shift": shift, "squeeze": squeeze})

def alpha_header_channel(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            match = re.fullmatch(r"#\s*channel=(\d+)\s+label=(\S+)\s*", line)
            if match:
                return {"index": int(match.group(1)), "label": match.group(2),
                        "source": "alpha_header_label"}
            if not line.startswith("#"):
                break
    raise ValueError("alpha header channel metadata is unavailable")

def alpha_time_source(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("row_idx"):
                columns = line.rstrip("\n").split("\t")
                if "datetime" in columns:
                    return "alpha_header_datetime"
                if "doy" in columns and DataIO._file_year(path) is not None:
                    return "alpha_header_doy_with_filename_year"
                break
            if not line.startswith("#"):
                break
    raise ValueError("alpha header time metadata is unavailable")

def alpha_stage2_metadata(path):
    """Read one alpha file once and return channel plus row time provenance."""
    channel = None
    header = None
    data_rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                match = re.fullmatch(r"#\s*channel=(\d+)\s+label=(\S+)\s*", line)
                if match:
                    parsed = {"index": int(match.group(1)), "label": match.group(2),
                              "source": "alpha_header_label"}
                    if channel is not None:
                        raise ValueError("alpha header channel metadata is duplicated")
                    channel = parsed
                continue
            text = line.strip()
            if not text:
                continue
            if text.startswith("row_idx"):
                header = text.split("\t")
            elif header is not None:
                data_rows.append(text.split("\t"))
    if channel is None or header is None or not data_rows:
        raise ValueError("alpha header or row metadata is unavailable")
    dt_idx = header.index("datetime") if "datetime" in header else None
    doy_idx = header.index("doy") if "doy" in header else None
    year = DataIO._file_year(path)
    rows = []
    for row_index, parts in enumerate(data_rows):
        timestamp = None
        source = None
        if dt_idx is not None and dt_idx < len(parts):
            for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
                try:
                    timestamp = datetime.strptime(parts[dt_idx], fmt)
                    source = "alpha_header_datetime"
                    break
                except ValueError:
                    pass
        if timestamp is None and doy_idx is not None and doy_idx < len(parts) and year:
            try:
                timestamp = datetime(year, 1, 1) + timedelta(
                    days=float(parts[doy_idx]) - 1.0)
                source = "alpha_header_doy_with_filename_year"
            except ValueError:
                pass
        if timestamp is None:
            raise ValueError("alpha row timestamp metadata is unavailable")
        rows.append((row_index, timestamp, source))
    return channel, rows

def stage1_paths_in_date_range(paths, date_from, date_to):
    """Preserve the Stage 1 contract: the parent directory is its date."""
    selected = []
    for path in paths:
        try:
            day = date.fromisoformat(os.path.basename(os.path.dirname(path)))
        except ValueError:
            continue
        if date_from <= day <= date_to:
            selected.append(path)
    return selected

def load_selected_scans(selected, sampling=None):
    """Load selected rows, reusing Stage 2 sample identities when supplied."""
    samples = sampling.get("samples", []) if sampling is not None else []
    if samples and len(samples) != len(selected):
        raise ValueError("selected rows and sample provenance disagree")
    hashes = {}
    scans = []
    for index, (path, row_index) in enumerate(selected):
        wave, alpha, temp, pressure, px_start = DataIO.load_alpha_trace_row_mapped(
            path, row_index)
        if samples:
            sample = samples[index]
            digest, scan_id = sample["sha256"], sample["id"]
        else:
            if path not in hashes:
                hashes[path] = FE.sha256_file(path)
            digest = hashes[path]
            scan_id = (f"{os.path.basename(path)}#sha256={digest[:12]}"
                       f"#row={row_index}")
        scans.append({"id":scan_id, "wave":wave, "alpha":alpha,
                      "temperature_C":float(temp), "pressure_mbar":float(pressure),
                      "px_start":int(px_start)})
    return scans

def report_sampling(sampling, scans, stage):
    out = dict(sampling)
    if stage == "1":
        out["samples"] = [{"id": scan["id"]} for scan in scans]
    elif [sample["id"] for sample in out.get("samples", [])] != [
            scan["id"] for scan in scans]:
        raise ValueError("Stage 2 public sample provenance does not match selected scans")
    return out

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fitset", required=True); p.add_argument("--key", default="cold")
    p.add_argument("--alpha-glob", required=True); p.add_argument("--output", required=True)
    p.add_argument("--date-from", required=True); p.add_argument("--date-to", required=True)
    p.add_argument("--stage", choices=("1", "2"), default="1")
    shift = p.add_mutually_exclusive_group()
    shift.add_argument("--shift-fix", type=float)
    shift.add_argument("--shift-limit", type=float, nargs=2, metavar=("LOWER", "UPPER"))
    squeeze = p.add_mutually_exclusive_group()
    squeeze.add_argument("--squeeze-fix", type=float)
    squeeze.add_argument("--squeeze-limit", type=float, nargs=2,
                         metavar=("LOWER", "UPPER"))
    a = p.parse_args(argv)
    if a.shift_fix is None and a.shift_limit is None: a.shift_limit = (-1.0, 1.0)
    if a.squeeze_fix is None and a.squeeze_limit is None: a.squeeze_limit = (.9999, 1.0001)
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
    paths = sorted(glob.glob(a.alpha_glob))
    if a.stage == "1":
        paths = stage1_paths_in_date_range(paths, date_from, date_to)
    try:
        if a.stage == "2":
            headers, rows = {}, []
            for path in paths:
                headers[path], timed_rows = alpha_stage2_metadata(path)
                if headers[path]["label"] != a.key:
                    raise ValueError("matched alpha file channel does not match --key")
                rows.extend((path, row_index, timestamp, time_source)
                            for row_index, timestamp, time_source in timed_rows)
        else:
            rows = [row for path in paths for row in DataIO.expand_to_scan_list(path)]
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
        raise SystemExit("ABSTAIN: " + type(exc).__name__) from None
    try:
        if a.stage == "1":
            selected, indices = FE.select_representative_rows(rows, 4)
            sampling = {"contract":FE.STAGE1_SAMPLE_CONTRACT,"eligible_rows":len(rows),
                "selected_zero_based_indices":indices,"date_range":[a.date_from,a.date_to]}
        else:
            records = []
            for path,row_index,timestamp,time_source in rows:
                header = headers[path]
                if not date_from <= timestamp.date() <= date_to:
                    continue
                records.append({"path":path,"row_index":row_index,
                    "date":timestamp.date().isoformat(),
                    "timestamp":timestamp.isoformat(sep=" "),
                    "observation_key":timestamp.isoformat(sep=" "),
                    "time_source":time_source,
                    "channel":header["label"],"channel_source":header["source"]})
            selected, sampling = FE.select_stage2_rows(
                records, a.date_from, a.date_to, a.key)
        eng = OP.build_engine_from_config(cfg)
        if list(eng.gas_list) != [ref["name"] for ref in cfg["refs"]]:
            raise ValueError("engine reference order does not match FitSet")
        candidates = FE.zero_base_policy_candidates(cfg, eng._wave_axis)
        candidate = select_candidate(
            candidates, cfg, shift_fix=a.shift_fix, shift_limit=a.shift_limit,
            squeeze_fix=a.squeeze_fix, squeeze_limit=a.squeeze_limit)
        scans = load_selected_scans(selected, sampling if a.stage == "2" else None)
        callback = FE.production_stage1_callback(eng, DoasFitter(eng), cfg)
        runner = (FE.run_stage1_vertical_slice if a.stage == "1"
                  else FE.run_stage2_vertical_slice)
        report = runner(cfg, cfg["ref_props"], candidate, scans,
                        callback, allow_negative_gas=True)
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, StopIteration) as exc:
        raise SystemExit("ABSTAIN: " + type(exc).__name__) from None
    report["sampling"] = report_sampling(sampling, scans, a.stage)
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
