# process-design-2026

## 概要

京都大学のプロセス設計課題を進めるためのリポジトリです。

対象プロセスは、エチルベンゼンの脱水素によるスチレンモノマー製造プロセスです。本リポジトリでは、反応器設計、分離機設計、プロセス全体の接続、条件調整と最適化、最終的なレポート作成に向けた根拠整理を管理します。

## このリポジトリの位置づけ

- 授業のプロセス設計を進めるための開発基盤です。
- コードだけでなく、HYSYS ケース、設計判断、前提条件、作業記録も管理対象に含みます。
- 第23回プロセスデザイン学生コンテスト課題を主要な参考資料として扱います。
- ただし、授業を進めるうえで必要であれば、コンテスト課題に完全準拠しない判断もありえます。

## 主要な成果物

- Python コード
- HYSYS ケース
- 設計判断と作業記録
- 最終レポート用の技術的根拠

`pptx` は原則として本リポジトリで直接管理しません。必要であれば、スライド案を `md` で残します。

## 現在の方針

- 反応器側は主に Python で扱う想定です。
- 分離機側は主に HYSYS で扱う想定です。
- 両者は独立ではなく、最終的には接続して整合を取る前提です。
- 可能であれば Python 側の自動化範囲を広げますが、実際の運用は課題の進行に応じて決めます。

## 役割分担

- 反応器設計: 主担当は自分
- 分離機設計: 主担当は相方

ただし、反応器と分離機は相互依存するため、完全に独立して進める前提ではありません。

## 現状

- 反応器モデルは Python 側に実装済みです。
- 既定の反応器ケースは `uv run run-reactor-case` で実行できます。
- 反応器出口を HYSYS 分離系へ渡すプラントワンパス実行は `uv run run-plant-once` で実行できます。
- 目標 SM product 流量に合わせる高速 fresh feed 調整は `uv run tune-plant-feed` で実行できます。
- HYSYS ケースの調査用スクリプトは `scripts/` にあります。
- 分離機は HYSYS ケース側で構築中であり、Python 側にはまだ分離機専用モジュールはありません。
- `data/diagnostics/` には HYSYS ケースを COM 経由で調査した診断用 JSON を置いています。
- 厳密なリサイクル収束計算、経済収支計算は今後整理する対象です。

## 参考資料

- コンテスト課題: `data/chem_contest.md`
- 過去レポート: `data/report_md/~`, 

コンテスト課題は主要な参考資料ですが、最終的な設計判断は授業の目的と実際の検討内容を優先します。

## 開発環境

- OS: Windows
- Python: 3.11 を基本とする
- HYSYS: v14
- パッケージ管理: `uv`
- 静的解析: `ruff`
- テスト: 必要に応じて `pytest`

HYSYS との互換性の都合で Python バージョンを調整する可能性があります。

## セットアップ

```powershell
git clone https://github.com/Ri4385/process-design-2026.git
cd process-design-2026
uv sync
```

## ディレクトリ運用方針

### ディレクトリ概略

- `src/process_sim/`
  Python 実装を置く。
- `src/process_sim/constants/`
  反応器モデルなどで使う定数を置く。
- `src/process_sim/reactor/`
  反応器計算ロジックを置く。
- `src/process_sim/optimization/`
  最適化まわりの探索範囲、候補条件、制約値を置く。
- `src/process_sim/separator/`
  HYSYS 分離系との接続処理を置く。HYSYS COM オブジェクトはこの層の外に直接出さない方針である。
- `src/process_sim/plant/`
  反応器と分離系を接続し、プラント全体で固定される主要 stream の記録を扱う。
- `scripts/`
  実行スクリプト、HYSYS 接続確認、HYSYS ケース調査、反応器と HYSYS の接続試行を置く。
- `data/`
  参考資料や入力データを置く。
- `docs/`
  設計判断、前提条件、作業記録を置く。

### ディレクトリ詳細

- `src/process_sim/reactor/cases/`
  反応器の既定ケースを置く。
- `src/process_sim/reactor/core/`
  反応器の物質収支、反応速度、熱力学、ストリーム表現などの中核処理を置く。
- `src/process_sim/reactor/types/`
  反応器タイプごとのモデルを置く。
- `src/process_sim/optimization/`
  現在の構成は次の通りである。

  ```text
  src/process_sim/optimization/
    models.py          # 共通の探索範囲型
    reactor/
      parameters.py    # 反応器パラメータ範囲と候補条件
      constraints.py   # 反応器制約
  ```

  将来構成は次の通りである。

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
- `data/hysys/`
  HYSYS の `.hsc` などを置く想定である。
- `data/diagnostics/`
  HYSYS ケースの診断用 JSON を置く。これは人間向けのプロセスログではなく、ケース内部の状態確認用である。
- `data/report_md/`, `data/report_pdf/`
  過去レポートなどの参考資料を置く。
- `docs/reports/`
  Codex の作業記録、試算記録、比較結果をトピック単位で残す。
- `docs/overview.md`
  設定条件などの概要が書いてある。
- `docs/optimization.md`
  最適化まわりの探索範囲、候補条件、制約値の設計メモを置く。

### 実行

反応器単体を実行する場合は、以下を使います。

```powershell
uv run run-reactor-case
```

反応器単体は Python 側で完結して実行します。

プラントのワンパス実行は以下で行います。

```powershell
uv run run-plant-once
```

既定では `src/process_sim/plant/runner.py` の `DEFAULT_HYSYS_CASE_PATH` に設定された HYSYS ケースを使います。別ケースを使う場合は `--case-path` で指定します。Python 反応器出口を HYSYS 側の `reactor_outlet` stream に渡し、主要 stream の要約を出力します。

HYSYS 側の計算停止に備え、既定では子 Python プロセスに隔離して実行します。timeout は `src/process_sim/plant/runner.py` の `DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS` で管理し、CLI からは `--timeout-seconds` で変更できます。`--case-path` と `--hidden` は子プロセス側にも渡されます。

`run-plant-once` と `tune-plant-feed` は CLI 入口で logging を初期化し、plant 実行開始、使用する HYSYS case path、HYSYS 表示設定、反応器計算、分離計算の進行を標準エラーへ出します。

HYSYS の表示設定は用途で分けます。手動確認やデバッグ用の script 実行では、停止ダイアログやエラー内容を確認できるように `hysys_visible=True` を基本とします。自動探索では、ダイアログで処理が止まるのを避けるため `hysys_visible=False` または `--hidden` を明示して使う方針です。

目標 SM product 流量に合わせて fresh feed を調整する場合は、以下を使います。

```powershell
uv run tune-plant-feed --target-sm-kmol-h 240.033 --max-runs 5
```

`tune-plant-feed` は、目標 SM product 流量から初期 fresh feed と recycle 初期値を作り、2回目以降は直前 run の実効収率、未反応率、recycle 回収率から次回 fresh/recycle を計算します。secant 法は使いません。

主な引数は以下です。

- `--target-sm-kmol-h`
  目標とする `sm_product` 中の Styrene 流量です。
- `--max-runs`
  最大 plant 実行回数です。
- `--sm-tolerance-kmol-h`
  目標 SM 流量との差です。`0 <= SM product - target SM <= tolerance` の範囲を合格にします。既定値は `1.0 kmol/h` です。
- `--eb-recycle-tolerance-kmol-h`
  EB recycle の `output - input` に対する許容幅です。既定値は `1.0 kmol/h` です。
- `--h2o-recycle-tolerance-kmol-h`
  H2O recycle の `output - input` に対する許容幅です。既定値は `1.0 kmol/h` です。
- `--max-feed-step-fraction`
  旧 secant 更新用の設定です。現時点の初期値検証経路では使いません。
- `--case-path`
  使用する HYSYS ケースのパスです。

`tune-plant-feed` の HYSYS 表示は、複数回実行中にポップアップで止まることを避けるため `False` 固定です。

収束判定では、SM が目標以上かつ過剰分が許容内であること、EB recycle と H2O recycle の自己一致誤差が許容内であることを見ます。各 run 後に feed/SM と recycle consistency の累積表を logging で標準エラーへ出します。

## ドキュメント運用方針

- コード変更時は、必要に応じて関連文書も更新します。
- 設計上の仮定は一箇所にまとめて管理する方針です。
- 設計判断は、後から理由を追える形で残します。
- HYSYS 側の変更も、可能な限り文書として記録します。
- Codex を使った作業も、後から追跡できる形で残します。

## `docs/reports/` の命名規則

`docs/reports/` は日次ではなくトピック単位で管理します。

ファイル名の形式:

`YYYYMMDD_連番_topic-name.md`

例:

- `20260416_01_reactor-model-setup.md`
- `20260416_02_equilibrium-check.md`
- `20260416_03_hysys-interface-notes.md`

1ファイルには、原則として1つの主題だけを書きます。

加えて、通常は **1PRにつき `docs/reports/` は1ファイル** を基本とします。
（1PR内で内容が広がっても、同一ファイル内の見出しでまとめます。）

## 未確定事項

以下は現時点で未確定です。

- Python と HYSYS の接続方法の詳細
- HYSYS 分離機を Python 側でどこまで抽象化するか
- リサイクル収束計算の実装方針
- プラント全体ログの出力形式
- 経済収支計算に使う価格と出典の管理方法
- 数値モデルの妥当性確認に使う基準値
- 最終的な最適化の範囲

未確定事項は、その都度整理しながら `docs/` に反映していきます。
