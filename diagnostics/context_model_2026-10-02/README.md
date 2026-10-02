# Context model for the structural term (2026-10-02)
Records: 8847 non-bound budget records (18-24 May, clock-fixed R), target |delta_tri - median| of SumANs (production_budget_clockfixed.csv).
Features: channel NO2 (n2_b), relative change of (1-R)/d across the bracketing R interval (ch1+ch2), amplification |I0/(I0-I)|, distance to nearest zero-air knot.
Model: OLS on log|delta|, leave-one-day-out (7 days).
- Spearman(feature,|delta|): NO2 +0.30, amp -0.28, R jump +0.19/+0.20, ZA distance -0.12, interval length ~0 (all intervals ~1 h in this window)
- held-out Spearman(pred,|delta|) = 0.41
- AUC for |delta| > own fit sigma (45 % of records): 0.68 (NO2 alone 0.63, R jump alone 0.60)
- held-out coverage of |delta| <= 1/2 predicted sigma: 0.67 / 0.90 (Gaussian 0.68 / 0.95); per-day 1-sigma coverage 0.55-0.73
- top 10 % of records by predicted sigma carry 48 % of structural variance (oracle 69 %)
Interval length could not be tested: the window has ~1 h intervals throughout.
