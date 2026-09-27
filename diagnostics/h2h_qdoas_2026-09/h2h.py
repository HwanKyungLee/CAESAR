# Augur vs QDOAS head-to-head harness (pre-registered design dc49a43b)
# requires helpers from h1_prior.py lines 1-121 exec'd first
import time
QEXE = r"C:\Users\User\miniforge3\envs\qdoas\Library\bin\doas_cl.exe"
K = 1e7
BOUND_PX = 8.0
GASES = ("NO2", "CHOCHO", "H2O")

def setup(fit_nm):
    global FIT_NM
    FIT_NM = fit_nm
    with contextlib.redirect_stdout(io.StringIO()):
        eng, wave = build_engine(GASES)
    vp, center = window(wave)
    return eng, wave, vp, center

def write_qdoas(tag, eng, wave, vp, alphas, init_px=0.0, bound_px=BOUND_PX):
    OUT = os.path.join(os.getcwd(), "h2h", tag)
    for sub in ("spec", "xs", "out"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)
    px = vp.astype(int); wl = wave[px]; disp = float(np.median(np.diff(wl)))
    calib = os.path.join(OUT, "calib.txt"); np.savetxt(calib, wl, fmt="%.6f")
    flat = os.path.join(OUT, "reference_flat.asc")
    with open(flat, "w") as f:
        for w_ in wl: f.write(f"{w_:.6f}\t{1.0:.7e}\n")
    xs = {}
    for name, fn in REF_FILES:
        arr = np.loadtxt(os.path.join(REFDIR, fn), comments="#")
        p = os.path.join(OUT, "xs", f"{name}.xs"); np.savetxt(p, np.column_stack([wave, arr]), fmt="%.6f\t%.6e")
        xs[name] = p.replace("\\", "/")
    spec = os.path.join(OUT, "spec", "synth.asc")
    with open(spec, "w") as f:
        for k, a in enumerate(alphas):
            I = np.exp(-K * a)
            f.write(f"01/06/2026 {1.0 + k/86400.0:.8f} " + " ".join(f"{v:.9e}" for v in I) + "\n")
    rx = ET.parse(os.path.join(r"C:\GHL\CAESAR\diagnostics\qdoas_crossval_2026-09", "qdoas_input", "cold", "Cold.xml")).getroot()
    pns = [p for p in rx.findall("project") if p.get("name") == "PNs"][0]
    new = ET.Element("qdoas"); ET.SubElement(new, "paths"); sym = ET.SubElement(new, "symbols")
    for g in GASES: ET.SubElement(sym, "symbol", {"name": g, "descr": ""})
    proj = copy.deepcopy(pns); proj.set("name", "H2H")
    asc = proj.find("instrumental").find("ascii"); asc.set("size", str(len(px))); asc.set("calib", calib.replace("\\", "/"))
    o = proj.find("output"); o.set("path", os.path.join(OUT, "out", "r_").replace("\\", "/")); o.set("fileFormat", ".ASC")
    w = proj.find("analysis_window")
    w.set("min", f"{wl[0]:.3f}"); w.set("max", f"{wl[-1]:.3f}"); w.set("lambda0", f"{wl[len(wl)//2]:.3f}")
    w.find("files").set("refone", flat.replace("\\", "/")); w.find("linear").set("xpoly", "3")
    for cs in w.find("cross_sections"):
        cs.set("csfile", xs[cs.get("sym")]); cs.set("cstype", "interp")
    ss = w.find("shift_stretches")[0]
    ss.set("shmin", f"{-bound_px*disp:.4e}"); ss.set("shmax", f"{bound_px*disp:.4e}")
    ss.set("shini", f"{-init_px*disp:.4e}")
    for k_, v_ in (("shfit", "true"), ("stfit", "1st"), ("shstr", "true"), ("ststr", "true"), ("errstr", "true")): ss.set(k_, v_)
    new.append(proj)
    xmlp = os.path.join(OUT, "proj.xml"); ET.ElementTree(new).write(xmlp, encoding="utf-8", xml_declaration=True)
    return OUT, xmlp, spec, disp

def run_qdoas(OUT, xmlp, spec, disp):
    for f in os.listdir(os.path.join(OUT, "out")): os.remove(os.path.join(OUT, "out", f))
    t0 = time.perf_counter()
    r = subprocess.run([QEXE, "-c", xmlp, "-a", "H2H", "-f", spec], capture_output=True, text=True)
    dt = time.perf_counter() - t0
    outs = [f for f in os.listdir(os.path.join(OUT, "out")) if f.upper().endswith(".ASC")]
    assert outs, (r.stdout[-500:], r.stderr[-500:])
    ASC = os.path.join(OUT, "out", outs[0])
    raw = open(ASC, encoding="utf-8", errors="replace").read().splitlines()
    hdr_i = max(i for i, l in enumerate(raw) if l.startswith("#") or "SlntCol" in l)
    q = pd.read_csv(ASC, sep="\t", skiprows=hdr_i, engine="python")
    q.columns = [c.strip().lstrip("#").strip() for c in q.columns]
    Q = pd.DataFrame({"no2": q["NO2.SlCol(NO2)"].values / K, "err": q["NO2.SlErr(NO2)"].values / K,
                      "shift": -q["NO2.Shift(CHOCHO)"].values / disp, "rms": q["NO2.RMS"].values})
    return Q, dt, q

def run_augur(eng, vp, center, alphas, init_px=0.0, cond=False):
    fitter = DoasFitter(eng)
    props = props_for(GASES, sh_val=f"{-BOUND_PX}, {BOUND_PX}")
    rows = []; t0 = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        for a in alphas:
            r = recover(eng, fitter, props, vp, center, a, init_shift=init_px)
            d = dict(no2=r["scd"]["NO2"], err=r["err"]["NO2"], shift=r["shift"], sq=r["squeeze"])
            if cond:
                pf = props_for(GASES); pf["NO2"].update(sh_mode="Fix", sh_val=f"{r['shift']:.8f}",
                                                       sq_mode="Fix", sq_val=f"{r['squeeze']-1.0:.8f}")
                rc = recover(eng, fitter, pf, vp, center, a, init_shift=r["shift"])
                d.update(err_cond=rc["err"]["NO2"], shift_c=rc["shift"], sq_c=rc["squeeze"], no2_c=rc["scd"]["NO2"])
            rows.append(d)
    return pd.DataFrame(rows), time.perf_counter() - t0
