# Fig 6 (was Fig 7) — caption and provenance (2026-09-27)

> 번호 변경: 검증 그림이 Fig 3으로 들어오고 계획상의 Fig 6(스텝 리밋 흐름도)은 Fig 1b로 흡수돼, 현장 그림이 **Fig 6**이 됐다. 파일명은 그대로 둔다.

## Caption (draft)

**Figure 6.** What each reporting field flags during the deployment (18 May – 11 July 2026, KST).
**(a)** From top: hourly median NO$_2$ of the three configurations (symmetric-log axis; red: cold hours below
−5 ppb); hourly median reduced χ$^2$ with the misfit threshold of 1.5; for the cold channel, the interval between
the reflectivity knots that bracket each record (triangles: a knot departing by more than 50 % from its running
median); the raw cold-channel light at 460 nm in ambient and zero-air spectra, with the detector dark level;
the provenance of the heated-channel reflectivity; and records that terminated at a shift bound.
Numbered badges mark the episodes of panel f. **(b)** Episode ①: the change in ΣANs when the heated channels are
retrieved with the clock-aligned instead of the 9 h displaced reflectivity (points: records; line: 6 h median;
dashed: end of the displaced span). Below, for 18–24 May, the change in concentration expressed in units of its
reported σ, against the change in residual RMS and in reported σ. **(c)** Episodes ④ and ⑤: cold NO$_2$ and
reduced χ$^2$ per record, with reflectivity knot times as ticks; the excursions fall in 9.0 h and 4.7 h gaps.
**(d)** Episode ⑦: the same for 2 June, where the knots are regular and only the residual flags the records.
**(e)** Reported σ against residual RMS for every hot ANs record. **(f)** For each episode, whether the residual
(χ$^2$ > 1.5), the termination state, the distance to the nearest reference (knot interval > 2 h or knot
departure > 50 %) the reference provenance, or the raw light level (ambient or zero-air count below 30 % of its usual value) flags it;
the light level was not assessed for the heated channels (–); the cold configuration has fixed shift and squeeze, so its
termination state carries no bound information (n/a).

## Provenance (for the author; not caption text)

- Operational fits: `Output/fitting/ch1_429.5~461.9_ch2_444.1~470.6_ch3_438.4~475.8/*/neg_o/QCoff` (ANs 74 667, PNs 74 667,
  cold 43 259 records). KST: files ≤ 2026-05-29-010 as recorded, later +9 h (same rule as §7.3 counts).
  These fits are already clock-aligned: their ANs NO$_2$ matches `ans_fx` of the clock test (median |Δ| 0.011 ppb) and not `ans_op` (0.083).
- Status column in these files is the pre-2026-09-18 label (signal-relative RMS; see `core/result_io.py`), so the
  figure does not use it. Residual flag = χ$^2$ > 1.5 (`MISFIT_CHI2`); termination = NO$_2$ shift at the FitSet bound
  (ANs [−10, 0.5], PNs [−5, 5]; cold fixed at −0.5). Only PNs reaches a bound: 11 records 2026-06-21 06:13–06:23 (+5 px, χ$^2$ 4.7–5.5)
  plus one at 12:30.
- Cold episodes: hours with median NO$_2$ < −5 ppb on the KST axis, grouped when < 3 h apart → 6 episodes, 19 h
  (matches §7.3). Knot context from `C0` (`gap_h`, `knot_dev`); knot times `Output/R/R_cold.npz`, +9 h after 2026-05-29 21:00
  (checked against `dist_h`: median mismatch 0.0000 h).
- Episode ⑦ is at 11–14 KST on 2 June (earlier hourly table used logger hours, 02–05).
- Displacement: `diagnostics/i0_interp_2026-09/clock_impact.csv` (18–24 May) + `clock_impact_b.csv` (25 May – 1 June).
  Their `sec` axis is UTC (KST = sec + 9 h; r = 0.994 with the operational fit at +9 h). ΔΣANs drawn with g′ = 1/1.050; rSD over 18–24 May
  is 0.0998 ppb with g′ and 0.0997 with 0.82 (§5.4 table: 0.0999). Last non-zero Δ: 2026-05-30 10:07 KST.
  Lollipop values: §5.4 table (|δc|/σ 1.99 / 0.55; residual ratio 1.0020 / 1.0016; σ ratio 1.0022 / 1.0016).
- Panel e: all 74 667 ANs records: r = 0.9986, σ/RMS p95/p5 − 1 = 2.8 %. §7.3 currently cites the old-label OK subset
  (49 471 records, r = 0.998, 2.9 %) — text should switch to the full set.
- Also visible but not an episode in f: 14 hourly medians of hot ANs χ$^2$ > 1.5 between 14 and 22 June (no concentration excursion).
- Light level (added 2026-09-27 after cold raw moved to C:): every `RAW/cold/2026-0[5-6]/*.mat` (671 files), ch1 at
  460 nm; ambient = flag 1 records, zero air = per-file median of flag 502. Normal: ambient 37k, ZA 43k counts; dark ≈ 460.
  Episodes: ② ambient 7.2k / ZA 11.8k · ③ ZA 1.4k · ④ ambient 0.7k · ⑤ both ≈ 0.35k · ⑥ 1.7k / 1.2k · ⑦ ambient 9.4k (22 % of ZA 43k).
- Script: `fig7.py` (inputs prepared in-session: `H`, `C0`, `ev`, `CI`, `KC`).
