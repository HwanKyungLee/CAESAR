# CHANGES 2026-09-30 — follow-up edit round (items A–F)

Baseline: state after the 2026-09-29 evaluation pass (`backup_pre_edit0930`). Full diff: `CHANGES_2026-09-30_edit.diff`.

## 1. Items
- **A** — §3.6: new cause paragraph — time-base test (r 0.985 at zero lag, ≤0.03 at ±9 h; origin slopes 0.61/0.55 before and 0.58/0.49 after 29 May), present from 20 May (0.59) and in every calibration state (0.59/0.55/0.50), O3-driven oven loss not supported (night 300 °C/cold ratio 0.69/0.71/0.78 by O3 tercile; Thieser 2016, Dewald 2021, Wüst 2025), common factors bounded by the laboratory test (≥1.08), remaining candidates, "needs a standard delivered through the complete sampling path"; "No absolute accuracy is claimed" kept.
- **B** — §3.3: shift dependence of the QDOAS/Augur scale (0.9 %/px, 49/50 days, median shift −5.8 px; 0.6 %/px, 45/49 days; stretch ρ = −0.006; Beirle 2013); cold still 3.9 %, ~4 % common component unidentified. Split into two sentences (<60 words each).
- **C** — §2.9: opener "Both questions are loops over data already in memory." and measured runtimes (0.74 s/record, 74 s/100 records, 1.9 h for 9034; 1399-record channel-day 54 s + 90 s, 4.8 min per perturbation; 157 + 54 knots, ≈17 h). Long sentence split.
- **D1** — Abstract: 250 words; "per-scan σ"; best-calibrated week; time-base error stated as 0.100 ppb; 1.44 ratio removed.
- **D2** — §1, §8: time-base error stated first as 0.100 ppb (1.44 removed there). §5.4: kept 1.44 with the clause "the ratio compares a systematic displacement with a record-to-record budget and indicates scale only".
- **D3** — §4.2 LOO sentence: "an upper bound by construction for the interpolation terms (scope in Sect. 4.4)". §4.4: scope sentence — interpolation terms in the best-calibrated week only; excludes terms common to all knots (cross sections, Rayleigh, reflectivity scale) and periods of failed calibration; not a campaign-wide bound.
- **D4** — §4.5: "we report the two as consistent" → "The budget is not larger than the observed variation, as it must be, nor so far below it as to imply an undescribed dominant error; we assign no pass or fail." Caveats (white at 1 h lag, atmospheric variability, doubled interval, operator resolution 0.75–0.84) kept.
- **D5** — §3.5: digits reduced (1.228 at both steps; 1.232 / 1.231; 0.817 "the reciprocal of the same laboratory ratio"); "constant over the concentration steps within this test"; up to 30 % between states; new Table 4 `tab:relscale` (S1 0.952, S2 0.962, S3 1.014, lab current code 1.239 IQR 1.231–1.255, original 1.228–1.232; S2/S3 periods "--").
- **D6** — §5.1: operational cold shift fixed at −0.5 px stated first; −2.014 px / 85.5 % identified as the free-shift, QDOAS-matched setting; objective map (minimum at edge in 77 % of spectra, no optimiser) → bound termination follows from the flat objective; Beirle 2013 cited once.
- **D7** — Table 13 (noise floor) recomputed values (zero_air_floor_g09524_2026-09-30.txt): 155 paired blocks, robust 0.0733 / SD 0.0856 ppb, 3σ 0.220 / 0.257 ppb, median +0.0053 ppb, ratio to product column 0.91 / 1.06, r = −0.093. "Approximate" and "earlier evaluation … 0.82 … not recomputed" removed; ≈ removed. §7.2: +0.0053 in the difference (+0.0028 / −0.0020 in the channels); "a twentieth" → "a fortieth"; "0.84 to about 1.06" → "0.91 to 1.06". §8: same (+0.0053, fortieth, 0.220 to 0.257). Table D1 zero-air row ≈0.086 → 0.0856; caption "approximate" → "from Sect. 7.2".
- **D8** — Table 5 (split-half/LOO): cold "(earlier run)" row (—, 2.391 %, 3.95 %, 0.61) and caption clause "Cold: an earlier run … not recomputed" removed. No text referred to these values.
- **D9** — §4: no sentence >60 words remained after earlier edits (checked). Openers rewritten: "Second, neither variances nor robust scales add." → "Second, the joint scale differs from any quadrature combination of the single-term scales, whether robust scales or standard deviations are combined."; "The dominant term depends on the scale." → "The reflectivity term dominates the tail of the budget and the zero-air term its typical record."
- **D10** — §4.6: residual-based corrections (correlation factor of Stutz 1996; bootstrap and Monte Carlo of Hausmann 1999) address structure in the residual; structural terms leave it unchanged. Merged with the existing Stutz/Platt sentence to avoid repetition.
- **D11** — §6.1: per-record uncertainty components with different correlation scales are established practice for EO climate data records (Merchant 2017), building on JCGM 2008; the three-number convention applies it to a single retrieval.
- **D12** — §2.1: light-level changes between reference and sample enter α directly, a sensitivity that the ICAD method of Horbanski 2019 removes.
- **E** — references.bib: +8 entries (30 total). Thieser second author "Schuster, G." (CrossRef). Wust_2025 initials corrected from the brief (S.; S.) to CrossRef: Wüst, L. and Türk, G. N. T. E. Dewald_2021 authors match CrossRef. JCGM_2008 @misc (no DOI; not CrossRef-checkable).
- **trim** — Compensating cuts (no number changed): §3.4 group-B paragraph condensed (−31); §4.4 scope merged; §4.1 ILS sentence merged; §5.2 cold-shift sentence shortened; §5.4 boundary sentence merged; §6 intro block-length sentence removed; §6.1 clock sentence → pointer to Sect. 5.4; §6.1 load-time check sentence merged; §6.1a 74 %/17 % repetition → pointer to Sect. 4.4 (values remain in §4); §6.2 block-length evidence sentence shortened; §6.5 gain paragraph shortened.

## 2. Word counts (main text, internal counter; the evaluation's counter reads ≈ ×1.085)

| file | 2026-09-29 | 2026-09-30 | Δ |
|---|---|---|---|
| abstract.tex | 246 | 250 | +4 |
| sec1_intro.tex | 1025 | 1035 | +10 |
| sec2_retrieval.tex | 1122 | 1200 | +78 |
| sec3_verification.tex | 1829 | 2161 | +332 |
| sec4_budget.tex | 1958 | 2010 | +52 |
| sec5_pipeline.tex | 2138 | 2182 | +44 |
| sec6_reporting.tex | 2049 | 1997 | -52 |
| sec7_field.tex | 1018 | 1017 | -1 |
| sec8_conclusions.tex | 765 | 768 | +3 |
| **total** | **12150** | **12620** | **+470** |

Abstract: **250** words. Net main-text growth **+470** words, above the ~+400 target by ≈70 words after compensating cuts; §3 (+332, items A/B/D5) accounts for most of it. No sentence in the main text exceeds 60 words.

## 3. Numbers changed (old → new)

| where | old | new | reason |
|---|---|---|---|
| §3.5 per-record medians | 1.2278 / 1.2276 | 1.228 (both steps) | D5 digits |
| §3.5 median-reading ratios | 1.2322 / 1.2306 | 1.232 / 1.231 | D5 digits |
| §3.5 origin slope | 0.81666 | 0.817 | D5 digits |
| Table 13 robust 1σ | 0.0676 | 0.0733 | D7 recomputed, g′ = 0.9524 |
| Table 13 SD 1σ | ≈0.086 | 0.0856 | D7 |
| Table 13 robust 3σ DL | 0.203 | 0.220 | D7 |
| Table 13 SD 3σ DL | ≈0.257 | 0.257 | D7 (≈ removed) |
| Table 13 median at true zero | +0.0054 | +0.0053 | D7 |
| Table 13 ratio to product column | 0.84 / ≈1.06 | 0.91 / 1.06 | D7 |
| §7.2, §8 fraction of DL | a twentieth | a fortieth | D7 (0.0053/0.220 ≈ 1/41) |
| Table D1 zero-air SD | ≈0.086 | 0.0856 | D7, same quantity |
| abstract, §1, §8 | 1.44 × budget | removed (0.100 ppb stated) | D1/D2; 1.44 kept in §5.4 with caveat |
| Table 5 cold row | 2.391 %, 3.95 %, 0.61 | removed | D8 |

New `\fieldnum` values (A, B, C, D5, D6, D7): r 0.985, ≤0.03; slopes 0.61, 0.55, 0.58, 0.49; 0.59 (20 May); 0.59/0.55/0.50 (states); 0.69/0.71/0.78; 31–33 °C; 4–6 %; 0.6; 0.92–1.00; 0.9 %/px, 49/50, −5.8 px, 0.6 %/px, 45/49, ρ −0.006, 3.9 %, ~4 %; 0.74 s, 74 s, 1.9 h, 9034, 1399, 54 s, 90 s, 4.8 min, 157, 54, 17 h; 0.952/0.962/1.014 (Table 4); 77 % (repeated in §5.1); 155, r −0.093, +0.0028, −0.0020. `\fieldnum` sites: 548 (README §4 regenerated).

## 4. Flags for the lead / author

1. §3.6 20 May slope written as **0.59** (results.json 0.5949), not 0.60 as in the brief.
2. Table 4: S2 and S3 date ranges not available in the sources read — shown as "--".
3. `Wust_2025`: brief had "Wüst, S." and "Türk, S."; CrossRef gives Laura Wüst and Gunther N. T. E. Türk → corrected to L. and G. N. T. E. Dewald_2021 and Thieser_2016 match CrossRef. Hausmann_1999 end page 475 not in CrossRef (from brief).
4. Word budget: +470 vs ~+400 target (see §2).
5. `main.pdf` in the folder was overwritten this time (no lock).
6. §7.2 still says a quadrature assembly "would have come within about 4 % of the measured value". With the recomputed floor the file gives quadrature rSD 0.0753 against measured 0.0733 (≈3 %). Not changed because it was not on the list; the author should decide.
7. Build: 45 pages, 0 errors, 0 undefined references/citations, 0 overfull boxes; float numbering follows first citation (Table 4 = `tab:relscale`; budget now Table 6; noise floor Table 13).

## 5. Follow-up (lead, 2026-09-30)

- **Table 4 (`tab:relscale`)**: the S2 and S3 cells that read "--" now give the periods from `ans_cal_state` in the final_v3 merged file: S2 5–21 June, S3 21 June–10 July (S1 18 May–5 June unchanged). Caption: "field periods in local time (KST)". Resolves flag 2 in §4.
- **§7.2**: "within about 4 %" → "within about \fieldnum{3} %" (quadrature rSD 0.0753 vs paired 0.0733 ppb, +2.8 %, r = −0.093). Resolves flag 6 in §4.
- 20 May slope kept as 0.59 (confirmed by the lead).
- Rebuilt: 45 pages, 0 errors, 0 undefined references/citations, 0 overfull boxes.
