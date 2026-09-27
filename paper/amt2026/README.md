# AMT 2026 — figure sources

Manuscript: *Augur: an α-domain variable-projection DOAS retrieval, and what its diagnostics reveal that
standard fit reports do not* (AMT, in preparation).

| Figure | Content | How to reproduce | Standalone? |
|---|---|---|---|
| 1 | thesis figure (`amt_fig1_thesis_v2`) | session artifact; script not yet in this folder | no |
| 2 | representative fits (6/1 10:35 KST) | `python fig2_standalone.py` | **yes** — `data/amt_fig2_data.csv`, `data/amt_fig2_noise_profiles.csv`, `data/fig2_day_20260601.csv`, `data/fig2_records.json` (derived; `fig2_session.py` kept for the raw-data path) |
| 3 | validation | `python make_figs_345.py` | **yes** — `data/varpro_synth_results.csv`, `data/h2h_E1_coverage.csv`, `data/h2h_E2_basin.csv`; Jacobian and benchmark-B values from §3 text |
| 4 | structural error budget | `python make_figs_345.py` | **yes** — `data/production_budget_clockfixed.csv`; panel b values from §4.5 text |
| 5 | identifiability of the cold-channel shift | `python make_figs_345.py` | **yes** — `data/cold_shift_landscape.csv`, `data/kriss_injection_0602_shift_profiles.csv`; panel c/d values from §5.1 text |
| 6 | field flags (was Fig 7) | `python fig6_standalone.py` | **yes** — `data/fig6/*.csv`, `data/fig6/meta.json` (derived from the operational fits, `R_cold.npz`, cold raw light, `clock_impact*.csv`; `fig6_session.py` kept for the raw-data path) |

`out/` is written by the three scripts; the PNGs match the submitted versions to within 0.11 (Fig 3–5), 0.004 (Fig 2) and 0.05 (Fig 6) grey levels per pixel on average (2026-09-27 check). Fig 6 panel e uses all 74 667 ΣANs records (`data/fig6/ans_rms_sigma.csv`).

Captions and provenance: `amt_fig2_caption.md`, `amt_fig3_caption.md`, `amt_fig6_caption.md`; Fig 4 and Fig 5 captions are in the §4 and §5 drafts.

## Before archiving at Zenodo
- Fig 1 still needs a standalone script. Its recorded lineage contains hand-typed instrument-space values (`white_vals`, `ar1_vals`) that must be replaced by a file read from the Explorer trace before archiving; do not archive the lineage code as is.
- Decide whether field data (`Output/…`, `RAW/…`) can be archived (TBD-Z3). The derived CSVs in `data/` are enough to redraw Fig 2–6 either way.
- Channel identity for 2026 Yeosu hot raw: see `CHANNEL_IDENTITY_YEOSU2026.md` at the repository root.
