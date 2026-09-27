# Fig 3 — caption and provenance (v1, 2026-09-27)

## Caption (draft)

**Figure 3.** Validation of the retrieval core. **(a)** Error in the recovered NO$_2$ amount (filled, relative) and
wavelength shift (open, px) for 27 noise-free spectra: nine shifts between −4 and +4 px, each with squeezes 0.998, 1.000
and 1.002. **(b)** Error in NO$_2$ against the order of the fitted baseline for a noise-free spectrum built with a
fourth-order baseline; inset, on noisy realisations of the same spectrum, the realised scatter of NO$_2$ divided by the
reported 1σ. **(c)** Difference between the analytic Golub–Pereyra Jacobian and a central finite difference of the
projected residual, against the finite-difference step, for the shift and the squeeze; the dashed line has slope $h^2$.
**(d)** Shift recovered by Augur and by QDOAS minus the true shift, for true shifts from −7 to +7 px (five noisy
realisations each, both started at 0). **(e)** Standard deviation of (retrieved − true)/reported σ over 300 realisations
in each of three conditions (measurement noise; ten times that; a narrow window with three times the noise), for Augur
and QDOAS fitting the same model, and for Augur with its etalon terms switched on. **(f)** Benchmark group B: realised
scatter divided by the reported uncertainty under white, doubled and autocorrelated (AR(1), ρ = 0.5) noise, for Augur,
for the benchmark's reference implementation and for Augur with the shift fixed at its true value; the dashed line is the
√3 inflation predicted for ρ = 0.5.

## Provenance (for the author; not caption text)

- (a), (b): `varpro_synth_results.csv` (4ade456c), rows `g1_nonlinear_recovery` (27) and `g2_poly_sweep` (9).
- (c): values of the §3.2 table (no separate CSV found in the artifact store).
- (d): `h2h_E2_basin.csv` (4728d908), 75 rows. (e): `h2h_E1_coverage.csv` (5f367e13); matched = `Augur noEt(joint)`,
  etalon on = `Augur(joint)`; C3 scatter ratio etalon-on / QDOAS = 8.27 % / 4.11 % = 2.0.
- (f): values of §3.4 text (1.32 / 1.09 / 1.65; 1.19 / 1.33 / 1.57; shift fixed 1.19 and 1.75 — doubled-noise fixed-shift value not reported).
- Colour roles: blue = Augur, teal = independent reference (QDOAS, reference implementation), orange = the model choice that changes the result.
