# Araon 2025 second-dataset check (2026-10-02)
Raw 2025-06-10..12 (66 files) copied to C:\GHL\old_missions\Araon2025\raw. Layout 6181 cols (structural ch1/ch2); ch1 HK: P_ANs col 6164 (~866 mbar), tempcell1 col 6174.
Calibration cycles present hourly (24 He/ZA cycles on 06-11, ~33 scans each).
rt_precompute (ROI 444.96-465.03 nm, RL 1.0): only 18 valid R knots in 3 days; 19 of 24 cycles on 06-11 rejected for He/ZA contrast < 5 %
(median (He-ZA)/He mostly -0.5..+0.5 %, sometimes -7 to -67 %; valid cycles 11-17 %). The same holds in the other raw blocks (cols 5-2052: similar; 4101-6148: dark, ~660 counts).
=> helium calibration failed for most cycles (He not reaching the cavity or light drift during the block); the Augur alpha export used a fallback Leff.
R-term LOO is therefore not evaluable on Araon; a zero-air-only (I0) budget remains possible.

## Reporting fields applied to Araon (06-10..12, 3627 ambient 60-s bins) — araon_fields.json
- He/ZA cycles 65, valid R knots 18 (72 % rejected for contrast < 5 %)
- distance to nearest valid R knot: median 2.7 h, p90 7.7 h, max 10.9 h (Yeosu budget window: 0.26 / max 0.64 h)
- bracketing R interval: median 15.6 h, max 17.9 h (Yeosu 1.0 / 1.3 h); 15 rejected cycles inside the median bracket
- 17.5 % of records outside the valid-knot range (extrapolation); 69 % > 1 h and 23 % > 6 h from a valid R
- zero-air coverage normal: median 0.26 h to the nearest ZA, bracket 1.0 h
- the delivered Araon alpha used a fallback constant Leff (3.39 km): provenance field would read 'fallback', not 'measured R(t)'
