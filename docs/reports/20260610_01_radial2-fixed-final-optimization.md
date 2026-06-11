# radial 2段固定条件最終探索 runner

## 目的

全体最適化 v4 でおおよその傾向が見えたため、最後の確認用として radial 2段だけを回す runner を追加した。

固定する条件は次である。

| 項目 | 固定値 |
|---|---:|
| Steam/EB 比 | `5.0` |
| 1基目デカンター温度 | `55.0 ℃` |
| SM分離塔還流比 | `6.312` |

## 実装対象ディレクトリ

```text
src/process_sim/
  optimization/
    runner/
      whole_plant_radial2_fixed_final.py  # radial 2段だけを固定分離条件で探索する runner
scripts/
  whole_plant_radial2_fixed_final/
    plot_results.py                       # radial 2段固定条件 study の図表化
docs/
  reports/
    20260610_01_radial2-fixed-final-optimization.md
```

## ファイル責務

### `src/process_sim/optimization/runner/whole_plant_radial2_fixed_final.py`

radial 2段固定条件の Optuna 実行を担当する。

この runner は、他の runner から関数や設定値を import しない。`whole_plant_optuna_v4.py` などの実験用 runner は、対象 study、探索変数、固定条件が異なるため、そこへ依存すると最終確認用 script の挙動が間接的に変わる。したがって、radial 2段固定条件に必要な処理はこの module 内で明示する。

Optuna の探索変数は次である。

```text
stage_1_temperature_c
stage_2_temperature_c
inlet_pressure_kpa_abs
stage_1_bed_thickness_m
stage_2_bed_thickness_m
```

`steam_to_eb_ratio` は trial 変数にせず、`5.0` で固定する。分離器操作条件も trial 変数にせず、1基目デカンター温度 `55.0 ℃`、SM分離塔還流比 `6.312` の `SeparatorOperatingCandidate` を毎 trial に渡す。

storage と log は既存 v4 と分ける。

```text
data/optuna/whole_plant_radial2_fixed_final.db
logs/whole_plant_radial2_fixed_final.log
logs/whole_plant_radial2_fixed_final_detail.log
```

実行条件として、少なくとも次を module 先頭の定数で変更可能にする。

```text
TARGET_EFFECTIVE_TRIALS
N_STARTUP_TRIALS
SEED
```

`N_STARTUP_TRIALS` は Optuna の探索挙動に直接関わるため、他 runner の定数を import しない。この専用 runner の先頭を見れば変更できる構造にする。

### `scripts/whole_plant_radial2_fixed_final/plot_results.py`

radial 2段固定条件 study の SQLite storage を読み、図と上位 trial 表を出力する。

読み込み対象は `data/optuna/whole_plant_radial2_fixed_final.db` とし、v4 の storage や study 名には依存しない。

## 採用理由

既存 v4 runner は radial 2段、radial 3段、axial 2段、axial 3段を同一 runner で扱い、分離器操作条件も探索変数に含める。今回の目的は最後の radial 2段確認であり、対象外 study や固定したい操作条件を含める必要がない。

そのため、新規 runner として分け、既存 v4 は変更しない方針にした。これにより、v4 の探索結果と、固定条件での最終確認結果を storage 上でも分離して比較できる。

ただし、runner 間で直接 import して再利用すると、別 runner の定数や関数変更が radial 2段固定条件 runner に波及する。最終確認用 script としては不適切なので、依存先は反応器 model、plant convergence、HYSYS control、cost 評価などの下位 module に限定する。

## 既知の制約

- HYSYS 実行は行っていない。
- SM分離塔還流比 `6.312` は、ユーザー指定の「元の 6.312?」をそのまま固定値として採用した。
- trial 数の既定値は累積 `200` effective trials とし、module 先頭の `TARGET_EFFECTIVE_TRIALS` で変更する。
- Optuna startup trial 数の既定値は `15` とし、module 先頭の `N_STARTUP_TRIALS` で変更する。
