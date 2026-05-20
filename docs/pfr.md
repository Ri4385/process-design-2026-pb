# PFR 反応器

## 目的

この文書は、多段断熱 PFR 実装の恒久メモである。

PFR は、主設計の radial reactor と比較するための軸方向固定床モデルとして残す。特に、同じ触媒体積を与えたときに、PFR と radial reactor で圧力損失分布がどう異なるかを比較できるようにする。

## 現在の実装

- 1 基分の PFR は `src/process_sim/reactor/types/pfr_adiabatic.py` の `PfrAdiabaticReactor` である。
- 多段 PFR は `src/process_sim/reactor/types/staged_adiabatic_pfr.py` の `StagedAdiabaticPfrModel` である。
- 既定ケースは `src/process_sim/reactor/cases/styrene_default.py` に置く。
- CLI では `uv run run-reactor-case --reactor-model pfr` で実行する。
- plant one-pass では `uv run run-plant-once --reactor-model pfr` で PFR を使う。

## モデル

- 反応器は軸方向 1 次元の断熱 PFR として扱う。
- 1 基分の PFR と staged PFR は分ける。
- 各段は RK4 で軸方向に積分する。
- 圧力は状態変数として積分する。
- 圧力損失は Ergun 式で計算する。
- 分圧は局所圧力と局所組成から計算する。
- 反応ネットワークはコンテスト由来の 6 反応モデルを使う。
- 反応熱は成分エンタルピーから温度ごとに計算する。
- 段間再加熱は反応器外部で行うとみなし、再加熱負荷を計算する。
- 段間再加熱器圧力損失は、再加熱 1 回あたり `20 kPa` として固定する。

## 既定条件

- 入口圧力は `200 kPa abs` とする。
- 段入口温度は `550, 550, 550 degC` とする。
- 段長は `2.5, 2.5, 2.5 m` とする。
- 総触媒体積は radial 既定ケースと同じ `99.313 m3` とする。
- 断面積は `A_c = V_cat,total / L_total` で決める。
- 等価直径は `D_eq = sqrt(4 A_c / pi)` でログに出す。
- 触媒粒子径、空隙率、バルク密度、Ergun 係数、粘度は radial 既定ケースと同じ値を使う。

## 主な入力

- `ReactorFeed`
- `ReactorRunConditions`
  - `pressure_kpa`
  - `stage_inlet_temperatures_c`
  - `stage_lengths_m`
  - `total_catalyst_volume_m3`
  - `pellet_diameter_m`
  - `bed_void_fraction`
  - `catalyst_bulk_density_kg_m3`
  - `ergun_a`
  - `ergun_b`
  - `gas_viscosity_pa_s`
  - `interstage_reheater_pressure_drop_pa`
  - `segments_per_stage`
  - `profile_points_per_stage`

## 主な出力

- 出口温度
- 出口圧力
- 出口成分流量
- EB 転化率
- SM 選択率
- 反応器内圧力損失
- 段間再加熱器圧力損失
- 触媒体積
- 触媒質量
- 断面積
- 等価直径
- 各段の温度、圧力、線速、Re、再加熱負荷
- C と H の元素収支誤差
- 出口圧力、圧力正値、Ergun 適用範囲、元素収支の制約判定

## 注意点

PFR の触媒質量は、触媒体積に `catalyst_bulk_density_kg_m3` を掛けてログ用に計算する。現行の反応速度式は体積基準として扱っているため、`catalyst_bulk_density_kg_m3` は反応速度計算そのものには使わない。

同じ触媒体積を PFR と radial に与えると、PFR では出口圧力制約を満たさない場合がある。この場合も計算は中断せず、制約判定を `NG` としてログに残す。
