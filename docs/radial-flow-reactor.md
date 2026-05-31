# ラジアルフロー反応器

## 目的

この文書は、ラジアルフロー固定床反応器の現行実装メモである。詳細な設計判断は `docs/reports/20260518_01_radial-flow-reactor-design.md` を正とする。

## 現在の実装

- 実装は `src/process_sim/reactor/types/staged_adiabatic_radial.py` の `StagedAdiabaticRadialFlowModel` である。
- 1 基分の計算は `src/process_sim/reactor/types/radial_adiabatic.py` の `RadialAdiabaticReactor` が担当する。
- 既定ケースは `src/process_sim/reactor/cases/styrene_radial_default.py` に置く。
- CLI の既定モデルは radial である。
- `uv run run-reactor-case` は既定で radial を実行する。
- `uv run run-plant-once` は既定で radial を実行する。
- PFR を使う場合は `--reactor-model pfr` を明示する。

## モデル

- 各段を内側流入、外側流出の環状触媒層として扱う。
- 流通断面積は `A_r(r) = 2πrz` とする。
- 中心流路半径は `1.0 m` に固定する。
- 反応器高さは、各段入口空塔速度が `2.0 m/s` となるように各段入口体積流量から段ごとに計算する。
- 反応器半径は、中心流路半径と触媒層厚みの和として扱う。
- 触媒層出口後の流路は未設計とし、寸法へ加算しない。
- 触媒層出口空塔速度は `1.0 m/s` 以上とする。
- 圧力は状態変数として半径方向に積分する。
- 圧力損失は SI 単位で整理した Ergun 式で計算する。
- ガス密度は局所温度、局所圧力、局所組成から理想気体として計算する。
- 質量速度は `G(r) = m_dot(r) / A_r(r)` とする。
- 段間再加熱器圧力損失は 1 回あたり `20 kPa` とする。
- 主設計の多段モデルは 2 段または 3 段のみを許容する。

## 主な入力

- `ReactorFeed`
- `RadialReactorRunConditions`
  - `inlet_pressure_pa`
  - `stage_inlet_temperatures_k`
  - `inlet_superficial_velocity_m_per_s`
  - `center_channel_radius_m`
  - `bed_thicknesses_m`
  - `pellet_diameter_m`
  - `bed_void_fraction`
  - `catalyst_bulk_density_kg_m3`
  - `gas_viscosity_pa_s`
  - `interstage_reheater_pressure_drop_pa`

## 主な出力

- 出口温度
- 出口圧力
- 出口成分流量
- EB 転化率
- SM 選択率
- 反応器内圧力損失
- 段間再加熱器圧力損失
- 触媒体積、触媒質量
- 各段高さ、触媒層外半径、反応器径
- `Re/(1-eps)` の範囲
- C と H の元素収支誤差

## 注意点

混合ガス粘度は現時点では固定値 `2.6e-5 Pa s` として扱う。純成分粘度から混合粘度を推算する実装は未実装である。

触媒層出口後の流路厚みを固定値として加算するかは未確定である。
