# 全体最適化 Optuna 出力設計 v1

## 目的

全体最適化 v1 の script を作る前に、Optuna 探索結果として保存・描画すべき値を整理する。

本書で扱うのは、探索の妥当性、探索空間内での傾向、採用条件の位置を示すための出力である。経済収支の詳細比較、コスト内訳、T-Q stream、utility 内訳は、既存の `plant/cost/` と `fast-plant-convergence-cost` で出せるため、本書の主対象にはしない。

## 背景

既存の反応器 Pareto front は、SM 選択率と EB 単通反応率を目的値にしている。しかし、Pareto front 上の条件は分離コストや recycle、utility、HYSYS 分離系の影響を直接評価していない。そのため、反応器 Pareto front をそのまま全体最適候補とは扱わない。

全体最適化 v1 では、反応器条件を探索し、固定された HYSYS 分離系へ接続したうえで、収束後の全体プラント年収支を目的関数として評価する。つまり、主張したいことは「反応器単体の Pareto 最良」ではなく、「固定分離系に接続したときの全体経済目的関数で見た最適条件」である。

## 既存 runner との整合

既存 runner の使い分けは次の通りである。

| runner | 目的 | 保存形式 | 備考 |
|---|---|---|---|
| `radial_simple_optuna.py` | 反応器単体に近い簡易利益最大化 | メモリ上の study とログ | `TPESampler`、2段と3段を別 study |
| `radial_fast_plant_optuna.py` | HYSYS plant 収束後の簡易経済評価 | メモリ上の study とログ | `TPESampler`、1 trial ごとに HYSYS session を開閉 |
| `reactor_pareto_v2_optuna.py` | radial・axial の反応器 Pareto 探索 | SQLite storage | `NSGAIISampler`、累積 trial 数で再開可能 |
| `scripts/reactor_pareto_v2/plot_pareto_front.py` | Pareto v2 の描画 | PNG | runner と描画を分離 |

全体最適化 v1 は、評価内容としては `radial_fast_plant_optuna.py` の後継に近い。一方で、HYSYS を含む trial は重く、途中停止と再開が必要になりやすい。そのため、保存・再開・描画の運用は `reactor_pareto_v2_optuna.py` と同じく SQLite storage と描画 script 分離を採用する。

## v1 の最適化対象

v1 では蒸留塔、デカンターなどの分離器操作条件は動かさない。

探索対象は、radial 反応器と axial PFR の両方を定義する。ただし初期実行では axial の trial 数を 0 とし、radial だけを実行する。

| 項目 | 扱い |
|---|---|
| 段数 | 2段 study、3段 study に分ける |
| 各段入口温度 | 探索変数 |
| 反応器入口圧力 | 探索変数 |
| Steam/EB 比 | 探索変数。`FeedTuningOptions.initial_guess_policy` にも反映する |
| 各段触媒層厚み | 探索変数 |
| fresh EB、fresh H2O | 目標 SM 生産量と recycle 収束から決まる従属値 |
| EB recycle、H2O recycle | HYSYS 分離系と収束計算から決まる従属値 |
| 蒸留塔段数、還流比、デカンター温度 | 固定 |

radial の初期探索範囲は、既存の温度、Steam/EB 比、触媒層厚み範囲に合わせる。ただし入口圧力の下限は、反応器列出口で `60 kPa abs` 以上を保証するように、段間再加熱器圧損を足して設定する。

```text
inlet_pressure_lower_kpa_abs = 60 + (stage_count - 1) * 20
```

ここで、反応器列出口 `60 kPa abs` は、後段熱交換器で `10 kPa` 低下してもデカンター入口で `50 kPa abs` 以上を保つための下限である。段間再加熱器圧損は既存条件に合わせて 1 基あたり `20 kPa` とする。

| 変数 | 2段 radial | 3段 radial | 備考 |
|---|---:|---:|---|
| 第1段入口温度 | 550 から 650 ℃ | 550 から 650 ℃ | 各段独立に探索する |
| 第2段入口温度 | 550 から 650 ℃ | 550 から 650 ℃ | 各段独立に探索する |
| 第3段入口温度 | - | 550 から 650 ℃ | 3段 study のみ |
| 反応器入口圧力 | 80 から 200 kPa abs | 100 から 200 kPa abs | 出口 60 kPa abs と段間圧損から決める |
| Steam/EB 比 | 5 から 11 mol/mol | 5 から 11 mol/mol | `FeedTuningOptions.initial_guess_policy` にも渡す |
| 第1段触媒層厚み | 0.3 から 1.2 m | 0.3 から 1.2 m | 各段独立に探索する |
| 第2段触媒層厚み | 0.3 から 1.2 m | 0.3 から 1.2 m | 各段独立に探索する |
| 第3段触媒層厚み | - | 0.3 から 1.2 m | 3段 study のみ |

反応器入口空塔速度は `2.0 m/s` 固定とする。fresh EB 流量は探索変数にしない。目標 SM 生産量に対する production target と recycle convergence の中で決まる従属値として扱う。

axial PFR の探索範囲は、Pareto v2 の axial 探索範囲に合わせる。

| 変数 | 2段 axial | 3段 axial | 備考 |
|---|---:|---:|---|
| 第1段入口温度 | 550 から 650 ℃ | 550 から 650 ℃ | 各段独立に探索する |
| 第2段入口温度 | 550 から 650 ℃ | 550 から 650 ℃ | 各段独立に探索する |
| 第3段入口温度 | - | 550 から 650 ℃ | 3段 study のみ |
| 反応器入口圧力 | 80 から 300 kPa abs | 100 から 300 kPa abs | 出口 60 kPa abs と段間圧損から決める |
| Steam/EB 比 | 5 から 11 mol/mol | 5 から 11 mol/mol | `FeedTuningOptions.initial_guess_policy` にも渡す |
| 第1段 L/D | 0.2 から 1.0 | 0.2 から 1.0 | 各段独立に探索する |
| 第2段 L/D | 0.2 から 1.0 | 0.2 から 1.0 | 各段独立に探索する |
| 第3段 L/D | - | 0.2 から 1.0 | 3段 study のみ |

axial PFR の入口空塔速度も `2.0 m/s` 固定とする。v1 初期実装では study 定義だけ用意し、target trial 数を 0 にする。

## 評価フロー

1 trial の処理は次とする。

```text
Optuna trial
  -> RadialReactorCandidate
  -> RadialReactorCase
  -> FeedTuningOptions
  -> OpenHysysPlantRunner
  -> run_production_target_convergence()
  -> build_inlet_control_plan()
  -> apply_post_convergence_controls()
  -> read_process_equipment()
  -> evaluate_whole_plant_cost()
  -> annual_profit_yen_per_year を objective として返す
```

`radial_fast_plant_optuna.py` と異なり、v1 では `plant_reactor_economic_breakdown()` ではなく、`plant/cost/evaluation.py` の `evaluate_whole_plant_cost()` を使う。

収束後の入口 stream 書き込みは、既存の `fast_convergence_cost.py` と同じく `build_inlet_control_plan()` と `apply_post_convergence_controls()` を使う。

## Study 設計

単目的最大化とする。

```text
direction = maximize
objective = WholePlantCostResult.annual_profit_yen_per_year
```

study 名は次を候補とする。

```text
radial_2stage_whole_plant_profit_v1
radial_3stage_whole_plant_profit_v1
axial_2stage_whole_plant_profit_v1
axial_3stage_whole_plant_profit_v1
```

SQLite storage は次とする。

```text
data/optuna/whole_plant_optuna_v1.db
```

既存の Pareto v2 と同じく、累積目標 trial 数を script 冒頭の定数で管理する。

```python
TARGET_EFFECTIVE_TRIALS_BY_STUDY = {
    "radial_2stage_whole_plant_profit_v1": 50,
    "radial_3stage_whole_plant_profit_v1": 50,
    "axial_2stage_whole_plant_profit_v1": 0,
    "axial_3stage_whole_plant_profit_v1": 0,
}
```

HYSYS を含むため、初期値は小さめにする。まず radial 2段と3段を各 50 trial 実行し、探索結果を見て増やす。

sampler は初期実装では `TPESampler(seed=42)` を使う。単目的であり、既存の `radial_simple_optuna.py` と `radial_fast_plant_optuna.py` が `SEED = 42` を使っているためである。Pareto v2 は `SEED = None` だが、これは多目的探索で全 trial 数も大きい別用途として扱う。

## 保存する trial 属性

描画 script が HYSYS や反応器再計算を行わずに済むよう、完了 trial には必要な値を `user_attrs` に保存する。

### 探索条件

```text
reactor_type
stage_count
stage_1_temperature_c
stage_2_temperature_c
stage_3_temperature_c
inlet_pressure_kpa_abs
steam_to_eb_ratio
stage_1_bed_thickness_m
stage_2_bed_thickness_m
stage_3_bed_thickness_m
```

`trial.params` からも読めるが、表出力を安定させるため主要条件は `user_attrs` にも残してよい。

### 反応器結果

```text
eb_conversion
styrene_selectivity
outlet_pressure_kpa
total_catalyst_volume_m3
total_catalyst_mass_kg
reactor_pressure_drop_kpa
total_pressure_drop_kpa
```

### plant 収束後の主要値

```text
sm_product_kmol_h
fresh_eb_kmol_h
fresh_h2o_kmol_h
eb_recycle_kmol_h
h2o_recycle_kmol_h
offgas_total_kmol_h
```

ここでは詳細な stream 全成分は保存しない。詳細確認は既存の convergence summary と cost report に任せる。

### 目的関数まわりの要約値

```text
annual_profit_yen_per_year
revenue_yen_per_year
raw_material_yen_per_year
annualized_equipment_yen_per_year
utility_yen_per_year
fixed_operating_yen_per_year
heat_recovery_duty_kw
```

これらは新しい経済収支比較図を作るためではなく、top trials 表と探索傾向確認に使う。

### 失敗 trial

pruned trial には少なくとも次を保存する。

```text
prune_reason
reactor_type
stage_count
```

候補条件を生成できた後に失敗した場合は、探索変数も保存する。

## 出力ファイル

runner と描画を分離する。

```text
src/process_sim/optimization/runner/
  whole_plant_optuna_v1.py

scripts/whole_plant_optuna_v1/
  plot_results.py
  media/
  results/

data/optuna/
  whole_plant_optuna_v1.db

logs/
  whole_plant_optuna_v1.log
```

`scripts/whole_plant_optuna_v1/media/` には PNG、`scripts/whole_plant_optuna_v1/results/` には CSV または Markdown を置く。

## 必須図

初期実装で作る図は多くしすぎない。最低限は次の5つとする。

### 1. best objective history

```text
best_objective_history.png
```

横軸を trial number、縦軸をその時点までの best `annual_profit_yen_per_year` とする。

探索が進むにつれて目的関数が改善しているか、頭打ちになっているかを見るための図である。

### 2. objective trial scatter

```text
objective_trials.png
```

横軸を trial number、縦軸を各 trial の `annual_profit_yen_per_year` とする。study が複数ある場合は、2段と3段を色で分ける。

best history だけでは、悪い条件やばらつきが見えないため、全 trial の散布図も出す。

### 3. parameter importance

```text
parameter_importance.png
```

Optuna の `get_param_importances()` を使う。対象は完了 trial のみとする。

重要度は study ごとに出す。2段と3段では探索変数数が異なり、同一の重要度として混ぜると解釈しにくいためである。

### 4. objective slice plot

```text
objective_slice_plot.png
```

各探索変数と objective の関係を見る。初期実装では Optuna visualization の slice plot を使い、HTML または画像として保存する。見にくい場合は、後続で matplotlib による独自描画へ置き換える。

特に見る変数は次である。

```text
steam_to_eb_ratio
inlet_pressure_kpa_abs
stage_1_temperature_c
stage_2_temperature_c
stage_1_bed_thickness_m
stage_2_bed_thickness_m
```

3段 study では第3段も含める。

### 5. top trials table

```text
top_trials.csv
top_trials.md
```

上位 10 trial 程度を保存する。列は次を基本とする。

```text
rank
study_name
trial_number
annual_profit_yen_per_year
stage_count
stage temperatures
inlet_pressure_kpa_abs
steam_to_eb_ratio
bed_thicknesses_m
eb_conversion
styrene_selectivity
fresh_eb_kmol_h
fresh_h2o_kmol_h
eb_recycle_kmol_h
h2o_recycle_kmol_h
utility_yen_per_year
annualized_equipment_yen_per_year
```

## 余裕があれば作る図

初期実装では必須にしないが、発表やレポートで使いやすい図として次を残す。

| 図 | 目的 |
|---|---|
| `parallel_coordinate.html` または `parallel_coordinate.png` | 良い trial のパラメータ組み合わせを見る |
| `best_parameter_position.png` | 最良条件が探索範囲の端に張り付いていないかを見る |
| `study_best_objective_comparison.png` | 2段、3段の best objective を比較する |
| `contour_steam_to_eb_vs_stage1_temp.png` | 重要度上位2変数の相互作用を見る |

これらは trial 数が少ない段階では不安定になりやすい。まず必須図を作り、探索数が増えてから追加する。

### parallel coordinate の意味

parallel coordinate plot は、各探索変数を縦軸として横に並べ、1 trial を1本の折れ線で表す図である。線の色を objective で塗ると、高い annual profit を与える trial がどの変数範囲を同時に通っているかを見られる。

例えば、良い trial の線が `steam_to_eb_ratio` では低め、`stage_1_temperature_c` では高め、`stage_2_bed_thickness_m` では中間付近を通るなら、単独の slice plot では見えにくい条件の組み合わせを説明できる。

一方で、trial 数が少ない場合や低品質 trial が多い場合は図が読みにくい。そのため、初期実装では必須図にせず、探索数が増えた後の補助図として扱う。まずは Optuna visualization の parallel coordinate を保存し、見にくい場合だけ独自描画に切り替える。

## 採用しない案

### 反応器 Pareto front 上の候補だけを全体評価する案

採用しない。Pareto front は分離コスト、recycle、utility を考えていないため、全体最適化の探索空間として偏りがある。全体目的関数で探索し直す。

### 経済収支内訳の比較図を新規作成する案

本設計では優先しない。既存の `WholePlantCostResult` と `format_whole_plant_cost_report()` で確認できるため、全体最適化 script の初期出力では探索妥当性の図を優先する。

### 描画 script で HYSYS を再実行する案

採用しない。描画は SQLite storage の trial 値だけから行う。HYSYS を再実行すると、描画が重くなり、再現性も悪くなる。

## 既知の制約

- HYSYS trial は重いため、初期 trial 数は小さくなる。
- `get_param_importances()` は完了 trial 数が少ないと不安定である。
- 2段と3段を同じ重要度図に混ぜると、変数数が違うため解釈しにくい。
- HYSYS 収束や COM エラーによる prune は、探索傾向にも影響する。
- v1 では蒸留塔還流比とデカンター温度を動かさないため、完全な分離器込み最適化ではない。

## 今後の拡張

入口条件書き込みが安定した後、`HysysControlPlan.operations` に蒸留塔還流比とデカンター温度を書き込めるようにする。その段階で、`optimization/separator/parameters.py` を追加し、全体最適化の探索変数へ分離操作条件を含める。

その場合でも、探索結果の出力方針は本書を維持する。すなわち、runner は SQLite storage へ必要値を保存し、描画 script は storage だけを読んで図と表を生成する。

## 初期実装で確定する点

- `whole_plant_optuna_v1.py` には radial と axial の study 定義を両方置く。
- 初期実行では radial 2段と3段を各 50 trial、axial 2段と3段を各 0 trial とする。
- `TPESampler(seed=42)` を使う。
- 可視化はまず Optuna visualization を使う。見にくい図だけ、後続で matplotlib の独自描画へ置き換える。

## 実装結果

以下を追加した。

```text
src/process_sim/optimization/runner/
  whole_plant_optuna_v1.py

scripts/whole_plant_optuna_v1/
  plot_results.py
```

`whole_plant_optuna_v1.py` は、radial 2段、radial 3段、axial 2段、axial 3段の study 定義を持つ。初期設定では radial 2段と3段だけを各 50 trial 実行し、axial は各 0 trial とする。

trial では、候補条件から反応器 case を作り、`run_production_target_convergence()`、`build_inlet_control_plan()`、`apply_post_convergence_controls()`、`read_process_equipment()`、`evaluate_whole_plant_cost()` の順で評価する。目的関数は `annual_profit_yen_per_year` の最大化である。

`plot_results.py` は、`data/optuna/whole_plant_optuna_v1.db` を読み、次を生成する。

```text
scripts/whole_plant_optuna_v1/media/
  best_objective_history.png
  objective_trials.png
  parameter_importance.png
  objective_slice_plot_<study_name>.png

scripts/whole_plant_optuna_v1/results/
  top_trials.csv
  top_trials.md
```

README に、runner と描画 script の実行方法、ディレクトリ概略を追記した。

HYSYS 実行、`uv run`、ruff、pyright は本作業では実行していない。

## 未確定要素

- axial PFR の trial 数をいつ増やすか。
- Optuna visualization の出力形式を HTML 主体にするか、PNG 主体にするか。
