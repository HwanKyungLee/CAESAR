# Hot left-cavity T back-cast (Yeosu 2026)

The PNs ("좌측") cavity temperature sensor was not reporting for the first
days of the campaign:

| Column | Status |
|---|---|
| `col 6175` (tempcell2, the canonical left-cavity sensor) | **sentinel until 2026-05-27 10:56 KST**, then operational |
| `col 6180` (tempcell-like backup sensor at the same cavity) | sentinel until 2026-05-22 00:08 KST, then operational |

We trained a Gradient Boosting Regressor on the **5/22 ~ 5/29** window
(where col 6180 is alive and serves as the target), then applied it to
**5/18 ~ 5/27 morning** to back-cast the missing left-cavity T.
A +0.10 °C bias correction puts the predictions on the col 6175 scale.

| Metric | Value |
|---|---|
| Test R² (20% hold-out) | **0.981** |
| Test RMSE | **0.244 °C** |
| Feature importance — T_spt (col 6174) | 87 % |
| Feature importance — preheater T (col 6153) | 7 % |
| Feature importance — LED1 T (col 6149) | 3 % |
| Feature importance — P_PNs (col 6162) | 2 % |
| Feature importance — P_ANs (col 6164) | 1 % |

## Layout

```
hot_cavity_t/
├── scripts/
│   ├── 01_train_gbr.py             # train + benchmark models, save best as .pkl
│   ├── 02_backcast_all.py          # apply model to 5/18~5/29; T_measured = col 6180
│   └── 03_rebuild_with_c6175.py    # rebuild unified CSV with col 6175 as truth
├── exploration/                    # column-discovery + correlation studies (provenance)
│   ├── hot_hk_inspect.py
│   ├── hot_27_detailed_check.py
│   ├── hot_col6180_full_check.py
│   ├── hot_pressure_revisit.py
│   └── hot_cav_t_explore.py
└── model/
    ├── hot_t_best_model.pkl                 # the trained GBR (sklearn 1.8)
    ├── hot_t_model_train.png                # training-fit plot
    └── sample_unified_timeseries.png        # 5/18~5/30 measured + predicted overlay
```

The large per-row CSV (`hot_T_left_cavity_unified_c6175.csv`, ~8.5 MB) is
**not committed** because it's fully regenerable from the .pkl + raw .dat
files. Run `03_rebuild_with_c6175.py` to recreate it.

## Reproduce

```bash
cd campaigns/yeosu_2026/hot_cavity_t/scripts

# (optional) point at a different Hot raw directory
set CAESAR_HOT_DIR=D:\Yeosu_2026\CAESAR_Hot\2026-05

# 1. retrain (~7 min on ~150k rows, writes hot_t_best_model.pkl into ../model)
python 01_train_gbr.py

# 2. back-cast all rows; writes hot_T_left_cavity_unified.csv + .png
python 02_backcast_all.py

# 3. rebuild final with col 6175 as the measured-source-of-truth
python 03_rebuild_with_c6175.py
```

`CAESAR_TPRED_OUT` overrides the output directory if you want artefacts
somewhere else.

## CSV columns

| Column | Meaning |
|---|---|
| `ts` | row timestamp (KST, ISO) |
| `T_spt_C` | spectrometer-housing T (col 6174 ÷ 100), the dominant predictor |
| `T_predicted_C` | GBR output (+0.1 °C bias) for every row |
| `T_measured_c6175_C` | col 6175 ÷ 100 when available, else empty |
| `T_aux_c6180_C` | col 6180 ÷ 100 when available — auxiliary cross-check |
| **`T_final_C`** | **measured if available, else predicted — use this** |
| `source` | `"measured"` or `"predicted"` flag for `T_final_C` |
| `file`, `row_idx` | provenance back to the raw .dat |

## Linear-regression fallback

If a hand-computable formula is needed in place of the .pkl (e.g. for a
quick spreadsheet check), the single-variable linear regression is:

```
T_cav_left ≈ 0.606 × T_spt + 8.943      # R²=0.83, RMSE=0.75 °C
```

— accurate to ±0.75 °C, vs the GBR's ±0.24 °C.
