# radial・axial 反応器 Pareto front 探索 v2 詳細設計

## 目的

本資料は、SM 選択率と EB 単通反応率を同時に最大化する multi-objective optimization を、radial 反応器と axial 反応器で比較できる形に再設計するための詳細設計である。

axial 反応器は、現行コード上の PFR を指す。図の凡例とファイル名では `axial` を使い、Python module 名では既存実装との整合を優先して `pfr` を使う。

既存の `src/process_sim/optimization/runner/radial_pareto_optuna.py` は、radial 反応器だけを対象にした初期版として残す。v2 は別 runner、別 SQLite storage、別描画 directory とし、初期版の探索結果を混ぜない。

## 前回設計からの変更点

- radial だけでなく axial PFR を探索対象に含める。
- radial 2段、radial 3段、axial 2段、axial 3段を別 study として保存する。
- `scripts/reactor_pareto_v2/` を新設し、比較図はすべてこの directory で生成する。
- runner 内で feed と反応器条件を明示的に作成する。既定ケースを参照しない。
- radial に Peclet 数による一次元押し出し流れ判定と、触媒層出口空塔速度 `1 m/s` 以上の制約を追加する。
- radial の反応器外半径は、中心流路半径、触媒層厚み、外部流路厚みの和として扱う。
- axial PFR は、各段入口空塔速度 `2 m/s` から各段の直径を決め、各段 `L/D` を探索する。
- trial ごとに反応器寸法を必須保存する。

## 維持する既存仕様

v2 でも、初期版 Pareto runner の次の仕様を維持する。

- Optuna の `NSGAIISampler` を使う。
- 2段と3段は探索空間の次元が異なるため study を分ける。
- SQLite storage を使い、中断後に同じ study を再開する。
- 段数ごとに累積目標 trial 数を指定し、不足分だけを追加する。
- 有効 trial 数は `COMPLETE` と `PRUNED` の合計とする。`FAIL` は含めない。
- 制約違反と反応器計算失敗は `optuna.TrialPruned` とする。
- 探索変数、目的値、主要ログ、制約判定、prune 理由を `user_attrs` に保存する。
- runner と描画 script を分ける。描画 script は DB を更新しない。
- SQLite DB と実行ログは Git 管理対象外とし、生成図は Git 管理対象とする。

## ディレクトリ構成

実装時に追加または変更する範囲は次の通りである。

```text
src/process_sim/
  reactor/
    core/
      models.py                         # radial と axial の寸法、速度、Peclet 数ログを追加
      radial_geometry.py                # 外部流路厚みと反応器外半径の計算を追加
    types/
      staged_adiabatic_radial.py        # radial の寸法計算と制約用ログを追加
      staged_adiabatic_pfr.py           # 段別径、段別 L/D、段別長さで計算するよう変更
  optimization/
    reactor/
      parameters.py                     # axial 用の段別 L/D 探索空間を追加
      constraints.py                    # v2 の radial と axial 制約値を追加
    runner/
      reactor_pareto_v2_optuna.py       # 新規。4 study の探索、再開、trial 記録
scripts/
  reactor_pareto_v2/
    plot_pareto_front.py                # 新規。7種類の比較図を生成
    select_best_condition.py            # 新規。条件を満たす trial を表示
    media/
      radial_stage_pareto_front.png
      radial_axial_global_pareto_front.png
      axial_stage_pareto_front.png
      all_stage_pareto_front.png
      radial_all_trials.png
      axial_all_trials.png
      all_trials.png
data/
  optuna/
    reactor_pareto_v2_optuna.db         # v2 専用 SQLite storage
logs/
  reactor_pareto_v2_optuna.log          # v2 専用探索ログ
docs/
  optimization.md                       # 実装後に恒久仕様を反映
  pfr.md                                # 実装後に axial 寸法決定方法を反映
  radial-flow-reactor.md                # 実装後に外部流路と制約を反映
  reports/
    20260531_02_reactor-pareto-v2-design.md
README.md                               # 実装後に directory 概略と実行方法を反映
```

`scripts/reactor_pareto/` は初期版 radial 描画用として残す。v2 の図を同じ directory に入れない。

## Study 設計

study 名は次の4つで固定する。

```text
radial_2stage_selectivity_conversion_v2
radial_3stage_selectivity_conversion_v2
axial_2stage_selectivity_conversion_v2
axial_3stage_selectivity_conversion_v2
```

目的関数の順序は初期版と同じにする。

```python
return result.styrene_selectivity, result.eb_conversion
```

study 作成条件も初期版と同じにする。

```python
directions=("maximize", "maximize")
sampler=NSGAIISampler(
    population_size=50,
    seed=None,
)
```

SQLite storage は次を使う。

```text
sqlite:///data/optuna/reactor_pareto_v2_optuna.db
```

runner 冒頭には、4 study の累積目標 trial 数を明示する。

```python
TARGET_EFFECTIVE_TRIALS_BY_REACTOR_AND_STAGE_COUNT = {
    ("radial", 2): 1300,
    ("radial", 3): 1300,
    ("axial", 2): 1300,
    ("axial", 3): 1300,
}
```

## runner の feed 作成

`reactor_pareto_v2_optuna.py` は、`DEFAULT_STYRENE_FEED`、`DEFAULT_STYRENE_REACTOR_CASE`、`DEFAULT_STYRENE_RADIAL_REACTOR_CASE` を import しない。

runner 内に探索専用の基準 feed を明示する。

```python
PARETO_V2_BASE_FEED = ReactorFeed(
    eb=...,
    steam=...,
    styrene=...,
    hydrogen=...,
    benzene=...,
    toluene=...,
    co2=...,
    ethylene=...,
    methane=...,
    co=...,
)
```

Steam 流量だけは trial の `steam_to_eb_ratio` から作る。

```text
steam = PARETO_V2_BASE_FEED.eb × steam_to_eb_ratio
```

触媒粒子径、空隙率、触媒バルク密度、Ergun 係数、粘度、段間再加熱器圧力損失、積分分割数、profile 点数も runner 内の探索専用定数として明示する。既定ケースを `replace()` して候補条件を作らない。

feed の数値は、実装時に採用値を明示し、`docs/optimization.md` に同じ値と採用理由を記録する。

## 共通探索条件

radial と axial で、比較可能な条件は揃える。

| 項目 | radial | axial PFR |
|---|---|---|
| 目的値 | SM 選択率、EB 単通反応率 | SM 選択率、EB 単通反応率 |
| 段数 | 2段、3段 | 2段、3段 |
| 各段入口温度 | 各段独立に探索 | 各段独立に探索 |
| 反応器列入口圧力 | 探索 | 探索 |
| Steam/EB 比 | 探索 | 探索 |
| 段間再加熱器圧損 | 同じ固定値 | 同じ固定値 |
| 触媒物性と Ergun 係数 | 同じ値 | 同じ値 |
| 各段入口空塔速度 | `2 m/s` 固定 | `2 m/s` 固定 |

圧力探索範囲は、入口圧力上限を約 `3 atm` とする意図に合わせて radial と axial で揃える。ただし、厳密な上限値は未確定事項とする。

## radial 反応器仕様

### 探索変数

radial では次を探索する。

| 項目 | 扱い |
|---|---|
| 各段入口温度 | 各段独立に探索する。 |
| 反応器列入口圧力 | 探索する。 |
| Steam/EB 比 | 探索する。 |
| 各段触媒層厚み | 各段独立に探索する。 |
| 段数 | 2段 study と3段 study に分ける。 |

各段入口空塔速度は `2 m/s` に固定し、探索変数にしない。現行実装と同様に、各段入口流量、温度、圧力から中心流路半径を求める。

```text
Q_in,i = F_total,in,i R T_in,i / P_in,i
A_in,i = Q_in,i / 2
r_center,i = A_in,i / (2 π H)
```

ここで `H` は反応器高さである。

### 外部流路

触媒層出口の外側に、完全な軸流れを仮定した環状の外部流路を置く。外部流路の軸方向空塔速度が `2 m/s` となるように流路厚みを決める。

```text
r_bed_outer,i = r_center,i + bed_thickness_i
Q_out,i = F_total,out,i R T_out,i / P_out,i
A_outer_channel,i = Q_out,i / 2
r_reactor,i = sqrt(r_bed_outer,i^2 + A_outer_channel,i / π)
outer_channel_thickness_i = r_reactor,i - r_bed_outer,i
```

最終的な関係は次である。

```text
反応器半径 = 中心流路半径 + 触媒厚み + 外部流路厚み
```

現行の `ReactorStageLog.outer_radius_m` は触媒層外半径を表している。v2 では意味を変更せず、次のフィールドを追加する。

```python
bed_outer_radius_m: float | None
outer_channel_thickness_m: float | None
reactor_outer_radius_m: float | None
reactor_diameter_m: float | None
```

既存 `outer_radius_m` は後方互換のため残し、触媒層外半径として扱う。経済収支で反応器胴径を使う場合は、`reactor_outer_radius_m` を優先するよう更新する。

### radial 制約

radial では既存制約に加えて、少なくとも次を判定する。

- 各段の触媒層出口空塔速度が `1 m/s` 以上である。
- 一次元押し出し流れとして扱える Peclet 数条件を満たす。
- 外部流路厚みと反応器外半径が正値である。

触媒層出口空塔速度は、現行の `ReactorStageLog.outlet_superficial_velocity_m_per_s` を使って判定できる。

```text
radial_bed_outlet_velocity_ok =
    all(stage.outlet_superficial_velocity_m_per_s >= 1.0)
```

Peclet 数は、採用する相関式、代表長さ、分散係数、合格閾値が現時点で決まっていない。値を仮定して実装せず、実装前に根拠を確定する。モデル上は段別 Peclet 数と全段判定を保存できるようにする。

```python
peclet_number: float | None
peclet_ok: bool | None
radial_bed_outlet_velocity_ok: bool | None
```

Peclet 数条件が確定するまでは、v2 の正式探索を開始しない。

## axial PFR 仕様

### 寸法決定方法

現行 `StagedAdiabaticPfrModel` は、総触媒体積と総段長から全段共通断面積を決める。

```text
A = V_cat,total / sum(L_i)
```

この方法では、各段入口空塔速度を `2 m/s` に固定しながら各段 `L/D` を探索できない。v2 では、各段を独立した反応器胴として扱い、段ごとに断面積、直径、長さを決める。

```text
Q_in,i = F_total,in,i R T_in,i / P_in,i
A_i = Q_in,i / 2
D_i = sqrt(4 A_i / π)
L_i = (L/D)_i × D_i
V_cat,i = A_i × L_i
```

各段入口では空塔速度が定義上 `2 m/s` となる。段内では反応、温度変化、圧力損失によって空塔速度が変わるため、profile 全体で制約を判定する。

### 探索変数

axial PFR では次を探索する。

| 項目 | 扱い |
|---|---|
| 各段入口温度 | 各段独立に探索する。 |
| 各段 `L/D` | 各段独立に `2–4` で探索する。 |
| 反応器列入口圧力 | 探索する。上限は約 `3 atm` とする。 |
| Steam/EB 比 | radial と揃えて探索する。 |
| 段数 | 2段 study と3段 study に分ける。 |

現行 `ReactorRunConditions.total_catalyst_volume_m3` は、v2 axial PFR では入力ではなく段別寸法から決まる結果になる。既存 CLI と既定ケースを壊さないため、現行 PFR 実行経路は残す。v2 用には段別 `L/D` と入口空塔速度を受ける新しい条件モデルまたは明示的な別実行経路を追加する。

### axial 制約

axial PFR では少なくとも次を判定する。

- 各段長が `10 m` 以下である。
- 各段 profile 上の空塔速度が `1–3 m/s` の範囲にある。
- 既存の圧力正値、出口圧力、元素収支、Ergun 適用範囲を満たす。
- SM 生成量が正である。

段長 `10 m` 以下は、各段に適用する設計とする。合計長にも適用するかは未確定事項とする。

## ログと trial 属性

簡易経済収支計算へ接続できるよう、反応器寸法は必須ログとする。`COMPLETE` trial では、共通値に加えて段別寸法を `user_attrs` に保存する。

### 共通保存項目

```text
reactor_type
stage_count
eb_conversion
styrene_selectivity
outlet_pressure_kpa
reactor_pressure_drop_kpa
reheat_pressure_drop_kpa
total_pressure_drop_kpa
total_catalyst_volume_m3
total_catalyst_mass_kg
pressure_positive_ok
atom_balance_ok
ergun_range_ok
outlet_pressure_ok
prune_reason
```

### radial 段別保存項目

```text
stage_{i}_center_channel_radius_m
stage_{i}_bed_thickness_m
stage_{i}_bed_outer_radius_m
stage_{i}_outer_channel_thickness_m
stage_{i}_reactor_outer_radius_m
stage_{i}_reactor_diameter_m
stage_{i}_bed_height_m
stage_{i}_catalyst_volume_m3
stage_{i}_bed_inlet_velocity_m_per_s
stage_{i}_bed_outlet_velocity_m_per_s
stage_{i}_outer_channel_velocity_m_per_s
stage_{i}_peclet_number
radial_bed_outlet_velocity_ok
peclet_ok
```

### axial 段別保存項目

```text
stage_{i}_ld_ratio
stage_{i}_cross_section_area_m2
stage_{i}_diameter_m
stage_{i}_length_m
stage_{i}_catalyst_volume_m3
stage_{i}_inlet_velocity_m_per_s
stage_{i}_outlet_velocity_m_per_s
stage_{i}_min_velocity_m_per_s
stage_{i}_max_velocity_m_per_s
length_ok
velocity_range_ok
```

ログファイルにも、完了 trial では目的値、探索条件、主要制約値、各段寸法を残す。prune 時には、判定できた範囲の寸法と prune 理由を残す。

## 描画仕様

`scripts/reactor_pareto_v2/plot_pareto_front.py` は、4 study の `COMPLETE` trial だけを読み、次の7枚を生成する。

| 出力ファイル | 内容 |
|---|---|
| `radial_stage_pareto_front.png` | radial 2段、radial 3段の段数別 Pareto front 2本 |
| `radial_axial_global_pareto_front.png` | radial 全 trial の global Pareto front、axial 全 trial の global Pareto front 2本 |
| `axial_stage_pareto_front.png` | axial 2段、axial 3段の段数別 Pareto front 2本 |
| `all_stage_pareto_front.png` | radial 2段、radial 3段、axial 2段、axial 3段の段数別 Pareto front 4本 |
| `radial_all_trials.png` | radial 2段、radial 3段の全完了 trial 2系列 |
| `axial_all_trials.png` | axial 2段、axial 3段の全完了 trial 2系列 |
| `all_trials.png` | radial 2段、radial 3段、axial 2段、axial 3段の全完了 trial 4系列 |

横軸と縦軸は初期版と同じにする。

```text
x: EB single-pass conversion [%]
y: SM selectivity [%]
```

軸目盛は内向きとし、上下左右へ表示する。目盛線とタイトルは表示しない。4系列を重ねる図では、reactor type と段数を凡例で区別する。

`radial_axial_global_pareto_front.png` の2本は、次の定義で計算する。

- radial global Pareto front: radial 2段と radial 3段を合わせた非支配点
- axial global Pareto front: axial 2段と axial 3段を合わせた非支配点

4種類すべてを合わせた単一 global Pareto front は、今回の必須図には含めない。

## `select_best_condition.py`

初期版と同じく、指定 EB 単通反応率以上で SM 選択率が最大の trial を表示する。v2 では4 study ごとの最良条件、radial 全体、axial 全体、全体の最良条件を表示する。

表示には探索変数だけでなく、段別反応器寸法と制約判定を含める。反応器再計算は行わず、SQLite storage の保存値だけを使う。

## 実行形態

探索 runner と描画 script は分ける。

```powershell
uv run python -m process_sim.optimization.runner.reactor_pareto_v2_optuna
uv run python scripts/reactor_pareto_v2/plot_pareto_front.py
uv run python scripts/reactor_pareto_v2/select_best_condition.py
```

runner は Python 反応器計算だけを行い、HYSYS を起動しない。

## ファイル責務

### `src/process_sim/reactor/core/models.py`

- radial の触媒層外半径と反応器外半径を区別するログ項目を追加する。
- axial の段別断面積、直径、段長、`L/D`、profile 上の速度範囲を保存できる項目を追加する。
- Peclet 数と追加制約判定を保存できる項目を追加する。

### `src/process_sim/reactor/core/radial_geometry.py`

- 触媒層外半径を返す。
- 外部流路断面積から外部流路厚みと反応器外半径を計算する。
- 幾何条件が正値であることを検証する。

### `src/process_sim/reactor/types/staged_adiabatic_radial.py`

- 各段反応後の体積流量から外部流路厚みと反応器外半径を計算する。
- 触媒層出口空塔速度制約を集約する。
- 確定後の Peclet 数計算と判定を集約する。

### `src/process_sim/reactor/types/staged_adiabatic_pfr.py`

- v2 axial 経路では、各段入口体積流量と入口空塔速度 `2 m/s` から段別断面積を計算する。
- 各段 `L/D` と段別直径から段長を計算する。
- 各段で `PfrAdiabaticReactor.run()` を呼び、段別寸法、速度範囲、制約判定を集約する。
- 現行 CLI 用の既存 PFR 経路は維持する。

### `src/process_sim/optimization/runner/reactor_pareto_v2_optuna.py`

- 探索専用 feed と固定条件を runner 内で明示的に作る。
- radial 2段、radial 3段、axial 2段、axial 3段の study を作成または再開する。
- 制約違反を prune する。
- 寸法を含む trial 属性とログを保存する。
- 初期版 runner の DB とログを変更しない。

### `scripts/reactor_pareto_v2/plot_pareto_front.py`

- v2 SQLite storage を読み、7種類の図を生成する。
- 描画用の trial 値は `pydantic.BaseModel` に変換して扱う。
- DB の書き込みと反応器再計算を行わない。

### `scripts/reactor_pareto_v2/select_best_condition.py`

- v2 SQLite storage を読み、指定単通反応率以上の条件を表示する。
- DB の書き込みと反応器再計算を行わない。

## 検証方針

反応器モデルと runner の変更を優先して確認する。`scripts/` に対するテストは作らない。

- runner が既定ケースを import せず、feed と固定条件を明示作成する。
- radial の各段で `reactor_outer_radius_m = center_channel_radius_m + bed_thickness_m + outer_channel_thickness_m` が成り立つ。
- radial の外部流路速度が数値誤差の範囲で `2 m/s` になる。
- radial の触媒層出口空塔速度が `1 m/s` 未満の候補は prune される。
- Peclet 数の定義確定後、radial の Peclet 数違反候補が prune される。
- axial の各段入口空塔速度が数値誤差の範囲で `2 m/s` になる。
- axial の各段で `2 <= L/D <= 4` が成り立つ。
- axial の段長が `10 m` を超える候補は prune される。
- axial の profile 上で空塔速度が `1–3 m/s` を外れる候補は prune される。
- 4 study が別名で SQLite storage に作られ、再実行時に不足 trial だけが追加される。
- `COMPLETE` trial に段別反応器寸法が保存される。
- 既存の PFR と radial の収束計算経路が動作する。

`uv run` と `ruff` の実行は、リポジトリ方針に従いユーザーが行う。

## 採用しない案

### 初期版 radial Pareto runner を直接拡張する

採用しない。初期版の SQLite storage と生成図を残し、v2 の radial・axial 比較結果と混同しないためである。

### axial PFR で全段共通径を使う

採用しない。各段入口で空塔速度 `2 m/s` とする要件に対し、段間で流量、温度、圧力が変わるため、全段共通径では整合しない。

### axial PFR の総触媒体積を探索入力にする

採用しない。v2 では段別入口速度、段別直径、段別 `L/D` から段別触媒体積が決まる。総触媒体積は結果として記録する。

### radial の触媒層外半径を反応器外半径として扱う

採用しない。外部流路を追加するため、反応器胴径の見積もりが不足する。

## 未確定事項

- Pareto v2 専用 feed の各成分流量を確定する必要がある。runner 内に明示し、既定ケースから参照しない。
- 入口圧力上限を約 `3 atm` とする場合の厳密な値を確定する必要がある。`300 kPa abs`、`303.975 kPa abs`、その他の丸め値のどれを採用するか決める。
- radial の Peclet 数について、相関式、代表長さ、分散係数、合格閾値を確定する必要がある。未確定のまま値を仮定しない。
- radial の Peclet 数判定を触媒層内の各 profile 点で行うか、段別の代表値で行うかを確定する必要がある。
- radial の外部流路は軸方向流れとして設計するが、外部流路の圧力損失を今回の反応器圧損へ含めるかを確定する必要がある。
- radial の反応器高さ `H` を固定値とするか、探索変数にするかを確定する必要がある。
- axial の `L <= 10 m` 制約を各段長だけに適用するか、全段合計長にも適用するかを確定する必要がある。
- axial の入口圧力下限を radial と完全に共通化するか、段数別に設定するかを確定する必要がある。
