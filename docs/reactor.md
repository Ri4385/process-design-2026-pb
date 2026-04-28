# Reactor

## 目的

この文書は、反応器モデルの恒久的な設計メモとして使う。
現時点の実装状態、設計上の意味、入出力、ログ項目を上書き更新しながら管理する。

## 現在の実装方針

- 反応器サイドは HYSYS を使わず、純 Python で計算する。
- モデル本体は `src/process_sim/reactor/simulator.py` の `StyreneReactorModel` である。
- 採用している構成は 3 段断熱 PFR であり、各段の入口で中間加熱されたものとして計算する。
- 現時点では、`data/report_md/report_7.md` で使われている 3 反応の速度式を採用している。
- 圧力損失は入れていない。
- 熱損失は入れていない。
- 反応器内の半径方向分布は持たず、軸方向 1 次元で扱う。
- 気体は理想気体として扱う。

## 採用している反応

- 主反応
  - `EB ⇆ SM + H2`
- 副反応
  - `EB + 4H2O -> BZ + 2CO2 + 6H2`
  - `EB + 2H2O -> TL + CO2 + 3H2`

## モデルの計算内容

- 各段の入口温度からアレニウス式で `k11`、`k12`、`k2`、`k3` を計算する。
- 各成分の分圧から反応速度を求める。
- 物質収支と断熱熱収支を連立して、各段を軸方向に積分する。
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
  - `stage_inlet_temperatures_c` [degC, degC, degC]
  - `stage_lengths_m` [m, m, m]
  - `inlet_superficial_velocity_m_per_s` [m/s]
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

ログ不足を避けるため、現在は以下を返す。

- `ReactorRunLog.cross_section_area_m2`
  - 入口線速から逆算した反応器断面積
- `ReactorRunLog.inlet_volumetric_flow_m3_s`
  - 第1段入口の体積流量
- `ReactorRunLog.stage_logs`
  - 各段の入口温度、出口温度、段長、入口線速、出口線速、転化率、選択率、再加熱負荷
- `ReactorRunLog.profile`
  - 軸方向の温度、転化率、選択率、各成分流量の記録点

CLI の既定出力は、生の JSON ではなく人間向けのテキストログにしている。
見る順番は次の通りである。

- `全体サマリー`
  - 最終出口温度、EB転化率、スチレン選択率を確認する
- `出口流量`
  - 最終的にどの成分が何 kmol/h 出ているかを確認する
- `入口から出口までの差分`
  - 反応器列全体で、EB や Steam がどれだけ減り、Styrene や副生成物がどれだけ増えたかを見る
- `各段ログ`
  - 各段での温度低下、線速変化、段ごとの転化率と選択率、次段に入る前の再加熱負荷を確認する
  - さらに各段での成分流量差分を出し、段内で何が増減したかを読む

生の構造化データが必要な場合は、CLI の `--json` オプションで従来どおり JSON を出力できる。

## 参照ケース

CLI の既定値は、`data/report_md/report_7.md` の 3 段断熱反応器の最適化結果を参照したケースである。

- 圧力 `101.325 kPa`
- 各段入口温度 `545.4, 571.0, 605.9 degC`
- 各段長 `3.09, 3.09, 3.09 m`
- 入口線速 `1.93 m/s`
- 入口 EB `605.9 kmol/h`
- 入口 steam `3029.5 kmol/h`
- 入口不純物
  - `styrene = 0.0606 kmol/h`
  - `benzene = 0.0606 kmol/h`
  - `toluene = 0.0606 kmol/h`

この参照ケースで現在のコードを実行すると、概ね次の傾向になる。

- 第1段で大きく温度が低下する
- 第2段、第3段でも断熱的に温度が低下する
- 転化率は段ごとに増加する
- 選択率は段が進むほどやや低下する
- 再加熱負荷は段間ログで確認できる

## 注意点

- これは設計を前進させるための 3 段断熱・純 Python モデルであり、最終検証済みの設計値ではない。
- 妥当性確認の基準はまだ確定していない。
- どの基準を正とするかは、手計算、文献値、HYSYS 結果のどれを採用するかを別途決める必要がある。
- 6 反応の詳細モデルや圧力損失モデルは、現時点では未採用である。
- HYSYS bridge は現行の反応器中核設計から外している。
