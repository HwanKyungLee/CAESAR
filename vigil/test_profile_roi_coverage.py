"""Profile consistency: each channel's reflectance.roi_nm must cover its concentration fit window.

RMonitor fits the R curve inside roi_nm only and sets (1-R)/d to NaN outside it (outside is an
extrapolation that can clip to R=1, i.e. alpha 0 = fake 'no absorption'). ConcMonitor then refuses
a fit window that is not fully covered. The profile is in nm and the FitSet in px, so the mismatch
is invisible by eye -- this check converts through the reflectance wavecal.

FitSet / wavecal are machine-specific paths; a channel whose files are not local is SKIPped (CI passes).

usage: python vigil/test_profile_roi_coverage.py  -> exit 0 if all PASS
"""
import json
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from vigil.monitors.conc_monitor import pick_fitset_channel
from vigil.profile import DEFAULT_PROFILE_DIR, ProfileSet

_n_pass = _n_fail = _n_skip = 0


def check(name, cond, detail=""):
    global _n_pass, _n_fail
    if cond:
        _n_pass += 1
        print(f"  PASS  {name}")
    else:
        _n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def main():
    global _n_skip
    print("[1] reflectance.roi_nm covers the channel's fit window")
    from tools.optimize_params import load_wavecal

    for prof in ProfileSet.load(DEFAULT_PROFILE_DIR).profiles:
        for ch in prof.signal_channels():
            if ch.concentration is None or ch.reflectance is None:
                continue
            tag = f"{prof.profile_id}/{ch.id}"
            try:
                scen = json.load(open(ch.concentration.fitset_path, encoding="utf-8"))
                fit_ch = pick_fitset_channel(scen, ch.concentration.wl_dir)
                wave = np.asarray(load_wavecal(ch.reflectance.wavecal_path), dtype=float)
            except Exception as e:                     # noqa: BLE001
                _n_skip += 1
                print(f"  SKIP  {tag} — FitSet/wavecal not local ({type(e).__name__})")
                continue
            lo, hi = int(fit_ch["f_min"]), int(fit_ch["f_max"])
            if hi >= len(wave):
                check(f"{tag} fit window inside wavelength axis", False, f"f_max={hi} >= {len(wave)}")
                continue
            f_lo, f_hi = float(wave[lo]), float(wave[hi])
            r_lo, r_hi = (float(x) for x in ch.reflectance.roi_nm)
            check(f"{tag} roi_nm [{r_lo}, {r_hi}] covers fit window {f_lo:.3f}-{f_hi:.3f} nm",
                  r_lo <= f_lo and f_hi <= r_hi,
                  f"low margin {f_lo - r_lo:+.4f} nm, high margin {r_hi - f_hi:+.4f} nm")

    print(f"\nprofile roi coverage: {_n_pass} PASS · {_n_fail} FAIL · {_n_skip} SKIP")
    return 1 if _n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
