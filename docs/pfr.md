# PFR 反応器

## 目的

この文書は、既存の多段断熱 PFR 実装の恒久メモである。

## 現在の実装

- 実装は `src/process_sim/reactor/types/staged_adiabatic_pfr.py` の `StagedAdiabaticPfrModel` である。
- 既定ケースは `src/process_sim/reactor/cases/styrene_default.py` に置く。
- CLI では `uv run run-reactor-case --reactor-model pfr` で実行する。
- plant one-pass では `uv run run-plant-once --reactor-model pfr` で PFR を使う。

## モデル

- 反応器は多段断熱 PFR として扱う。
- 各段は軸方向 1 次元で RK4 積分する。
- 圧力損失は考慮しない。
- 圧力は `pressure_kpa` として全段一定で扱う。
- 反応ネットワークはコンテスト由来の 6 反応モデルを使う。
- 反応熱は成分エンタルピーから温度ごとに計算する。
- 段間再加熱は反応器外部で行うとみなし、再加熱負荷だけを計算する。

## 主な入力

- `ReactorFeed`
- `ReactorRunConditions`
  - `pressure_kpa`
  - `stage_inlet_temperatures_c`
  - `stage_lengths_m`
  - `inlet_superficial_velocity_m_per_s`
  - `segments_per_stage`
  - `profile_points_per_stage`

## 主な出力

- 出口温度
- 出口圧力
- 出口成分流量
- EB 転化率
- SM 選択率
- 各段の温度低下、線速、再加熱負荷

## 注意点

PFR は比較用、既存検証用、ラジアルフロー導入前の基準ケースとして残す。主設計の既定モデルはラジアルフロー反応器である。
