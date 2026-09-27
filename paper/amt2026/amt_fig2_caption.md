# Fig 2 — caption and provenance (v2, 2026-09-27)

## Caption (draft)

**Figure 2.** One record (1 June 2026, 10:35 KST; cold channel 10:34:34) retrieved in the three
configurations of Table 1. Columns: **(a)** hot ANs (300 °C), **(b)** hot PNs (180 °C), **(c)** cold.
**Top row:** per-pixel noise of the 60 s extinction spectrum in the hour around the record, with the fit window
shaded. Each window sits on the low-noise band set by its LED (bar: LED emission half-maximum from zero-air
spectra); the cold window extends 13 nm below its LED half-maximum, where the noise is several times higher; the step at 428 nm in (a) is the band-pass filter edge and the step at 470 nm in (b) is the
red edge of the 469 nm LED. **Middle block,** top to bottom: measured extinction with the fitted model and the
baseline-plus-etalon term (shading: sum of trace-gas terms); the NO$_2$ contribution, shown as the measurement minus
every other fitted term, with the fitted NO$_2$ term; the same for H$_2$O, with the fitted CHOCHO term; and the
residual, with ±RMS shaded and its histogram against a Gaussian of the same RMS at right. The lower three rows share
one vertical scale across columns. Values in the NO$_2$ row are the operational retrieval and its reported 1σ;
"band depth / RMS" is the peak-to-peak of the fitted NO$_2$ term divided by the residual RMS. **Bottom row:**
the NO$_2$ retrieved by the same configuration over the surrounding 24 h (status-OK fits only; n = 844, 945, 706),
the star marking this record; inset: distribution of residual RMS over those fits, on which this record sits at the
28th, 46th and 82th percentile.

## Provenance (for the author; not caption text)

- Record: logger time 2026-06-01 01:35:00 (cold 01:34:34). **KST = logger + 9 h**, confirmed by matching the
  day's 5-min ANs-channel NO$_2$ with `SigmaANs_5min_KST_chfix_20260927.csv` (`NO2_300C_ppb`): r = 1.000 at +9 h,
  0.35 at −9 h, −0.14 at 0 h. This closes the time-zone ⚠ of v1.
- Selection: v1 caption stated "297 all-OK times, percentiles 0.49/0.53/0.60". That could not be reproduced (the
  all-three-OK set with a 60 s cold match gives 306 times; percentiles within it 0.39/0.53/0.75). v2 therefore
  reports the percentile within each channel's status-OK fits of the day and drops the selection claim.
- Top row: α traces `Output\alpha\60s\{hot\ch1, hot\ch2, cold}\2026-06-01\*-00[1-4]_*_alpha_trace.dat`; 60 records within ±30 min;
  each spectrum high-passed by removing a 31-pixel running median; noise = std of successive-record differences / √2,
  15-pixel running mean; dead pixels (std < 1e-12) masked. Array: `amt_fig2_noise_profiles.csv`.
- LED half-max: `channel_identity_led_fingerprint.csv`, campaign 06-09-011 ZA spectra, block 2053 (ANs) 428.1–456.1 nm,
  block 4101 (PNs) 451.3–470.8 nm. Cold (added 2026-09-27 after the raw copy to C:): `RAW/cold/2026-06/2026-06-01-002.mat`,
  flag 502 mean, 1st-percentile offset (461 counts) removed, 5-px smoothing: peak 460.4 nm, half-max 451.7–473.4 nm.
- Middle block: unchanged arrays `amt_fig2_data.csv` (Augur refit reproducing the operational record; see v1 table:
  NO$_2$ deviation 0.004 / 0.108 / 0.370 σ). CHOCHO is now drawn unscaled (peak-to-peak 0.2 / 0.4 / 5.4 × 10$^{-9}$ cm$^{-1}$).
- Bottom row: operational results `Output\fitting\new\26yeosu\2026-06-01\fitting\260601_CH{1,2,3}_*.dat`, Status == "OK".
- Script: `fig2v2.py`.
