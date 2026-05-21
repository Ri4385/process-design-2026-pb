# fast production target HYSYS session 設計

## 目的

`tune-plant-feed` と `run-plant-convergence` は、複数回の plant run を行うたびに HYSYS case を開いて閉じる。HYSYS case の open/close が時間を要するため、production target や recycle convergence の一連の計算中は、同じ HYSYS case を開いたまま再利用する実行経路を追加する。

既存の実行経路は残し、短い範囲の追加で `fast-production-target` と `fast-plant-convergence` 相当の入口を作る方針とする。

## 現状確認

現在の HYSYS 接続は `src/process_sim/separator/hysys_io.py` に集約されている。

- `hysys_case(case_path, visible)`
  HYSYS application を接続し、case を開き、終了時に case close と application quit を行う。
- `run_hysys_separation_once(...)`
  `hysys_case` を使って1回分の分離計算を実行する。
- `src/process_sim/plant/runner.py`
  `run_plant_once` が反応器計算後に `run_hysys_separation_once` を呼ぶ。
- `src/process_sim/plant/production_target.py`
  `tune_fresh_feed_fast` が `PlantRunner` を複数回呼ぶ。
- `src/process_sim/plant/convergence.py`
  `run_plant_convergence` と `run_production_target_convergence` が同じ `PlantRunner` を反復実行する。

このため、既存の `run_plant_once_for_reactor_case` を使う限り、production target の各 run と convergence の各 iteration で HYSYS case が開閉される。

## 採用方針

HYSYS case を保持する session runner を追加する。

追加する runner は、最初に HYSYS case を1回だけ開き、同一 process 内で複数の reactor case を順に流す。各 run では、反応器出口を既存 case の `reactor_outlet` stream に書き込み、HYSYS solve 後に既存と同じ主要 stream を読む。

既存の `run_plant_once`、`tune-plant-feed`、`run-plant-convergence` は変更しない。新規 CLI からのみ session runner を使う。

まずは、production target と convergence を1つの HYSYS session で連続実行できる経路を作る。これにより、production target 後に convergence 用として HYSYS case を開き直す時間を避けられる。初期実装では、途中で HYSYS case を開き直す安全策は入れない。

fast 系 CLI は基本的に引数を持たせない。既定の HYSYS case、既定 target SM、既定 radial 反応器を使う。HYSYS visible は `False` 固定にする。探索条件によって HYSYS の UI や停止ダイアログが出ると処理が止まり続けるため、fast 実行では GUI 表示を避ける。

一方で、ハイパーパラメータ探索の全 trial を1つの HYSYS session に固定することは、初期実装では既定にしない。探索では多数の条件を連続して流すため、HYSYS case 内部状態、未解放 COM 状態、前 trial の残留状態が蓄積するリスクがある。実装としては可能にしておくが、既定は「1 trial または1 production target 単位で session を閉じる」方が説明しやすい。

## 想定ファイル構成

```text
src/process_sim/
  separator/
    hysys_io.py
      HYSYS case を開いたまま使う低レベル関数を追加する。
  plant/
    session_runner.py
      HYSYS session を保持する PlantRunner を定義する。
    fast_production_target.py
      fast production target 用 CLI を定義する。
    fast_convergence.py
      fast plant convergence 用 CLI を定義する。
    production_target.py
      既存の feed tuning ロジックはそのまま利用する。
    convergence.py
      既存の convergence ロジックはそのまま利用する。
pyproject.toml
  fast-production-target と fast-plant-convergence などの CLI entry point を追加する。
```

## 責務

### `separator/hysys_io.py`

HYSYS COM オブジェクトを外へ直接出さない方針を維持する。

追加候補:

- `run_hysys_separation_with_open_case(...)`
  既に開いている `simulation_case` を受け取り、1回分の stream 書き込み、solve、stream 読み取りだけを行う。
- 既存の `run_hysys_separation_once(...)`
  従来通り、開閉込みの単発実行として残す。

この追加により、case open/close と1回分の分離計算を分離する。

### `plant/session_runner.py`

HYSYS case を保持する context manager 型の runner を定義する。

想定クラス:

- `OpenHysysPlantRunner`
  - `case_path`
  - `hysys_visible`
  - `reactor_model`
  - `log_reactor_detail`
  - `__enter__` で HYSYS case を開く
  - `__exit__` で HYSYS case を閉じ、HYSYS application を終了する
  - `__call__(reactor_case)` で `PlantRunRecord` を返す

`__call__` の戻り値は既存の `PlantRunner` と同じ `PlantRunRecord` にする。これにより `tune_fresh_feed_fast` と `run_plant_convergence` は既存のまま使える。

### `plant/fast_production_target.py`

production target 用の新しい CLI 入口を定義する。

- `fast-production-target`
  production target のみを、HYSYS case を開いたまま実行する。

### `plant/fast_convergence.py`

convergence 用の新しい CLI 入口を定義する。

- `fast-plant-convergence`
  production target と recycle convergence を、同じ HYSYS session で続けて実行する。

今回の主対象は、production target と convergence を1つの session で実行する `fast-plant-convergence` である。`fast-production-target` は、ハイパーパラメータ探索から production target だけを呼ぶ場合にも使えるように残す。

`run_production_target_convergence` を高速化する場合は、production target runner と convergence runner に同じ `OpenHysysPlantRunner` インスタンスを渡す。

`fast_convergence.py` は `convergence.py` のロジックを移行しない。既存の `run_production_target_convergence` を呼び、runner だけ session 再利用版に差し替える。`convergence.py` は変更しないため、production target と convergence の既存依存関係はそのまま維持する。

### ハイパーパラメータ探索との接続

ハイパーパラメータ探索では、以下の2つの運用を許容できる設計にする。

- 既定運用:
  1 trial の production target ごとに HYSYS session を開き、trial 終了時に閉じる。
- 高速運用:
  探索 runner 側で `OpenHysysPlantRunner` を1つ開き、複数 trial に同じ runner を渡す。

ただし、高速運用は初期実装の既定にはしない。全 trial で HYSYS case を開きっぱなしにすると、前 trial の状態が次 trial に影響する可能性を切り分けにくい。探索では production target だけを呼ぶ想定なので、convergence のたびに開き直すかどうかは探索側の主要な時間増加要因ではない。

## 実行イメージ

```powershell
uv run fast-production-target
uv run fast-plant-convergence
```

production target だけを対象にする場合は、内部で以下のように動く。

```python
with OpenHysysPlantRunner(case_path=args.case_path, hysys_visible=False, reactor_model=args.reactor_model) as runner:
    result = tune_fresh_feed_fast(
        options=options,
        base_reactor_case=default_reactor_case_for_model(args.reactor_model),
        plant_runner=runner,
        reactor_model=args.reactor_model,
    )
```

convergence まで続ける場合は、同じ `runner` を `run_production_target_convergence` の `production_target_runner` と `convergence_runner` に渡す。

```python
with OpenHysysPlantRunner(case_path=args.case_path, hysys_visible=False, reactor_model=args.reactor_model) as runner:
    result = run_production_target_convergence(
        target_sm_kmol_h=args.target_sm_kmol_h,
        production_target_runner=runner,
        convergence_runner=runner,
        reactor_model=args.reactor_model,
    )
```

## 影響範囲

影響するのは以下に限定できる。

- `separator/hysys_io.py`
  開いている case に対して1回分の分離計算を行う関数を追加する。
- `plant/session_runner.py`
  新規追加。
- `plant/fast_production_target.py`
  新規追加。
- `plant/fast_convergence.py`
  新規追加。
- `pyproject.toml`
  CLI entry point を追加する。
- `README.md`
  新規 CLI の実行方法を短く追記する。

既存の `production_target.py` と `convergence.py` は、原則として変更不要である。CLI 引数処理を共通化したい場合のみ小変更が発生するが、最初の実装では重複を許容した方が変更範囲は小さい。

## 採用しない案

### 既存 `run_plant_once` を直接変更する案

採用しない。`run_plant_once` は単発実行として分かりやすく、timeout 用の子 process 実行とも結びついている。ここに session 状態を混ぜると、既存 CLI の挙動が変わる。

### `hysys_case` を閉じないように変更する案

採用しない。既存の context manager は、開いたものを閉じる責務が明確である。閉じない動作を既存名に入れると、HYSYS application が残る原因になる。

### HYSYS COM オブジェクトを `production_target.py` へ渡す案

採用しない。HYSYS COM オブジェクトを plant や production target 層へ出すと、既存の境界設計に反する。COM 操作は `separator` と session runner 内に閉じる。

## 既知の制約

- 同じ HYSYS case を連続更新するため、case 内部状態が前 run の影響を受ける可能性は残る。production target から convergence までの同一 session では許容するが、全探索 trial を同一 session にする場合は影響確認が必要である。
- HYSYS の solve 完了判定は、既存の `wait_for_hysys_calculation` の範囲に留まる。収束確認済みとは書かない。
- HYSYS が途中でエラーやダイアログ停止した場合、session 全体が止まる可能性がある。
- timeout の扱いは既存 `run_plant_once` の子 process 隔離とは異なる。fast CLI 初期版では、session 全体を同一 process で実行する。

## テスト方針

今回はテストを追加しない。

理由は、HYSYS COM 実行を伴う動作確認はユーザーのローカル環境での実行結果を根拠に扱うためである。既存の純 Python ロジックは変更しない前提なので、production target と convergence の既存単体テスト対象には触れない。

## 実装結果

以下を追加した。

- `src/process_sim/separator/hysys_io.py`
  - `run_hysys_separation_with_open_case`
  - `HysysSeparationSession`
- `src/process_sim/plant/session_runner.py`
  - `OpenHysysPlantRunner`
- `src/process_sim/plant/fast_production_target.py`
  - `fast_production_target_main`
- `src/process_sim/plant/fast_convergence.py`
  - `fast_plant_convergence_main`
- `pyproject.toml`
  - `fast-production-target`
  - `fast-plant-convergence`

`fast-production-target` と `fast-plant-convergence` は CLI 引数を持たない。どちらも `DEFAULT_HYSYS_CASE_PATH`、`DEFAULT_TARGET_SM_KMOL_H`、radial 反応器を使う。HYSYS visible は `False` 固定である。

`fast-plant-convergence` では、production target と convergence に同じ `OpenHysysPlantRunner` を渡す。したがって、production target 後に convergence 用として HYSYS case を開き直さない。

確認は以下のみ実施した。HYSYS case の実行確認はしていない。

- `uv run pyright`
- `uv run ruff check src/process_sim/separator/hysys_io.py src/process_sim/plant/session_runner.py src/process_sim/plant/fast_production_target.py`
- 新規 CLI 入口の import 確認

## 未確定要素

- ハイパーパラメータ探索で、全 trial 同一 session を許可する実行オプション名をどうするか。
- 探索で同一 session を使う場合、何 trial ごとに HYSYS case を開き直す安全策を入れるか。
- fast CLI で timeout を設けるか。設ける場合は、session 全体 timeout か、各 run timeout かを決める必要がある。
