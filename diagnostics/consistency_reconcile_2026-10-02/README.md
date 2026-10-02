# LOO vs observed-variance consistency, reconciled (2026-10-02)

Question: two earlier checks disagreed. (1) The paired gate test (robust, hourly differences, Sigma ANs with g' = 0.9524) found the
LOO budget at 0.79x the observed statistic (consistent). (2) The ACP-robustness check found LOO 2x larger than the 2-h high-pass SD of the
G-version Sigma ANs (inconsistent). Both use the same principle: the observed series contains the realised calibration error, so for any
linear filter Var(filtered observed) >= Var(filtered realised error), assuming error and atmosphere are independent.

## Yeosu budget window (8847 non-bound 60-s records, 2026-05-18..24), combination X_g = NO2(300 C) - g * NO2(180 C), 5-min means
The bound depends strongly on g, because atmospheric NO2 cancels only near the true response ratio. Smoothest observed combination at g ~ 1.21
(= the ambient-scaled G version; the August lab ratio is 1.24).

| g | observed 2-h HP SD (ppb) | LOO 2-h HP SD | LOO/obs SD | LOO/obs robust | LOO/obs 5-min diff robust |
|---|---|---|---|---|---|
| 0.820 | 0.255 | 0.107 | 0.42 | 0.51 | 0.17 |
| 0.952 | 0.173 | 0.109 | 0.63 | 0.72 | 0.25 |
| 1.000 | 0.144 | 0.110 | 0.76 | 0.85 | 0.29 |
| 1.048 | 0.117 | 0.111 | 0.95 | 0.98 | 0.34 |
| 1.100 | 0.089 | 0.112 | 1.26 | 1.17 | 0.39 |
| 1.150 | 0.068 | 0.113 | 1.67 | 1.37 | 0.45 |
| 1.210 | 0.058 | 0.114 | 1.98 | 1.47 | 0.47 |
| 1.300 | 0.084 | 0.116 | 1.39 | 1.13 | 0.39 |

Reading: at g' = 0.9524 atmospheric NO2 leaks into the combination and loosens the bound -> LOO looks consistent (test 1).
At g ~ 1.2 the bound is tight and the LOO 2-h high-pass variation exceeds what the data allow: robust x1.47, SD x1.98.
Removing white fit noise of a 5-min mean (~0.028 ppb at g = 1.21) from the observed robust value (0.045) leaves <= ~0.035 ppb for
realised error plus atmosphere, i.e. LOO >= ~1.9x the realised error (robust), and realised error <= ~0.55-0.7 of the 60-s fit sigma
of this combination (0.063 ppb). The two tests therefore agree once the same g is used; test 2 is the binding one.

## Seosan 2020 (3939 60-s bins, 11 knot pairs, intervals 2.7-16.5 h), ch1 - k*ch2 (k = 1.046; both channels retrieve NO2, identity unverified)
| combination | filter | observed robust | LOO robust | observed SD | LOO SD |
|---|---|---|---|---|---|
| k=1.0 | level | 0.374 | 0.396 | 0.538 | 1.951 |
| k=1.0 | hp2h | 0.095 | 0.024 | 0.178 | 0.399 |
| k=1.046 | level | 0.411 | 0.397 | 0.430 | 2.014 |
| k=1.046 | hp2h | 0.089 | 0.024 | 0.136 | 0.412 |

Reading: the typical (robust) LOO error, ~0.40 ppb (~4 % of NO2, ~3.7 sigma of the channel difference, sigma = 0.108 ppb),
equals the observed inter-channel scatter (0.41 ppb): at multi-hour intervals a slow, realised error of LOO size is allowed (and the earlier
ch1/ch2 ratio drift of +4.6 % at 5-8.5 h from a knot points the same way). The LOO SD (2.0 ppb) is 4.7x the observed SD: the LOO tail
(removing the knot next to the R step) is a what-if sensitivity, not a realised error.

## Consequences
1. LOO is a conservative estimator; its tail must not be reported as realised error. Report it as a sensitivity / upper estimate and
   pair it with the observed-variance bound (computed at the best-cancelling channel weight).
2. At 1-h calibration cadence (Yeosu) the realised interpolation term on sub-2-h scales is at most ~0.6-0.7 of the 60-s fit sigma.
   At 3-16 h intervals (Seosan) a realised slow error of ~4 % of NO2 (several sigma) is allowed and indicated.
3. The manuscript's 'structural/sigma 1.28 (robust) / 2.28 (SD)' are LOO values; they overstate the realised term at Yeosu.
Caveats: independence of error and atmosphere; 2-h high-pass excludes slower error components; one week at Yeosu; Seosan channel identity.
