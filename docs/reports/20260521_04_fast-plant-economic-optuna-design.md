# fast plant economic Optuna 設計

## 目的

既存の `radial_simple_optuna.py` は、反応器単体の出口基準で簡易利益を評価している。

次の段階として、`fast-plant-convergence` と同じ考え方で、HYSYS case を開いたまま production target と recycle convergence を実行し、定常状態に近い plant 流量から経済収支を評価する Optuna runner を追加する。

CLI は追加しない。実行条件は runner ファイル冒頭の定数を直接編集する。

## ディレクトリ構成

```text
src/process_sim/optimization/runner/
  radial_fast_plant_optuna.py      # 新規 runner。Optuna trial から radial 条件を作り plant 収束と経済評価を行う。
  radial_simple_optuna.py          # 既存 runner。反応器単体の簡易評価として残す。
src/process_sim/plant/
  convergence.py                   # 既存の production target と recycle convergence を利用する。
  session_runner.py                # 既存の OpenHysysPlantRunner を利用する。
  economics.py                     # plant 経済収支用の関数を追加する候補。
  summary.py                       # plant summary と reactor log の表示を利用する。
docs/reports/
  20260521_04_fast-plant-economic-optuna-design.md
```

## 採用方針

新しい runner を追加する。既存の `radial_simple_optuna.py` は反応器単体評価として残し、目的関数を plant 全体評価へ差し替えない。

1 trial の流れは次の通りにする。

1. Optuna trial から radial 反応器条件を作る。
2. `OpenHysysPlantRunner` を開く。
3. `run_production_target_convergence(...)` に trial の `RadialReactorCase` を渡す。
4. convergence が成立した場合だけ、最終 iteration の `PlantRunRecord` から経済収支を計算する。
5. reactor 詳細ログ、plant convergence summary、final plant summary、経済収支をログへ出す。
6. convergence 不成立、HYSYS 異常値、反応器制約違反は `TrialPruned` とする。

初期実装では、1 trial ごとに `OpenHysysPlantRunner` session を開閉する。trial 内の production target から recycle convergence までは同じ session を使うが、次 trial では HYSYS case を開き直す。trial 間で HYSYS case 内部状態が残る影響を避けるためである。

## 経済収支

初期実装では、装置費と用役費の範囲を反応器まわりだけに限定する。

- 収入
  - `sm_product` の Styrene
  - `bz_product` の Benzene
  - `tl_product` の Toluene
- 原料費
  - fresh EB
  - fresh steam
- 反応器費
  - 既存の radial 反応器本体費
  - 7年定額償却

分離系装置費、冷却用役、加熱用役、off gas 有価成分損失は、初期実装では目的関数に入れない。後続でこのファイルまたは新規ファイルに追加する。

目的関数は次を基本形にする。

```text
objective = product_revenue - fresh_feed_cost - reactor_annual_cost
```

## ログ方針

ユーザーが運転条件を追えるように、既存の reactor log と plant summary を流用する。

- `OpenHysysPlantRunner(log_reactor_detail=True)` を使い、各 plant run の reactor 詳細ログを出す。
- `format_plant_convergence_result(result)` を trial ごとに出す。
- 同関数に含まれる `Final Plant Summary` により、最終 iteration の主要 stream、recycle、product、off gas、回収率を確認する。
- 経済収支は trial 終了時に、収入、原料費、反応器費、損失、objective を1ブロックで出す。

ファイルログは2種類に分ける。

- `logs/radial_fast_plant_optuna_detail.log`
  - reactor summary、plant summary、convergence summary、経済収支を含む詳細ログ。
  - 20 MB、5世代でローテーションする。
- `logs/radial_fast_plant_optuna_params.log`
  - 探索 param、trial status、objective、主要な反応器指標だけを残す。
  - plant summary は入れない。
  - 5 MB、5世代でローテーションする。

## 変更責務

### `radial_fast_plant_optuna.py`

- `radial_simple_optuna.py` の探索空間と候補生成を再利用する。
- `run_production_target_convergence` に trial の reactor case を渡すため、`convergence.py` 側に `base_reactor_case` 引数を追加する。
- `OpenHysysPlantRunner` は 1 trial ごとに開閉する。
- `N_TRIALS`、`SEED`、対象 study はファイル冒頭に置く。
- CLI entry point は追加しない。

### `plant/economics.py`

- `PlantRunRecord` と `PlantConvergenceResult` の最終 iteration から、plant 経済収支を作る関数を追加する候補とする。
- 既存の価格表、`component_value_yen_per_year`、`radial_reactor_capital_cost_yen` を使う。
- 反応器費計算に必要な `ReactorResult` は、runner 側で得た反応器計算結果を明示的な経済計算入力として渡す。

`PlantRunRecord.metadata` に `ReactorResult` や反応器費を隠し込む案は採用しない。metadata は HYSYS 実行記録や表示用の補助情報が混ざりやすく、経済計算の必須入力にすると依存関係が読みにくくなるためである。

### `plant/convergence.py`

- `run_production_target_convergence` に `base_reactor_case` 引数を追加する。
- 既定値は従来通り `default_reactor_case_for_model(reactor_model)` を使う。
- Optuna runner から呼ぶ場合だけ、trial 条件で作った `RadialReactorCase` を渡す。

## Steam/EB 比の扱い

現状の `production_target.py` では、Steam/EB 比は主に feed tuning の初期値生成に使われている。

- `InitialRecycleGuessPolicy.steam_to_eb_ratio`
  初回 run の reactor inlet H2O/EB 比を決める。既定値は `5.0`。
- 2回目以降の production target
  直前 run の reactor inlet H2O/EB 比を保持する形で次の feed を推定する。
- recycle convergence
  production target で得た fresh feed と、直前 iteration の recycle output から reactor feed を作る。

したがって、現在のままでは `radial_simple_optuna.py` の `candidate.steam_to_eb_ratio` を `RadialReactorCase.feed` に入れても、plant 側の production target ではその feed が上書きされる。plant Optuna で Steam/EB 比を探索変数として効かせるには、trial の `steam_to_eb_ratio` を `FeedTuningOptions(initial_guess_policy=InitialRecycleGuessPolicy(steam_to_eb_ratio=...))` に渡す必要がある。

初期実装では、Steam/EB 比を探索変数として残し、production target の初期 reactor inlet H2O/EB 比へ渡す。これにより、plant 側の feed tuning と Optuna 条件の対応を保つ。

## 未確定要素

- 分離系装置費、冷却用役、加熱用役、有価成分損失を後続で同じファイルに足すか、新規ファイルに分けるか。

## 実装結果

以下を実装した。

- `src/process_sim/optimization/runner/radial_fast_plant_optuna.py`
  - 新規 runner として追加した。
  - CLI entry point は追加していない。
  - module 直接実行で動かす。
  - 1 trial ごとに `OpenHysysPlantRunner` を開閉する。
  - HYSYS に渡す前に、各 plant run の reactor case を Python 側で事前計算し、圧力などの反応器制約が NG の場合は HYSYS を呼ばずに trial を prune する。
  - 詳細ログと param ログをローテーション付きで出す。
- `src/process_sim/plant/convergence.py`
  - `run_production_target_convergence` に `base_reactor_case` と `feed_tuning_options` を追加した。
  - 既存呼び出しでは従来通り既定 case と既定 options を使う。
- `src/process_sim/plant/economics.py`
  - `PlantReactorEconomicBreakdown` を追加した。
  - product 収入、fresh EB と fresh steam の原料費、radial 反応器年換算費から objective を計算する。
  - `PlantRunRecord.metadata` には経済計算の必須入力を入れない。
- `src/process_sim/reactor/types/staged_adiabatic_radial.py`
  - outlet pressure 下限を 50 kPa に変更した。
- `src/process_sim/reactor/types/staged_adiabatic_pfr.py`
  - outlet pressure 下限を 50 kPa に変更した。
- `src/process_sim/plant/summary.py`
  - reactor log の outlet pressure 制約表示を 50 kPa に変更した。

実行方法は次の通りである。

```powershell
uv run python -m process_sim.optimization.runner.radial_fast_plant_optuna
```

確認は以下のみ実施した。HYSYS case の実行確認はしていない。

```powershell
uv run ruff check src/process_sim/optimization/runner/radial_fast_plant_optuna.py src/process_sim/reactor/types/staged_adiabatic_radial.py src/process_sim/reactor/types/staged_adiabatic_pfr.py src/process_sim/plant/summary.py src/process_sim/optimization/reactor/constraints.py
uv run pyright
```
