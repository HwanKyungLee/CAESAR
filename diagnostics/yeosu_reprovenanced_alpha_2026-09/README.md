# Yeosu hot — reprovenanced alpha evidence (2026-09-10)

This directory is a separate Explorer evidence run. It does not overwrite the
operational alpha products under `C:/GHL/2026 yeosu/Output/alpha`, and it does
not change any FitSet.

## Inputs fixed for this run

- raw hot files: 2026-05-26-001, 2026-05-30-019, 2026-06-04-022, and
  2026-06-09-026;
- 60 s ambient averaging, PCHIP I0 handling, cavity length 51.8 cm, and
  `rl_factor=1.0`;
- ANs: channel 1, ROI [599, 1270), `R_CH1.npz`;
- PNs: channel 2, ROI [899, 1450), `R_CH2.npz`;
- the runtime diagnostic FitSet at
  `../yeosu_profile_2026-09/yeosu_hot_runtime_fitset.json`.

Every regenerated alpha file records
`# T_P_PROVENANCE: measured_raw_housekeeping`. The old alpha products remain
valid historical inputs but lack this machine-readable provenance statement.

## Contents

- `ANs/`, `PNs/`: regenerated alpha files, separated by channel and date.
- `stage1_hot_reprovenanced_config.json`: six-candidate, four-date Stage 1
  batch configuration and its `stage1_results/` evidence.
- `stage2_*_sampling_source.json`: immutable, channel-specific selection of
  twelve timestamped rows used by every candidate in Stage 2.
- `stage2_hot_reprovenanced_config.json`: six-candidate Stage 2 configuration
  and its `stage2_results/` evidence.

## Scope and current interpretation

All six Stage 2 candidate runs completed 24/24 controlled-start fits. The
candidate reports retain solver, boundary-hit, seed-stability, T/P provenance,
and reference-observability evidence. They do not rank candidates, declare a
plateau, mutate a FitSet, or apply a setting.

T/P provenance is now measured and available. T2 absolute-anchor remains
`UNAVAILABLE` because this FitSet declares no independent absolute-amount
anchor; that is not a fallback-T/P failure and is not an absolute calibration
claim. A human review must decide any mission-local conclusion.
