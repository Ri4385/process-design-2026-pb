# Reactor

## 目的

この文書は、反応器モデルの恒久的な設計メモとして使う。
現時点の実装状態、設計上の意味、入出力、ログ項目を上書き更新しながら管理する。

## 現在の実装方針

- 反応器サイドは HYSYS を使わず、純 Python で計算する。
- 物性値、反応ネットワーク、共通計算、具体的な反応器型、実行ケースを分離している。
- axial の具体モデルは `src/process_sim/reactor/types/staged_adiabatic_pfr.py` の `StagedAdiabaticPfrModel` である。
- radial の具体モデルは `src/process_sim/reactor/types/staged_adiabatic_radial.py` の `StagedAdiabaticRadialFlowModel` である。
- 既定 axial ケースでは 3 段断熱 PFR として扱う。
- 反応ネットワークは `data/chem_contest.md` の 6 反応モデルを参照している。
- 反応熱は固定値を使わず、化学量論と成分エンタルピーから温度ごとに計算する。
- Ergun 式による触媒層圧力損失と段間再加熱器圧力損失を扱う。
- 熱損失は入れていない。
- 反応器内の半径方向分布は持たず、軸方向 1 次元で扱う。
- 気体は理想気体として扱う。

## ディレクトリ構成

- `src/process_sim/constants/`
  - 物性値、反応ネットワーク、普遍定数を置く。
- `src/process_sim/reactor/core/`
  - 成分順序、流量モデル、反応速度評価、熱力学計算、収支式、積分器を置く。
- `src/process_sim/reactor/types/`
  - 具体的な反応器型を置く。
- `src/process_sim/reactor/cases/`
  - 既定 feed と運転条件を Python 定数として置く。
- `src/process_sim/cli.py`
  - 実行入口と表示整形だけを扱う。

## 採用している反応

`data/chem_contest.md` の 5-2 反応モデルを参照し、次の 6 反応を採用している。

- `EB ⇆ SM + H2`
- `EB -> BZ + C2H4`
- `EB + H2 -> TL + CH4`
- `2H2O + C2H4 -> 2CO + 4H2`
- `H2O + CH4 -> CO + 3H2`
- `H2O + CO -> CO2 + H2`

## モデルの計算内容

- 各成分の分圧を Pa で計算する。
- `chem_contest` に記載されたアレニウス型速度式から、6 反応の反応速度を計算する。
- 主反応は正反応速度と逆反応速度の差を正味速度として扱う。
- 各反応の反応エンタルピーは、成分の標準生成エンタルピーと Cp 積分から温度ごとに計算する。
- 物質収支と断熱熱収支を連立して、各段を軸方向に RK4 で積分する。
- 中間加熱そのものは反応器外で行うとみなし、各段の入口温度を条件として与える。
- 各段の再加熱に必要な熱量は、ログとして別に計算する。

## 入力

- `ReactorFeed`
  - `eb` [kmol/h]
  - `steam` [kmol/h]
  - `styrene` [kmol/h]
  - `hydrogen` [kmol/h]
  - `benzene` [kmol/h]
  - `toluene` [kmol/h]
  - `co2` [kmol/h]
  - `ethylene` [kmol/h]
  - `methane` [kmol/h]
  - `co` [kmol/h]
- `ReactorRunConditions`
  - `pressure_kpa` [kPa]
  - `stage_inlet_temperatures_c` [degC, ...]
  - `inlet_superficial_velocity_m_per_s` [m/s]
  - `stage_ld_ratios` [-, ...]
  - `segments_per_stage` [-]
  - `profile_points_per_stage` [-]

## 出力

- `ReactorResult.outlet`
  - 最終段出口の状態
- `ReactorResult.eb_conversion`
  - EB 転化率
- `ReactorResult.styrene_selectivity`
  - スチレン選択率
- `ReactorResult.log`
  - 反応器ログ

## ログ

- `ReactorRunLog.cross_section_area_m2`
  - 入口線速から逆算した反応器断面積
- `ReactorRunLog.inlet_volumetric_flow_m3_s`
  - 第1段入口の体積流量
- `ReactorRunLog.stage_logs`
  - 各段の入口温度、出口温度、段長、入口線速、出口線速、転化率、選択率、再加熱負荷
- `ReactorRunLog.profile`
  - 軸方向の温度、転化率、選択率、各成分流量の記録点

## 参照ケース

既定ケースは `src/process_sim/reactor/cases/styrene_default.py` に置いている。
CLI はこのケースを読むだけで、feed や運転条件を直接持たない。

- 圧力 `300 kPa abs`
- 各段入口温度 `550, 550, 550 degC`
- 各段 `L/D = 3, 3, 3`
- 入口線速 `2.0 m/s`
- 入口 EB `400 kmol/h`
- 入口 steam `2744 kmol/h`
- 入口不純物
  - `benzene = 2.0 kmol/h`
  - `toluene = 2.0 kmol/h`

## 注意点

- これは設計を前進させるための 6 反応・純 Python モデルであり、最終検証済みの設計値ではない。
- 妥当性確認の基準はまだ確定していない。
- どの基準を正とするかは、手計算、文献値、HYSYS 結果のどれを採用するかを別途決める必要がある。
- 3 反応モデルは現行実装から削除した。
- HYSYS bridge は現行の反応器中核設計から外している。
