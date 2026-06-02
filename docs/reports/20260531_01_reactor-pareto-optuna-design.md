# 選択率・単通反応率 Pareto front 探索 script 初期設計

※この文章は古い文章である。現行の実装で使ってはいない。

## 目的

ラジアルフロー反応器について、次の 2 目的を同時に最大化し、Pareto front を可視化する。

```text
目的1: SM 選択率
目的2: EB 単通反応率
```

この探索は、経済収支を直接最適化する既存 runner とは分ける。選択率と単通反応率のトレードオフを確認し、後続の反応器条件検討に使うことを目的とする。

初回設計ではラジアルフロー反応器だけを対象とする。PFR を採用しない理由の検討は別作業とし、この script には含めない。

## 設計方針

- Optuna の `NSGAIISampler` を使う。
- 2段と3段では探索空間の次元が異なるため、study を分ける。
- 2段と3段は、段数ごとに指定した累積目標 trial 数まで進める。
- 長時間の一括実行は前提にしない。小分けに探索を追加し、その時点までの結果から図を更新できる構成にする。
- 制約違反や反応器計算失敗は `optuna.TrialPruned` とする。
- 中断後に再開できるよう、Optuna の SQLite storage を使う。
- trial の入力条件、目的値、prune 理由を後から確認できる形で残す。

## ディレクトリ構成

初回実装で追加または参照する範囲は次の通りである。

```text
src/process_sim/optimization/
  reactor/
    parameters.py                 # 既存のラジアル反応器探索範囲と候補条件
  runner/
    radial_pareto_optuna.py       # 新規。探索実行、再開、trial 記録
scripts/
  reactor_pareto/
    plot_pareto_front.py          # 新規。DB から途中結果を読み、図を更新
    select_best_condition.py      # 指定単通反応率以上で選択率が最大の条件を表示
    media/
      radial_all_trials.png       # 全完了 trial の散布図
      radial_stage_pareto_front.png   # 段数ごとの Pareto front
      radial_global_pareto_front.png  # 2段と3段を合わせた global Pareto front
data/
  optuna/
    radial_pareto_optuna.db       # Optuna SQLite storage
logs/
  radial_pareto_optuna.log        # 探索の進行確認用ログ
docs/
  reports/
    20260531_01_reactor-pareto-optuna-design.md
```

SQLite DB とログは Git 管理対象外とする。生成図は Git 管理対象とする。

## ファイル責務

### `radial_pareto_optuna.py`

- 既存のラジアル反応器探索範囲から trial 条件を生成する。
- 2段 study と3段 study を別々に作成または再開する。
- `NSGAIISampler` を使って各 study を段数ごとの累積目標 trial 数まで進める。
- 反応器計算を実行し、制約判定を行う。
- 完了 trial では SM 選択率と EB 単通反応率を返す。
- trial の補助情報を `user_attrs` に保存する。
- prune 理由と実行進行をファイルログへ残す。
- trial ごとの詳細 profile は保存しない。

既存の `radial_simple_optuna.py` は、経済収支の簡易評価 runner として残す。Pareto 探索 runner へ置き換えない。

### `plot_pareto_front.py`

- SQLite storage から2段 study と3段 study を読む。
- 完了 trial の目的値を散布図として表示する。
- 各段数の Pareto front を計算し、同じ図に表示する。
- 2段と3段を合わせた全完了 trial から global Pareto front を計算する。
- global Pareto front 上の点を段数別に識別できる形で表示する。
- 探索途中でも、その時点までの結果から図を更新する。
- DB を更新せず、読み取りと図生成だけを行う。
- 全完了 trial、段数ごとの Pareto front、global Pareto front は別々の PNG に出力する。

### `select_best_condition.py`

- SQLite storage の完了 trial だけを読む。
- script 冒頭の `MIN_EB_CONVERSION` で EB 単通反応率の下限を指定する。
- 下限以上の trial から、SM 選択率が最大の条件を選ぶ。
- 2段、3段、全体の最良条件を標準出力へ表示する。
- 探索や反応器再計算は行わない。

## Study 設計

study 名は段数ごとに固定する。

```text
radial_2stage_selectivity_conversion
radial_3stage_selectivity_conversion
```

目的関数は次の順序で返す。

```python
return result.styrene_selectivity, result.eb_conversion
```

study 作成時の方向は次とする。

```python
directions=("maximize", "maximize")
sampler=NSGAIISampler(
    population_size=50,
    seed=None,
)
```

2段と3段を同一 study に混ぜない理由は、各段入口温度と各段触媒層厚みの変数数が異なるためである。比較時は、各 study の結果を同じ図に重ねて表示する。

`population_size` は NSGA-II の1世代あたりの trial 数である。`50` に設定する。累積目標 trial 数は、原則として `population_size` の倍数にする。`seed` は `None` とする。SQLite storage を使って小分けに探索を再開する運用では、プロセス起動ごとに固定 seed の乱数系列が先頭へ戻ると、同じ候補を再生成する可能性があるためである。探索済み条件と目的値は SQLite storage に残す。その他の sampler 引数は Optuna の既定値を使う。

## 探索変数

初回実装では、既存の `RadialReactorParameterConfig` と既存範囲を再利用する。

| 項目 | 扱い |
|---|---|
| 各段入口温度 | 各段独立に探索する。 |
| 反応器列入口圧力 | 2段は `70–200 kPa abs`、3段は `90–200 kPa abs` とする。 |
| Steam/EB 比 | 探索する。 |
| 各段触媒層厚み | 各段独立に探索する。 |
| 入口空塔速度 | 既存方針どおり `2.0 m/s` に固定する。 |
| 段数 | 2段 study と3段 study に分ける。 |

現行コードの `INITIAL_RADIAL_INLET_PRESSURE_RANGE_KPA_ABS` は、2段と3段で共通の `90–200 kPa abs` である。Pareto 探索では、出口側に接続するデカンターで `50 kPa abs` 以上を必要とすることと、段間再加熱器1基あたり `20 kPa` の圧力損失を考慮し、入口圧力範囲を段数ごとに分ける。

```text
2段: 70–200 kPa abs
3段: 90–200 kPa abs
```

2段では段間再加熱器が1基、3段では2基あるため、圧力下限をそれぞれ `50 + 20 = 70 kPa abs`、`50 + 20 × 2 = 90 kPa abs` とする。実際には反応器内部の圧力損失も加わるため、下限付近の候補は prune される可能性がある。

初回実装では、温度、Steam/EB 比、触媒層厚みの範囲は既存設定を再利用する。入口圧力だけは、Pareto 探索用の2段設定と3段設定で下限を分ける。

## SQLite storage と再開

中断後の再開と途中可視化のため、in-memory study ではなく SQLite storage を使う。

```text
sqlite:///data/optuna/radial_pareto_optuna.db
```

study は `load_if_exists=True` で開く。段数ごとに累積目標 trial 数を指定し、現在の有効 trial 数との差分だけを追加する。

```text
TARGET_EFFECTIVE_TRIALS_BY_STAGE_COUNT = {
    2: 1300,
    3: 1300,
}
```

例えば2段が300件、3段が300件まで完了した時点で中断し、目標を2段400件、3段500件として再実行した場合、2段には100件、3段には200件を追加する。3段だけ追加する場合は、2段の目標を現在の有効 trial 数のままにし、3段の目標だけを増やす。

ここで有効 trial は `COMPLETE` または `PRUNED` の trial とする。中断時に `KeyboardInterrupt` が発生した trial は Optuna により `FAIL` として記録されるが、有効 trial 数には含めない。

## 制約と prune

既存の `radial_simple_optuna.py` と同様に、少なくとも次を prune 対象にする。

- 反応器計算で例外が発生する。
- `pressure_positive_ok` が `False` である。
- `atom_balance_ok` が `False` である。
- `ergun_range_ok` が `False` である。
- `outlet_pressure_ok` が `False` である。
- SM 生成量が正でない。

制約違反に対するペナルティ目的値は返さない。prune 理由はログと trial の属性に残す。

prune 理由は、反応器評価で制約違反または計算失敗を検出した直後、`optuna.TrialPruned` を送出する前に `trial.set_user_attr("prune_reason", reason)` で保存する。これにより、SQLite storage 上でも prune された trial の失敗理由を後から確認できる。

## 保存する trial 情報

Optuna が保存する探索変数と目的値に加え、少なくとも次を `user_attrs` に残す。

```text
stage_count
eb_conversion
styrene_selectivity
outlet_pressure_kpa
total_catalyst_volume_m3
constraint 判定結果
prune_reason
```

探索再開の正本は SQLite storage とする。ファイルログは人間が進行と失敗理由を確認するために使い、再開処理の入力には使わない。

## ログ

`logs/radial_pareto_optuna.log` には、少なくとも次を記録する。

```text
[start] study 名、段数、今回追加する trial 数、有効 trial 数、DB 保存済み trial 数
[finished] trial 番号、探索条件、SM 選択率、EB 単通反応率、主要制約値
[pruned] trial 番号、探索条件、prune 理由
[done] study 名、今回の完了件数、prune 件数、有効 trial 数、DB 保存済み trial 数
```

trial ごとの詳細な反応器 profile は保存しない。Pareto front の追跡に必要な要約ログだけを残す。

## 出力図

初回の図は、横軸を EB 単通反応率、縦軸を SM 選択率とする。

```text
x: EB single-pass conversion
y: SM selectivity
```

2段と3段は系列を分ける。全完了 trial と Pareto front は、次の3枚に分けて保存する。

```text
scripts/reactor_pareto/media/radial_all_trials.png
scripts/reactor_pareto/media/radial_stage_pareto_front.png
scripts/reactor_pareto/media/radial_global_pareto_front.png
```

`radial_all_trials.png` には全完了 trial を表示する。`radial_stage_pareto_front.png` には2段と3段の Pareto front をそれぞれ表示する。`radial_global_pareto_front.png` には、2段と3段を合わせた全完了 trial に対する global Pareto front 上の trial を表示する。

3枚の図で、軸目盛は内向きとし、上下左右へ表示する。目盛線は表示せず、タイトルは付けない。

生成図は Git 管理対象とする。SQLite DB とログは Git 管理対象外とする。

## 実行単位

探索 runner と描画 script は分ける。

```powershell
uv run python -m process_sim.optimization.runner.radial_pareto_optuna
uv run python scripts/reactor_pareto/plot_pareto_front.py
```

探索 runner の冒頭に、段数ごとの累積目標 trial 数を置く。

```python
TARGET_EFFECTIVE_TRIALS_BY_STAGE_COUNT = {
    2: 1300,
    3: 1300,
}
```

現在の有効 trial 数が目標以上の場合、その study には trial を追加しない。

## 採用しない案

### 2段と3段を同一 study に入れる

採用しない。探索次元と変数の意味が異なるため、study を分ける。

### 追加 trial 数を単一の定数で指定する

採用しない。現在の累積件数との差分が分かりにくく、段数ごとに探索量を変えられないためである。

### PFR 比較を同時に実装する

採用しない。PFR を採用しない理由の検討は必要だが、今回の Pareto 探索 script とは分けて扱う。

## 未確定要素

現時点ではなし。
