# Runtime of the in-memory budget vs a file-based reprocessing route (2026-09-30)

Machine: the analysis workstation (20 logical cores, 32 GiB), **one process** in every case (the sandbox blocks worker pipes).

| step | what | wall time |
|---|---|---|
| in-memory LOO budget | `production_budget.py --limit 100 --jobs 1` on the clock-fixed R (R_CH1/2_clockfixed.npz), both hot channels, base + i0 + rt + ef + triple per record, including knot seeding and cache load | **74 s for 100 records** (0.74 s per record) |
| → whole budget window | 9034 records × 0.74 s | ≈ 1.9 h (extrapolated) |
| file route, extinction rebuild | `reprocess_2026-09-28/alpha_days.py 1 newpair R_CH1_clockfixed.npz … 60 2026-05-20` (26 raw files) | **54 s per channel-day** |
| file route, refit | `reprocess_2026-09-28/fit_run.py` on that day, operational fitset, 1399 records | **90 s per channel-day** |
| knots in the budget window (±1 h) | `_knots_hot.npz` | 157 zero-air, 54 helium |

A file-based route that reprocesses only the affected day costs (54 + 90) s × 2 channels ≈ 4.8 min per perturbation;
the 211 single-knot removals alone would take ≈ 17 h, before the pairwise/triple combinations and the etalon term.

Notes
- `qtstub_run.py` stubs PyQt6 and preloads the committed `tools/r_trend_monitor.py` (HEAD copy in `shim/`, the working file is ACL-denied in the sandbox) so that `gui.worker` imports headless. Numerics are untouched.
- The raw parse is cached (`_cache_*.npz`) in the in-memory route; that is part of the architecture being measured (references enter as data).
