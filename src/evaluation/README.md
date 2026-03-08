# Evaluation Default Strategy Baseline

Updated on 2026-03-07.

## What was set as default

The evaluation default baseline now follows the champion combo found in
`matrix_1x9x4x2_risk65_profit35_20260305.csv`, except for entry mechanism settings.

Applied defaults:

- Exit strategy: `MVX_N9_R3p6_T1p7_D18_B20p0`
- Position profile source file: `evaluation-position-1x9x4.json`
- Overlay mode: enabled (`ovl=on`)

## Config keys

These defaults are defined in `config.json` under `evaluation`:

- `default_position_file`
- `default_overlay_enabled`
- `default_exit_strategies`

## Notes

Entry mechanism defaults were intentionally not changed, per request.
