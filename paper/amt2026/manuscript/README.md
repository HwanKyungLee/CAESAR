# AMT 2026 manuscript — LaTeX project

*Augur: an α-domain variable-projection DOAS retrieval, and what its diagnostics reveal that standard fit reports do not*
(Atmospheric Measurement Techniques, research article). Assembled 2026-09-28 from the section drafts listed below.

**Note (2026-09-30):** `main.pdf` and `main_fieldnum_coloured.pdf` in this folder were overwritten with the 2026-09-30 build (the 09-29 lock is gone; `main_build_2026-09-29.pdf` no longer exists).

**Status (2026-10-03).** §6 intro updated to the implementation status of the §6.1 convention (all three numbers implemented in the current version, later than v0.2.0; remaining context fields named) — `CHANGES_2026-10-03_edit.md`. +81 words. `main.pdf` rebuilt 2026-10-03 (TinyTeX, TeX Live 2026, pdfTeX + BibTeX): 0 errors, 0 undefined references/citations, 0 overfull boxes, 0 BibTeX warnings; 46 pages, Appendix A on p. 33. `main_fieldnum_coloured.pdf` was not rebuilt.

**Status (2026-09-30, follow-up edit round A–F).** §3.6 cause paragraph (time-base test, calibration states, O$_3$ terciles, bound from the laboratory test); §3.3 shift dependence of the QDOAS scale; §2.9 measured runtimes; external-review fixes D1–D12 (abstract 250 words without the 1.44 ratio; §3.5 digits and new Table 4 `tab:relscale`; LOO scope; §4.5 wording; §5.1 fixed-shift framing; Table 13 noise floor recomputed with g′ = 0.9524; cold "earlier run" row removed from Table 5; §4 topic sentences; Stutz/Hausmann, Merchant/JCGM and Horbanski citations); 8 new bib entries (30 total). Main text 12,620 words by the internal counter (12,150 before, +470). 45 pages; 0 errors, 0 undefined references/citations, 0 overfull boxes. Details and old→new numbers in `CHANGES_2026-09-30_edit.md`.

**Status (2026-09-29, after the evaluation edit pass).** Abstract rewritten to 246 words; research questions stated in §1 ¶2; main text cut from 16,215 to 12,150 words (running text, this README's counter; ≈13,190 on the evaluation's count) by moving implementation detail to Appendix B5–B6 and supplementary budget analyses to a new Appendix D, merging duplicated passages and folding the four 'What the pipeline could report instead' blocks into §6.1 pointers; new §4.6 on previous uncertainty treatments; sentences over 60 words 23 → 0, over 40 words 121 → 37; bold removed from running text; captions ≤ ~120 words; 19 uncited bib entries removed, one reference added; AI-use disclosure and [AUTHOR] placeholders added. No number changed (number-invariance diff in `CHANGES_2026-09-29_edit.md`). 43 pages (main text pp. 1–31).

**Phase 3 status (2026-09-28).** Appendix A (configuration) and Appendix C (calibration-block length, moved from §6.2) added, §6.5 added, framing made profile-general, Figs 1 and 4 re-rendered from data files; see `CHANGES_2026-09-28_phase3.md`. 48 pages (main text pp. 1–38).

**Phase 1+2 status (2026-09-28).** Numbers were replaced and audit contradictions/overclaims fixed per the claim audit and recomputation report of 2026-09-28; every change is listed in `CHANGES_2026-09-28_phase12.md` (unresolved items in its Sect. 3). Phase 3 (restructuring) has not started.

**Earlier status (2026-09-28, after the consistency pass).** All figures and tables are numbered, captioned and cited in order; all nine stale cross-reference items (the seven README entries, of which two covered two sites each) are fixed; implemented-vs-specified wording matches the code (Sect. 7). Four author decisions remain (Sect. 8).

**Field numbers.** Field numbers were checked against the reprocessing on 2026-09-28 and did not change at that step; they were then revised in the Phase 1+2 revision (Sect. 4) (check run by the lead session; report at the repository root, `C:\GHL\CAESAR\docs\재처리_점검_2026-09-28.md`, not part of this folder); all six previously missing references are now in `references.bib`, and `main.pdf` builds with no undefined citations or references.

## 1. Template route

**Official Copernicus class.** `copernicus.cls`, `copernicus.cfg`, `copernicus.bst`, `pdfscreen*.sty` are the
Copernicus LaTeX package 7.16, downloaded from `publications.copernicus.org/Copernicus_LaTeX_Package.zip` on
2026-09-28 (`README_copernicus_package_7_16.txt`). `main.tex` uses `\documentclass[amt, manuscript]{copernicus}`, so no shim was needed.

## 2. Build

```
latexmk -pdf main.tex          # or: pdflatex main; bibtex main; pdflatex main; pdflatex main
```
`main.pdf` in this folder was built on 2026-09-28 with TinyTeX 2026.09 (pdfTeX + BibTeX): **0 errors, 0 undefined
references or citations, 0 overfull boxes, 0 BibTeX warnings**. The only remaining warning is "Text page 12 contains only
floats" (Fig. 2, a full-page float). 45 pages (rebuilt 2026-09-30 after the follow-up round; 43 on 2026-09-29 after the evaluation edit pass; 48 after Phase 3, 46 after Phase 1+2). Main text through §8 ends before Appendix A on p. 33 (2026-09-30; was pp. 1–31 on 09-29, 1–38 earlier).

copernicus.cls needs a few packages that a minimal TeX install lacks: `cancel`, `supertabular`, `newunicodechar`,
`accents`, `subfloat`, `fontawesome5`, `fontawesome` (v4, for `fontawesomesymbols-*.tex`), `regexpatch`, and `t5enc.def`
from `vntex`. With TeX Live/MiKTeX: `tlmgr install cancel supertabular newunicodechar accents subfloat fontawesome5 fontawesome regexpatch vntex`.
A fresh TinyTeX (2026-10-03) also needed `ulem upquote listings pgf babel-english courier helvetic times psnfss algorithms
caption lineno multirow`. The class only *warns* ("Cannot find caption.sty; proceeding without it") when an optional
package is missing and still produces a PDF with a different layout — check `main.log` for "Cannot find".
(conda-forge `tectonic` 0.17 was tried first and fails on this Windows sandbox with "Unable to find standard directories for platform".)

**Proof-reading switch.** Uncomment `\fielddrafttrue` in `main.tex` to print every `\fieldnum{}` value in magenta
(a coloured build of 2026-09-28 is saved as the artifact `main_fieldnum_coloured.pdf`).

## 3. Files

| file | content | source draft |
|---|---|---|
| `main.tex` | class, macros (`\fieldnum`, `\strong`), title/authors (placeholders), section inputs, back matter | — |
| `abstract.tex` | Abstract | 초록 v5 (2026-09-21, 09-27 edits) |
| `sec1_intro.tex` | 1 Introduction (+ Fig. 1 float) | §1 v1 |
| `sec2_retrieval.tex` | 2.1–2.8, 2.9 | §2 v1; §2.9 from §2.9+§3 v1 |
| `sec3_verification.tex` | 3.1–3.6, Tables 1–4 (Table 3 = QDOAS field table, `tab:qdoas_field`; Table 4 = `tab:relscale`, 2026-09-30) (+ Fig. 2, Fig. 3 floats) | §2.9+§3 v1 |
| `sec4_budget.tex` | 4.1–4.6, Tables 5–7 (budget = Table 6, `tab:2`), Fig. 4 | §4 v16 |
| `sec5_pipeline.tex` | 5.1–5.4, Fig. 5 | §5 v6 |
| `sec6_reporting.tex` | 6.1, 6.1.1 (draft "6.1a"), 6.2–6.4 | §6 v1 |
| `sec7_field.tex` | 7.1–7.3, Fig. 6 | §7 v1 |
| `sec8_conclusions.tex` | 8 Conclusions (trimmed) | §8 v1 |
| `availability.tex` | Code and data availability | availability draft (2026-09-27) |
| `appA_config.tex` | Appendix A: instrument and retrieval configuration (Tables A1, A2) | Phase 3; operational fit-setting JSON + wavecal files |
| `appB.tex` | Appendix B: projected Jacobian, column scaling, joint covariance (Table B1) | 부록 B v1 |
| `appD_denominator.tex` | Appendix D: supplementary budget analyses (D1 choice of denominator, Table D1; D2 shift coupling, Table D2) | moved from §4.4 and §5.1 (2026-09-29) |
| `CHANGES_2026-09-29_edit.md` | evaluation edit pass: word/sentence statistics, moved blocks, references, number-invariance diff | — |
| `appC_blocks.tex` | Appendix C: calibration-block length and duty cycle (Eq. 18, Tables C1–C3) | moved verbatim from §6.2 (Phase 3) |
| `references.bib` | bibliography | augur_AMT_references.bib (cleaned, see Sect. 6) |
| `CHANGES_2026-09-28_phase3.md` / `.diff` | Phase 3 changelog (moves, cuts, page counts, figures, claims touched, unresolved) and diff | — |
| `CHANGES_2026-09-28_phase12.md` / `.diff` | Phase 1+2 changelog (edit table, kept/removed numbers, unresolved) and unified diff against the pre-revision copy | — |
| `figures/fig01.pdf … fig06.pdf` | copies of amt_fig1_thesis_v2, amt_fig2_representative_fits, amt_fig3_validation, amt_fig4_error_budget, amt_fig5_identifiability, amt_fig7_field_flags (= Fig. 6) | artifact store |

## 4. Field numbers: revised 2026-09-28 (Phase 1+2)

The field-record values were first checked on 2026-09-28 against the reprocessing (hot pressure-sensor pairing fix,
cold R(t) without the three KRISS-injection knots), which moves channel NO$_2$ by only −0.25 %/+0.25 % (see `docs/재처리_점검_2026-09-28.md`).
**They were then replaced where the claim audit and the recomputation report of 2026-09-28 gave new values** (clock-aligned R(t),
g′ = 0.9524, the 9034/187/8847 budget population, denominator 0.0541 ppb). Every replacement, and every number kept with an explicit
basis, weakened or removed, is listed in `CHANGES_2026-09-28_phase12.md` (full line diff: `CHANGES_2026-09-28_phase12.diff`).
The `\fieldnum{}` macro is kept (it prints its argument unchanged; `\fielddrafttrue` colours it) so that any later update remains a search-and-replace.

Wrapping rule used: every numeral that comes from the 2026 field record (ppb values, record/block/hour counts, percentages of
records, budget-table (now Table 5, draft "Table 2") / Fig. 4 values, ratios and shape statistics derived from them, slopes, correlation coefficients,
§5.4 and §7.3 statistics). **Not wrapped:** Sect. 3 synthetic and laboratory numbers (including the §3.5 injection
experiment), Appendix B, the KRISS cylinder-injection results in §5.1 (−0.10/−0.15 px, 9.3/3.6 ppb, 39 %/7.5 %/2.0 %,
0.06 px), instrument/configuration constants (windows, orders, bounds, N = 34, T = 32 s, cadences, duty cycles, d, R_L,
dispersion, ILS FWHM), thresholds (−5 ppb, 1.5, 30 %, 50 %, 2 h), dates, and counts spelled out in words ("twelve days",
"six excursions", "eleven of the thirteen"). The Sect. 3.3 field comparison (text and Table 3) is wrapped.

**548 `\fieldnum` sites** (line numbers as of 2026-09-30, after the follow-up edit round):

| file | line | value |
|---|---|---|
| abstract.tex | 12 | `1.28` |
| abstract.tex | 12 | `2.29` |
| abstract.tex | 13 | `1.63` |
| abstract.tex | 13 | `2.50` |
| abstract.tex | 16 | `0.100` |
| sec1_intro.tex | 53 | `1.6` |
| sec1_intro.tex | 53 | `2.5` |
| sec1_intro.tex | 56 | `0.100` |
| sec1_intro.tex | 83 | `1.63` |
| sec1_intro.tex | 84 | `2.50` |
| sec1_intro.tex | 84 | `8847` |
| sec1_intro.tex | 85 | `8446` |
| sec2_retrieval.tex | 159 | `9034` |
| sec2_retrieval.tex | 160 | `8847` |
| sec2_retrieval.tex | 168 | `0.74` |
| sec2_retrieval.tex | 169 | `74` |
| sec2_retrieval.tex | 169 | `1.9` |
| sec2_retrieval.tex | 169 | `9034` |
| sec2_retrieval.tex | 170 | `1399` |
| sec2_retrieval.tex | 170 | `54` |
| sec2_retrieval.tex | 170 | `90` |
| sec2_retrieval.tex | 171 | `4.8` |
| sec2_retrieval.tex | 171 | `157` |
| sec2_retrieval.tex | 172 | `54` |
| sec2_retrieval.tex | 172 | `17` |
| sec3_verification.tex | 41 | `1397` |
| sec3_verification.tex | 41 | `1399` |
| sec3_verification.tex | 41 | `707` |
| sec3_verification.tex | 42 | `49` |
| sec3_verification.tex | 42 | `53` |
| sec3_verification.tex | 42 | `81` |
| sec3_verification.tex | 136 | `0.990` |
| sec3_verification.tex | 137 | `1.039` |
| sec3_verification.tex | 137 | `1.063` |
| sec3_verification.tex | 138 | `1.043` |
| sec3_verification.tex | 138 | `1.000` |
| sec3_verification.tex | 139 | `4` |
| sec3_verification.tex | 139 | `6` |
| sec3_verification.tex | 140 | `0.9` |
| sec3_verification.tex | 140 | `49` |
| sec3_verification.tex | 140 | `50` |
| sec3_verification.tex | 141 | `$-5.8$` |
| sec3_verification.tex | 141 | `0.6` |
| sec3_verification.tex | 141 | `45` |
| sec3_verification.tex | 141 | `49` |
| sec3_verification.tex | 142 | `-0.006` |
| sec3_verification.tex | 144 | `3.9` |
| sec3_verification.tex | 144 | `4` |
| sec3_verification.tex | 145 | `0.889` |
| sec3_verification.tex | 145 | `0.959` |
| sec3_verification.tex | 145 | `0.81` |
| sec3_verification.tex | 145 | `1.19` |
| sec3_verification.tex | 145 | `1.04` |
| sec3_verification.tex | 145 | `1.38` |
| sec3_verification.tex | 157 | `36\,241` |
| sec3_verification.tex | 157 | `1.039` |
| sec3_verification.tex | 157 | `0.990` |
| sec3_verification.tex | 158 | `36\,241` |
| sec3_verification.tex | 158 | `0.807` |
| sec3_verification.tex | 158 | `0.889` |
| sec3_verification.tex | 159 | `36\,241` |
| sec3_verification.tex | 159 | `1.377` |
| sec3_verification.tex | 159 | `0.887` |
| sec3_verification.tex | 160 | `73\,916` |
| sec3_verification.tex | 160 | `1.063` |
| sec3_verification.tex | 160 | `1.000` |
| sec3_verification.tex | 161 | `73\,916` |
| sec3_verification.tex | 161 | `1.195` |
| sec3_verification.tex | 161 | `0.914` |
| sec3_verification.tex | 162 | `73\,916` |
| sec3_verification.tex | 162 | `1.042` |
| sec3_verification.tex | 162 | `0.974` |
| sec3_verification.tex | 163 | `74\,539` |
| sec3_verification.tex | 163 | `1.043` |
| sec3_verification.tex | 163 | `1.000` |
| sec3_verification.tex | 164 | `74\,539` |
| sec3_verification.tex | 164 | `1.054` |
| sec3_verification.tex | 164 | `0.959` |
| sec3_verification.tex | 165 | `74\,539` |
| sec3_verification.tex | 165 | `1.038` |
| sec3_verification.tex | 165 | `0.981` |
| sec3_verification.tex | 208 | `0.952` |
| sec3_verification.tex | 222 | `0.952` |
| sec3_verification.tex | 223 | `0.962` |
| sec3_verification.tex | 224 | `1.014` |
| sec3_verification.tex | 236 | `0.57` |
| sec3_verification.tex | 236 | `0.65` |
| sec3_verification.tex | 237 | `0.92` |
| sec3_verification.tex | 237 | `1.00` |
| sec3_verification.tex | 237 | `0.72` |
| sec3_verification.tex | 243 | `0.985` |
| sec3_verification.tex | 243 | `0.03` |
| sec3_verification.tex | 243 | `0.61` |
| sec3_verification.tex | 244 | `0.55` |
| sec3_verification.tex | 244 | `0.58` |
| sec3_verification.tex | 244 | `0.49` |
| sec3_verification.tex | 244 | `0.59` |
| sec3_verification.tex | 245 | `0.59` |
| sec3_verification.tex | 245 | `0.55` |
| sec3_verification.tex | 245 | `0.50` |
| sec3_verification.tex | 248 | `0.69` |
| sec3_verification.tex | 248 | `0.71` |
| sec3_verification.tex | 248 | `0.78` |
| sec3_verification.tex | 250 | `31` |
| sec3_verification.tex | 250 | `33` |
| sec3_verification.tex | 251 | `4` |
| sec3_verification.tex | 251 | `6` |
| sec3_verification.tex | 252 | `0.6` |
| sec3_verification.tex | 255 | `0.92` |
| sec3_verification.tex | 255 | `1.00` |
| sec4_budget.tex | 10 | `0.55` |
| sec4_budget.tex | 18 | `0.1` |
| sec4_budget.tex | 23 | `1.05` |
| sec4_budget.tex | 23 | `1.57` |
| sec4_budget.tex | 41 | `0.74` |
| sec4_budget.tex | 41 | `0.91` |
| sec4_budget.tex | 44 | `0.40` |
| sec4_budget.tex | 44 | `0.43` |
| sec4_budget.tex | 46 | `15` |
| sec4_budget.tex | 46 | `33` |
| sec4_budget.tex | 47 | `7` |
| sec4_budget.tex | 47 | `19` |
| sec4_budget.tex | 60 | `1.437` |
| sec4_budget.tex | 60 | `1.782` |
| sec4_budget.tex | 60 | `1.95` |
| sec4_budget.tex | 60 | `0.74` |
| sec4_budget.tex | 60 | `0.91` |
| sec4_budget.tex | 61 | `0.90` |
| sec4_budget.tex | 61 | `0.97` |
| sec4_budget.tex | 61 | `2.25` |
| sec4_budget.tex | 61 | `0.40` |
| sec4_budget.tex | 61 | `0.43` |
| sec4_budget.tex | 72 | `0.8` |
| sec4_budget.tex | 72 | `2.2` |
| sec4_budget.tex | 74 | `8.3` |
| sec4_budget.tex | 75 | `6.4` |
| sec4_budget.tex | 75 | `$-0.2$` |
| sec4_budget.tex | 80 | `$+13.3$` |
| sec4_budget.tex | 80 | `$-8.1$` |
| sec4_budget.tex | 80 | `$+6.9$` |
| sec4_budget.tex | 81 | `15.5` |
| sec4_budget.tex | 82 | `7.6` |
| sec4_budget.tex | 82 | `2.5` |
| sec4_budget.tex | 83 | `0.25` |
| sec4_budget.tex | 83 | `0.18` |
| sec4_budget.tex | 84 | `0.03` |
| sec4_budget.tex | 84 | `28.7` |
| sec4_budget.tex | 85 | `12.9` |
| sec4_budget.tex | 85 | `15.8` |
| sec4_budget.tex | 87 | `0.73` |
| sec4_budget.tex | 87 | `0.32` |
| sec4_budget.tex | 87 | `0.98` |
| sec4_budget.tex | 88 | `0.56` |
| sec4_budget.tex | 108 | `9034` |
| sec4_budget.tex | 109 | `187` |
| sec4_budget.tex | 110 | `8847` |
| sec4_budget.tex | 111 | `0.9524` |
| sec4_budget.tex | 118 | `0.0437` |
| sec4_budget.tex | 118 | `0.0350` |
| sec4_budget.tex | 118 | `0.0082` |
| sec4_budget.tex | 118 | `0.0641` |
| sec4_budget.tex | 119 | `0.0600` |
| sec4_budget.tex | 119 | `0.0829` |
| sec4_budget.tex | 119 | `0.0086` |
| sec4_budget.tex | 119 | `0.1186` |
| sec4_budget.tex | 120 | `0.73` |
| sec4_budget.tex | 120 | `0.42` |
| sec4_budget.tex | 120 | `0.95` |
| sec4_budget.tex | 120 | `0.54` |
| sec4_budget.tex | 121 | `0.0416` |
| sec4_budget.tex | 121 | `0.0126` |
| sec4_budget.tex | 121 | `0.0187` |
| sec4_budget.tex | 121 | `0.0435` |
| sec4_budget.tex | 122 | `0.0428` |
| sec4_budget.tex | 122 | `0.0384` |
| sec4_budget.tex | 122 | `0.0189` |
| sec4_budget.tex | 122 | `0.0590` |
| sec4_budget.tex | 123 | `0.97` |
| sec4_budget.tex | 123 | `0.33` |
| sec4_budget.tex | 123 | `0.99` |
| sec4_budget.tex | 123 | `0.74` |
| sec4_budget.tex | 124 | `0.0558` |
| sec4_budget.tex | 124 | `0.0269` |
| sec4_budget.tex | 124 | `0.0191` |
| sec4_budget.tex | 124 | `0.0693` |
| sec4_budget.tex | 125 | `0.0768` |
| sec4_budget.tex | 125 | `0.0831` |
| sec4_budget.tex | 125 | `0.0195` |
| sec4_budget.tex | 125 | `0.1236` |
| sec4_budget.tex | 126 | `0.73` |
| sec4_budget.tex | 126 | `0.32` |
| sec4_budget.tex | 126 | `0.98` |
| sec4_budget.tex | 126 | `0.56` |
| sec4_budget.tex | 131 | `74` |
| sec4_budget.tex | 132 | `45` |
| sec4_budget.tex | 132 | `17` |
| sec4_budget.tex | 132 | `52` |
| sec4_budget.tex | 134 | `155` |
| sec4_budget.tex | 134 | `57` |
| sec4_budget.tex | 139 | `8847` |
| sec4_budget.tex | 140 | `0.9524` |
| sec4_budget.tex | 144 | `57` |
| sec4_budget.tex | 151 | `11.03` |
| sec4_budget.tex | 156 | `0.0541` |
| sec4_budget.tex | 156 | `1.28` |
| sec4_budget.tex | 157 | `2.29` |
| sec4_budget.tex | 157 | `1.63` |
| sec4_budget.tex | 157 | `2.50` |
| sec4_budget.tex | 173 | `1.00` |
| sec4_budget.tex | 173 | `1.03` |
| sec4_budget.tex | 174 | `$-0.60$` |
| sec4_budget.tex | 175 | `$+0.73$` |
| sec4_budget.tex | 186 | `1258` |
| sec4_budget.tex | 186 | `0.081` |
| sec4_budget.tex | 187 | `154` |
| sec4_budget.tex | 187 | `0.082` |
| sec4_budget.tex | 188 | `0.0618` |
| sec4_budget.tex | 188 | `0.75` |
| sec4_budget.tex | 189 | `0.0693` |
| sec4_budget.tex | 189 | `0.84` |
| sec4_budget.tex | 194 | `0.75` |
| sec4_budget.tex | 195 | `154` |
| sec4_budget.tex | 195 | `153` |
| sec4_budget.tex | 195 | `0.082` |
| sec4_budget.tex | 196 | `0.76` |
| sec4_budget.tex | 200 | `0.75` |
| sec4_budget.tex | 200 | `0.84` |
| sec4_budget.tex | 204 | `0.366` |
| sec5_pipeline.tex | 22 | `1.0120` |
| sec5_pipeline.tex | 22 | `1.0611` |
| sec5_pipeline.tex | 22 | `165` |
| sec5_pipeline.tex | 23 | `77` |
| sec5_pipeline.tex | 24 | `0.01` |
| sec5_pipeline.tex | 24 | `4.35` |
| sec5_pipeline.tex | 25 | `3.09\times10^{5}` |
| sec5_pipeline.tex | 27 | `$-2.014$` |
| sec5_pipeline.tex | 27 | `85.5` |
| sec5_pipeline.tex | 28 | `$-0.088$` |
| sec5_pipeline.tex | 28 | `4.5` |
| sec5_pipeline.tex | 29 | `77` |
| sec5_pipeline.tex | 42 | `5364` |
| sec5_pipeline.tex | 42 | `0.940` |
| sec5_pipeline.tex | 43 | `0.858` |
| sec5_pipeline.tex | 43 | `1.027` |
| sec5_pipeline.tex | 43 | `1.019` |
| sec5_pipeline.tex | 43 | `0.662` |
| sec5_pipeline.tex | 43 | `1.178` |
| sec5_pipeline.tex | 44 | `23` |
| sec5_pipeline.tex | 46 | `34` |
| sec5_pipeline.tex | 46 | `18` |
| sec5_pipeline.tex | 48 | `2.2` |
| sec5_pipeline.tex | 49 | `$-0.06$` |
| sec5_pipeline.tex | 49 | `$+2.2$` |
| sec5_pipeline.tex | 49 | `$-0.8$` |
| sec5_pipeline.tex | 49 | `23` |
| sec5_pipeline.tex | 60 | `5364` |
| sec5_pipeline.tex | 67 | `$-2.014 \pm 0.03$` |
| sec5_pipeline.tex | 67 | `$\pm 2$` |
| sec5_pipeline.tex | 80 | `22` |
| sec5_pipeline.tex | 80 | `$-1.000$` |
| sec5_pipeline.tex | 84 | `187` |
| sec5_pipeline.tex | 84 | `9034` |
| sec5_pipeline.tex | 86 | `121` |
| sec5_pipeline.tex | 87 | `4` |
| sec5_pipeline.tex | 98 | `11.8` |
| sec5_pipeline.tex | 100 | `157` |
| sec5_pipeline.tex | 100 | `157` |
| sec5_pipeline.tex | 101 | `164` |
| sec5_pipeline.tex | 101 | `164` |
| sec5_pipeline.tex | 101 | `1313` |
| sec5_pipeline.tex | 107 | `9149` |
| sec5_pipeline.tex | 114 | `76\,282` |
| sec5_pipeline.tex | 114 | `0.08` |
| sec5_pipeline.tex | 114 | `0.07` |
| sec5_pipeline.tex | 114 | `3.76` |
| sec5_pipeline.tex | 114 | `1.23` |
| sec5_pipeline.tex | 114 | `10.6` |
| sec5_pipeline.tex | 115 | `9\,088` |
| sec5_pipeline.tex | 115 | `0.01` |
| sec5_pipeline.tex | 115 | `0.00` |
| sec5_pipeline.tex | 115 | `0.00` |
| sec5_pipeline.tex | 115 | `0.00` |
| sec5_pipeline.tex | 115 | `1.3` |
| sec5_pipeline.tex | 116 | `43\,259` |
| sec5_pipeline.tex | 116 | `0.13` |
| sec5_pipeline.tex | 116 | `0.34` |
| sec5_pipeline.tex | 116 | `2.89` |
| sec5_pipeline.tex | 116 | `11.03` |
| sec5_pipeline.tex | 116 | `11.8` |
| sec5_pipeline.tex | 117 | `7\,069` |
| sec5_pipeline.tex | 117 | `0.42` |
| sec5_pipeline.tex | 117 | `0.00` |
| sec5_pipeline.tex | 117 | `17.32` |
| sec5_pipeline.tex | 117 | `18.31` |
| sec5_pipeline.tex | 117 | `11.8` |
| sec5_pipeline.tex | 122 | `0.08` |
| sec5_pipeline.tex | 123 | `0.07` |
| sec5_pipeline.tex | 123 | `922` |
| sec5_pipeline.tex | 127 | `11.3` |
| sec5_pipeline.tex | 128 | `0.24` |
| sec5_pipeline.tex | 128 | `3` |
| sec5_pipeline.tex | 128 | `1\,264` |
| sec5_pipeline.tex | 128 | `75` |
| sec5_pipeline.tex | 128 | `743` |
| sec5_pipeline.tex | 128 | `10.1` |
| sec5_pipeline.tex | 129 | `11.3` |
| sec5_pipeline.tex | 129 | `3.5` |
| sec5_pipeline.tex | 130 | `11.03` |
| sec5_pipeline.tex | 130 | `11.8` |
| sec5_pipeline.tex | 135 | `2.8` |
| sec5_pipeline.tex | 135 | `5.8` |
| sec5_pipeline.tex | 137 | `0.00` |
| sec5_pipeline.tex | 137 | `18.31` |
| sec5_pipeline.tex | 148 | `9\,132` |
| sec5_pipeline.tex | 152 | `0.9524` |
| sec5_pipeline.tex | 158 | `0.1048` |
| sec5_pipeline.tex | 158 | `0.1627` |
| sec5_pipeline.tex | 158 | `3.0` |
| sec5_pipeline.tex | 159 | `0.0358` |
| sec5_pipeline.tex | 159 | `0.0563` |
| sec5_pipeline.tex | 159 | `2.8` |
| sec5_pipeline.tex | 160 | `0.100` |
| sec5_pipeline.tex | 160 | `0.1418` |
| sec5_pipeline.tex | 160 | `3.7` |
| sec5_pipeline.tex | 165 | `0.100` |
| sec5_pipeline.tex | 166 | `1.44` |
| sec5_pipeline.tex | 178 | `3.37\times10^{-9}` |
| sec5_pipeline.tex | 178 | `1.0020` |
| sec5_pipeline.tex | 178 | `1.0022` |
| sec5_pipeline.tex | 178 | `1.99` |
| sec5_pipeline.tex | 178 | `0.0053` |
| sec5_pipeline.tex | 179 | `1.53\times10^{-8}` |
| sec5_pipeline.tex | 179 | `1.0016` |
| sec5_pipeline.tex | 179 | `1.0016` |
| sec5_pipeline.tex | 179 | `0.55` |
| sec5_pipeline.tex | 179 | `0.0065` |
| sec5_pipeline.tex | 185 | `6.16\times10^{-9}` |
| sec5_pipeline.tex | 187 | `0.005` |
| sec5_pipeline.tex | 188 | `0.243` |
| sec5_pipeline.tex | 193 | `7.0` |
| sec5_pipeline.tex | 193 | `0.0745` |
| sec5_pipeline.tex | 193 | `0.0693` |
| sec5_pipeline.tex | 193 | `4.5` |
| sec5_pipeline.tex | 193 | `0.1183` |
| sec5_pipeline.tex | 193 | `0.1236` |
| sec5_pipeline.tex | 194 | `1.70` |
| sec5_pipeline.tex | 194 | `2.41` |
| sec5_pipeline.tex | 194 | `1.63` |
| sec5_pipeline.tex | 194 | `2.50` |
| sec5_pipeline.tex | 195 | `8505` |
| sec5_pipeline.tex | 195 | `9034` |
| sec5_pipeline.tex | 195 | `9149` |
| sec5_pipeline.tex | 196 | `93.0` |
| sec5_pipeline.tex | 196 | `98.7` |
| sec5_pipeline.tex | 198 | `$+0.412$` |
| sec5_pipeline.tex | 198 | `$+0.146$` |
| sec5_pipeline.tex | 203 | `0.0622` |
| sec5_pipeline.tex | 203 | `0.0000` |
| sec5_pipeline.tex | 204 | `0.100` |
| sec5_pipeline.tex | 205 | `0.0622` |
| sec6_reporting.tex | 58 | `42.3` |
| sec6_reporting.tex | 66 | `0.0` |
| sec6_reporting.tex | 66 | `9` |
| sec6_reporting.tex | 69 | `0.80` |
| sec6_reporting.tex | 69 | `1.09` |
| sec6_reporting.tex | 69 | `0.83` |
| sec6_reporting.tex | 69 | `1.11` |
| sec6_reporting.tex | 80 | `155` |
| sec6_reporting.tex | 90 | `0.73` |
| sec6_reporting.tex | 90 | `63` |
| sec6_reporting.tex | 90 | `41` |
| sec6_reporting.tex | 90 | `24` |
| sec6_reporting.tex | 90 | `38` |
| sec6_reporting.tex | 90 | `45` |
| sec6_reporting.tex | 91 | `0.32` |
| sec6_reporting.tex | 91 | `26` |
| sec6_reporting.tex | 91 | `17` |
| sec6_reporting.tex | 91 | `12` |
| sec6_reporting.tex | 91 | `22` |
| sec6_reporting.tex | 91 | `52` |
| sec6_reporting.tex | 92 | `0.98` |
| sec6_reporting.tex | 92 | `118` |
| sec6_reporting.tex | 92 | `76` |
| sec6_reporting.tex | 92 | `26` |
| sec6_reporting.tex | 92 | `29` |
| sec6_reporting.tex | 92 | `3` |
| sec6_reporting.tex | 98 | `37` |
| sec6_reporting.tex | 109 | `0.87` |
| sec6_reporting.tex | 109 | `1.00` |
| sec6_reporting.tex | 109 | `2.05` |
| sec6_reporting.tex | 110 | `2.73` |
| sec6_reporting.tex | 115 | `7` |
| sec6_reporting.tex | 118 | `45` |
| sec6_reporting.tex | 119 | `0.1236` |
| sec6_reporting.tex | 119 | `0.1008` |
| sec6_reporting.tex | 119 | `18.5` |
| sec6_reporting.tex | 120 | `0.0901` |
| sec6_reporting.tex | 128 | `28` |
| sec6_reporting.tex | 128 | `76` |
| sec6_reporting.tex | 129 | `97` |
| sec6_reporting.tex | 131 | `13` |
| sec6_reporting.tex | 131 | `38` |
| sec6_reporting.tex | 131 | `13` |
| sec6_reporting.tex | 132 | `99.9` |
| sec6_reporting.tex | 132 | `25` |
| sec6_reporting.tex | 133 | `2` |
| sec6_reporting.tex | 133 | `3` |
| sec6_reporting.tex | 133 | `8` |
| sec6_reporting.tex | 180 | `0.6` |
| sec7_field.tex | 19 | `$-6.12$` |
| sec7_field.tex | 20 | `0.25` |
| sec7_field.tex | 29 | `155` |
| sec7_field.tex | 31 | `-0.093` |
| sec7_field.tex | 31 | `4` |
| sec7_field.tex | 35 | `155` |
| sec7_field.tex | 35 | `0.9524` |
| sec7_field.tex | 35 | `-0.093` |
| sec7_field.tex | 41 | `0.0733` |
| sec7_field.tex | 41 | `0.0856` |
| sec7_field.tex | 42 | `0.220` |
| sec7_field.tex | 42 | `0.257` |
| sec7_field.tex | 43 | `$+0.0053$` |
| sec7_field.tex | 43 | `$+0.0053$` |
| sec7_field.tex | 44 | `0.0806` |
| sec7_field.tex | 44 | `0.91` |
| sec7_field.tex | 44 | `1.06` |
| sec7_field.tex | 49 | `$+0.0053$` |
| sec7_field.tex | 49 | `$+0.0028$` |
| sec7_field.tex | 49 | `$-0.0020$` |
| sec7_field.tex | 54 | `0.91` |
| sec7_field.tex | 54 | `1.06` |
| sec7_field.tex | 55 | `0.0806` |
| sec7_field.tex | 57 | `46.1` |
| sec7_field.tex | 58 | `1.48` |
| sec7_field.tex | 59 | `0.0806` |
| sec7_field.tex | 59 | `0.0543` |
| sec7_field.tex | 73 | `+0.999` |
| sec7_field.tex | 73 | `74\,667` |
| sec7_field.tex | 74 | `2.8` |
| sec7_field.tex | 77 | `19` |
| sec7_field.tex | 78 | `8` |
| sec7_field.tex | 78 | `600` |
| sec7_field.tex | 79 | `5.6` |
| sec7_field.tex | 79 | `91` |
| sec7_field.tex | 79 | `1.2` |
| sec7_field.tex | 80 | `2.6` |
| sec7_field.tex | 80 | `9.0` |
| sec7_field.tex | 81 | `66` |
| sec7_field.tex | 81 | `300` |
| sec7_field.tex | 81 | `10` |
| sec7_field.tex | 85 | `22` |
| sec7_field.tex | 91 | `4.7` |
| sec7_field.tex | 91 | `5.5` |
| sec7_field.tex | 103 | `9.0` |
| sec7_field.tex | 103 | `4.7` |
| sec8_conclusions.tex | 14 | `0.990` |
| sec8_conclusions.tex | 14 | `4` |
| sec8_conclusions.tex | 14 | `6` |
| sec8_conclusions.tex | 14 | `$+0.0053$` |
| sec8_conclusions.tex | 15 | `0.220` |
| sec8_conclusions.tex | 15 | `0.257` |
| sec8_conclusions.tex | 21 | `1.28` |
| sec8_conclusions.tex | 21 | `2.29` |
| sec8_conclusions.tex | 22 | `1.63` |
| sec8_conclusions.tex | 22 | `2.50` |
| sec8_conclusions.tex | 29 | `187` |
| sec8_conclusions.tex | 29 | `9034` |
| sec8_conclusions.tex | 33 | `0.100` |
| sec8_conclusions.tex | 36 | `0.6` |
| appA_config.tex | 60 | `0.1` |
| appA_config.tex | 70 | `1261` |
| appA_config.tex | 71 | `1.00` |
| appA_config.tex | 81 | `157` |
| appA_config.tex | 82 | `54` |
| appC_blocks.tex | 39 | `2.506\times10^{-4}` |
| appC_blocks.tex | 39 | `1.095\times10^{-4}` |
| appC_blocks.tex | 40 | `2.332\times10^{-4}` |
| appC_blocks.tex | 40 | `0.820\times10^{-4}` |
| appC_blocks.tex | 41 | `0.104` |
| appC_blocks.tex | 41 | `0.416` |
| appC_blocks.tex | 42 | `2.26` |
| appC_blocks.tex | 42 | `1.22` |
| appC_blocks.tex | 47 | `7` |
| appC_blocks.tex | 87 | `45` |
| appC_blocks.tex | 88 | `0.1236` |
| appC_blocks.tex | 88 | `0.1008` |
| appC_blocks.tex | 88 | `18.5` |
| appC_blocks.tex | 98 | `0.1236` |
| appC_blocks.tex | 99 | `0.1008` |
| appC_blocks.tex | 99 | `0.82` |
| appC_blocks.tex | 100 | `0.0901` |
| appC_blocks.tex | 100 | `0.73` |
| appC_blocks.tex | 101 | `0.0547` |
| appC_blocks.tex | 101 | `0.44` |
| appC_blocks.tex | 109 | `7.6` |
| appC_blocks.tex | 109 | `0.1236` |
| appC_blocks.tex | 109 | `0.1149` |
| appC_blocks.tex | 129 | `40` |
| appC_blocks.tex | 129 | `34` |
| appC_blocks.tex | 130 | `1.29` |
| appC_blocks.tex | 130 | `1.23` |
| appC_blocks.tex | 135 | `1.88` |
| appC_blocks.tex | 136 | `1.17` |
| appC_blocks.tex | 145 | `$+248$` |
| appC_blocks.tex | 146 | `$-314$` |
| appC_blocks.tex | 146 | `$-261$` |
| appC_blocks.tex | 146 | `$+235$` |
| appD_denominator.tex | 18 | `0.0541` |
| appD_denominator.tex | 18 | `1.63` |
| appD_denominator.tex | 18 | `2.50` |
| appD_denominator.tex | 19 | `0.0806` |
| appD_denominator.tex | 19 | `1.32` |
| appD_denominator.tex | 19 | `1.83` |
| appD_denominator.tex | 20 | `0.025` |
| appD_denominator.tex | 21 | `0.0856` |
| appD_denominator.tex | 27 | `14\,974` |
| appD_denominator.tex | 27 | `0.04209` |
| appD_denominator.tex | 27 | `0.00025` |
| appD_denominator.tex | 28 | `+0.9997` |
| appD_denominator.tex | 32 | `0.0558` |
| appD_denominator.tex | 37 | `8832` |
| appD_denominator.tex | 40 | `0.0558` |
| appD_denominator.tex | 40 | `1.59` |
| appD_denominator.tex | 40 | `2.43` |
| appD_denominator.tex | 40 | `0.0217` |
| appD_denominator.tex | 41 | `0.0326` |
| appD_denominator.tex | 48 | `0.006` |
| appD_denominator.tex | 48 | `0.027` |
| appD_denominator.tex | 49 | `0.285` |
| appD_denominator.tex | 55 | `8847` |
| appD_denominator.tex | 62 | `0.187` |
| appD_denominator.tex | 62 | `0.826` |
| appD_denominator.tex | 62 | `4.388` |
| appD_denominator.tex | 63 | `0.006` |
| appD_denominator.tex | 63 | `0.027` |
| appD_denominator.tex | 63 | `0.285` |
| appD_denominator.tex | 64 | `0.154` |
| appD_denominator.tex | 64 | `0.347` |
| appD_denominator.tex | 64 | `2.941` |
| appD_denominator.tex | 65 | `0.243` |
| appD_denominator.tex | 65 | `0.766` |
| appD_denominator.tex | 65 | `4.276` |
| appD_denominator.tex | 71 | `6.2` |
| appD_denominator.tex | 71 | `5.0` |
| appD_denominator.tex | 72 | `0.0693` |
| appD_denominator.tex | 72 | `0.0706` |
| appD_denominator.tex | 72 | `0.1236` |
| appD_denominator.tex | 72 | `0.1244` |

## 5. §8 Conclusions — trimmed

*2026-09-29:* §8 was rewritten again in the evaluation edit pass (1031 → 768 words, mean sentence length 24.0); the counts below are historical.

| | words | paragraphs (words each) |
|---|---|---|
| draft (§8 v1, English body) | **1,050** | 121 / 117 / 151 / 166 / 150 / 122 / 121 / 102 |
| `sec8_conclusions.tex` | **841** | 95 / 75 / 115 / 139 / 127 / 97 / 106 / 87 |

Counted as whitespace-separated tokens with inline math as one token. Paragraph 2 (verification recap) was tightened first
(117 → 75), then every paragraph. Target was ~800; 841 is where further cuts would start removing claims. Retained: the
+0.0054 ppb true-zero value and 0.203–0.243 ppb detection limit, ~10 % white-noise agreement, 1.40 / 2.49 / 1.72–2.68,
22/22-type cold bound statement, 123 bound terminations, ~1 % vs five orders of magnitude, 1.43 × budget and two parts in a
thousand, all six context-flag fields, both operational recommendations, the 261-case benchmark and its
instrument-dependence caveat, the three future directions (shared-shift VP with the KRISS tenth-of-a-pixel evidence, reference
covariance, He/ZA intensities ~5 and 20 % and raw light level). Removed: the sentence "The rest of this paper is what they
returned when asked." and redundant connective phrasing.

After the consistency pass (2026-09-28) the §8 body is **853** words by the same counter: +12 from the rewording of
paragraph 1 (termination state and reference distance are carried; reference build time and time convention are specified,
not implemented).

## 6. Citations and bibliography

**2026-09-30:** 8 entries added (30 total): `Beirle_2013`, `Hausmann_1999`, `Merchant_2017`, `JCGM_2008` (@misc), `Horbanski_2019`, `Thieser_2016` (second author "Schuster, G.", no umlaut, per CrossRef), `Dewald_2021`, `Wust_2025`. Authors, volume, pages and year checked against CrossRef; `Wust_2025` initials corrected to CrossRef (Wüst, L.; Türk, G. N. T. E.). Hausmann_1999 last page (475) is from the lead's publisher check, CrossRef gives the first page only.

**2026-09-29:** `references.bib` reduced to the 22 cited entries (19 uncited removed; list in `CHANGES_2026-09-29_edit.md` §3). New entry `Fritsch_1980` (doi:10.1137/0717021, CrossRef-verified). Newly cited existing entries: `Raue_2009`, `Efron_1979`, `Day_2002`, `Wooldridge_2010`; `Washenfelder_2008`, `Min_2016`, `Nam_2022`, `Stutz_1996`, `Platt` are cited in the new §4.6 for statements checked against their full texts or abstracts. The table below records the 2026-09-28 additions.

**Added 2026-09-28** (metadata supplied by the lead session from CrossRef; author lists, volume/issue/pages of the four DOI
entries re-read from api.crossref.org on 2026-09-28). The former `\citep{MISSING-…}` keys were replaced:

| old key | new key | reference | where cited |
|---|---|---|---|
| `MISSING-OLeary-Rust-2013` | `OLeary_2013` | O'Leary and Rust, Comput. Optim. Appl., 54, 579–593, 2013, doi:10.1007/s10589-012-9492-9 | §2.5 |
| `MISSING-HITRAN` | `Gordon_2022` | Gordon et al., HITRAN2020, JQSRT, 277, 107949, 2022, doi:10.1016/j.jqsrt.2021.107949 (the draft names no edition) | availability |
| `MISSING-Vandaele-2002` | `Vandaele_2002` | Vandaele et al., JGR, 107(D18), 2002, doi:10.1029/2001JD000971 (no page/article number in CrossRef) | availability |
| `MISSING-Volkamer-2005` | `Volkamer_2005` | Volkamer et al., J. Photoch. Photobio. A, 172, 35–46, 2005, doi:10.1016/j.jphotochem.2004.11.011 | availability |
| `MISSING-Kraus-2006` | `Kraus_2006` | Kraus, S.: DOASIS – A Framework Design for DOAS, PhD thesis, Univ. Mannheim, 2006 — **to be verified by the author** (bib `note={verify}`, which prints in the reference list until removed) | §2.3 |
| `MISSING-Danckaert-QDOAS` | `Danckaert_2017` | Danckaert, Fayt, Van Roozendael et al.: QDOAS Software User Manual, BIRA-IASB (techreport) — **year 2017 is a placeholder; confirm the manual version/year you used** (bib `note` prints until removed) | §3.3 |

`Vandaele_1998` was removed (not cited anywhere in the text); the availability section cites the 2002 paper.

Changes to the bib file: duplicate `Kreher_2020` removed; `Vandaele_1998` removed and six entries added (40 entries now); `year={2008}` added to `Platt` (had no year);
HTML `<sub>`/`<i>` converted to LaTeX; non-ASCII characters converted to LaTeX accents; `month=June/July/Sept` → `jun/jul/sep`.
Golub & LeVeque (1979) is listed in the format notes for §8 but is not cited in the §8 text.

## 7. Figures, tables, cross-references — resolved 2026-09-28

* Build: 0 errors, 0 undefined references/citations, 0 overfull boxes. Checked from `main.aux` and the PDF text:
  every figure and table is cited in numerical order, and every float is on or after the page of its first citation.
* Fig. 2 bottom row: selection changed to chi2 <= 1.5 on 2026-09-28; n and percentiles updated.
* **Figure citations added**: Fig. 1 in the last paragraph of Sect. 1 ("Figure 1 previews the argument: what a
  converged fit reports, against what the data support."); Fig. 2 at the end of the Table 1 paragraph in Sect. 3
  ("Figure 2 shows one record retrieved in all three configurations."). Figs. 1–6 are now cited in order 1..6.
* **Tables**: the 17 unnumbered in-line tables (the earlier count of 18 was a miscount) are now Copernicus table floats
  with the caption above the tabular and an in-text `Table~\ref{}` in the sentence that introduces each. Numbering is now:

*Numbering after the 2026-09-30 follow-up round:*

| no. | label | caption (start) |
|---|---|---|
| 1 | `tab:1` | Retrieval configurations used in Sects.~\ref{sec:3}--\ref{sec:6}, in short form; windows a … |
| 2 | `tab:jacobian_steps` | Difference between the analytic Golub--Pereyra Jacobian and a central finite difference of … |
| 3 | `tab:qdoas_field` | Agreement of QDOAS with Augur on the field record, per retrieval configuration and species … |
| 4 | `tab:relscale` | Relative response of the two heated channels, block 2053 over block 4101 (300\,$^{\circ}$C … |
| 5 | `tab:splithalf_loo` | Zero-air reference-interpolation error in the channel NO$_2$ amount (per cent) from the sp … |
| 6 | `tab:2` | Structural error budget, ppb, from a single propagation over the 60\,s ambient records of  … |
| 7 | `tab:hourly_check` | Hour-to-hour variation of hourly $\Sigma$ANs, summarised by $1.4826\,\mathrm{median}|\Delt … |
| 8 | `tab:coverage` | Calibration coverage of the retrieved records, from calibration blocks extracted directly  … |
| 9 | `tab:clock_displacement` | Change in the retrieved amounts when the heated channels are retrieved with the clock-alig … |
| 10 | `tab:clock_fitreport` | What the fit report shows for the displacement of Table~\ref{tab:clock_displacement}: RMS  … |
| 11 | `tab:context_fields` | Fields of the context flag, reported per record and per reference type (zero air, reflecti … |
| 12 | `tab:shape_remedy` | Concentration in time of each structural term over the hours of the budget window (clock-a … |
| 13 | `tab:noise_floor` | Noise floor of the $\Sigma$ANs product, measured on the paired zero-air blocks of the two  … |
| A1 | `tab:config` | Operational retrieval configuration of the three channels. ``Linked'' parameters take the  … |
| A2 | `tab:cal_schedule` | Calibration schedule of the heated channels, with block counts for the budget window (18-- … |
| B1 | `tab:colscaling` | Effect of rescaling one column of the small test problem of Appendix~\ref{app:B2} on the c … |
| C1 | `tab:subblock_scaling` | Scatter of contiguous sub-block contrasts within the operational calibration block ($N = 3 … |
| C2 | `tab:duty_blocks` | Calibration duty cycle for the operational zero-air block and for blocks two and four time … |
| C3 | `tab:ceilings` | Best attainable $\Sigma$ANs structural uncertainty (standard deviation) under each remedy, … |
| D1 | `tab:denominators` | Candidate denominators for the ratio of total to reported $\Sigma$ANs uncertainty: value ( … |
| D2 | `tab:shift_degeneracy` | Change in the fitted wavelength shift (px) when each structural term of Sect.~\ref{sec:4}  … |

  The old "Table 2" (budget) is now **Table 6** (2026-09-30; Table 4 = new `tab:relscale`); all prose uses `\ref`, so no hard-coded table numbers remain
  (only "Sect. 8.3.4" of the cited textbook).
* **Cross-references fixed** (target subsection re-read in each case):
  - §4.1 "covariance returned by the fit": Sect. 2.6 → **Sect. 2.5**.
  - §6.1 item 1 "covariance of the projected problem": Sect. 2.6 → **Sect. 2.5**.
  - §2.3 "regression test rather than a claim": Sect. 3.1 → **Sect. 3.2**.
  - §2.6 "that effect is large": Sect. 6.3 → **Sects. 5.2 and 7.3** (bound terminations; the termination-state episode).
  - §2.6 "the classifier is deliberately conservative … (Sect. 3.2)": no subsection tests the classifier's
    conservativeness, so the reference was **removed**; the lead session then added the basis from the code (see Sect. 8).
  - §2.5 end "the size of the difference can be read directly": Sect. 4.5 → **Appendix B4** (printed "A4"), the only
    place the conditional/joint covariance difference is quantified (inflation 1.001–1.257 on the test problem).
  - §3.6 "model error … on the benchmark": Sect. 4.3 → **Sect. 3.4** (benchmark groups C and E).
  - §6.1 table "the gates' cost, which Sect. 6.2 argues": → **Sect. 6.4**.
  - Code and data availability: "sources cited in Sect. 2" → the cross sections are cited directly: NO$_2$
    Vandaele et al. (2002), CHOCHO Volkamer et al. (2005), O$_4$ Thalman and Volkamer (2013), H$_2$O from HITRAN
    (Gordon et al., 2022), as listed in `reference_data/raw/SOURCES.md`. The HITRAN edition actually used is not recorded in
    the repository (`hitran_data/H2O_Lines.*` has no edition tag); HITRAN2020 is assumed.
* **§6.4 hot coverage** now uses the clock-aligned §5.3 values (3.76 % out of range, 1.23 % in gaps > 2 h); the AUTHOR CHECK
  comment was removed.
* **§7.2 denominators** made explicit: the noise-floor ratios and "1.33 to 1.84 … 42 % of records" are stated against the
  product-column figure of 0.0806 ppb (Sect. 4.4), followed by the fit-propagated-σ headline (1.72–2.68 × 0.0501 ppb); the
  table row reads "against the product-column 0.0806 ppb".
* **Implemented vs specified** (Abstract ¶5, §4.6, §6 intro, §8 ¶1), reworded to match the working-tree code checked on
  2026-09-28 (git itself cannot run in this sandbox, so commit status was not checked):
  - Termination state **is exported**: `gui/worker.py` `_fit_status_cols()` writes `Fit_Status`, `Bound_Params`,
    `Underdetermined` columns (called at lines 955 and 1227), in addition to the Status-string suffix.
  - Distance to the nearest knot / bracketing interval / out-of-range flag **are produced** by the post-hoc sidecar
    `tools/alpha_context_sidecar.py` (`I0_dt_s, I0_gap_h, I0_edge, R_dt_s, R_gap_h, R_edge`; distance is unsigned — the sign
    is carried by the edge flag). The count of adjacent gate-rejected blocks is not produced.
  - Reference provenance: the alpha header records the code version (`# code=`), the R(t) file used
    (`# Calibration: external R(t) — <file>`) and the spectra's clock epoch (`# clock_epoch=`). The **build time and time
    convention of the reference itself are not recorded**, and no load-time convention check exists → "specified".
  - The low-light I₀ gate **acts on knot selection**: `gui/worker.py` `low_light_knots()` removes zero-air blocks from the
    I₀ knot set (lines 2527–2547, default `i0_low_light_frac = 0`, i.e. off; count written to the alpha header). This
    matches §6.3 as written; the earlier README note that it "only flags scans" was out of date.

## 8. Remaining author decisions and inconsistencies (not changed)

* ~~(a) §3.5 plateau ratios~~ — resolved in Phase 1+2: 1.2278/1.2276 are medians of per-record ratios (ratios of medians 1.2322/1.2306); §3.5 rewritten, AUTHOR CHECK removed.
* ~~(b) Cold shift~~ — resolved in Phase 1+2: operational cold shift is fixed at −0.5 px; the [−1, +1] px run is described as a sensitivity run (§5.2, §8).
* ~~(c) Appendices A and C not drafted~~ — resolved in Phase 3: A = instrument and retrieval configuration, C = calibration-block length and duty cycle; the projected-Jacobian appendix now prints as B. No synthetic-suite appendix (by decision).
* **(d) References to confirm**: `Kraus_2006` (`note={verify}` prints in the reference list) and `Danckaert_2017` (year 2017
  is a placeholder for the QDOAS manual version used).
* Author list, affiliations, ORCID, Author contributions, Competing interests and Acknowledgements are placeholders, now marked `[AUTHOR: …]`; the Acknowledgements carry an AI-use disclosure placeholder in which the author must name the tool and scope (2026-09-29).
* Resolved 2026-09-28 (lead session), after the consistency pass:
  - §5.2 now reads "In the delivered campaign product they were not carried alongside the retrieved amount; the current version exports them as separate columns (Sect. 2.6)".
  - §2.6 "deliberately conservative" now states its basis from `core/doas_fit.py` (bound proximity relative to box width is flagged even if the optimum lies there; least favourable state kept across solves).
  - §6.1: Table `tab:context_fields` first row is "seconds to the nearest knot, with the side (before/after)" and the text says "The distance and in-range fields" (matches the sidecar: unsigned seconds + edge flag).
  - Typographical fixes made earlier: Fig. 2 caption "82th" → "82nd"; Fig. 6 caption missing comma.

## 9. Author notes not carried into the manuscript

(초고의 한국어 주석·작업 메모·「남은 구멍」 중 아직 열려 있는 항목. 해소 표시된 TBD와 개정 이력은 옮기지 않았다.)

- 초록: Augur 자체의 벤치마크 B·C·E군 v7 재채점 대기 — 그 전까지 상관잡음(AR(1)) 항은 초록에 넣지 않는다(§3.4 본문에는 이미 Augur B군 값이 있음 — 어느 쪽이 최신인지 확인).
- 초록 ¶2 "independent DOAS code reproduces Augur to within its output resolution"은 shift = 0 조건에서만 성립(운영 shift에서는 1.4e-3) — 본문(§3.3)에서 즉시 한정할 것.
- 초록 ¶4 85.5 %는 정합조건 비교값 — 종료상태 export(TBD-5C)가 구현되면 운영값으로 교체.
- ~~종료상태 열 export·출처 사이드카 미구현~~ → 2026-09-28 코드 확인으로 해소: 종료상태 열(`Fit_Status`·`Bound_Params`)과 knot 거리 사이드카는 구현됨; 기준 파일의 생성 시각·시각 규약 기록만 미구현 — 네 곳 문구를 그에 맞춤(7절).
- 서술 원칙: 9시간 사건을 "버그"로 쓰지 말 것 — 표준 지표로는 안 보였고 출처 보고가 있었으면 첫날 보였다는 논증의 자료.
- Table 1 "Light level" 열은 정성값 — 정량값(캠페인 중앙 광량 대비 비 등)이 있으면 교체.
- §3.4: 벤치마크 A군 설계 경위(초판 squeeze 1.002 → 보간자 중립으로 수정)를 본문에 남길지 결정(초고 권고: 남김).
- §3.4: 기준 구현 채점표를 Augur 값과 나란히 놓지 말 것 — 채점표 전체는 부록 A로.
- §3.5: 상대 눈금만 주장; 절대 회수와 오프셋 원인은 ACP로(두 한정 문장 유지).
- §4: cold 저광량 ZA knot 게이팅 적용 전후 값(§6 첫 처방 사례) 미산출.
- §4: Table 2의 백분율 판본은 이전 CSV와 섞지 말고 같은 실행에서 재생성.
- §5.1 KRISS: QDOAS shift 부호가 Augur와 같다는 전제 확인 필요.
- ~~§5.1 KRISS: −0.1 px 고정 재처리 없음~~ → Phase 1+2에서 해소: −0.1 vs −0.5 px 고정의 차이는 NO₂ −0.06 %, CHOCHO +2.2 %, H₂O −0.8 %(§5.1에 기재).
- §5.1 / Fig 1c / Fig 5a: 12개 스펙트럼이 165개의 부분집합인지 미확인(지도 열 이름 spec0…spec494).
- §5.1의 곡률 사전점검은 미구현 — 미구현이면 "제안"으로 표기.
- §5.2: 분모(cold 고정 shift 레코드 수, hot PNs 경계 종료 분모)는 Table 2와 같은 실행·기저(8,847)에서 다시 받은 뒤에만 복원.
- §5.4: 캠페인 제출본(`..._20260831_v4.xlsx`)은 알파–병합 사이 어느 단계에서 시각 보정이 적용됐는지 미특정 — 제출본은 제출본으로 고정(TBD-G2 범위 밖).
- ~~§6: 예산표 하한(split-half) 짝/홀 인터리브 기저~~ → Phase 1+2에서 해소: Table 4에 연속·인터리브 두 기저를 함께 싣고 LOO와 같은 기저로 교체(hot 두 채널; cold 행은 이전 실행 기저로 유지).
- ~~§6.1: `low_light`는 스캔만 플래그~~ → 2026-09-28 코드 확인으로 해소: `low_light_knots()`가 I₀ knot 선택에서 ZA 블록을 뺀다(기본 꺼짐) — §6.3 서술과 일치.
- §6.2: 마지막 열(상한)은 예측값 — "predicted" 성격 유지.
- §6.4: cold 블록당 스캔 수는 29(hot 34) — cold raw가 E:(exFAT)에만 있어 재추출 불가, 본문은 'heated channels'로 한정(TBD-A3 범위 밖).
- §7.1: hot ANs base shift 중앙 −6.12 px가 정렬 기준 실행 값인지 확인.
- §7.1: 계기 절은 반 페이지 이내(변환 효율·인렛은 ACP).
- §7.3: 원시 광량을 §6.1의 넷째 필드로 올릴지 저자 판단(현재는 원인 서술로만).
- §8: future work 두 방향의 순서(공유 shift → 공분산 전파) 유지 여부 — 초고 권고는 현 순서.
- 가용성: TBD-Z1 Augur 릴리스 태그(0.2.0 유지 vs 0.3.0), worktree → main 병합 후 GitHub–Zenodo DOI; TBD-Z2 벤치마크 README 패치본 덮어쓴 뒤 별도 레코드.
- 가용성: `.git/config`의 이메일은 이 절에 쓰지 않음(교신 주소는 표지).
- Fig 1 (b): 8446 스캔이 어느 채널인지 스윕 출력에 없음 — 확인 후 캡션에 추가.
- Fig 1: 기록된 v2 lineage 코드는 손으로 친 값(white 13개·AR(1) 13개)을 담고 있어 그대로 보관하지 말 것 → `../fig1_standalone.py`로 대체(아래 10절).
- 형식 노트: ~~부록 A(피팅 설정·단면적)와 부록 C(합성 검증 모음) 미작성~~ → Phase 3에서 부록 A(계기·리트리벌 설정)와 부록 C(보정 블록 길이) 작성, 합성 검증 모음 부록은 쓰지 않기로 함; 노트북 제출 시 "Interactive computing environment" 절 필요; ACP 동반 원고를 제출 시 명시.
- 참고문헌: Kraus (2006) DOASIS 학위논문 서지(제목·학교·연도) 확인 후 bib의 `note={verify}` 삭제.
- 참고문헌: 사용한 QDOAS 매뉴얼의 판(version)과 연도 확인 — 현재 `Danckaert_2017`의 year=2017은 자리표시자, 확인 후 `note` 삭제.
- 저자 목록·소속·ORCID·Author contributions·Competing interests·Acknowledgements는 자리표시자.

## 10. Fig. 1 reproduction script (`../fig1_standalone.py`)

*Phase 3 (2026-09-28):* panel (a) bar now read from `../data/amt_recompute_values.json` (`multiples.new`, 1.63–2.50) and cross-checked against `../data/production_budget_clockfixed.csv`; Fig. 4 (`../make_figs_345.py` fig4()) uses g′ = 0.9524 and the JSON denominator/hourly values. Pre-Phase-3 scripts kept as `*.bak_pre_phase3`.

Writes `../out/amt_fig1_thesis_file.{png,pdf}` (instrument-space points read from
`../data/instrument_space_metrics_by_coordinate.csv`, a copy of the synthetic `benchmark/instrument_space/metrics_by_coordinate.csv`)
and `../out/amt_fig1_thesis_legacy.{png,pdf}` (the 26 hand-typed values of the recorded lineage, kept only to document the
discrepancy). Panel a bar and panel b are read in place from `diagnostics/sensitivity_sweep_2026-09/` (field-derived, not
copied); panel c from the existing private `data/cold_shift_landscape.csv` (identical to artifact 2bb6642f). Set
`FIG1_SPL_CSV` to the `shift_profile_likelihood_intervals.csv` path for an optional interval cross-check
(max |Δlo| = 0, max |Δhi| = 0.05 px = one grid step).

* The hand-typed values **do not match the file**. The file has 30 white-noise points (13 coordinates × noise ×1, ×2, plus
  the four extra noise levels of `snr6`) and 13 AR(1) points; the lineage typed 13 white values and 13 AR(1) values, evenly
  spread between the file's minimum and maximum. Only the end points agree (white 0.911 / 1.323, AR(1) 1.420 / 2.049);
  AR(1) sorted pairwise max |Δ| = 0.115 (mean 0.046); white cannot be paired one-to-one (13 vs 30; 4/13 vs 6/30 below 1).
* **The saved Fig. 1 v2 PNG was not produced by its recorded code**: it shows 30 white points, as the caption says. Mean
  absolute pixel difference against the saved v2 PNG (0–255 grey levels, same 2127 × 907 px canvas): file-based re-render
  **0.255**; legacy (hand-typed) re-render **0.548**; in panel a alone 0.24 vs 1.11. The remaining 0.26 in panels b–c is
  identical in both renders (anti-aliasing / library version). The manuscript therefore keeps the saved v2 PDF; the
  figure is consistent with the file, and only the lineage record was wrong.
* Panel a bar (1.71927–2.67891) and panel b (65.36 / 21.42 / 13.23 % vs 86.94 / 0.00 / 13.06 %, median NO$_2$
  2.20911 → 2.20932 ppb) read from the diagnostics CSVs are identical to the hand-typed values.

- O'Leary & Rust: year 2013 is the print year (vol. 54, issue 3, April 2013); CrossRef lists 2012-08-02 as online-first. Checked 2026-09-28.
