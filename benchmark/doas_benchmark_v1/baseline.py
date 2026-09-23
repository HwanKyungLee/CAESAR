
"""
Reference retrieval for the DOAS benchmark: profiled shift search + linear solve.

Deliberately plain. It exists so that a submitter can see the expected output
format and has something to beat, not as a recommended implementation.
The squeeze factor is taken as given (it is supplied in the manifest).
"""
import numpy as np, pandas as pd
from pathlib import Path

PKG = Path("bench/doas_benchmark_v1")


def cheb(x, order):
    T = [np.ones_like(x), x]
    for k in range(2, order + 1):
        T.append(2 * x * T[-1] - T[-2])
    return np.array(T[:order + 1])


def design(sig, px, centre, gases, shift, squeeze, order, etalon_f=None):
    src = np.arange(len(next(iter(sig.values()))), dtype=float)
    pp = centre + (px - centre) * squeeze + shift
    cols = [np.interp(pp, src, sig[g]) for g in gases]
    cols += list(cheb(np.linspace(-1, 1, len(px)), order))
    if etalon_f:
        cols += [np.sin(2 * np.pi * etalon_f * px), np.cos(2 * np.pi * etalon_f * px)]
    return np.array(cols).T


def solve(A, y):
    sc = np.linalg.norm(A, axis=0); sc[sc == 0] = 1.0
    An = A / sc
    x, *_ = np.linalg.lstsq(An, y, rcond=None)
    r = y - An @ x
    n, p = A.shape
    s2 = r @ r / max(n - p, 1)
    cov = s2 * np.linalg.pinv(An.T @ An)
    return x / sc, np.sqrt(np.diag(cov)) / sc, r @ r


def run(sig_by_channel, Z, man, grid=np.arange(-5, 5.0001, 0.02)):
    out = []
    for _, r in man.iterrows():
        sig = sig_by_channel[r.channel]
        px = Z[f"pixel__{r.channel}"].astype(float)
        centre = float(r.centre_pixel)
        y = Z[r.case_id]
        gases = r.gases_to_fit.split(",")
        order = int(r.fit_poly_order)
        ef = float(r.fit_etalon_f)
        rss = np.array([solve(design(sig, px, centre, gases, d, r["squeeze_factor"],
                                     order, ef), y)[2] for d in grid])
        k = int(np.argmin(rss))
        c, s, _ = solve(design(sig, px, centre, gases, grid[k], r["squeeze_factor"],
                               order, ef), y)
        # shift uncertainty from the local curvature of the profiled objective
        if 0 < k < len(grid) - 1:
            d2 = (rss[k - 1] - 2 * rss[k] + rss[k + 1]) / (grid[1] - grid[0]) ** 2
            n, p = len(y), len(gases) + order + 3
            ss = float(np.sqrt(2 * rss[k] / max(n - p, 1) / d2)) if d2 > 0 else np.inf
        else:
            ss = np.inf
        out.append(dict(case_id=r.case_id, channel=r.channel, NO2=c[0], NO2_sigma=s[0],
                        shift_px=grid[k], shift_sigma=ss,
                        at_grid_edge=bool(k in (0, len(grid) - 1))))
    return pd.DataFrame(out)
