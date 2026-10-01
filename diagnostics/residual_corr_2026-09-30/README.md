# Residual-correlation (sandwich) uncertainty vs the structural budget (2026-09-30)

Question: does a residual-based correction for correlated residuals (Stutz & Platt 1996 type; here the sandwich
covariance pinv(M) Σ pinv(M)^T with Σ = Toeplitz(s² ACF_r)) account for the structural budget of Sect. 4?

## 1. Benchmark group B (bench_residual_corr.py -> bench_summary.csv), 60 cases per condition, Augur operational fit path
scatter / RMS(sigma):
| condition | white sigma | joint sigma | corrected (ACF truncated at first non-positive lag) | corrected (Bartlett 20) |
|---|---|---|---|---|
| white x1 | 1.20 | 1.20 | 1.19 | 1.38 |
| white x2 | 0.92 | 0.92 | 0.91 | 1.08 |
| AR(1) 0.5 | 1.85 | 1.85 | 1.15 | 1.27 |
Fixed-shift fits give the same (1.19 / 0.95 / 1.87 white). The correction recovers most of the correlated-noise deficit.

## 2. Field budget window (field_residual_corr.py -> field_ANs.csv, field_PNs.csv, field_summary.json)
9034 records per heated channel, 8847 non-bound; reconstruction of the operational fit exact (NO2 rel. diff 4e-16, sigma 5e-14).
- residual lag-1 autocorrelation: median 0.063 (300 C), 0.012 (180 C)
- sigma inflation (corrected/white): median 1.24 (p90 1.84) at 300 C, 1.02 (p90 1.35) at 180 C; joint = linear to 0.1 %
- SumANs (g' 0.9524) median sigma: white 0.0546, corrected 0.0613 (trunc) / 0.0589 (Bartlett) ppb
- structural (LOO triple, non-bound): rSD 0.0701, SD 0.1245 ppb
- structural / sigma: 1.28 / 2.28 (white) -> 1.14 / 2.03 (corrected); total / corrected sigma 1.52 / 2.26
- records with |structural change| > own sigma: 45.4 % (white) -> 40.3 % (corrected); Spearman(inflation, |struct|/sigma) = 0.23
Conclusion: the residual-based correction raises the SumANs sigma by 12 %; the structural terms remain 1.1-2.0 times the corrected sigma.
