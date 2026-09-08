"""Run diagnostic multi-start/fixed-grid profiling for one alpha row."""
from __future__ import annotations
import argparse, json, os, sys, copy
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core.data_io import DataIO
from core.doas_fit import DoasFitter
from core import fit_profile as FP
from core import param_optimizer as PO
from tools import optimize_params as OP

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fitset", required=True); p.add_argument("--key", required=True)
    p.add_argument("--alpha", required=True); p.add_argument("--row", required=True, type=int)
    p.add_argument("--output", required=True); p.add_argument("--candidate-id")
    p.add_argument("--shift-grid", default="-7.5,-3.75,0,3.75,6")
    p.add_argument("--squeeze-grid", default="0.9678,0.9825,1,1.0125,1.0272")
    g=p.add_mutually_exclusive_group(required=True); g.add_argument("--allow-negative-gas",action="store_true"); g.add_argument("--nonnegative-gas",action="store_true")
    a=p.parse_args(argv)
    if os.path.exists(a.output): raise SystemExit("ABSTAIN: output exists")
    with open(a.fitset,encoding="utf-8") as f: scenario=json.load(f)
    cfg = (scenario.get("channels", {}).get(a.key)
           if isinstance(scenario.get("channels"), dict) else None)
    if cfg is None:
        cfg = OP.pick_channel(scenario, a.key)
    policy=bool(a.allow_negative_gas)
    if type(cfg.get("allow_negative_gas")) is not bool or cfg["allow_negative_gas"] != policy: raise SystemExit("ABSTAIN: gas policy mismatch")
    if not os.path.isfile(a.alpha): raise SystemExit("ABSTAIN: alpha unavailable")
    wave, alpha, temp, pressure, px_start=DataIO.load_alpha_trace_row_mapped(a.alpha,a.row)
    eng=OP.build_engine_from_config(cfg); fitter=DoasFitter(eng)
    px_min,px_max,poly=int(cfg["f_min"]),int(cfg["f_max"]),int(cfg["poly_deg"])
    candidates=[{"candidate_id":"baseline","px_min":px_min,"px_max":px_max,"poly":poly}]
    if a.candidate_id: candidates=[c for c in candidates if c["candidate_id"]==a.candidate_id]
    if not candidates: raise SystemExit("ABSTAIN: candidate unavailable")
    ref_props=cfg.get("ref_props",{})
    try: tb=__import__("core.fit_explorer",fromlist=["target_global_bounds"]).target_global_bounds(ref_props,"NO2")
    except Exception as e: raise SystemExit("ABSTAIN: bounds unavailable") from e
    def nums(text,name):
        try: vals=[float(x) for x in text.split(",") if x.strip()]
        except ValueError: raise SystemExit("ABSTAIN: invalid "+name)
        return vals
    sg,qg=nums(a.shift_grid,"shift-grid"),nums(a.squeeze_grid,"squeeze-grid")
    if not sg or not qg or not np.isfinite(sg+qg).all() or len(set(sg)) != len(sg) or len(set(qg)) != len(qg):
        raise SystemExit("ABSTAIN: grids must be non-empty, finite, and unique")
    starts=[(float(s),float(q)) for s in (sg[0],sg[-1]) for q in (qg[0],qg[-1])]
    c=candidates[0]; scan_id={"file":os.path.basename(a.alpha),"row_index":a.row,"sha256":FP.source_sha256(a.alpha)}
    if tb["squeeze"]["mode"] != "INTERVAL": raise SystemExit("ABSTAIN: squeeze interval unavailable")
    fit_bounds={"shift": (tb["shift"]["lower"],tb["shift"]["upper"]), "squeeze": (tb["squeeze"]["lower"],tb["squeeze"]["upper"])}
    def fit(sh,sq,mode):
        r=PO.fit_scan(eng,fitter,ref_props,wave,alpha,float(temp),float(pressure),c["px_min"]-px_start,c["px_max"]-px_start,c["poly"],float(cfg.get("step_limit",.5)),allow_negative_gas=policy,controlled_start=(sh,sq),controlled_bounds={"NO2_sh":fit_bounds["shift"],"NO2_sq":fit_bounds["squeeze"]})
        return {"shift":r["shifts"]["NO2"],"squeeze":r["squeezes"]["NO2"],"rms_sig":r["rms_sig"],"conc":r["conc"],"n_free":r["n_free"],"nonlinear_initialization":r["nonlinear_initialization"]}
    def fixed_fit(sh, sq, mode):
        fixed_props = copy.deepcopy(ref_props)
        for gas in eng.gas_list:
            props = fixed_props.setdefault(gas, {})
            if gas == "NO2":
                props["sh_mode"], props["sh_val"] = "Fix", str(float(sh))
                props["sq_mode"], props["sq_val"] = "Fix", str(float(sq))
            else:
                # Freeze non-target references at their declared center/fixed value.
                props["sh_mode"] = "Fix"
                raw_sh = str(props.get("sh_val", "0,0"))
                try: sh0 = float(raw_sh.split(",")[0])
                except ValueError: sh0 = 0.0
                props["sh_val"] = str(sh0)
                props["sq_mode"] = "Fix"
                try: raw = float(str(props.get("sq_val", "1")).split(",")[0])
                except ValueError: raw = 0.0
                props["sq_val"] = str(1.0 + raw if abs(raw) < .5 else raw)
        r=PO.fit_scan(eng,fitter,fixed_props,wave,alpha,float(temp),float(pressure),c["px_min"]-px_start,c["px_max"]-px_start,c["poly"],float(cfg.get("step_limit",.5)),allow_negative_gas=policy,controlled_start=(float(sh),float(sq)))
        r["shift"], r["squeeze"] = float(r["shifts"]["NO2"]), float(r["squeezes"]["NO2"])
        if not np.isclose(r["shift"],sh,rtol=0,atol=1e-12) or not np.isclose(r["squeeze"],sq,rtol=0,atol=1e-12):
            raise ValueError("fixed VARPRO changed grid coordinates")
        return r
    report=FP.run_profile(scan_identity=scan_id,starts=starts,shift_grid=sg,squeeze_grid=qg,bounds=fit_bounds,fit_callback=fit,fixed_fit_callback=fixed_fit,allow_negative_gas=policy,source_files=[a.fitset,cfg["wl_path"],a.alpha,*[x["path"] for x in cfg.get("refs",[])]],provenance_root=ROOT)
    report["candidate"]={**c,"channel_key":a.key}; report["scan"]["temperature_C"]=float(temp); report["scan"]["pressure_mbar"]=float(pressure)
    tmp=a.output+".tmp"
    with open(tmp,"w",encoding="utf-8") as fh: json.dump(report,fh,ensure_ascii=False,indent=2)
    os.replace(tmp,a.output)
    print(json.dumps({"status":report["status"],"output":os.path.abspath(a.output),"multi_start":len(report["multi_start"]),"fixed_grid":len(report["fixed_grid"])}))
    return 0
if __name__=="__main__": main()
