#!/usr/bin/env python
"""Per-record structural terms — the second of the manuscript's three numbers (§4.2, §6.1), product tool.

For every alpha record: fit it, then re-fit it with the nearest zero-air knot removed (i0), with
the paired R knot removed (rt), with its own etalon frequency (ef), and with all three (tri). The
change in each gas is that record's structural term — what an error of the size the pipeline
actually makes in that input does to *this* retrieval. The fit uncertainty cannot show it; the
residual does not change.

Inputs: alpha files of one channel + the knot file alpha generation wrote next to the zero-air LOO
file (`{campaign}/_zeroair/calib_knots_<label>_….npz`; the alpha is inverted exactly, no raw is
read — core/structural.py) + the FitSet. Fits follow the canonical run
(diagnostics/i0_interp_2026-09/production_budget.py): one shift seed per zero-air knot window
shared by all its records and perturbations, box = seed ± step limit, base etalon f fixed.
Records at a bound are kept and flagged (dropping them would remove the records the perturbation
moved most).

    python tools/structural_budget.py --fitset FitSet.json --channel 1 \
        --alpha "<campaign>/2026-05-20/alpha/ch1/*.dat" --knots <campaign>/_zeroair/calib_knots_ANs_….npz \
        [--alpha-b … --knots-b … --channel-b 2 --ratio 0.9524]   # ΣANs = A − g′·B summary
        [--result <fit result>.dat]                               # → <result>_struct.dat

Outputs: structural_<label>.csv (one row per record: base and the four signed changes per gas,
bound flag), a printed summary (robust and SD scale per term, for each gas and for ΣANs), and with
--result a copy of the result with <gas>_Struct (|tri|) and <gas>_Struct_i0/_rt/_ef columns.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OPERATIONAL_EF = 0.12
TERMS = ("i0", "rt", "ef", "tri")
_W = {}


def rsd(v):
    v = np.asarray(v, float)
    v = v[np.isfinite(v)]
    return float(1.4826 * np.median(np.abs(v - np.median(v)))) if v.size else float("nan")


def read_records(paths):
    """[(file basename, row, sec, T, P, wave, alpha)] over all alpha files, any px start → (recs, px0)."""
    from zero_air_floor import read_rows
    recs, px0 = [], None
    for p in paths:
        rows, p0 = read_rows(p)
        if px0 is None:
            px0 = p0
        elif p0 != px0:
            raise SystemExit(f"alpha files start at different pixels ({px0} vs {p0}) — one channel per run")
        b = os.path.basename(p)
        recs += [(b, i, sec, T, P, wave, a) for i, (sec, wave, a, T, P) in enumerate(rows)]
    return recs, px0 or 0


def _init(spec):
    from core import param_optimizer as PO
    from core.doas_fit import DoasFitter
    from core.structural import CalibKnots
    from optimize_params import build_engine_from_config
    cfg = spec["cfg"]
    eng = build_engine_from_config(cfg)
    _W.update(PO=PO, eng=eng, fitter=DoasFitter(eng), K=CalibKnots(spec["knots"]), cfg=cfg,
              lo=spec["lo"], hi=spec["hi"], ef=spec["ef"], step=spec["step"], target=spec["target"])


def _fit(alpha, wave, T, P, seed, ef):
    W, cfg = _W, _W["cfg"]
    r = W["PO"].fit_scan(W["eng"], W["fitter"], cfg.get("ref_props") or {}, wave, alpha, T, P,
                         W["lo"], W["hi"], int(cfg["poly_deg"]), W["step"], target=W["target"],
                         allow_negative_gas=bool(cfg.get("allow_negative_gas", True)),
                         return_solver_diagnostics=True, use_etalon=bool(cfg.get("use_etalon", True)),
                         etalon_freq=ef, seed=seed)
    bound = bool((r.get("solver_diagnostics") or {}).get("theta_bound_hits"))
    return r, bound


def _window(recs):
    """One zero-air knot window: a shared seed, then base + four perturbations per record."""
    K, gases = _W["K"], list(_W["eng"].gas_list)
    out, seed = [], None
    for (b, i, sec, T, P, wave, a) in recs:
        p = K.perturbed(a, sec, T, P)
        if p is None:
            continue
        try:
            if seed is None:
                r0, _ = _fit(a, wave, T, P, None, _W["ef"])
                ds = r0["deterministic_seed"]
                seed = (ds["shift"], ds["squeeze"])
            base, bb = _fit(a, wave, T, P, seed, _W["ef"])
            fits, bnd = {"base": base}, bb
            for term, aa, ef in (("i0", p["i0"], _W["ef"]), ("rt", p["rt"], _W["ef"]),
                                 ("ef", a, None), ("tri", p["tri"], None)):
                if aa is None:
                    fits[term] = None
                    continue
                fits[term], b2 = _fit(aa, wave, T, P, seed, ef)
                bnd = bnd or b2
        except Exception:      # noqa: BLE001 — a record that does not fit is skipped, counted by the caller
            continue
        row = {"file": b, "row": i, "sec": sec, "k": p["k"], "kr": -1 if p["kr"] is None else p["kr"],
               "at_bound": int(bnd)}
        for g in gases:
            b0 = base["conc_all"][g]
            row[f"{g}"] = b0
            for t in TERMS:
                row[f"{g}_d_{t}"] = (fits[t]["conc_all"][g] - b0) if fits[t] is not None else float("nan")
        out.append(row)
    return out


def run_channel(paths, knots, cfg, target, ef, step, jobs, label):
    from core.calib_context import KNOT_TAGS  # noqa: F401  (import check: core on path)
    from core.structural import CalibKnots
    recs, px0 = read_records(paths)
    K = CalibKnots(knots)
    by = {}
    for r in recs:
        by.setdefault(K.nearest_za(r[2]), []).append(r)
    work = [by[k] for k in sorted(by)]
    spec = dict(cfg=cfg, knots=knots, lo=int(cfg["f_min"]) - px0, hi=int(cfg["f_max"]) - px0,
                ef=ef, step=step, target=target)
    rows = []
    nw = max(1, min(jobs, len(work)))
    if nw > 1:
        for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ.setdefault(v, "1")
        with cf.ProcessPoolExecutor(max_workers=nw, initializer=_init, initargs=(spec,)) as ex:
            for part in ex.map(_window, work):
                rows += part
    else:
        _init(spec)
        for w in work:
            rows += _window(w)
    rows.sort(key=lambda r: r["sec"])
    print(f"[{label}] records {len(recs)} · structural {len(rows)} · knot windows {len(work)} · "
          f"at bound {sum(r['at_bound'] for r in rows)}")
    return rows


def _summary(rows, gases, label):
    import pandas as pd
    d = pd.DataFrame(rows)
    ok = d[d.at_bound == 0]
    print(f"  [{label}] robust SD (non-bound n={len(ok)}) / SD:")
    for g in gases:
        parts = "  ".join(f"{t} {rsd(ok[f'{g}_d_{t}']):.4g}" for t in TERMS)
        print(f"    {g:7s} {parts}   tri SD {np.nanstd(ok[f'{g}_d_tri'], ddof=1):.4g}   "
              f"(base median {np.nanmedian(ok[g]):.4g})")
    return d


def merge_result(result, tables, gases):
    """Copy of `result` with <gas>_Struct = |tri| and the signed components; unmatched rows NaN."""
    import pandas as pd
    head, body_start = [], 0
    with open(result, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    while body_start < len(lines) and lines[body_start].startswith("#"):
        head.append(lines[body_start]); body_start += 1
    import io
    df = pd.read_csv(io.StringIO("\n".join(lines[body_start:])), sep="\t")
    st = pd.concat(tables, ignore_index=True)
    key = {(r.file, int(r.row)): r for r in st.itertuples(index=False)}
    names = df["File"].astype(str).str.extract(r"^(.*) \[(\d+)\]$")
    for g in gases:
        cols = {f"{g}_Struct": [], **{f"{g}_Struct_{t}": [] for t in TERMS[:3]}}
        for fname, ridx in names.itertuples(index=False):
            r = key.get((fname, int(ridx))) if isinstance(fname, str) else None
            v = (lambda t: getattr(r, f"{g}_d_{t}") if r is not None else float("nan"))
            cols[f"{g}_Struct"].append(abs(v("tri")))
            for t in TERMS[:3]:
                cols[f"{g}_Struct_{t}"].append(v(t))
        for c, v in cols.items():
            df[c] = v
    out = os.path.splitext(result)[0] + "_struct" + os.path.splitext(result)[1]
    with open(out, "w", encoding="utf-8") as fh:
        for h in head:
            fh.write(h + "\n")
        fh.write("# Structural terms (tools/structural_budget.py): {gas}_Struct = |change| with the nearest I0 "
                 "knot, its R knot and the fixed etalon f all perturbed; _Struct_i0/_rt/_ef = signed single "
                 "terms. Not in {gas}_Error; report alongside it (manuscript Sect. 6.1).\n")
        df.to_csv(fh, sep="\t", index=False, lineterminator="\n")
    print(f"→ {out}  ({int(np.isfinite(df[f'{gases[0]}_Struct']).sum())}/{len(df)} rows matched)")
    return out


def main(argv=None):
    from core.parallel import max_workers
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fitset", required=True)
    ap.add_argument("--alpha", required=True, nargs="+", help="alpha files / globs of channel A")
    ap.add_argument("--knots", required=True, help="calib_knots_*.npz of channel A")
    ap.add_argument("--channel", required=True)
    ap.add_argument("--alpha-b", nargs="+")
    ap.add_argument("--knots-b")
    ap.add_argument("--channel-b")
    ap.add_argument("--ratio", type=float, default=0.9524)
    ap.add_argument("--target", default="NO2", help="gas whose shift seeds the fit")
    ap.add_argument("--etalon-f", type=float, default=OPERATIONAL_EF)
    ap.add_argument("--step-limit", type=float, default=3.0, help="box = seed ± this (canonical run: 3)")
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--result", help="fit result .dat to copy with the structural columns added")
    ap.add_argument("--out-dir", help="where structural_<label>.csv goes (default: next to the knot file)")
    a = ap.parse_args(argv)
    chans = json.load(open(a.fitset, encoding="utf-8"))["channels"]
    jobs = a.jobs or max_workers()
    tables, gases = [], None
    runs = [("A", a.alpha, a.knots, a.channel)]
    if a.alpha_b:
        runs.append(("B", a.alpha_b, a.knots_b, a.channel_b))
    res = {}
    for tag, pats, knots, key in runs:
        paths = sorted({p for pat in pats for p in (glob.glob(pat) or [pat]) if os.path.isfile(p)})
        cfg = chans[str(key)]
        label = (cfg.get("data_label") or f"ch{key}").strip()
        rows = run_channel(paths, knots, cfg, a.target, a.etalon_f, a.step_limit, jobs, label)
        if not rows:
            print(f"[{label}] no structural records (no R(t) knots in {knots}?)")
            continue
        gases = [c for c in rows[0] if c not in ("file", "row", "sec", "k", "kr", "at_bound") and "_d_" not in c]
        d = _summary(rows, gases, label)
        dst = os.path.join(a.out_dir or os.path.dirname(os.path.abspath(knots)), f"structural_{label}.csv")
        d.to_csv(dst, index=False)
        print(f"→ {dst}")
        tables.append(d)
        res[tag] = d
    if "A" in res and "B" in res:
        A, B = res["A"], res["B"]
        ka, kb = np.round(A.sec.values, 0), np.round(B.sec.values, 0)
        common, ia, ib = np.intersect1d(ka, kb, return_indices=True)
        ok = (A.at_bound.values[ia] == 0) & (B.at_bound.values[ib] == 0)
        g = a.target
        print(f"[A − {a.ratio:g}·B] paired {len(common)} records (non-bound {int(ok.sum())}):")
        for t in TERMS:
            v = A[f"{g}_d_{t}"].values[ia] - a.ratio * B[f"{g}_d_{t}"].values[ib]
            print(f"    {g} {t:3s} robust {rsd(v[ok]):.4f}  SD {np.nanstd(v[ok], ddof=1):.4f} ppb")
    if a.result and tables:
        merge_result(a.result, tables, gases)


if __name__ == "__main__":
    main()
