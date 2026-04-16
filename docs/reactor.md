# Reactor

## 目的

この文書は、反応器モデルの恒久的な設計メモとして使う。
一時的な作業記録ではなく、現時点での実装状態、入出力、出力の意味を上書きしながら更新する。

## 現在の実装範囲

- 現在実装されているのは、`src/process_sim/reactor/simulator.py` の `StyreneReactorModel` である。
- これは Python 側の簡易 PFR モデルである。
- HYSYS の内部反応器を直接操作しているのではなく、`src/process_sim/reactor/hysys_bridge.py` の `ReactorService` がタグ値を読み書きして Python モデルを 1 回実行する構成である。
- 入口条件として使っているのは `eb`、`steam`、`pressure_kpa`、`temperature_c` である。
- `ReactorService.run_once()` では、入口の `styrene`、`hydrogen`、`benzene`、`toluene`、`co2` は 0.0 固定で与えている。

## モデルの計算内容

- 温度からアレニウス式で `k11`、`k12`、`k2`、`k3` を計算する。
- 圧力と各成分流量から、`p_eb`、`p_styrene`、`p_h2` を全圧基準の分圧として計算する。
- 主反応速度は `r1 = k11 * p_eb - k12 * p_styrene * p_h2` である。
- 主反応は可逆として扱っており、`r1 < 0` のときは逆反応を表す。
- 副反応速度は `r2 = k2 * p_eb`、`r3 = k3 * p_eb` を 0 以上に制限している。
- 反応器体積を `steps` 分割し、各ステップで物質収支を更新している。
- 各ステップでは `eb`、`steam`、`styrene`、`hydrogen` が負にならないように `feasible_scale` で反応速度を縮小している。

## データモデル

### 入力

- `ReactorFeed`
  - `eb` [kmol/h]
  - `steam` [kmol/h]
  - `styrene` [kmol/h]
  - `hydrogen` [kmol/h]
  - `benzene` [kmol/h]
  - `toluene` [kmol/h]
  - `co2` [kmol/h]
- `ReactorRunConditions`
  - `pressure_kpa` [kPa]
  - `temperature_c` [degC]
  - `reactor_volume_m3` [m^3]
  - `steps` [-]

### 出力

- `ReactorResult.outlet`
  - 反応器出口の各成分流量を持つ。
- `ReactorResult.eb_conversion`
  - `max(feed.eb - outlet.eb, 0.0) / feed.eb`
  - EB 転化率である。
- `ReactorResult.styrene_selectivity`
  - `(outlet.styrene - feed.styrene) / converted`
  - EB の正味消費量に対するスチレン生成量である。
  - 現在の実装では 0 未満にならないようにして返している。

## タグと意味

- `RCTR_EB_IN`
  - 反応器入口の EB 流量 [kmol/h]
- `RCTR_H2O_IN`
  - 反応器入口の水蒸気流量 [kmol/h]
- `RCTR_P_IN`
  - 反応器入口圧力 [kPa]
- `RCTR_T_IN`
  - 反応器入口温度 [degC]
- `RCTR_EB_OUT`
  - 反応器出口の EB 流量 [kmol/h]
- `RCTR_H2O_OUT`
  - 反応器出口の水蒸気流量 [kmol/h]
- `RCTR_STY_OUT`
  - 反応器出口のスチレン流量 [kmol/h]
- `RCTR_H2_OUT`
  - 反応器出口の水素流量 [kmol/h]
- `RCTR_BZ_OUT`
  - 反応器出口のベンゼン流量 [kmol/h]
- `RCTR_TOL_OUT`
  - 反応器出口のトルエン流量 [kmol/h]
- `RCTR_CO2_OUT`
  - 反応器出口の二酸化炭素流量 [kmol/h]
- `RCTR_X_EB`
  - EB 転化率 [-]

## 出力の読み方

既定条件は以下である。

- EB 入口流量 `700.0 kmol/h`
- 水蒸気入口流量 `3500.0 kmol/h`
- 圧力 `152.0 kPa`
- 温度 `600.0 degC`
- 反応器体積 `15.0 m^3`
- 分割数 `200`

この条件で現在のコードを実行すると、以下の値が出る。

- `RCTR_EB_OUT = 556.960856277843`
- `RCTR_H2O_OUT = 3459.9428787117663`
- `RCTR_STY_OUT = 127.60338851060494`
- `RCTR_H2_OUT = 187.68907044295256`
- `RCTR_BZ_OUT = 4.592805432563649`
- `RCTR_TOL_OUT = 10.842949778988588`
- `RCTR_CO2_OUT = 20.02856064411589`
- `RCTR_X_EB = 0.20434163388879564`

意味は次の通りである。

- `RCTR_*_OUT`
  - 各成分の出口流量である。
- `RCTR_X_EB`
  - EB の転化率である。
- `RCTR_EB_OUT`
  - 入口の EB のうち未反応で残った量である。
- `RCTR_STY_OUT`
  - 生成したスチレンの出口流量である。
- `RCTR_H2_OUT`
  - 主反応と副反応で発生した水素の出口流量である。
- `RCTR_BZ_OUT`
  - 副反応 `r2` で生成したベンゼンの出口流量である。
- `RCTR_TOL_OUT`
  - 副反応 `r3` で生成したトルエンの出口流量である。
- `RCTR_CO2_OUT`
  - 副反応で生成した二酸化炭素の出口流量である。
- `RCTR_H2O_OUT`
  - 副反応で消費された後の水蒸気流量である。

## 注意点

- これらの値は現在の Python モデルの出力であり、妥当性確認済みの設計値ではない。
- 手計算、文献値、HYSYS 結果のどれを基準に検証するかは、まだ確定していない。
- `ReactorService` 経由では入口の生成物側成分を 0.0 固定で与えているため、リサイクルや入口生成物同伴の影響はまだ表現していない。
- 圧力降下、熱収支、触媒劣化、平衡の独立検証は、コード上ではまだ扱っていない。
- `styrene_selectivity` は計算されているが、現在の HYSYS タグ出力には接続されていない。

## 更新ルール

- 反応器の恒久仕様はこのファイルを上書き更新する。
- その時点の一時的な試行錯誤や作業メモは `docs/reports/` に書く。
