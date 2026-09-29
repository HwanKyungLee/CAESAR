# Edit pass 2026-09-29 (evaluation items 1–5)

Manuscript: `C:\GHL\CAESAR\paper\amt2026\manuscript\` (starting point d299db080c). Hard rule: no scientific claim or number changed. Pre-edit copy: build workspace `backup_pre_edit0929/`; full line diff: `CHANGES_2026-09-29_edit.diff`.

## 1. Length and sentence statistics

Word counts are of running text only (tables, figure/table environments, captions, equations and comments excluded; `\ref` counted as one word, citations as none). The evaluation's count of the same text was 17,600 against 16,215 here; the last column rescales by that factor (×1.085) for comparison with its 12,000–13,000 target.

| section | words before | words after | sentences >40 before/after | >60 before/after | mean sentence length before/after |
|---|---|---|---|---|---|
| Abstract | 659 | 246 | 7/0 | 2/0 | 34.7/22.4 |
| 1 Introduction | 1136 | 1025 | 11/1 | 1/0 | 28.4/23.3 |
| 2 Retrieval formulation | 1967 | 1122 | 14/5 | 2/0 | 24.6/22.9 |
| 3 Verification | 2075 | 1829 | 21/4 | 5/0 | 32.4/25.4 |
| 4 Structural error budget | 2542 | 1958 | 10/5 | 1/0 | 24.0/24.8 |
| 5 What the pipeline knows | 2911 | 2138 | 24/5 | 2/0 | 26.5/25.2 |
| 6 What should be reported | 2644 | 2049 | 14/7 | 2/0 | 24.9/24.4 |
| 7 Field demonstration | 1250 | 1018 | 7/7 | 1/0 | 30.5/26.8 |
| 8 Conclusions | 1031 | 765 | 12/3 | 6/0 | 34.4/23.9 |
| **total** | **16215** (≈17600 on the evaluation's count) | **12150** (≈13188) | 120/37 | 22/0 | 27.2/24.6 |

Abstract: 659 → 246 words (two paragraphs). Sentences: 596 → 494; over 40 words 120 → 37; over 60 words 22 → 0. Mean sentence length: abstract 22.4, introduction 23.3, conclusions 23.9 words (target ≤ 25).
Pages: 48 → 43 (main text, abstract to Sect. 8: pp. 1–38 → pp. 1–31). Build: 0 errors, 0 undefined references/citations, 0 overfull boxes, 0 BibTeX warnings. Figure and table first citations in order (main Tables 1–12, A1–A2, B1, C1–C3, D1–D2; Figs 1–6). All figure captions ≤ ~120 words (longest: Fig. 3).

## 2. Moved blocks

| from | to |
|---|---|
| Sect. 2.3 (QR factorisation, Eq. 7, second-term/Kaufman discussion, relation to QDOAS/DOASIS/textbook/BIRRA) | Appendix B5 |
| Sect. 2.5 (Schur-complement argument; V is not the projected Jacobian) | Appendix B5 |
| Sect. 2.7 (scaling of the fitted quantity) | Appendix B6 |
| Sect. 2.8 (non-negativity, Tikhonov, robust options) | Appendix B6 |
| Sect. 3.2 (why the two parameters must be swept separately) | Table 2 caption |
| Fig. 2 caption (LED band, 13 nm, 428/470/469 nm edges) | Sect. 3 introduction text |
| Sect. 4.4 (denominator discussion and Table 6) | Appendix D (Table D1) |
| Sect. 4.6 (three-number prescription) | Sect. 6.1 (pointer from new Sect. 4.6) |
| Sect. 4.6 | replaced by discussion "Relation to previous uncertainty treatments" (+ covariance-propagation outlook sentence kept) |
| Sect. 5.1 (coupling of structural terms to the shift, Table 8, basin-hopping check) | Appendix D2 (Table D2) |
| Sect. 6.1 (clock history: local time until 29 May, twelve days, correction two months later) | Sect. 5.4 (kept there; removed as duplicate) |
| Sect. 4.4 denominator discussion and Table 6 | Appendix D1 (Table D1) |
| Sect. 5.3 duplicate statistics in Sect. 6.4 (extrapolation/gap percentages, rejection runs, gate cost) | kept in Sect. 5.3 and Table 7; Sect. 6.4 keeps the remedy argument with a pointer |
| Four 'What the pipeline could report instead.' blocks (Sects. 5.1–5.4) | one sentence each, pointing to Sect. 6.1 (numbers −2.014 ± 0.03 px, ±2 px, 0.00 %, 18.31 %, dates 2026-07-10 / 2026-09-19 kept) |
| Three-number prescription (Sects. 4.6, 6.1, 8) | stated once in Sect. 6.1 (now also listing the termination state and the objective-ratio identifiability flag from Sects. 2.6/5.1); Sect. 4.6 and Sect. 8 point to it |
| Fig. 2 caption (1 June 2026, 10:35 KST; LED band edges) | Sect. 3 introduction text |
| Fig. 3 caption (definition of the three noise conditions) | Sect. 3.3 text |
| Fig. 6 caption (flagging criteria, n/a and -- conventions, 9.0 h / 4.7 h gaps partly) | Sect. 7.3 text (gaps kept in caption) |
| Sect. 7.2 repeat of Sect. 4.4 multiples (1.32–1.83, 0.0541, 1.63–2.50) | removed as duplicate (in Sect. 4.4 and Table D1) |
| Sect. 7.3 repeat of the Sect. 5.4 displacement numbers | removed as duplicate |

New: Sect. 4.6 'Relation to previous uncertainty treatments' (replaces the old 4.6); research questions in Sect. 1 ¶2 with a preview of the third category (Sect. 6.5); Appendix D 'Supplementary budget analyses' (D1 denominator, D2 shift coupling); Appendix B5 (implementation of the projected Jacobian, relation to DOAS codes, Schur-complement argument) and B6 (scaling, unused options).

## 3. References

New bibliography entry (verified with CrossRef, cited for PCHIP in Sect. 2.4):

- Fritsch, F. N. and Carlson, R. E.: Monotone piecewise cubic interpolation, SIAM J. Numer. Anal., 17, 238–246, 1980, doi:10.1137/0717021.

Entries already in references.bib, now cited (metadata re-verified with CrossRef; content checked as stated):

| key | DOI | cited for | basis of the content check |
|---|---|---|---|
| Washenfelder_2008 | 10.5194/acp-8-7779-2008 | Sect. 2.4 (R from Rayleigh of He and zero air); Sect. 4.6 (quadrature accuracy, ±4.6 % NO2) | full text (abstract; Sect. 4.4 accuracy paragraph) |
| Min_2016 | 10.5194/amt-9-423-2016 | Sect. 4.6 (NO2 accuracy 5.0 %, limited by absorption cross sections; zero-air Rayleigh 2 %) | full text (abstract; Sect. 4.2) |
| Nam_2022 | 10.5194/amt-15-4473-2022 | Sect. 4.6 (R(λ) uncertainty 2.2 % from zero-air Rayleigh 2 %; d_eff 5.2 %) | full text (Sects. 3.1) |
| Stutz_1996 | 10.1364/ao.35.006041 | Sect. 4.6 (error estimate including residual structure and wavelength-mapping correction) | abstract (OpenAlex) |
| Platt | 10.1007/978-3-540-75776-4_8 | Sect. 4.6 (conditions for the least-squares error) | chapter title/metadata; already cited in Sect. 1 for the same point |
| Raue_2009 | 10.1093/bioinformatics/btp358 | Sect. 5.1 (profile-likelihood practical identifiability) | title/metadata |
| Efron_1979 | 10.1214/aos/1176344552 | Sect. 4.2 (LOO as jackknife-type resampling) | title/metadata |
| Day_2002, Wooldridge_2010 | 10.1029/2001jd000779, 10.5194/amt-3-593-2010 | Sect. 7.1 (thermal dissociation of PNs/ANs to NO2) | title/metadata |

Literature numbers added in Sect. 4.6 (new values in the main text, from the papers above, not from this study): 4.6 % (Washenfelder 2008), 5.0 % (Min 2016), 2.2 % and 5.2 % (Nam 2022), 2 % (zero-air Rayleigh). The multiset diff lists only 4.6 and 5.2 as new strings because 5.0, 2.2 and 2 already occurred elsewhere.

Removed uncited bib entries (19):

- Fiedler_2003 (doi:10.1016/s0009-2614(03)00263-x)
- Langridge_2008 (doi:10.1063/1.3046282)
- W_st_2025 (doi:10.5194/amt-18-1943-2025)
- Serdyuchenko_2014 (doi:10.5194/amt-7-625-2014)
- Hausmann_1997 (doi:10.1029/97jd00931)
- Tuckermann_1997 (doi:10.3402/tellusb.v49i5.16005)
- Alicke_2002 (doi:10.1029/2000jd000075)
- Pu_te_2010 (doi:10.5194/amt-3-631-2010)
- Beirle_2013 (doi:10.5194/amt-6-661-2013)
- Wagner_2019 (doi:10.5194/amt-12-2745-2019)
- Davis_2020 (doi:10.5194/amt-13-3993-2020)
- Roscoe_2010 (doi:10.5194/amt-3-1629-2010)
- Tirpitz_2021 (doi:10.5194/amt-14-1-2021)
- Thalman_2010 (doi:10.5194/amt-3-1797-2010)
- Virtanen_2020 (doi:10.1038/s41592-019-0686-2)
- Marquardt_1963 (doi:10.1137/0111030)
- Branch_1999 (doi:10.1137/s1064827595289108)
- Golub_2003 (doi:10.1088/0266-5611/19/2/201)
- Hochstaffl_2023 (doi:10.5194/amt-16-4195-2023)

references.bib now has 22 entries, all cited; the bibliography prints 22 items.

## 4. Style and format

- Bold removed from running text (`\strong` run-in heads in Sects. 2 and 4–6; in Appendix A now `\emph`). Bold entries in main-text tables were also removed, except the column minima of Table 2 (explained in its caption). Bold remains for figure panel letters and in appendix tables A2, C1 and C3.
- Transition-only paragraph openers replaced by topic sentences (e.g. 'Leave-one-out (LOO).', 'What the pipeline could report instead.' ×4, 'This is the benchmark doing what it was built for.', 'One correction must be avoided, because it is available and wrong.', '13 of 38 is a poor hit rate and a good filter.').
- Figure captions shortened (words, same counter as Sect. 1): Fig. 1 189→119, Fig. 2 271→115, Fig. 3 230→120, Fig. 4 133→89, Fig. 5 167→118, Fig. 6 299→119.
- Author, affiliation, correspondence, contributions, competing interests and acknowledgements marked `[AUTHOR: …]`. AI-use disclosure placeholder added to the Acknowledgements (tool and scope left for the author).

## 5. Number invariance

Method: every numeral in the LaTeX source of the main text (abstract, Sects. 1–8, including tables and captions; labels, references, citation keys and layout lengths excluded) was collected as a multiset before and after, together with the appendices (A–D, availability). `\fieldnum{}` values were compared separately.

- No number changed value. Values new to the main text: 4.6 and 5.2 only (literature values in Sect. 4.6, Sect. 3 of this file).
- `\fieldnum` values that no longer occur anywhere: `2.3` (abstract, rounded form of 2.29, which remains in the abstract and body), and `$+13$`, `$-8$`, `$+15.5$`, `$-2.5$`, `$+7.6$` (the repeated listing in the old Sect. 4.3 'The discrepancy is +13 % in one channel and −8 % in another … +15.5 %, −2.5 % and +7.6 %', a duplicate of the preceding sentences that give +13.3 %, −8.1 %, 15.5 %, 2.5 % below and 7.6 %).
- Two statements that were only in the old abstract were restored in the body so that no result is lost: AR(1) ratio 1.42–2.05 and 'within 10 % in 15 of the 30 cases' (Sect. 3.1).
- Every other number whose count in the main text fell is either still present in the main text (a duplicate occurrence removed) or now in an appendix:

| value | main before | main after | appendices before | appendices after | reason |
|---|---|---|---|---|---|
| `0` | 34 | 33 | 21 | 22 | partly moved to appendix; value still in main text |
| `1` | 40 | 37 | 1 | 3 | partly moved to appendix; value still in main text |
| `2` | 55 | 49 | 19 | 22 | partly moved to appendix; value still in main text |
| `4` | 12 | 11 | 7 | 7 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `5` | 14 | 6 | 2 | 8 | partly moved to appendix; value still in main text |
| `6` | 6 | 5 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `7` | 7 | 6 | 1 | 2 | partly moved to appendix; value still in main text |
| `9` | 6 | 5 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `-1` | 10 | 7 | 12 | 15 | partly moved to appendix; value still in main text |
| `-7` | 7 | 6 | 0 | 1 | partly moved to appendix; value still in main text |
| `-8` | 7 | 5 | 1 | 2 | partly moved to appendix; value still in main text |
| `10` | 22 | 18 | 5 | 9 | partly moved to appendix; value still in main text |
| `12` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `13` | 8 | 5 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `14` | 1 | 0 | 0 | 1 | moved to appendix |
| `18` | 8 | 7 | 2 | 2 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `22` | 4 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `26` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `29` | 4 | 3 | 1 | 1 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `30` | 7 | 6 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `34` | 6 | 4 | 7 | 9 | partly moved to appendix; value still in main text |
| `38` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `40` | 3 | 2 | 1 | 1 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `53` | 4 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `60` | 8 | 5 | 1 | 3 | partly moved to appendix; value still in main text |
| `90` | 7 | 3 | 0 | 3 | partly moved to appendix; value still in main text |
| `95` | 4 | 2 | 0 | 1 | partly moved to appendix; value still in main text |
| `-15` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.5` | 8 | 7 | 4 | 4 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `1.2` | 3 | 2 | 1 | 1 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `1.3` | 2 | 1 | 1 | 1 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `1.5` | 4 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `1.6` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `155` | 4 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `165` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `180` | 17 | 16 | 1 | 2 | partly moved to appendix; value still in main text |
| `2.3` | 1 | 0 | 0 | 0 | abstract rounded duplicate of 2.29 |
| `2.5` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `2.8` | 4 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `3.5` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `300` | 20 | 19 | 2 | 3 | partly moved to appendix; value still in main text |
| `6.2` | 1 | 0 | 0 | 1 | moved to appendix |
| `7.6` | 2 | 1 | 1 | 1 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `974` | 1 | 0 | 0 | 1 | moved to appendix |
| `-2.5` | 1 | 0 | 0 | 0 | duplicate listing in Sect. 4.3 |
| `0.03` | 4 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.07` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.08` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.24` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.32` | 4 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.91` | 5 | 4 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `1.22` | 2 | 1 | 1 | 1 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `1.23` | 2 | 1 | 1 | 1 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `1.32` | 9 | 5 | 0 | 1 | partly moved to appendix; value still in main text |
| `1.59` | 1 | 0 | 0 | 1 | moved to appendix |
| `1.63` | 6 | 5 | 0 | 1 | partly moved to appendix; value still in main text |
| `1.83` | 2 | 0 | 0 | 1 | moved to appendix |
| `11.3` | 4 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `11.8` | 5 | 4 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `15.5` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `2.43` | 1 | 0 | 0 | 1 | moved to appendix |
| `2.50` | 6 | 5 | 0 | 1 | partly moved to appendix; value still in main text |
| `2.89` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `2026` | 10 | 9 | 4 | 4 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `3.76` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `85.5` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `8832` | 2 | 0 | 0 | 1 | moved to appendix |
| `8847` | 5 | 4 | 0 | 1 | partly moved to appendix; value still in main text |
| `0.005` | 2 | 1 | 2 | 2 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.006` | 2 | 0 | 0 | 2 | moved to appendix |
| `0.025` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.027` | 2 | 0 | 0 | 2 | moved to appendix |
| `0.086` | 2 | 1 | 0 | 1 | partly moved to appendix; value still in main text |
| `0.100` | 5 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.154` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.187` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.243` | 2 | 1 | 0 | 1 | partly moved to appendix; value still in main text |
| `0.285` | 2 | 0 | 0 | 2 | moved to appendix |
| `0.347` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.766` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.826` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.990` | 4 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `0.999` | 2 | 1 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `11.03` | 6 | 3 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `18.31` | 3 | 2 | 0 | 0 | duplicate removed from abstract/intro/conclusions or merged section; value still in main text |
| `2.941` | 1 | 0 | 0 | 1 | moved to appendix |
| `4.276` | 1 | 0 | 0 | 1 | moved to appendix |
| `4.388` | 1 | 0 | 0 | 1 | moved to appendix |
| `8.3.4` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.0000` | 2 | 1 | 0 | 1 | partly moved to appendix; value still in main text |
| `0.0217` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.0326` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.0541` | 3 | 1 | 0 | 1 | partly moved to appendix; value still in main text |
| `0.0558` | 3 | 1 | 0 | 2 | partly moved to appendix; value still in main text |
| `0.0693` | 4 | 3 | 0 | 1 | partly moved to appendix; value still in main text |
| `0.0706` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.0806` | 5 | 3 | 0 | 1 | partly moved to appendix; value still in main text |
| `0.1236` | 4 | 3 | 3 | 4 | partly moved to appendix; value still in main text |
| `0.1244` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.9997` | 1 | 0 | 0 | 1 | moved to appendix |
| `-0.5000` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.00025` | 1 | 0 | 0 | 1 | moved to appendix |
| `0.04209` | 1 | 0 | 0 | 1 | moved to appendix |

Small integers (0–100) are counted too; for them a lower count usually reflects a removed duplicate sentence, a removed cross-reference-like phrase, or text moved into an appendix, and was checked by context for 12, 13, 18, 22, 26, 29, 30, 34, 38, 40, 53, 95 and 2026.

## 6. Not done / open

1. Main text is ≈13,100 words on the evaluation's count (12150 here), at the upper edge of the 12,000–13,000 target; further cuts would need removing content rather than duplicates.
2. 37 sentences remain over 40 words (from 120); none over 60 (0).
3. Evaluation item 6 (candidate causes of the 0.6 absolute-scale and 4–6 % QDOAS scale differences) was not in the approved scope and was not added.
4. Kraus_2006 `note={verify}` and Danckaert_2017 year placeholder remain; HITRAN edition unverified.
5. Stutz_1996 content was checked from its abstract only (full text is closed access); Platt 2008, Raue 2009, Efron 1979, Day 2002 and Wooldridge 2010 are cited only for what their titles and metadata state.