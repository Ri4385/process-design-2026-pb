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
- HYSYS ケースの調査と、反応器出口を HYSYS 側へ渡す処理は `scripts/` にあります。
- 分離機は HYSYS ケース側で構築中であり、Python 側にはまだ分離機専用モジュールはありません。
- `data/diagnostics/` には HYSYS ケースを COM 経由で調査した診断用 JSON を置いています。
- リサイクル収束計算、プラント全体ログ、経済収支計算は今後整理する対象です。

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

- `src/process_sim/`
  Python 実装を置きます。
- `src/process_sim/constants/`
  反応器モデルなどで使う定数を置きます。
- `src/process_sim/reactor/`
  反応器計算ロジックを置きます。
- `src/process_sim/reactor/cases/`
  反応器の既定ケースを置きます。
- `src/process_sim/reactor/core/`
  反応器の物質収支、反応速度、熱力学、ストリーム表現などの中核処理を置きます。
- `src/process_sim/reactor/types/`
  反応器タイプごとのモデルを置きます。
- `src/process_sim/separator/`
  HYSYS 分離系との接続処理を置きます。HYSYS COM オブジェクトはこの層の外に直接出さない方針です。
- `src/process_sim/plant/`
  反応器と分離系を接続し、プラント全体で固定される主要 stream の記録を扱います。
- `scripts/`
  実行スクリプト、HYSYS 接続確認、HYSYS ケース調査、反応器と HYSYS の接続試行を置きます。
- `data/`
  参考資料や入力データを置きます。
- `data/hysys/`
  HYSYS の `.hsc` などを置く想定です。
- `data/diagnostics/`
  HYSYS ケースの診断用 JSON を置きます。これは人間向けのプロセスログではなく、ケース内部の状態確認用です。
- `data/report_md/`, `data/report_pdf/`
  過去レポートなどの参考資料を置きます。
- `docs/`
  設計判断、前提条件、作業記録を置きます。
- `docs/reports/`
  Codex の作業記録、試算記録、比較結果をトピック単位で残します。
- `docs/overview.md`
  設定条件などの概要が書いてあります

### 実行

```powershell
uv run run-reactor-case
```

反応器単体は Python 側で完結して実行します。HYSYS 連携を含む確認は `scripts/` の個別スクリプトから実行します。

プラントのワンパス実行は以下のスクリプトから行います。

```powershell
uv run python scripts/run_plant_once.py
```

既定では `data/hysys/process_design_0430v3.hsc` を使い、Python 反応器出口を HYSYS 側の `reactor_outlet` stream に渡して、主要 stream を JSON で出力します。

HYSYS 側の計算停止に備え、既定では子 Python プロセスに隔離して実行します。timeout は `src/process_sim/plant/runner.py` の `DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS` で管理します。

HYSYS の表示設定は用途で分けます。手動確認やデバッグ用の script 実行では、停止ダイアログやエラー内容を確認できるように `hysys_visible=True` を基本とします。Optuna などの自動探索では、ダイアログで処理が止まるのを避けるため `hysys_visible=False` を明示して使う方針です。

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
