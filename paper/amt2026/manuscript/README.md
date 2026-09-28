# AMT 2026 manuscript — LaTeX project

*Augur: an α-domain variable-projection DOAS retrieval, and what its diagnostics reveal that standard fit reports do not*
(Atmospheric Measurement Techniques, research article). Assembled 2026-09-28 from the section drafts listed below.

**Status (2026-09-28).** Field numbers were checked against the reprocessing on 2026-09-28 and did not change (check run by the lead session; report at the repository root, `C:\GHL\CAESAR\docs\재처리_점검_2026-09-28.md`, not part of this folder); all six previously missing references are now in `references.bib`, and `main.pdf` builds with no undefined citations or references.

## 1. Template route

**Official Copernicus class.** `copernicus.cls`, `copernicus.cfg`, `copernicus.bst`, `pdfscreen*.sty` are the
Copernicus LaTeX package 7.16, downloaded from `publications.copernicus.org/Copernicus_LaTeX_Package.zip` on
2026-09-28 (`README_copernicus_package_7_16.txt`). `main.tex` uses `\documentclass[amt, manuscript]{copernicus}`, so no shim was needed.

## 2. Build

```
latexmk -pdf main.tex          # or: pdflatex main; bibtex main; pdflatex main; pdflatex main
```
`main.pdf` in this folder was built on 2026-09-28 with TinyTeX 2026.09 (pdfTeX + BibTeX): **0 errors, 0 undefined
references or citations, 0 overfull boxes, 0 BibTeX warnings**. The only remaining warning is "Text page 11 contains only
floats" (Fig. 2, a full-page float). 42 pages.

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
| `sec3_verification.tex` | 3.1–3.6, Table 1 (+ Fig. 2, Fig. 3 floats) | §2.9+§3 v1 |
| `sec4_budget.tex` | 4.1–4.6, Table 2, Fig. 4 | §4 v16 |
| `sec5_pipeline.tex` | 5.1–5.4, Fig. 5 | §5 v6 |
| `sec6_reporting.tex` | 6.1, 6.1.1 (draft "6.1a"), 6.2–6.4 | §6 v1 |
| `sec7_field.tex` | 7.1–7.3, Fig. 6 | §7 v1 |
| `sec8_conclusions.tex` | 8 Conclusions (trimmed) | §8 v1 |
| `availability.tex` | Code and data availability | availability draft (2026-09-27) |
| `appB.tex` | Appendix: projected Jacobian, column scaling, joint covariance | 부록 B v1 |
| `references.bib` | bibliography | augur_AMT_references.bib (cleaned, see Sect. 6) |
| `figures/fig01.pdf … fig06.pdf` | copies of amt_fig1_thesis_v2, amt_fig2_representative_fits, amt_fig3_validation, amt_fig4_error_budget, amt_fig5_identifiability, amt_fig7_field_flags (= Fig. 6) | artifact store |

## 4. Field numbers: frozen

The field-record values in the drafts were **checked on 2026-09-28 against the reprocessing (hot pressure-sensor pairing fix,
cold R(t) without the three KRISS-injection knots) and did not change**: the pairing fix moves channel NO$_2$ by only
−0.25 %/+0.25 % and the other checks are below the reported precision (see `docs/재처리_점검_2026-09-28.md`).
All values below are therefore final as transcribed. The `\fieldnum{}` macro is kept (it prints its argument unchanged) so that
any later update remains a search-and-replace.

Wrapping rule used: every numeral that comes from the 2026 field record (ppb values, record/block/hour counts, percentages of
records, Table 2 / Fig. 4 budget values, ratios and shape statistics derived from them, slopes, correlation coefficients,
§5.4 and §7.3 statistics). **Not wrapped:** Sect. 3 synthetic and laboratory numbers (including the §3.5 injection
experiment), Appendix B, the KRISS cylinder-injection results in §5.1 (−0.10/−0.15 px, 9.3/3.6 ppb, 39 %/7.5 %/2.0 %,
0.06 px), instrument/configuration constants (windows, orders, bounds, N = 34, T = 32 s, cadences, duty cycles, d, R_L,
dispersion, ILS FWHM), thresholds (−5 ppb, 1.5, 30 %, 50 %, 2 h), dates, and counts spelled out in words ("twelve days",
"six excursions", "eleven of the thirteen"). The single field sentence in Sect. 3.3 (r² > 0.99) is wrapped.

**439 `\fieldnum` sites:**

| file | line | value |
|---|---|---|
| abstract.tex | 29 | `1.4` |
| abstract.tex | 29 | `2.5` |
| abstract.tex | 30 | `1.7` |
| abstract.tex | 30 | `2.7` |
| abstract.tex | 41 | `1.2` |
| abstract.tex | 43 | `85.5` |
| abstract.tex | 47 | `0.0999` |
| abstract.tex | 47 | `1.43` |
| abstract.tex | 48 | `0.005` |
| sec1_intro.tex | 73 | `1.7` |
| sec1_intro.tex | 73 | `2.7` |
| sec1_intro.tex | 76 | `1.43` |
| sec1_intro.tex | 106 | `1.72` |
| sec1_intro.tex | 106 | `2.68` |
| sec1_intro.tex | 107 | `8847` |
| sec1_intro.tex | 107 | `8446` |
| sec2_retrieval.tex | 255 | `8847` |
| sec3_verification.tex | 50 | `844` |
| sec3_verification.tex | 50 | `945` |
| sec3_verification.tex | 50 | `706` |
| sec3_verification.tex | 52 | `28` |
| sec3_verification.tex | 52 | `46` |
| sec3_verification.tex | 52 | `82` |
| sec3_verification.tex | 166 | `0.99` |
| sec4_budget.tex | 10 | `0.55` |
| sec4_budget.tex | 28 | `0.1` |
| sec4_budget.tex | 58 | `2.073` |
| sec4_budget.tex | 58 | `2.19` |
| sec4_budget.tex | 58 | `0.95` |
| sec4_budget.tex | 59 | `1.122` |
| sec4_budget.tex | 59 | `2.29` |
| sec4_budget.tex | 59 | `0.49` |
| sec4_budget.tex | 60 | `2.391` |
| sec4_budget.tex | 60 | `3.95` |
| sec4_budget.tex | 60 | `0.61` |
| sec4_budget.tex | 70 | `15` |
| sec4_budget.tex | 70 | `33` |
| sec4_budget.tex | 88 | `0.8` |
| sec4_budget.tex | 88 | `2.2` |
| sec4_budget.tex | 92 | `8.3` |
| sec4_budget.tex | 92 | `6.4` |
| sec4_budget.tex | 92 | `$-0.2$` |
| sec4_budget.tex | 98 | `$+13.3$` |
| sec4_budget.tex | 98 | `$-8.1$` |
| sec4_budget.tex | 98 | `$+6.5$` |
| sec4_budget.tex | 100 | `15.5` |
| sec4_budget.tex | 101 | `7.1` |
| sec4_budget.tex | 101 | `2.5` |
| sec4_budget.tex | 105 | `0.4` |
| sec4_budget.tex | 109 | `0.73` |
| sec4_budget.tex | 109 | `0.32` |
| sec4_budget.tex | 109 | `0.98` |
| sec4_budget.tex | 112 | `0.56` |
| sec4_budget.tex | 116 | `$+13$` |
| sec4_budget.tex | 116 | `$-8$` |
| sec4_budget.tex | 118 | `$+15.5$` |
| sec4_budget.tex | 118 | `$-2.5$` |
| sec4_budget.tex | 118 | `$+7.1$` |
| sec4_budget.tex | 140 | `8847` |
| sec4_budget.tex | 153 | `0.0437` |
| sec4_budget.tex | 153 | `0.0350` |
| sec4_budget.tex | 153 | `0.0082` |
| sec4_budget.tex | 153 | `0.0641` |
| sec4_budget.tex | 154 | `0.0600` |
| sec4_budget.tex | 154 | `0.0829` |
| sec4_budget.tex | 154 | `0.0086` |
| sec4_budget.tex | 154 | `0.1186` |
| sec4_budget.tex | 155 | `0.73` |
| sec4_budget.tex | 155 | `0.42` |
| sec4_budget.tex | 155 | `0.95` |
| sec4_budget.tex | 155 | `0.54` |
| sec4_budget.tex | 156 | `0.0416` |
| sec4_budget.tex | 156 | `0.0126` |
| sec4_budget.tex | 156 | `0.0187` |
| sec4_budget.tex | 156 | `0.0435` |
| sec4_budget.tex | 157 | `0.0428` |
| sec4_budget.tex | 157 | `0.0384` |
| sec4_budget.tex | 157 | `0.0189` |
| sec4_budget.tex | 157 | `0.0590` |
| sec4_budget.tex | 158 | `0.97` |
| sec4_budget.tex | 158 | `0.33` |
| sec4_budget.tex | 158 | `0.99` |
| sec4_budget.tex | 158 | `0.74` |
| sec4_budget.tex | 159 | `0.0567` |
| sec4_budget.tex | 159 | `0.0268` |
| sec4_budget.tex | 159 | `0.0200` |
| sec4_budget.tex | 159 | `0.0701` |
| sec4_budget.tex | 160 | `0.0781` |
| sec4_budget.tex | 160 | `0.0836` |
| sec4_budget.tex | 160 | `0.0203` |
| sec4_budget.tex | 160 | `0.1245` |
| sec4_budget.tex | 161 | `0.73` |
| sec4_budget.tex | 161 | `0.32` |
| sec4_budget.tex | 161 | `0.98` |
| sec4_budget.tex | 161 | `0.56` |
| sec4_budget.tex | 167 | `74` |
| sec4_budget.tex | 168 | `45` |
| sec4_budget.tex | 168 | `17` |
| sec4_budget.tex | 168 | `52` |
| sec4_budget.tex | 170 | `155` |
| sec4_budget.tex | 171 | `57` |
| sec4_budget.tex | 177 | `8847` |
| sec4_budget.tex | 183 | `57` |
| sec4_budget.tex | 209 | `11.03` |
| sec4_budget.tex | 215 | `0.0501` |
| sec4_budget.tex | 216 | `1.40` |
| sec4_budget.tex | 217 | `2.49` |
| sec4_budget.tex | 218 | `1.72` |
| sec4_budget.tex | 218 | `2.68` |
| sec4_budget.tex | 229 | `0.0501` |
| sec4_budget.tex | 229 | `1.72` |
| sec4_budget.tex | 229 | `2.68` |
| sec4_budget.tex | 230 | `0.0806` |
| sec4_budget.tex | 230 | `1.33` |
| sec4_budget.tex | 230 | `1.84` |
| sec4_budget.tex | 231 | `0.0224` |
| sec4_budget.tex | 232 | `0.0811` |
| sec4_budget.tex | 238 | `14\,974` |
| sec4_budget.tex | 239 | `0.04209` |
| sec4_budget.tex | 239 | `0.00025` |
| sec4_budget.tex | 239 | `+0.9997` |
| sec4_budget.tex | 245 | `0.0501` |
| sec4_budget.tex | 252 | `14\,974` |
| sec4_budget.tex | 255 | `0.0198` |
| sec4_budget.tex | 255 | `0.0296` |
| sec4_budget.tex | 274 | `1.00` |
| sec4_budget.tex | 274 | `1.03` |
| sec4_budget.tex | 279 | `$-0.50$` |
| sec4_budget.tex | 279 | `$-0.62$` |
| sec4_budget.tex | 280 | `$+0.68$` |
| sec4_budget.tex | 280 | `$+0.76$` |
| sec4_budget.tex | 294 | `1201` |
| sec4_budget.tex | 294 | `0.0832` |
| sec4_budget.tex | 295 | `107` |
| sec4_budget.tex | 295 | `0.0727` |
| sec4_budget.tex | 296 | `0.0618` |
| sec4_budget.tex | 296 | `0.85` |
| sec4_budget.tex | 297 | `0.0701` |
| sec4_budget.tex | 297 | `0.96` |
| sec4_budget.tex | 304 | `0.0727` |
| sec4_budget.tex | 305 | `107` |
| sec4_budget.tex | 305 | `106` |
| sec4_budget.tex | 306 | `0.74` |
| sec4_budget.tex | 309 | `0.85` |
| sec4_budget.tex | 319 | `0.87` |
| sec4_budget.tex | 319 | `1.39` |
| sec4_budget.tex | 327 | `0.379` |
| sec4_budget.tex | 339 | `0.32` |
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
| sec5_pipeline.tex | 67 | `1.027` |
| sec5_pipeline.tex | 67 | `1.019` |
| sec5_pipeline.tex | 67 | `0.662` |
| sec5_pipeline.tex | 67 | `1.178` |
| sec5_pipeline.tex | 68 | `23` |
| sec5_pipeline.tex | 75 | `0.858` |
| sec5_pipeline.tex | 76 | `0.662` |
| sec5_pipeline.tex | 76 | `1.027` |
| sec5_pipeline.tex | 76 | `1.178` |
| sec5_pipeline.tex | 80 | `$-2.0$` |
| sec5_pipeline.tex | 89 | `165` |
| sec5_pipeline.tex | 95 | `5364` |
| sec5_pipeline.tex | 109 | `0.179` |
| sec5_pipeline.tex | 109 | `0.743` |
| sec5_pipeline.tex | 109 | `4.755` |
| sec5_pipeline.tex | 110 | `0.006` |
| sec5_pipeline.tex | 110 | `0.020` |
| sec5_pipeline.tex | 110 | `0.097` |
| sec5_pipeline.tex | 111 | `0.151` |
| sec5_pipeline.tex | 111 | `0.343` |
| sec5_pipeline.tex | 111 | `2.675` |
| sec5_pipeline.tex | 126 | `6.2` |
| sec5_pipeline.tex | 126 | `4.8` |
| sec5_pipeline.tex | 137 | `$-2.014 \pm 0.03$` |
| sec5_pipeline.tex | 137 | `$\pm 2$` |
| sec5_pipeline.tex | 150 | `22` |
| sec5_pipeline.tex | 151 | `$-1.000$` |
| sec5_pipeline.tex | 157 | `123` |
| sec5_pipeline.tex | 157 | `121` |
| sec5_pipeline.tex | 158 | `4` |
| sec5_pipeline.tex | 181 | `11.8` |
| sec5_pipeline.tex | 186 | `157` |
| sec5_pipeline.tex | 186 | `157` |
| sec5_pipeline.tex | 186 | `164` |
| sec5_pipeline.tex | 186 | `164` |
| sec5_pipeline.tex | 187 | `1313` |
| sec5_pipeline.tex | 196 | `76\,282` |
| sec5_pipeline.tex | 196 | `0.08` |
| sec5_pipeline.tex | 196 | `0.07` |
| sec5_pipeline.tex | 196 | `3.76` |
| sec5_pipeline.tex | 196 | `1.23` |
| sec5_pipeline.tex | 196 | `10.6` |
| sec5_pipeline.tex | 197 | `9\,088` |
| sec5_pipeline.tex | 197 | `0.01` |
| sec5_pipeline.tex | 197 | `0.00` |
| sec5_pipeline.tex | 197 | `0.00` |
| sec5_pipeline.tex | 197 | `0.00` |
| sec5_pipeline.tex | 197 | `1.3` |
| sec5_pipeline.tex | 198 | `43\,259` |
| sec5_pipeline.tex | 198 | `0.13` |
| sec5_pipeline.tex | 198 | `0.34` |
| sec5_pipeline.tex | 198 | `2.89` |
| sec5_pipeline.tex | 198 | `11.03` |
| sec5_pipeline.tex | 198 | `11.8` |
| sec5_pipeline.tex | 199 | `7\,069` |
| sec5_pipeline.tex | 199 | `0.42` |
| sec5_pipeline.tex | 199 | `0.00` |
| sec5_pipeline.tex | 199 | `17.32` |
| sec5_pipeline.tex | 199 | `18.31` |
| sec5_pipeline.tex | 199 | `11.8` |
| sec5_pipeline.tex | 204 | `0.08` |
| sec5_pipeline.tex | 205 | `0.07` |
| sec5_pipeline.tex | 206 | `922` |
| sec5_pipeline.tex | 212 | `11.3` |
| sec5_pipeline.tex | 212 | `0.24` |
| sec5_pipeline.tex | 212 | `3` |
| sec5_pipeline.tex | 212 | `1\,264` |
| sec5_pipeline.tex | 213 | `75` |
| sec5_pipeline.tex | 213 | `743` |
| sec5_pipeline.tex | 213 | `10.1` |
| sec5_pipeline.tex | 214 | `11.3` |
| sec5_pipeline.tex | 214 | `3.5` |
| sec5_pipeline.tex | 215 | `11.03` |
| sec5_pipeline.tex | 216 | `11.8` |
| sec5_pipeline.tex | 227 | `2.8` |
| sec5_pipeline.tex | 227 | `5.8` |
| sec5_pipeline.tex | 235 | `0.00` |
| sec5_pipeline.tex | 236 | `18.31` |
| sec5_pipeline.tex | 252 | `9\,132` |
| sec5_pipeline.tex | 260 | `0.1048` |
| sec5_pipeline.tex | 260 | `0.1627` |
| sec5_pipeline.tex | 260 | `3.0` |
| sec5_pipeline.tex | 261 | `0.0358` |
| sec5_pipeline.tex | 261 | `0.0563` |
| sec5_pipeline.tex | 261 | `2.8` |
| sec5_pipeline.tex | 262 | `0.0999` |
| sec5_pipeline.tex | 262 | `0.1437` |
| sec5_pipeline.tex | 262 | `3.7` |
| sec5_pipeline.tex | 267 | `0.0999` |
| sec5_pipeline.tex | 268 | `1.43` |
| sec5_pipeline.tex | 280 | `3.37\times10^{-9}` |
| sec5_pipeline.tex | 280 | `1.0020` |
| sec5_pipeline.tex | 280 | `1.0022` |
| sec5_pipeline.tex | 280 | `1.99` |
| sec5_pipeline.tex | 280 | `0.0053` |
| sec5_pipeline.tex | 281 | `1.53\times10^{-8}` |
| sec5_pipeline.tex | 281 | `1.0016` |
| sec5_pipeline.tex | 281 | `1.0016` |
| sec5_pipeline.tex | 281 | `0.55` |
| sec5_pipeline.tex | 281 | `0.0065` |
| sec5_pipeline.tex | 287 | `6.16\times10^{-9}` |
| sec5_pipeline.tex | 290 | `+0.999` |
| sec5_pipeline.tex | 290 | `2.8` |
| sec5_pipeline.tex | 294 | `0.005` |
| sec5_pipeline.tex | 294 | `0.23` |
| sec5_pipeline.tex | 301 | `7.5` |
| sec5_pipeline.tex | 302 | `0.0758` |
| sec5_pipeline.tex | 302 | `0.0701` |
| sec5_pipeline.tex | 302 | `5.2` |
| sec5_pipeline.tex | 302 | `0.1184` |
| sec5_pipeline.tex | 303 | `0.1245` |
| sec5_pipeline.tex | 304 | `1.81` |
| sec5_pipeline.tex | 304 | `2.57` |
| sec5_pipeline.tex | 304 | `1.72` |
| sec5_pipeline.tex | 304 | `2.68` |
| sec5_pipeline.tex | 306 | `93.0` |
| sec5_pipeline.tex | 306 | `98.7` |
| sec5_pipeline.tex | 309 | `$+0.412$` |
| sec5_pipeline.tex | 309 | `$+0.146$` |
| sec5_pipeline.tex | 317 | `0.0600` |
| sec5_pipeline.tex | 317 | `0.0000` |
| sec5_pipeline.tex | 322 | `0.0999` |
| sec5_pipeline.tex | 322 | `0.0600` |
| sec6_reporting.tex | 65 | `42.3` |
| sec6_reporting.tex | 87 | `0.0` |
| sec6_reporting.tex | 87 | `9` |
| sec6_reporting.tex | 91 | `0.80` |
| sec6_reporting.tex | 91 | `1.09` |
| sec6_reporting.tex | 92 | `0.83` |
| sec6_reporting.tex | 92 | `1.11` |
| sec6_reporting.tex | 113 | `146` |
| sec6_reporting.tex | 120 | `0.73` |
| sec6_reporting.tex | 120 | `60` |
| sec6_reporting.tex | 120 | `41` |
| sec6_reporting.tex | 120 | `23` |
| sec6_reporting.tex | 120 | `36` |
| sec6_reporting.tex | 120 | `41` |
| sec6_reporting.tex | 121 | `0.27` |
| sec6_reporting.tex | 121 | `21` |
| sec6_reporting.tex | 121 | `14` |
| sec6_reporting.tex | 121 | `8` |
| sec6_reporting.tex | 121 | `18` |
| sec6_reporting.tex | 121 | `56` |
| sec6_reporting.tex | 122 | `0.97` |
| sec6_reporting.tex | 122 | `112` |
| sec6_reporting.tex | 122 | `77` |
| sec6_reporting.tex | 122 | `23` |
| sec6_reporting.tex | 122 | `27` |
| sec6_reporting.tex | 122 | `3` |
| sec6_reporting.tex | 128 | `40` |
| sec6_reporting.tex | 135 | `0.05` |
| sec6_reporting.tex | 138 | `76` |
| sec6_reporting.tex | 138 | `15` |
| sec6_reporting.tex | 149 | `0.87` |
| sec6_reporting.tex | 149 | `1.00` |
| sec6_reporting.tex | 149 | `2.05` |
| sec6_reporting.tex | 149 | `2.73` |
| sec6_reporting.tex | 182 | `2.506\times10^{-4}` |
| sec6_reporting.tex | 182 | `1.095\times10^{-4}` |
| sec6_reporting.tex | 183 | `2.332\times10^{-4}` |
| sec6_reporting.tex | 183 | `0.820\times10^{-4}` |
| sec6_reporting.tex | 184 | `0.104` |
| sec6_reporting.tex | 184 | `0.416` |
| sec6_reporting.tex | 185 | `2.26` |
| sec6_reporting.tex | 185 | `1.22` |
| sec6_reporting.tex | 190 | `7` |
| sec6_reporting.tex | 226 | `45` |
| sec6_reporting.tex | 227 | `0.1245` |
| sec6_reporting.tex | 227 | `0.1012` |
| sec6_reporting.tex | 227 | `19` |
| sec6_reporting.tex | 235 | `0.1245` |
| sec6_reporting.tex | 236 | `0.1012` |
| sec6_reporting.tex | 236 | `0.81` |
| sec6_reporting.tex | 237 | `0.0911` |
| sec6_reporting.tex | 237 | `0.73` |
| sec6_reporting.tex | 238 | `0.0552` |
| sec6_reporting.tex | 238 | `0.44` |
| sec6_reporting.tex | 246 | `7.1` |
| sec6_reporting.tex | 246 | `0.1245` |
| sec6_reporting.tex | 246 | `0.1162` |
| sec6_reporting.tex | 266 | `40` |
| sec6_reporting.tex | 266 | `34` |
| sec6_reporting.tex | 267 | `1.29` |
| sec6_reporting.tex | 267 | `1.23` |
| sec6_reporting.tex | 272 | `1.88` |
| sec6_reporting.tex | 273 | `1.17` |
| sec6_reporting.tex | 282 | `$+248$` |
| sec6_reporting.tex | 283 | `$-314$` |
| sec6_reporting.tex | 283 | `$-261$` |
| sec6_reporting.tex | 283 | `$+235$` |
| sec6_reporting.tex | 295 | `28` |
| sec6_reporting.tex | 295 | `76` |
| sec6_reporting.tex | 296 | `97` |
| sec6_reporting.tex | 301 | `13` |
| sec6_reporting.tex | 301 | `38` |
| sec6_reporting.tex | 302 | `13` |
| sec6_reporting.tex | 302 | `99.9` |
| sec6_reporting.tex | 303 | `25` |
| sec6_reporting.tex | 303 | `2` |
| sec6_reporting.tex | 303 | `3` |
| sec6_reporting.tex | 304 | `8` |
| sec6_reporting.tex | 307 | `13` |
| sec6_reporting.tex | 307 | `38` |
| sec6_reporting.tex | 331 | `4.45` |
| sec6_reporting.tex | 331 | `0.53` |
| sec6_reporting.tex | 332 | `2.89` |
| sec6_reporting.tex | 332 | `11.03` |
| sec6_reporting.tex | 333 | `0.08` |
| sec6_reporting.tex | 333 | `0.07` |
| sec6_reporting.tex | 344 | `11.3` |
| sec6_reporting.tex | 344 | `11.03` |
| sec6_reporting.tex | 344 | `18.31` |
| sec6_reporting.tex | 351 | `3.5` |
| sec6_reporting.tex | 352 | `11.03` |
| sec6_reporting.tex | 353 | `11.8` |
| sec6_reporting.tex | 356 | `21` |
| sec6_reporting.tex | 356 | `146` |
| sec6_reporting.tex | 357 | `8` |
| sec6_reporting.tex | 357 | `18` |
| sec6_reporting.tex | 366 | `0.24` |
| sec6_reporting.tex | 367 | `11.3` |
| sec6_reporting.tex | 397 | `157` |
| sec6_reporting.tex | 398 | `54` |
| sec7_field.tex | 31 | `$-6.12$` |
| sec7_field.tex | 42 | `155` |
| sec7_field.tex | 52 | `0.0676` |
| sec7_field.tex | 52 | `0.0811` |
| sec7_field.tex | 53 | `0.203` |
| sec7_field.tex | 53 | `0.243` |
| sec7_field.tex | 54 | `$+0.0054$` |
| sec7_field.tex | 54 | `$+0.0054$` |
| sec7_field.tex | 55 | `0.0806` |
| sec7_field.tex | 55 | `0.84` |
| sec7_field.tex | 55 | `1.01` |
| sec7_field.tex | 60 | `-0.093` |
| sec7_field.tex | 61 | `4.3` |
| sec7_field.tex | 66 | `$+0.0054$` |
| sec7_field.tex | 74 | `0.84` |
| sec7_field.tex | 74 | `1.01` |
| sec7_field.tex | 74 | `0.0806` |
| sec7_field.tex | 79 | `1.33` |
| sec7_field.tex | 79 | `1.84` |
| sec7_field.tex | 80 | `42` |
| sec7_field.tex | 85 | `1.48` |
| sec7_field.tex | 85 | `0.0806` |
| sec7_field.tex | 85 | `0.0543` |
| sec7_field.tex | 101 | `0.0999` |
| sec7_field.tex | 103 | `+0.999` |
| sec7_field.tex | 104 | `74\,667` |
| sec7_field.tex | 104 | `2.8` |
| sec7_field.tex | 109 | `19` |
| sec7_field.tex | 110 | `8` |
| sec7_field.tex | 110 | `600` |
| sec7_field.tex | 111 | `5.6` |
| sec7_field.tex | 111 | `91` |
| sec7_field.tex | 111 | `1.2` |
| sec7_field.tex | 113 | `2.6` |
| sec7_field.tex | 113 | `9.0` |
| sec7_field.tex | 114 | `66` |
| sec7_field.tex | 114 | `300` |
| sec7_field.tex | 114 | `10` |
| sec7_field.tex | 121 | `22` |
| sec7_field.tex | 127 | `4.7` |
| sec7_field.tex | 127 | `5.5` |
| sec7_field.tex | 149 | `9.0` |
| sec7_field.tex | 149 | `4.7` |
| sec8_conclusions.tex | 19 | `$+0.0054$` |
| sec8_conclusions.tex | 21 | `0.203` |
| sec8_conclusions.tex | 21 | `0.243` |
| sec8_conclusions.tex | 27 | `1.40` |
| sec8_conclusions.tex | 28 | `2.49` |
| sec8_conclusions.tex | 29 | `1.72` |
| sec8_conclusions.tex | 29 | `2.68` |
| sec8_conclusions.tex | 36 | `123` |
| sec8_conclusions.tex | 42 | `1.43` |
| sec8_conclusions.tex | 77 | `5` |
| sec8_conclusions.tex | 77 | `20` |

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

## 7. Figures, tables, cross-references

* All `\ref` resolve (no undefined references).
* **Figure citation order: Figs. 3, 4, 5, 6 are cited in order. Figs. 1 and 2 are never cited in the text** (not in the
  drafts either). They are placed provisionally at the end of Sect. 1 (Fig. 1) and after Table 1 (Fig. 2). Copernicus
  requires every figure to be cited in order — add `Fig.~\ref{fig:1}` (e.g. in the last paragraph of §1) and
  `Fig.~\ref{fig:2}` (e.g. at Table 1 in §3) before submission.
* Tables 1 and 2 are floats with captions and are cited in order. The **18 other tables** in the drafts had no number or
  caption and are typeset as unnumbered in-line tables (§3.2, §4.2, §4.4 denominators, §4.5, §5.1, §5.3, §5.4 ×2, §6.1,
  §6.1a, §6.2 ×4, §6.4 ×2, §7.2, App. B). Copernicus requires numbered, captioned tables; promoting them will renumber Table 2.
* Equations are numbered automatically: (1)–(9) as in §2, the draft's "(18)" in §6.2 is now (10) (label `eq:18`).
* The draft's §6.1a is typeset as subsubsection **6.1.1**. Appendix B is the only appendix drafted, so the class prints it as
  **Appendix A** (label `app:B`); Appendices A (fit settings) and C (synthetic suite) of the outline are not drafted.
* **Cross-references that resolve but probably point at the wrong subsection** (numbers carried over from an older outline;
  left unchanged):
  - §4.1 and §6.1 item 1: "covariance … (Sect. 2.6)" — the covariance is §2.5; §2.6 is the termination state.
  - §2.3 end: "a regression test rather than a claim (Sect. 3.1)" — the Jacobian test is §3.2.
  - §2.6: classifier "(Sect. 3.2)" — §3.2 is the Jacobian; and "that effect is large (Sect. 6.3)" — §6.3 is knot gating
    (termination statistics are now §5.2/§7.3).
  - §2.5 end: "the size of the difference can be read directly (Sect. 4.5)" — §4.5 is the observed-variation check.
  - §3.6: "model error is precisely what Sect. 4.3 measures on the benchmark" — benchmark model-error groups are §3.4 (C, E).
  - §6.1 table: gates' cost "which Sect. 6.2 argues" — that argument is in §6.4.
  - Availability: cross sections "available from the sources cited in Sect. 2" — §2 cites none of them.

## 8. Internal inconsistencies found while assembling (transcribed unchanged; author to resolve)

* **§3.5 plateau ratios**: 14.75/11.97 = 1.2322 and 71.57/58.16 = 1.2306, not 1.2278/1.2276 as stated; the "0.02 %"
  agreement (actual ≈ 0.14 %) and 1/1.2277 = 0.8145 follow from the stated ratios. (`% AUTHOR CHECK` comment in the source.)
* **§6.4 hot coverage**: "4.45 % … 0.53 %" contradicts the §5.3 table (clock-aligned 3.76 % / 1.23 %); the §6 draft's own
  Korean note gives 3.76 / 1.23 as the aligned values. (`% AUTHOR CHECK` comment in the source.)
* **Cold shift**: §5.2 says the cold shift range is [−1, +1] px and all 22 base fits return −1.000 px; Table 1, §7.1 and the
  Fig. 1/5 captions say the operational cold shift is fixed at −0.5 px (the §3 note says −1 to 1 is the Oculus real-time fitset).
* **Implemented or proposed**: Abstract ¶5 ("implement in Augur"), §8 ¶1 (termination state and provenance "survive to the
  product"), §4.6 ("Section 6 implements all three") and §6 intro ("three of the four … implemented") vs the drafts' notes
  that termination-state export and the provenance sidecar are not implemented (TBD-5C, out of scope) and that `low_light`
  does not yet act on knot selection.
* **§7.2**: "1.33 to 1.84 times the same reported figure, and for 42 % of records" uses the old product-column denominator
  (0.0806 ppb); consistent with the §4.4 denominator table, but the headline elsewhere is 1.72–2.68 against 0.0501 ppb.
* Typographical fixes made: Fig. 2 caption "82th" → "82nd"; Fig. 6 caption missing comma before "the reference provenance".

## 9. Author notes not carried into the manuscript

(초고의 한국어 주석·작업 메모·「남은 구멍」 중 아직 열려 있는 항목. 해소 표시된 TBD와 개정 이력은 옮기지 않았다.)

- 초록: Augur 자체의 벤치마크 B·C·E군 v7 재채점 대기 — 그 전까지 상관잡음(AR(1)) 항은 초록에 넣지 않는다(§3.4 본문에는 이미 Augur B군 값이 있음 — 어느 쪽이 최신인지 확인).
- 초록 ¶2 "independent DOAS code reproduces Augur to within its output resolution"은 shift = 0 조건에서만 성립(운영 shift에서는 1.4e-3) — 본문(§3.3)에서 즉시 한정할 것.
- 초록 ¶4 85.5 %는 정합조건 비교값 — 종료상태 export(TBD-5C)가 구현되면 운영값으로 교체.
- 종료상태 열 export·출처 사이드카 CSV는 미구현(TBD-5C 범위 밖 확정) — 커밋 전에는 "propose"를 "implement"로 올리지 말 것(위 8절의 불일치와 연결).
- 서술 원칙: 9시간 사건을 "버그"로 쓰지 말 것 — 표준 지표로는 안 보였고 출처 보고가 있었으면 첫날 보였다는 논증의 자료.
- Table 1 "Light level" 열은 정성값 — 정량값(캠페인 중앙 광량 대비 비 등)이 있으면 교체.
- §3.4: 벤치마크 A군 설계 경위(초판 squeeze 1.002 → 보간자 중립으로 수정)를 본문에 남길지 결정(초고 권고: 남김).
- §3.4: 기준 구현 채점표를 Augur 값과 나란히 놓지 말 것 — 채점표 전체는 부록 A로.
- §3.5: 상대 눈금만 주장; 절대 회수와 오프셋 원인은 ACP로(두 한정 문장 유지).
- §4: cold 저광량 ZA knot 게이팅 적용 전후 값(§6 첫 처방 사례) 미산출.
- §4: Table 2의 백분율 판본은 이전 CSV와 섞지 말고 같은 실행에서 재생성.
- §5.1 KRISS: QDOAS shift 부호가 Augur와 같다는 전제 확인 필요.
- §5.1 KRISS: 운영 cold를 −0.1 px로 고정한 재처리 결과 없음 — 기울기 0.940/0.858/1.027이 어떻게 바뀌는지 미확인.
- §5.1 / Fig 1c / Fig 5a: 12개 스펙트럼이 165개의 부분집합인지 미확인(지도 열 이름 spec0…spec494).
- §5.1의 곡률 사전점검은 미구현 — 미구현이면 "제안"으로 표기.
- §5.2: 분모(cold 고정 shift 레코드 수, hot PNs 경계 종료 분모)는 Table 2와 같은 실행·기저(8,847)에서 다시 받은 뒤에만 복원.
- §5.4: 캠페인 제출본(`..._20260831_v4.xlsx`)은 알파–병합 사이 어느 단계에서 시각 보정이 적용됐는지 미특정 — 제출본은 제출본으로 고정(TBD-G2 범위 밖).
- §6: Table 2 하한(split-half)은 짝/홀 인터리브로 측정돼 약 5 % 과소 — 연속 기저로 재계산하거나 각주로 명시.
- §6.1: context flag 구현 상태 확인 — 현재 `low_light`는 스캔만 플래그하고 I₀ knot 선택에 관여하지 않음.
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
