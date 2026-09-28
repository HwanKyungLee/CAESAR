# AMT 2026 manuscript — LaTeX project

*Augur: an α-domain variable-projection DOAS retrieval, and what its diagnostics reveal that standard fit reports do not*
(Atmospheric Measurement Techniques, research article). Assembled 2026-09-28 from the section drafts listed below.

**Status (2026-09-28, after the Phase 1+2 revision).** Numbers were replaced and audit contradictions/overclaims fixed per the claim audit and recomputation report of 2026-09-28; every change is listed in `CHANGES_2026-09-28_phase12.md` (unresolved items in its Sect. 3). Phase 3 (restructuring) has not started.

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
floats" (Fig. 2, a full-page float). 46 pages (rebuilt 2026-09-28 after the Phase 1+2 revision; 43 before).

copernicus.cls needs a few packages that a minimal TeX install lacks: `cancel`, `supertabular`, `newunicodechar`,
`accents`, `subfloat`, `fontawesome5`, `fontawesome` (v4, for `fontawesomesymbols-*.tex`), `regexpatch`, and `t5enc.def`
from `vntex`. With TeX Live/MiKTeX: `tlmgr install cancel supertabular newunicodechar accents subfloat fontawesome5 fontawesome regexpatch vntex`.
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
| `sec3_verification.tex` | 3.1–3.6, Tables 1–3 (Table 3 = new QDOAS field table, `tab:qdoas_field`) (+ Fig. 2, Fig. 3 floats) | §2.9+§3 v1 |
| `sec4_budget.tex` | 4.1–4.6, Tables 4–7 (budget = Table 5, `tab:2`), Fig. 4 | §4 v16 |
| `sec5_pipeline.tex` | 5.1–5.4, Fig. 5 | §5 v6 |
| `sec6_reporting.tex` | 6.1, 6.1.1 (draft "6.1a"), 6.2–6.4 | §6 v1 |
| `sec7_field.tex` | 7.1–7.3, Fig. 6 | §7 v1 |
| `sec8_conclusions.tex` | 8 Conclusions (trimmed) | §8 v1 |
| `availability.tex` | Code and data availability | availability draft (2026-09-27) |
| `appB.tex` | Appendix: projected Jacobian, column scaling, joint covariance | 부록 B v1 |
| `references.bib` | bibliography | augur_AMT_references.bib (cleaned, see Sect. 6) |
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

**540 `\fieldnum` sites** (line numbers as of 2026-09-28, after the Phase 1+2 revision):

| file | line | value |
|---|---|---|
| abstract.tex | 22 | `0.990` |
| abstract.tex | 22 | `6` |
| abstract.tex | 29 | `1.3` |
| abstract.tex | 29 | `2.3` |
| abstract.tex | 30 | `1.6` |
| abstract.tex | 30 | `2.5` |
| abstract.tex | 40 | `1.2` |
| abstract.tex | 42 | `85.5` |
| abstract.tex | 46 | `0.100` |
| abstract.tex | 46 | `1.44` |
| abstract.tex | 47 | `0.005` |
| sec1_intro.tex | 73 | `1.6` |
| sec1_intro.tex | 73 | `2.5` |
| sec1_intro.tex | 76 | `1.44` |
| sec1_intro.tex | 107 | `1.63` |
| sec1_intro.tex | 107 | `2.50` |
| sec1_intro.tex | 108 | `8847` |
| sec1_intro.tex | 108 | `8446` |
| sec2_retrieval.tex | 260 | `9034` |
| sec2_retrieval.tex | 260 | `8847` |
| sec3_verification.tex | 49 | `1397` |
| sec3_verification.tex | 49 | `1399` |
| sec3_verification.tex | 49 | `707` |
| sec3_verification.tex | 51 | `49` |
| sec3_verification.tex | 51 | `53` |
| sec3_verification.tex | 51 | `81` |
| sec3_verification.tex | 170 | `0.990` |
| sec3_verification.tex | 171 | `1.039` |
| sec3_verification.tex | 171 | `1.063` |
| sec3_verification.tex | 172 | `1.043` |
| sec3_verification.tex | 172 | `1.000` |
| sec3_verification.tex | 173 | `4` |
| sec3_verification.tex | 173 | `6` |
| sec3_verification.tex | 174 | `0.889` |
| sec3_verification.tex | 174 | `0.959` |
| sec3_verification.tex | 174 | `0.81` |
| sec3_verification.tex | 174 | `1.19` |
| sec3_verification.tex | 174 | `1.04` |
| sec3_verification.tex | 174 | `1.38` |
| sec3_verification.tex | 185 | `36\,241` |
| sec3_verification.tex | 185 | `1.039` |
| sec3_verification.tex | 185 | `0.990` |
| sec3_verification.tex | 186 | `36\,241` |
| sec3_verification.tex | 186 | `0.807` |
| sec3_verification.tex | 186 | `0.889` |
| sec3_verification.tex | 187 | `36\,241` |
| sec3_verification.tex | 187 | `1.377` |
| sec3_verification.tex | 187 | `0.887` |
| sec3_verification.tex | 188 | `73\,916` |
| sec3_verification.tex | 188 | `1.063` |
| sec3_verification.tex | 188 | `1.000` |
| sec3_verification.tex | 189 | `73\,916` |
| sec3_verification.tex | 189 | `1.195` |
| sec3_verification.tex | 189 | `0.914` |
| sec3_verification.tex | 190 | `73\,916` |
| sec3_verification.tex | 190 | `1.042` |
| sec3_verification.tex | 190 | `0.974` |
| sec3_verification.tex | 191 | `74\,539` |
| sec3_verification.tex | 191 | `1.043` |
| sec3_verification.tex | 191 | `1.000` |
| sec3_verification.tex | 192 | `74\,539` |
| sec3_verification.tex | 192 | `1.054` |
| sec3_verification.tex | 192 | `0.959` |
| sec3_verification.tex | 193 | `74\,539` |
| sec3_verification.tex | 193 | `1.038` |
| sec3_verification.tex | 193 | `0.981` |
| sec3_verification.tex | 271 | `0.952` |
| sec3_verification.tex | 280 | `0.57` |
| sec3_verification.tex | 280 | `0.65` |
| sec3_verification.tex | 281 | `0.92` |
| sec3_verification.tex | 281 | `1.00` |
| sec3_verification.tex | 282 | `0.72` |
| sec4_budget.tex | 10 | `0.55` |
| sec4_budget.tex | 24 | `0.1` |
| sec4_budget.tex | 31 | `1.05` |
| sec4_budget.tex | 31 | `1.57` |
| sec4_budget.tex | 65 | `1.437` |
| sec4_budget.tex | 65 | `1.782` |
| sec4_budget.tex | 65 | `1.95` |
| sec4_budget.tex | 65 | `0.74` |
| sec4_budget.tex | 65 | `0.91` |
| sec4_budget.tex | 66 | `0.90` |
| sec4_budget.tex | 66 | `0.97` |
| sec4_budget.tex | 66 | `2.25` |
| sec4_budget.tex | 66 | `0.40` |
| sec4_budget.tex | 66 | `0.43` |
| sec4_budget.tex | 67 | `2.391` |
| sec4_budget.tex | 67 | `3.95` |
| sec4_budget.tex | 67 | `0.61` |
| sec4_budget.tex | 77 | `15` |
| sec4_budget.tex | 77 | `33` |
| sec4_budget.tex | 81 | `0.74` |
| sec4_budget.tex | 81 | `0.91` |
| sec4_budget.tex | 83 | `0.40` |
| sec4_budget.tex | 83 | `0.43` |
| sec4_budget.tex | 85 | `7` |
| sec4_budget.tex | 85 | `19` |
| sec4_budget.tex | 97 | `0.8` |
| sec4_budget.tex | 97 | `2.2` |
| sec4_budget.tex | 101 | `8.3` |
| sec4_budget.tex | 101 | `6.4` |
| sec4_budget.tex | 101 | `$-0.2$` |
| sec4_budget.tex | 107 | `$+13.3$` |
| sec4_budget.tex | 107 | `$-8.1$` |
| sec4_budget.tex | 107 | `$+6.9$` |
| sec4_budget.tex | 109 | `15.5` |
| sec4_budget.tex | 110 | `7.6` |
| sec4_budget.tex | 110 | `2.5` |
| sec4_budget.tex | 114 | `0.25` |
| sec4_budget.tex | 114 | `0.18` |
| sec4_budget.tex | 114 | `0.03` |
| sec4_budget.tex | 114 | `28.7` |
| sec4_budget.tex | 115 | `12.9` |
| sec4_budget.tex | 116 | `15.8` |
| sec4_budget.tex | 119 | `0.73` |
| sec4_budget.tex | 119 | `0.32` |
| sec4_budget.tex | 119 | `0.98` |
| sec4_budget.tex | 122 | `0.56` |
| sec4_budget.tex | 126 | `$+13$` |
| sec4_budget.tex | 126 | `$-8$` |
| sec4_budget.tex | 128 | `$+15.5$` |
| sec4_budget.tex | 128 | `$-2.5$` |
| sec4_budget.tex | 128 | `$+7.6$` |
| sec4_budget.tex | 150 | `9034` |
| sec4_budget.tex | 151 | `187` |
| sec4_budget.tex | 152 | `8847` |
| sec4_budget.tex | 153 | `0.9524` |
| sec4_budget.tex | 164 | `0.0437` |
| sec4_budget.tex | 164 | `0.0350` |
| sec4_budget.tex | 164 | `0.0082` |
| sec4_budget.tex | 164 | `0.0641` |
| sec4_budget.tex | 165 | `0.0600` |
| sec4_budget.tex | 165 | `0.0829` |
| sec4_budget.tex | 165 | `0.0086` |
| sec4_budget.tex | 165 | `0.1186` |
| sec4_budget.tex | 166 | `0.73` |
| sec4_budget.tex | 166 | `0.42` |
| sec4_budget.tex | 166 | `0.95` |
| sec4_budget.tex | 166 | `0.54` |
| sec4_budget.tex | 167 | `0.0416` |
| sec4_budget.tex | 167 | `0.0126` |
| sec4_budget.tex | 167 | `0.0187` |
| sec4_budget.tex | 167 | `0.0435` |
| sec4_budget.tex | 168 | `0.0428` |
| sec4_budget.tex | 168 | `0.0384` |
| sec4_budget.tex | 168 | `0.0189` |
| sec4_budget.tex | 168 | `0.0590` |
| sec4_budget.tex | 169 | `0.97` |
| sec4_budget.tex | 169 | `0.33` |
| sec4_budget.tex | 169 | `0.99` |
| sec4_budget.tex | 169 | `0.74` |
| sec4_budget.tex | 170 | `0.0558` |
| sec4_budget.tex | 170 | `0.0269` |
| sec4_budget.tex | 170 | `0.0191` |
| sec4_budget.tex | 170 | `0.0693` |
| sec4_budget.tex | 171 | `0.0768` |
| sec4_budget.tex | 171 | `0.0831` |
| sec4_budget.tex | 171 | `0.0195` |
| sec4_budget.tex | 171 | `0.1236` |
| sec4_budget.tex | 172 | `0.73` |
| sec4_budget.tex | 172 | `0.32` |
| sec4_budget.tex | 172 | `0.98` |
| sec4_budget.tex | 172 | `0.56` |
| sec4_budget.tex | 178 | `74` |
| sec4_budget.tex | 179 | `45` |
| sec4_budget.tex | 179 | `17` |
| sec4_budget.tex | 179 | `52` |
| sec4_budget.tex | 181 | `155` |
| sec4_budget.tex | 182 | `57` |
| sec4_budget.tex | 188 | `8847` |
| sec4_budget.tex | 194 | `57` |
| sec4_budget.tex | 221 | `11.03` |
| sec4_budget.tex | 227 | `0.0541` |
| sec4_budget.tex | 228 | `1.28` |
| sec4_budget.tex | 229 | `2.29` |
| sec4_budget.tex | 230 | `1.63` |
| sec4_budget.tex | 230 | `2.50` |
| sec4_budget.tex | 245 | `0.0541` |
| sec4_budget.tex | 245 | `1.63` |
| sec4_budget.tex | 245 | `2.50` |
| sec4_budget.tex | 246 | `0.0806` |
| sec4_budget.tex | 246 | `1.32` |
| sec4_budget.tex | 246 | `1.83` |
| sec4_budget.tex | 247 | `0.025` |
| sec4_budget.tex | 248 | `0.086` |
| sec4_budget.tex | 254 | `14\,974` |
| sec4_budget.tex | 255 | `0.04209` |
| sec4_budget.tex | 255 | `0.00025` |
| sec4_budget.tex | 255 | `+0.9997` |
| sec4_budget.tex | 262 | `0.0558` |
| sec4_budget.tex | 267 | `8832` |
| sec4_budget.tex | 270 | `0.0558` |
| sec4_budget.tex | 270 | `1.59` |
| sec4_budget.tex | 270 | `2.43` |
| sec4_budget.tex | 271 | `0.0217` |
| sec4_budget.tex | 271 | `0.0326` |
| sec4_budget.tex | 289 | `1.00` |
| sec4_budget.tex | 289 | `1.03` |
| sec4_budget.tex | 294 | `$-0.60$` |
| sec4_budget.tex | 295 | `$+0.73$` |
| sec4_budget.tex | 312 | `1258` |
| sec4_budget.tex | 312 | `0.081` |
| sec4_budget.tex | 313 | `154` |
| sec4_budget.tex | 313 | `0.082` |
| sec4_budget.tex | 314 | `0.0618` |
| sec4_budget.tex | 314 | `0.75` |
| sec4_budget.tex | 315 | `0.0693` |
| sec4_budget.tex | 315 | `0.84` |
| sec4_budget.tex | 322 | `0.082` |
| sec4_budget.tex | 323 | `154` |
| sec4_budget.tex | 323 | `153` |
| sec4_budget.tex | 324 | `0.76` |
| sec4_budget.tex | 326 | `0.75` |
| sec4_budget.tex | 334 | `0.75` |
| sec4_budget.tex | 335 | `0.84` |
| sec4_budget.tex | 341 | `0.366` |
| sec4_budget.tex | 353 | `0.32` |
| sec5_pipeline.tex | 39 | `1.0120` |
| sec5_pipeline.tex | 39 | `1.0611` |
| sec5_pipeline.tex | 39 | `165` |
| sec5_pipeline.tex | 40 | `77` |
| sec5_pipeline.tex | 41 | `0.01` |
| sec5_pipeline.tex | 42 | `4.35` |
| sec5_pipeline.tex | 43 | `3.09\times10^{5}` |
| sec5_pipeline.tex | 46 | `$-2.014$` |
| sec5_pipeline.tex | 47 | `85.5` |
| sec5_pipeline.tex | 47 | `$-0.088$` |
| sec5_pipeline.tex | 48 | `4.5` |
| sec5_pipeline.tex | 65 | `5364` |
| sec5_pipeline.tex | 66 | `0.940` |
| sec5_pipeline.tex | 66 | `0.858` |
| sec5_pipeline.tex | 66 | `1.027` |
| sec5_pipeline.tex | 66 | `1.019` |
| sec5_pipeline.tex | 67 | `0.662` |
| sec5_pipeline.tex | 67 | `1.178` |
| sec5_pipeline.tex | 68 | `23` |
| sec5_pipeline.tex | 73 | `34` |
| sec5_pipeline.tex | 73 | `18` |
| sec5_pipeline.tex | 77 | `2.2` |
| sec5_pipeline.tex | 77 | `$-0.06$` |
| sec5_pipeline.tex | 77 | `$+2.2$` |
| sec5_pipeline.tex | 77 | `$-0.8$` |
| sec5_pipeline.tex | 78 | `23` |
| sec5_pipeline.tex | 86 | `165` |
| sec5_pipeline.tex | 92 | `5364` |
| sec5_pipeline.tex | 104 | `8847` |
| sec5_pipeline.tex | 111 | `0.187` |
| sec5_pipeline.tex | 111 | `0.826` |
| sec5_pipeline.tex | 111 | `4.388` |
| sec5_pipeline.tex | 112 | `0.006` |
| sec5_pipeline.tex | 112 | `0.027` |
| sec5_pipeline.tex | 112 | `0.285` |
| sec5_pipeline.tex | 113 | `0.154` |
| sec5_pipeline.tex | 113 | `0.347` |
| sec5_pipeline.tex | 113 | `2.941` |
| sec5_pipeline.tex | 114 | `0.243` |
| sec5_pipeline.tex | 114 | `0.766` |
| sec5_pipeline.tex | 114 | `4.276` |
| sec5_pipeline.tex | 120 | `0.006` |
| sec5_pipeline.tex | 120 | `0.027` |
| sec5_pipeline.tex | 121 | `0.285` |
| sec5_pipeline.tex | 130 | `6.2` |
| sec5_pipeline.tex | 130 | `5.0` |
| sec5_pipeline.tex | 131 | `0.0693` |
| sec5_pipeline.tex | 131 | `0.0706` |
| sec5_pipeline.tex | 131 | `0.1236` |
| sec5_pipeline.tex | 131 | `0.1244` |
| sec5_pipeline.tex | 141 | `$-2.014 \pm 0.03$` |
| sec5_pipeline.tex | 141 | `$\pm 2$` |
| sec5_pipeline.tex | 154 | `22` |
| sec5_pipeline.tex | 155 | `$-1.000$` |
| sec5_pipeline.tex | 161 | `187` |
| sec5_pipeline.tex | 161 | `9034` |
| sec5_pipeline.tex | 164 | `121` |
| sec5_pipeline.tex | 164 | `4` |
| sec5_pipeline.tex | 188 | `11.8` |
| sec5_pipeline.tex | 193 | `157` |
| sec5_pipeline.tex | 193 | `157` |
| sec5_pipeline.tex | 193 | `164` |
| sec5_pipeline.tex | 193 | `164` |
| sec5_pipeline.tex | 194 | `1313` |
| sec5_pipeline.tex | 199 | `9149` |
| sec5_pipeline.tex | 206 | `76\,282` |
| sec5_pipeline.tex | 206 | `0.08` |
| sec5_pipeline.tex | 206 | `0.07` |
| sec5_pipeline.tex | 206 | `3.76` |
| sec5_pipeline.tex | 206 | `1.23` |
| sec5_pipeline.tex | 206 | `10.6` |
| sec5_pipeline.tex | 207 | `9\,088` |
| sec5_pipeline.tex | 207 | `0.01` |
| sec5_pipeline.tex | 207 | `0.00` |
| sec5_pipeline.tex | 207 | `0.00` |
| sec5_pipeline.tex | 207 | `0.00` |
| sec5_pipeline.tex | 207 | `1.3` |
| sec5_pipeline.tex | 208 | `43\,259` |
| sec5_pipeline.tex | 208 | `0.13` |
| sec5_pipeline.tex | 208 | `0.34` |
| sec5_pipeline.tex | 208 | `2.89` |
| sec5_pipeline.tex | 208 | `11.03` |
| sec5_pipeline.tex | 208 | `11.8` |
| sec5_pipeline.tex | 209 | `7\,069` |
| sec5_pipeline.tex | 209 | `0.42` |
| sec5_pipeline.tex | 209 | `0.00` |
| sec5_pipeline.tex | 209 | `17.32` |
| sec5_pipeline.tex | 209 | `18.31` |
| sec5_pipeline.tex | 209 | `11.8` |
| sec5_pipeline.tex | 214 | `0.08` |
| sec5_pipeline.tex | 215 | `0.07` |
| sec5_pipeline.tex | 216 | `922` |
| sec5_pipeline.tex | 222 | `11.3` |
| sec5_pipeline.tex | 222 | `0.24` |
| sec5_pipeline.tex | 222 | `3` |
| sec5_pipeline.tex | 222 | `1\,264` |
| sec5_pipeline.tex | 223 | `75` |
| sec5_pipeline.tex | 223 | `743` |
| sec5_pipeline.tex | 223 | `10.1` |
| sec5_pipeline.tex | 224 | `11.3` |
| sec5_pipeline.tex | 224 | `3.5` |
| sec5_pipeline.tex | 225 | `11.03` |
| sec5_pipeline.tex | 226 | `11.8` |
| sec5_pipeline.tex | 237 | `2.8` |
| sec5_pipeline.tex | 237 | `5.8` |
| sec5_pipeline.tex | 245 | `0.00` |
| sec5_pipeline.tex | 246 | `18.31` |
| sec5_pipeline.tex | 262 | `9\,132` |
| sec5_pipeline.tex | 267 | `0.9524` |
| sec5_pipeline.tex | 273 | `0.1048` |
| sec5_pipeline.tex | 273 | `0.1627` |
| sec5_pipeline.tex | 273 | `3.0` |
| sec5_pipeline.tex | 274 | `0.0358` |
| sec5_pipeline.tex | 274 | `0.0563` |
| sec5_pipeline.tex | 274 | `2.8` |
| sec5_pipeline.tex | 275 | `0.100` |
| sec5_pipeline.tex | 275 | `0.1418` |
| sec5_pipeline.tex | 275 | `3.7` |
| sec5_pipeline.tex | 280 | `0.100` |
| sec5_pipeline.tex | 281 | `1.44` |
| sec5_pipeline.tex | 296 | `3.37\times10^{-9}` |
| sec5_pipeline.tex | 296 | `1.0020` |
| sec5_pipeline.tex | 296 | `1.0022` |
| sec5_pipeline.tex | 296 | `1.99` |
| sec5_pipeline.tex | 296 | `0.0053` |
| sec5_pipeline.tex | 297 | `1.53\times10^{-8}` |
| sec5_pipeline.tex | 297 | `1.0016` |
| sec5_pipeline.tex | 297 | `1.0016` |
| sec5_pipeline.tex | 297 | `0.55` |
| sec5_pipeline.tex | 297 | `0.0065` |
| sec5_pipeline.tex | 303 | `6.16\times10^{-9}` |
| sec5_pipeline.tex | 306 | `+0.999` |
| sec5_pipeline.tex | 306 | `2.8` |
| sec5_pipeline.tex | 310 | `0.005` |
| sec5_pipeline.tex | 310 | `0.243` |
| sec5_pipeline.tex | 317 | `7.0` |
| sec5_pipeline.tex | 318 | `0.0745` |
| sec5_pipeline.tex | 318 | `0.0693` |
| sec5_pipeline.tex | 318 | `4.5` |
| sec5_pipeline.tex | 318 | `0.1183` |
| sec5_pipeline.tex | 319 | `0.1236` |
| sec5_pipeline.tex | 320 | `1.70` |
| sec5_pipeline.tex | 320 | `2.41` |
| sec5_pipeline.tex | 320 | `1.63` |
| sec5_pipeline.tex | 320 | `2.50` |
| sec5_pipeline.tex | 322 | `8505` |
| sec5_pipeline.tex | 322 | `9034` |
| sec5_pipeline.tex | 322 | `9149` |
| sec5_pipeline.tex | 323 | `93.0` |
| sec5_pipeline.tex | 323 | `98.7` |
| sec5_pipeline.tex | 326 | `$+0.412$` |
| sec5_pipeline.tex | 326 | `$+0.146$` |
| sec5_pipeline.tex | 334 | `0.0622` |
| sec5_pipeline.tex | 334 | `0.0000` |
| sec5_pipeline.tex | 339 | `0.100` |
| sec5_pipeline.tex | 339 | `0.0622` |
| sec6_reporting.tex | 73 | `42.3` |
| sec6_reporting.tex | 95 | `0.0` |
| sec6_reporting.tex | 95 | `9` |
| sec6_reporting.tex | 99 | `0.80` |
| sec6_reporting.tex | 99 | `1.09` |
| sec6_reporting.tex | 100 | `0.83` |
| sec6_reporting.tex | 100 | `1.11` |
| sec6_reporting.tex | 121 | `155` |
| sec6_reporting.tex | 130 | `0.73` |
| sec6_reporting.tex | 130 | `63` |
| sec6_reporting.tex | 130 | `41` |
| sec6_reporting.tex | 130 | `24` |
| sec6_reporting.tex | 130 | `38` |
| sec6_reporting.tex | 130 | `45` |
| sec6_reporting.tex | 131 | `0.32` |
| sec6_reporting.tex | 131 | `26` |
| sec6_reporting.tex | 131 | `17` |
| sec6_reporting.tex | 131 | `12` |
| sec6_reporting.tex | 131 | `22` |
| sec6_reporting.tex | 131 | `52` |
| sec6_reporting.tex | 132 | `0.98` |
| sec6_reporting.tex | 132 | `118` |
| sec6_reporting.tex | 132 | `76` |
| sec6_reporting.tex | 132 | `26` |
| sec6_reporting.tex | 132 | `29` |
| sec6_reporting.tex | 132 | `3` |
| sec6_reporting.tex | 138 | `37` |
| sec6_reporting.tex | 146 | `74` |
| sec6_reporting.tex | 146 | `17` |
| sec6_reporting.tex | 156 | `0.87` |
| sec6_reporting.tex | 156 | `1.00` |
| sec6_reporting.tex | 156 | `2.05` |
| sec6_reporting.tex | 157 | `2.73` |
| sec6_reporting.tex | 191 | `2.506\times10^{-4}` |
| sec6_reporting.tex | 191 | `1.095\times10^{-4}` |
| sec6_reporting.tex | 192 | `2.332\times10^{-4}` |
| sec6_reporting.tex | 192 | `0.820\times10^{-4}` |
| sec6_reporting.tex | 193 | `0.104` |
| sec6_reporting.tex | 193 | `0.416` |
| sec6_reporting.tex | 194 | `2.26` |
| sec6_reporting.tex | 194 | `1.22` |
| sec6_reporting.tex | 199 | `7` |
| sec6_reporting.tex | 239 | `45` |
| sec6_reporting.tex | 240 | `0.1236` |
| sec6_reporting.tex | 240 | `0.1008` |
| sec6_reporting.tex | 240 | `18.5` |
| sec6_reporting.tex | 250 | `0.1236` |
| sec6_reporting.tex | 251 | `0.1008` |
| sec6_reporting.tex | 251 | `0.82` |
| sec6_reporting.tex | 252 | `0.0901` |
| sec6_reporting.tex | 252 | `0.73` |
| sec6_reporting.tex | 253 | `0.0547` |
| sec6_reporting.tex | 253 | `0.44` |
| sec6_reporting.tex | 261 | `7.6` |
| sec6_reporting.tex | 261 | `0.1236` |
| sec6_reporting.tex | 261 | `0.1149` |
| sec6_reporting.tex | 281 | `40` |
| sec6_reporting.tex | 281 | `34` |
| sec6_reporting.tex | 282 | `1.29` |
| sec6_reporting.tex | 282 | `1.23` |
| sec6_reporting.tex | 287 | `1.88` |
| sec6_reporting.tex | 288 | `1.17` |
| sec6_reporting.tex | 297 | `$+248$` |
| sec6_reporting.tex | 298 | `$-314$` |
| sec6_reporting.tex | 298 | `$-261$` |
| sec6_reporting.tex | 298 | `$+235$` |
| sec6_reporting.tex | 310 | `28` |
| sec6_reporting.tex | 310 | `76` |
| sec6_reporting.tex | 311 | `97` |
| sec6_reporting.tex | 316 | `13` |
| sec6_reporting.tex | 316 | `38` |
| sec6_reporting.tex | 317 | `13` |
| sec6_reporting.tex | 317 | `99.9` |
| sec6_reporting.tex | 318 | `25` |
| sec6_reporting.tex | 318 | `2` |
| sec6_reporting.tex | 318 | `3` |
| sec6_reporting.tex | 319 | `8` |
| sec6_reporting.tex | 322 | `13` |
| sec6_reporting.tex | 322 | `38` |
| sec6_reporting.tex | 344 | `3.76` |
| sec6_reporting.tex | 344 | `1.23` |
| sec6_reporting.tex | 345 | `2.89` |
| sec6_reporting.tex | 345 | `11.03` |
| sec6_reporting.tex | 346 | `0.08` |
| sec6_reporting.tex | 346 | `0.07` |
| sec6_reporting.tex | 359 | `11.3` |
| sec6_reporting.tex | 359 | `11.03` |
| sec6_reporting.tex | 359 | `18.31` |
| sec6_reporting.tex | 366 | `3.5` |
| sec6_reporting.tex | 367 | `11.03` |
| sec6_reporting.tex | 368 | `11.8` |
| sec6_reporting.tex | 371 | `26` |
| sec6_reporting.tex | 371 | `155` |
| sec6_reporting.tex | 372 | `12` |
| sec6_reporting.tex | 372 | `22` |
| sec6_reporting.tex | 381 | `0.24` |
| sec6_reporting.tex | 382 | `11.3` |
| sec6_reporting.tex | 407 | `1261` |
| sec6_reporting.tex | 407 | `1.00` |
| sec6_reporting.tex | 417 | `157` |
| sec6_reporting.tex | 418 | `54` |
| sec7_field.tex | 28 | `0.25` |
| sec7_field.tex | 35 | `$-6.12$` |
| sec7_field.tex | 46 | `155` |
| sec7_field.tex | 52 | `0.9524` |
| sec7_field.tex | 58 | `0.0676` |
| sec7_field.tex | 58 | `0.086` |
| sec7_field.tex | 59 | `0.203` |
| sec7_field.tex | 59 | `0.257` |
| sec7_field.tex | 60 | `$+0.0054$` |
| sec7_field.tex | 60 | `$+0.0054$` |
| sec7_field.tex | 61 | `0.0806` |
| sec7_field.tex | 61 | `0.84` |
| sec7_field.tex | 61 | `1.06` |
| sec7_field.tex | 66 | `-0.093` |
| sec7_field.tex | 67 | `4` |
| sec7_field.tex | 72 | `$+0.0054$` |
| sec7_field.tex | 81 | `0.84` |
| sec7_field.tex | 81 | `1.06` |
| sec7_field.tex | 81 | `0.0806` |
| sec7_field.tex | 86 | `1.32` |
| sec7_field.tex | 86 | `1.83` |
| sec7_field.tex | 87 | `0.0806` |
| sec7_field.tex | 87 | `0.0541` |
| sec7_field.tex | 88 | `1.63` |
| sec7_field.tex | 88 | `2.50` |
| sec7_field.tex | 88 | `46.1` |
| sec7_field.tex | 88 | `8832` |
| sec7_field.tex | 94 | `1.48` |
| sec7_field.tex | 94 | `0.0806` |
| sec7_field.tex | 94 | `0.0543` |
| sec7_field.tex | 110 | `0.100` |
| sec7_field.tex | 112 | `+0.999` |
| sec7_field.tex | 113 | `74\,667` |
| sec7_field.tex | 113 | `2.8` |
| sec7_field.tex | 118 | `19` |
| sec7_field.tex | 119 | `8` |
| sec7_field.tex | 119 | `600` |
| sec7_field.tex | 120 | `5.6` |
| sec7_field.tex | 120 | `91` |
| sec7_field.tex | 120 | `1.2` |
| sec7_field.tex | 122 | `2.6` |
| sec7_field.tex | 122 | `9.0` |
| sec7_field.tex | 123 | `66` |
| sec7_field.tex | 123 | `300` |
| sec7_field.tex | 123 | `10` |
| sec7_field.tex | 130 | `22` |
| sec7_field.tex | 137 | `4.7` |
| sec7_field.tex | 137 | `5.5` |
| sec7_field.tex | 146 | `0.6` |
| sec7_field.tex | 162 | `9.0` |
| sec7_field.tex | 162 | `4.7` |
| sec8_conclusions.tex | 21 | `0.990` |
| sec8_conclusions.tex | 21 | `4` |
| sec8_conclusions.tex | 21 | `6` |
| sec8_conclusions.tex | 22 | `$+0.0054$` |
| sec8_conclusions.tex | 23 | `0.203` |
| sec8_conclusions.tex | 23 | `0.257` |
| sec8_conclusions.tex | 29 | `1.28` |
| sec8_conclusions.tex | 30 | `2.29` |
| sec8_conclusions.tex | 31 | `1.63` |
| sec8_conclusions.tex | 31 | `2.50` |
| sec8_conclusions.tex | 38 | `187` |
| sec8_conclusions.tex | 38 | `9034` |
| sec8_conclusions.tex | 44 | `1.44` |
| sec8_conclusions.tex | 47 | `0.6` |
| main.tex | 10 | `...` |

## 5. §8 Conclusions — trimmed

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

| no. | label | content |
|---|---|---|
| 1 | `tab:1` | retrieval configurations (unchanged) |
| 2 | `tab:jacobian_steps` | analytic vs finite-difference Jacobian against step $h$ (§3.2) |
| 3 | `tab:splithalf_loo` | split-half knot noise vs LOO per channel (§4.2) |
| 4 | `tab:2` | structural error budget (was Table 2; label kept) |
| 5 | `tab:denominators` | candidate denominators for total/reported (§4.4) |
| 6 | `tab:hourly_check` | observed vs predicted hour-to-hour variation (§4.5) |
| 7 | `tab:shift_degeneracy` | shift change per structural perturbation (§5.1) |
| 8 | `tab:coverage` | calibration coverage, campaign and windows (§5.3) |
| 9 | `tab:clock_displacement` | change from the 9 h reflectivity displacement (§5.4) |
| 10 | `tab:clock_fitreport` | what the fit report shows for it (§5.4) |
| 11 | `tab:context_fields` | context-flag fields (§6.1) |
| 12 | `tab:shape_remedy` | time concentration of each term and remedy (§6.1.1) |
| 13 | `tab:subblock_scaling` | sub-block averaging within a calibration block (§6.2) |
| 14 | `tab:duty_blocks` | duty cycle for longer zero-air blocks (§6.2) |
| 15 | `tab:ceilings` | best attainable ΣANs structural SD per remedy (§6.2) |
| 16 | `tab:coverage_causes` | causes of the remaining reflectivity coverage deficit (§6.4) |
| 17 | `tab:cal_schedule` | calibration schedule of the heated channels (§6.4) |
| 18 | `tab:noise_floor` | noise floor of the ΣANs product (§7.2) |
| A1 | `tab:colscaling` | column-scaling test (appendix) |

  The old "Table 2" (budget) is now **Table 4**; all prose uses `\ref`, so no hard-coded table numbers remain
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
* **(c) Appendices A and C** are not drafted; Appendix B is therefore printed as "Appendix A".
* **(d) References to confirm**: `Kraus_2006` (`note={verify}` prints in the reference list) and `Danckaert_2017` (year 2017
  is a placeholder for the QDOAS manual version used).
* Author list, affiliations, ORCID, Author contributions, Competing interests and Acknowledgements are placeholders.
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
- 형식 노트: 부록 A(피팅 설정·단면적)와 부록 C(합성 검증 모음) 미작성; 노트북 제출 시 "Interactive computing environment" 절 필요; ACP 동반 원고를 제출 시 명시.
- 참고문헌: Kraus (2006) DOASIS 학위논문 서지(제목·학교·연도) 확인 후 bib의 `note={verify}` 삭제.
- 참고문헌: 사용한 QDOAS 매뉴얼의 판(version)과 연도 확인 — 현재 `Danckaert_2017`의 year=2017은 자리표시자, 확인 후 `note` 삭제.
- 저자 목록·소속·ORCID·Author contributions·Competing interests·Acknowledgements는 자리표시자.

## 10. Fig. 1 reproduction script (`../fig1_standalone.py`)

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
