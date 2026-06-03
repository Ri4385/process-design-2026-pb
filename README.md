# process-design-2026

## 概要

京都大学のプロセス設計課題を進めるためのリポジトリである。

対象プロセスは、エチルベンゼンの脱水素によるスチレンモノマー製造プロセスである。本リポジトリでは、反応器設計、分離機設計、プロセス全体の接続、条件調整と最適化、最終的なレポート作成に向けた根拠整理を管理する。

## 反応系

扱う反応系は、SMの生成である反応1を主反応とする下記の6反応である。

反応1		C6H5-CH2CH3 (EB) ⇄ C6H5-CH=CH2 (SM) + H2\
反応2		C6H5-CH2CH3 (EB) → C6H6 (BZ) + C2H4\
反応3		C6H5-CH2CH3 (EB) + H2 → C6H5-CH3 (TL) + CH4\
反応4		2H2O + C2H4 → 2CO + 4H2\
反応5		H2O + CH4 → CO + 3H2\
反応6		H2O + CO → CO2 + H2

## プロセスフロー

主な流れは、反応器で反応させたのち、デカンターで油相(SM, EBなど)と水相、オフガス(エチレン, メタンなど)に分離し、SM, EB, TL, BZを3つの蒸留塔を使って分離する。EBとスチームはリサイクルを行う。ブロックフロー図、プロセスフロー図は下記のとおりである。

(作成中)
### TODO: プロセスフロー図を作成する
**プロセスフロー図**

**ブロックフロー図**

## このリポジトリの位置づけ

- 授業のプロセス設計を進めるための開発基盤である。
- コード、HYSYS ケース、設計判断、前提条件、作業記録を管理対象とする
- 第23回プロセスデザイン学生コンテスト課題を主要な参考資料として扱う。(完全準拠するわけではない)

## 主要な成果物

- Python コード
- HYSYS ケース
- 設計判断と作業記録
- 最終レポート用の技術的根拠

## 現在の方針

- 反応器側は主に Python で扱う想定である。
- 分離機側は主に HYSYS で扱う想定である。
- 両者は独立ではなく、最終的には接続して整合を取る前提である。
- 可能であれば Python 側の自動化範囲を広げるが、実際の運用は課題の進行に応じて決める。

## 現状

- 反応器モデルは Python 側に実装済みである。
- 既定の反応器ケースは `uv run run-reactor-case` で実行できる。
- 反応器出口を HYSYS 分離系へ渡すプラントワンパス実行は `uv run run-plant-once` で実行できる。
- 目標 SM product 流量に合わせる高速 fresh feed 調整は `uv run tune-plant-feed` で実行できる。
- production target で求めた feed 条件から、正式な recycle 収束計算を `uv run run-plant-convergence` で実行できる。
- HYSYS case を開いたまま recycle 収束後に全体コスト評価まで行う入口は `uv run fast-plant-convergence-cost` で実行できる。
- radial 反応器の簡易利益 Optuna tuning は `uv run python -m process_sim.optimization.runner.radial_simple_optuna` で実行できる。
- HYSYS ケースの調査用スクリプトと部分最適化スクリプトは `scripts/` にある。
- 分離機は HYSYS ケース側に構築されており、Python 側には HYSYS I/O と機器読み取り用のモジュールがある。
- 既定 HYSYS ケースから蒸留塔、デカンター、冷却器、加熱器、ポンプ、コンプレッサーを読み取り、確認結果を標準出力へ表示できる。
- `data/diagnostics/` には HYSYS ケースを COM 経由で調査した診断用 JSON を置いている。
- `plant/economics.py` には暫定的な経済計算が残っている。全体プラントのコスト評価は `plant/cost/` 側で扱う。

## 参考資料

- コンテスト課題: `data/chem_contest.md`
- 過去レポート: `data/report_md/~`, 

コンテスト課題は主要な参考資料とする。

## 開発環境

- OS: Windows
- Python: 3.11
- HYSYS: v14
- パッケージ管理: `uv`
- 静的解析: `ruff`
- テスト: `pytest`

## セットアップ

```powershell
git clone https://github.com/Ri4385/process-design-2026.git
cd process-design-2026
uv sync
```

## ディレクトリ運用方針

### ディレクトリ概略

```text
data/
  chem_contest.md                     # コンテスト課題資料
  hysys/                              # HYSYS ケース
  optuna/                             # Optuna SQLite storage
  diagnostics/                        # HYSYS ケース診断 JSON
  report_md/                          # 過去レポート Markdown
  report_pdf/                         # 過去レポート PDF
scripts/
  axial-radial-comparison/            # axial/radial 比較スクリプト
  check_hysys_connection.py           # HYSYS 接続確認
  decanter/                           # デカンター部分最適化
  distillation/                       # 蒸留塔部分最適化
  reactor-profile/                    # 反応器プロファイル出力
  reactor_sensitivity_analysis/       # 反応器感度分析
  reactor_pareto/                     # 旧 radial pareto
  reactor_pareto_v2/                  # radial・axial Pareto front 描画
  export_code_snapshot.py             # スナップショット出力
  inspect_hysys_case.py               # HYSYS ケース調査
  read_hysys_equipment.py             # 既定 HYSYS case の機器読み取り確認
  run_fixed_plant_convergence.py      # 固定 feed で plant convergence
  run_reactor_to_decanter.py          # 反応器からデカンターへの接続試行
docs/
  cost.md                             # コスト式と単価の整理
  documentation-policy.md             # 文書運用方針
  optimization.md                     # 最適化設計メモ
  overview.md                         # 設定条件概要
  physical_property.md                # 物性メモ
  reactor.md                          # 旧反応器設計メモ
  pfr.md                              # PFR反応器実装メモ
  radial-flow-reactor.md              # ラジアルフロー反応器実装メモ
  reports/                            # 作業記録
src/process_sim/
  cli.py                              # CLI入口
  constants/
    physical_properties.py            # 物性定数
    reaction_networks.py              # 反応ネットワーク定義
    universal.py                      # 普遍定数
  reactor/
    cases/
      styrene_default.py              # 既定反応器ケース
      styrene_radial_default.py       # 既定ラジアル反応器ケース
    core/
      balance.py                      # 反応器収支式
      config.py                       # 反応器中核計算の切り替え設定
      integrator.py                   # 数値積分
      kinetics.py                     # 反応速度式
      models.py                       # 反応器入出力モデル
      numba_reactor.py                # 既定反応器の Numba 高速積分
      pressure_drop.py                # 圧力損失計算
      radial_geometry.py              # ラジアルフロー形状計算
      reaction.py                     # 反応定義
      stream.py                       # 反応器ストリーム
      thermodynamics.py               # 熱力学計算
    types/
      staged_adiabatic_pfr.py         # 多段断熱PFR
      staged_adiabatic_radial.py      # 多段断熱ラジアル
      pfr_adiabatic.py                # 断熱PFR
      radial_adiabatic.py             # 断熱ラジアル
  optimization/
    models.py                         # 共通の探索範囲型
    reactor/
      parameters.py                   # 反応器パラメータ範囲と候補条件
      constraints.py                  # 反応器制約
    runner/
      radial_simple_optuna.py         # radial 反応器の簡易利益 Optuna runner
      radial_fast_plant_optuna.py     # plant 経済収支 Optuna runner
      reactor_pareto_optuna.py        # 旧radial反応器の Pareto front 探索 runner
      reactor_pareto_v2_optuna.py     # radial・axial 反応器の Pareto front 探索 runner
  separator/
    equipment.py                      # HYSYS から読んだ機器状態モデル
    equipment_log.py                  # 機器読み取り確認用の標準出力
    hysys_equipment_reference.py      # 固定 HYSYS case 上の参照先定義
    hysys_io.py                       # HYSYS 分離系 I/O
    equipment_reader/
      common.py                       # COM 読み取り共通処理
      decanter.py                     # デカンター寸法読み取り
      distillation.py                 # 蒸留塔読み取り、塔径・塔高計算
      heat_exchanger.py               # 冷却器、加熱器読み取り
      process_equipment.py            # 機器一式の組み立て
      rotating_equipment.py           # ポンプ、コンプレッサー読み取り
  plant/
    const.py                         # plant 共通固定値
    convergence.py                   # plant recycle 収束計算
    economics.py                     # 既存の暫定経済計算
    fast_convergence_cost.py         # HYSYS session 再利用 convergence と全体コスト評価
    fast_convergence.py              # HYSYS session 再利用 convergence
    fast_production_target.py        # HYSYS session 再利用 production target
    feed.py                           # plant feed 作成
    models.py                         # plant 記録モデル
    production_target.py              # 生産量調整
    runner.py                         # plant 実行入口
    session_runner.py                 # HYSYS session runner
    summary.py                        # plant 結果要約
    cost/
      constants.py                    # コスト評価の単価、係数、utility 条件
      common.py                       # 年間金額、LMTD、伝熱面積などの共通計算
      equipment.py                    # 装置費、熱回収器面積、建設費の計算
      evaluation.py                   # 全体プラント収支の組み立て
      log.py                          # コスト評価ログの整形
      models.py                       # コスト評価結果と T-Q 用モデル
      revenue.py                      # 製品収入と原料費
      tq.py                           # T-Q stream と外部 utility load の生成
      utility.py                      # steam、冷却水、冷媒、電力、燃料費
```

### ディレクトリ詳細

- `src/process_sim/`
  Python 実装を置く。
- `src/process_sim/constants/`
  反応器モデルなどで使う定数を置く。
- `src/process_sim/reactor/`
  反応器計算ロジックを置く。
- `src/process_sim/reactor/cases/`
  反応器の既定ケースを置く。
- `src/process_sim/reactor/core/`
  反応器の物質収支、反応速度、熱力学、ストリーム表現などの中核処理を置く。
- `src/process_sim/reactor/types/`
  反応器タイプごとのモデルを置く。
- `src/process_sim/optimization/`
  最適化まわりの探索範囲、候補条件、制約値を置く。
- `src/process_sim/separator/`
  HYSYS 分離系との接続処理と、コスト計算へ渡す機器モデルの読み取り処理を置く。HYSYS COM オブジェクトはこの層の外に直接出さない方針である。
- `src/process_sim/separator/equipment_reader/`
  固定 HYSYS ケースから蒸留塔、デカンター、冷却器、加熱器、ポンプ、コンプレッサーを読み取り、明示的な Python モデルへ変換する。読み取れない必須値は補完せず、例外として扱う。
- `src/process_sim/plant/`
  反応器と分離系を接続し、プラント全体で固定される主要 stream の記録を扱う。
- `src/process_sim/plant/cost/`
  収束後の `PlantConvergenceResult`、`ReactorResult`、`ProcessEquipment` から、収入、原料費、装置費、utility、固定費、T-Q 用 stream、年間収支を計算する。既存の `plant/economics.py` とは分けて管理する。
- `scripts/`
  実行スクリプト、HYSYS 接続確認、HYSYS ケース調査、反応器と HYSYS の接続試行、デカンターと蒸留塔の部分最適化を置く。部分最適化に固有の HYSYS ケース、診断 JSON、図も各ディレクトリ内で管理する。
- `scripts/reactor_pareto_v2/`
  radial・axial 反応器の全 trial と Pareto front の図を生成する。
- `data/`
  参考資料や入力データを置く。
- `data/hysys/`
  HYSYS の `.hsc` などを置く想定である。
- `data/optuna/`
  中断後に再開する Optuna 探索の SQLite storage を置く。DB は Git 管理対象外とする。
- `data/diagnostics/`
  HYSYS ケースの診断用 JSON を置く。これは人間向けのプロセスログではなく、ケース内部の状態確認用である。
- `data/report_md/`, `data/report_pdf/`
  過去レポートなどの参考資料を置く。
- `docs/`
  設計判断、前提条件、作業記録を置く。

### 将来のoptimizationの概略

```text
src/process_sim/optimization/
  models.py          # 共通の探索範囲型
  reactor/
    parameters.py      # 反応器パラメータ範囲と候補条件
    constraints.py     # 反応器制約
  separator/
    parameters.py      # 分離パラメータ範囲
    constraints.py     # 分離制約
    hysys_controls.py  # HYSYS操作条件への変換
  heat_integration/
    models.py          # 熱流・温度範囲の型
    composite_curve.py # 与熱/受熱複合線の作成
    evaluation.py      # HI後の外部負荷評価
  economics/
    revenue.py         # 製品・副生成物収入の計算
    operating_cost.py  # 原料・用役・電力費の計算
    equipment_cost.py  # 機器費の年換算計算
  objective/
    profit.py          # 経済収支の評価関数
  runner/
    optuna_runner.py   # Optuna study の実行入口
```

## 実行

反応器単体を実行する場合は、以下を使う。

```powershell
uv run run-reactor-case
```

反応器単体は Python 側で完結して実行する。既定はラジアルフロー反応器である。PFR を使う場合は `--reactor-model pfr` を付ける。

プラントのワンパス実行は以下で行う。

```powershell
uv run run-plant-once
```

既定ではラジアルフロー反応器を使う。PFR を使う場合は `--reactor-model pfr` を付ける。既定では `src/process_sim/plant/const.py` の `DEFAULT_HYSYS_CASE_PATH` に設定された HYSYS ケースを使う。別ケースを使う場合は `--case-path` で指定する。Python 反応器出口を HYSYS 側の `reactor_outlet` stream に渡し、主要 stream の要約を出力する。

HYSYS 側の計算停止に備え、既定では子 Python プロセスに隔離して実行する。timeout は `src/process_sim/plant/const.py` の `DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS` で管理し、CLI からは `--timeout-seconds` で変更できる。`--case-path` と `--hidden` は子プロセス側にも渡される。

`run-plant-once` と `tune-plant-feed` は CLI 入口で logging を初期化し、plant 実行開始、使用する HYSYS case path、HYSYS 表示設定、反応器計算、分離計算の進行を標準エラーへ出す。

HYSYS の表示設定は用途で分ける。手動確認やデバッグ用の script 実行では、停止ダイアログやエラー内容を確認できるように `hysys_visible=True` を基本とする。自動探索では、ダイアログで処理が止まるのを避けるため `hysys_visible=False` または `--hidden` を明示して使う方針である。

既定 HYSYS ケースからコスト計算用の機器情報を読み取れるか確認する場合は、以下を使う。

```powershell
uv run python scripts/read_hysys_equipment.py
```

この script は CLI 引数を持たない。`src/process_sim/plant/const.py` の `DEFAULT_HYSYS_CASE_PATH` を使って HYSYS ケースを開き、蒸留塔、デカンター、冷却器、加熱器、ポンプ、コンプレッサーの読み取り結果を標準出力へ表示する。確認用の一時実行であり、ログファイルは作らない。

目標 SM product 流量に合わせて fresh feed を調整する場合は、以下を使う。

```powershell
uv run tune-plant-feed --target-sm-kmol-h 240.033 --max-runs 5
```

`tune-plant-feed` は、目標 SM product 流量から初期 fresh feed と recycle 初期値を作り、2回目以降は直前 run の実効収率、未反応率、recycle 回収率から次回 fresh/recycle を計算する。secant 法は使わない。既定ではラジアルフロー反応器を使う。PFR を使う場合は `--reactor-model pfr` を付ける。

主な引数は以下である。

- `--target-sm-kmol-h`
  目標とする `sm_product` 中の Styrene 流量である。
- `--max-runs`
  最大 plant 実行回数である。
- `--sm-tolerance-kmol-h`
  目標 SM 流量との差である。微小な浮動小数点数誤差を除き、`0 <= SM product - target SM <= tolerance` の範囲を合格にする。既定値は `0.1 kmol/h` である。
- `--eb-recycle-tolerance-kmol-h`
  EB recycle の `output - input` に対する許容幅である。既定値は `0.1 kmol/h` である。
- `--h2o-recycle-tolerance-kmol-h`
  H2O recycle の `output - input` に対する許容幅である。既定値は `0.1 kmol/h` である。
- `--max-feed-step-fraction`
  旧 secant 更新用の設定である。現時点の初期値検証経路では使わない。
- `--case-path`
  使用する HYSYS ケースのパスである。

`tune-plant-feed` の HYSYS 表示は、複数回実行中にポップアップで止まることを避けるため `False` 固定である。

収束判定では、SM が目標以上かつ過剰分が許容内であること、EB recycle と H2O recycle の自己一致誤差が許容内であることを見る。各 run 後に feed/SM と recycle consistency の累積表を logging で標準エラーへ出す。

HYSYS case を開いたまま production target を実行する場合は、以下を使う。

```powershell
uv run fast-production-target
```

この入口は CLI 引数を持たない。既定の HYSYS case、既定 target SM、既定 radial 反応器を使い、HYSYS 表示は `False` 固定である。

正式な recycle 収束計算は以下で行う。

```powershell
uv run run-plant-convergence
```

この実行では、まず `tune-plant-feed` と同じ production target 計算で feed 条件を求める。その最終 run の reactor feed を初回の recycle なし feed とし、2回目以降は固定 fresh feed と直前 run の `eb_recycle`、`water_recycle` を足して反復する。収束判定は3回目以降に、EB recycle と H2O recycle の自己一致だけで行い、SM product は記録するが判定には使わない。既定ではラジアルフロー反応器を使う。PFR を使う場合は `--reactor-model pfr` を付ける。

HYSYS case を開いたまま production target から recycle convergence まで連続実行する場合は、以下を使う。

```powershell
uv run fast-plant-convergence
```

この入口も CLI 引数を持たない。production target と convergence で同じ HYSYS session を使い、途中で case を開き直さない。HYSYS 表示は `False` 固定である。

HYSYS case を開いたまま production target、recycle convergence、機器読み取り、全体コスト評価まで連続実行する場合は、以下を使う。

```powershell
uv run fast-plant-convergence-cost
```

この入口も CLI 引数を持たない。`fast-plant-convergence` と同じ収束計算後に、同じ HYSYS session から `ProcessEquipment` を読み取り、`plant/cost/` で年間収支を評価する。出力には、コスト Summary、機器詳細、熱回収、T-Q stream、熱回収後の外部 utility load を含める。

固定 feed plan を直接書いて実行したい場合は、`scripts/run_fixed_plant_convergence.py` の `FEED_PLAN` を編集して実行する。

radial 反応器の簡易利益 tuning は以下で行う。

```powershell
uv run python -m process_sim.optimization.runner.radial_simple_optuna
```

探索条件は `src/process_sim/optimization/runner/radial_simple_optuna.py` の冒頭定数を直接編集する。2段と3段は別 study として実行し、各 trial の候補条件、制約結果、簡易利益内訳を logging に出す。各 trial の反応器詳細ログは標準出力に出す。

radial・axial 反応器の SM 選択率と EB 単通反応率の Pareto front 探索は以下で行う。

```powershell
uv run python -m process_sim.optimization.runner.reactor_pareto_v2_optuna
```

radial 2段、radial 3段、axial 2段、axial 3段は別 study として `data/optuna/reactor_pareto_v2_optuna.db` に保存する。`src/process_sim/optimization/runner/reactor_pareto_v2_optuna.py` 冒頭の `TARGET_EFFECTIVE_TRIALS_BY_REACTOR_AND_STAGE_COUNT` で累積目標 trial 数を指定し、不足分だけを追加する。`FAIL` は有効 trial 数に含めない。

途中時点までの全 trial、段数ごとの Pareto front、global Pareto front を描画する場合は、以下を使う。

```powershell
uv run python scripts/reactor_pareto_v2/plot_pareto_front.py
```

指定した EB 単通反応率以上で SM 選択率が最大の条件を確認する場合は、以下を使う。

```powershell
uv run python scripts/reactor_pareto_v2/select_best_condition.py
```

単通反応率の下限は `scripts/reactor_pareto_v2/select_best_condition.py` 冒頭の `MIN_EB_CONVERSION` で指定する。


## 主要文書

- `docs/cost.md`
  コスト式、単価、経済収支の評価条件。
- `docs/overview.md`
  プロセス全体の条件、検討メモ、現状整理。人間のみが編集する。
- `docs/reactor.md`
  旧反応器モデルの仕様、入出力、ログ項目。
- `docs/pfr.md`
  多段断熱 PFR 反応器の実装メモ。
- `docs/radial-flow-reactor.md`
  ラジアルフロー反応器の実装メモ。
- `docs/optimization.md`
  最適化まわりの探索範囲、候補条件、制約値。
- `docs/documentation-policy.md`
  文書の役割分担と運用方針。
- `docs/reports/`
  作業記録、試算記録、比較結果。


## ドキュメント運用方針

- コード変更時は、必要に応じて関連文書も更新する。
- 設計上の仮定は一箇所にまとめて管理する方針である。
- 設計判断は、後から理由を追える形で残す。
- HYSYS 側の変更も、可能な限り文書として記録する。
- Codex が行った作業も、後から追跡できる形で残す。
