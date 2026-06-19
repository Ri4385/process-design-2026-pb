# HYSYS global timeout 設計メモ

## 背景

全体最適化 v2 では、各 trial で反応器計算、HYSYS 分離計算、recycle convergence、機器読み取り、コスト評価を行う。HYSYS は条件によって計算が返らない場合があり、同一 Python process 内で `solver.IsSolving` を監視するだけでは停止を保証できない。

現状の `wait_for_hysys_calculation()` は、`solver.Solve()` または `solver.Run()` が Python 側へ戻ってきた後に `IsSolving` を確認する実装である。そのため、COM 呼び出し自体が返らない場合には timeout として機能しない。

ユーザー実行時の観測では、通常の最終 convergence 到達までの時間はおおむね 16-34 s 程度である。一方で HYSYS 初回起動は遅い場合があるため、trial の timeout 判定に初回起動時間を含めると、正常条件も不当に prune される可能性がある。

## 結論

HYSYS が値を返さないことを前提にする場合、timeout は process 境界でかける必要がある。同一 process 内の thread、signal、`time.monotonic()` 監視では、COM 呼び出しが固着した場合に停止できない。

今回の方針では、separator 1 回ごとの timeout ではなく、trial 全体に対する global timeout を採用する。

採用方針は以下である。

```text
Optuna 親 process
  study 実行、trial 管理、timeout 監視、prune 判定を行う

trial worker process
  HYSYS case を1回だけ開く
  その trial 内で production target、recycle convergence、cost 評価を実行する
  結果を親 process へ返す

timeout 時
  親 process が trial worker process を terminate する
  該当 trial は TrialPruned として扱う
```

この方式では、固定 parameter 群、すなわち 1 trial について HYSYS case を開くのは 1 回までにできる。その後の trial 内の separator 計算は、同じ HYSYS session を使い回す。

## 初回 HYSYS 起動への対応

trial 実行前に prewarm を行う。

```text
1. Optuna 探索開始前に HYSYS を1回開く
2. default radial reactor case で separator を1回実行する
3. case を保存せず閉じる
4. その後に trial worker を起動し、global timeout を適用する
```

prewarm は HYSYS 初回起動と初回 solver 実行の遅さを trial timeout から切り離す目的で行う。prewarm 自体にも別 timeout を設ける。prewarm が失敗した場合は、探索開始前の環境エラーとして扱い、trial prune ではなく実行停止とする。

## timeout 秒数の考え方

通常条件で 16-34 s 程度かかるため、global timeout は 5 s では短すぎる。5 s は separator 1 回単位なら候補になり得るが、trial 全体の timeout としては正常計算も prune する可能性が高い。

現状案では、trial 全体 timeout の既定値は 60 s 程度が妥当である。観測値 34 s に対し、HYSYS の一時的な遅延と Python 側のコスト評価を含める余裕を持たせる。

```text
prewarm timeout: 180 s
trial global timeout: 60 s
```

この値は実行ログを見ながら調整する。

## separator 1 回 timeout を採用しない理由

separator 1 回に対して確実な timeout をかけるには、separator 1 回を別 process にする必要がある。しかしその場合、HYSYS COM object は process 間で安全に渡せないため、各 separator worker が HYSYS を開く必要がある。

これは次の必須仕様と衝突する。

```text
固定 parameter 群では HYSYS を開けるのは1回まで
その後は同じ HYSYS session を使い回す
```

そのため、今回の必須仕様を優先し、separator 1 回 timeout ではなく trial 全体 timeout とする。

## 修正対象

主な修正対象は以下である。

```text
src/process_sim/optimization/runner/whole_plant_optuna_v2.py
  Optuna trial を timeout 付き worker process で実行する
  TimeoutError を optuna.TrialPruned へ変換する

src/process_sim/plant/session_runner.py
  trial worker 内では現行の OpenHysysPlantRunner を使い、HYSYS session を再利用する

src/process_sim/separator/hysys_io.py
  prewarm 用に HYSYS case を開いて閉じる小さな関数を追加する候補

src/process_sim/plant/const.py
  prewarm timeout と trial global timeout の既定値を追加する候補
```

追加 module を切る場合の候補は以下である。

```text
src/process_sim/optimization/runner/whole_plant_timeout_worker.py
  worker process で実行する関数を分離する
  親 process との受け渡し用 payload と result を定義する
```

## 修正しない対象

以下は今回の主対象にしない。

```text
src/process_sim/optimization/runner/whole_plant_optuna_v1.py
src/process_sim/optimization/runner/reactor_pareto_v2_optuna.py
src/process_sim/optimization/runner/radial_pareto_optuna.py
src/process_sim/optimization/runner/radial_simple_optuna.py
scripts/whole_plant_optuna_v1/
scripts/reactor_pareto_v2/
```

今回の timeout 方針は、固定寸法 radial 方針の `whole_plant_optuna_v2` を対象とする。

## 実装仕様案

`whole_plant_optuna_v2.py` の objective は、直接 HYSYS を呼ばず、worker process を起動して結果を待つ。

```text
objective(trial)
  candidate を作る
  worker payload を作る
  worker process を起動する
  result queue を trial timeout 秒だけ待つ
  timeout したら worker を terminate して TrialPruned
  result が例外なら TrialPruned または fail に変換
  result が正常なら trial attrs を保存して目的関数値を返す
```

worker process 側では、現在の `OpenHysysPlantRunner` を使う。

```text
worker(payload)
  pythoncom.CoInitialize は hysys_case 内で行う
  HYSYS case を1回開く
  production target と convergence を同一 session で実行する
  同一 session から equipment を読む
  cost を評価する
  親 process へ結果を返す
```

`multiprocessing` は Windows 前提のため `spawn` で動く。worker に渡す値は pydantic model、dataclass、dict、float、str、Path など pickle 可能な値に限定する。COM object は渡さない。

## 例外の扱い

以下は prune とする。

```text
trial global timeout
HYSYS 計算停止
HYSYS から invalid sentinel が返る
制約違反
コスト評価で物理的に成立しない条件
```

以下は fail または探索停止候補とする。

```text
HYSYS case を開けない
prewarm が失敗する
worker protocol の実装不整合
pickle できない payload/result
```

## 既知の制約

timeout 時には worker process を kill するため、その worker 内で開いていた HYSYS session は破棄される。これは正常な cleanup より粗い停止であり、HYSYS 側の残存 process が発生する可能性がある。

そのため、timeout 後に次 trial を続ける場合は、新しい worker process を起動する。残存 HYSYS process の監視や掃除は、必要になった段階で別途扱う。

また、trial ごとに worker process を起動するため、完全な同一 process 内再利用よりは遅くなる。ただし、trial 内では HYSYS case を1回だけ開き、production target と recycle convergence では session を使い回せる。

## 採用しない案

### 同一 process 内 timeout

COM 呼び出しが返らない場合に停止できないため採用しない。

### 親 process で開いた HYSYS COM object を子 process に渡す

COM object は Python の通常 object として process 間共有できないため採用しない。

### separator 1 回ごとの process timeout

timeout は確実になるが、separator 1 回ごとに HYSYS を開く必要が出るため、必須仕様に合わない。

## 未確定要素

trial global timeout の既定値は未確定である。現時点では 60 s を候補とする。

prewarm timeout の既定値は未確定である。現時点では 120 s を候補とする。

timeout した worker の HYSYS process が残る場合の cleanup 方針は未確定である。

timeout 以外の HYSYS 例外をすべて prune にするか、一部を fail として残すかは実装時に整理する。

## 実装結果

2026-06-08 時点で、`whole_plant_optuna_v2` に global timeout を実装した。

修正対象は以下である。

```text
src/process_sim/optimization/runner/whole_plant_optuna_v2.py
  trial 全体を multiprocessing worker process で実行する
  親 process は 60 s 待ち、超過時は worker を terminate する
  timeout、HYSYS 例外、制約違反、コスト評価例外はいずれも TrialPruned として扱う
  worker から親へは目的関数値と user_attrs のみ返す
  親 process の簡易ログは logs/whole_plant_optuna_v2.log に出す
  prewarm と trial worker の詳細ログは logs/whole_plant_optuna_v2_detail.log に出す

src/process_sim/plant/const.py
  DEFAULT_HYSYS_PREWARM_TIMEOUT_SECONDS = 180.0
  DEFAULT_WHOLE_PLANT_TRIAL_TIMEOUT_SECONDS = 60.0
```

prewarm も worker process で実行し、180 s を超えた場合は探索開始前の実行エラーとして扱う。trial timeout とは異なり、prewarm 失敗は候補条件に依存しないため prune にはしない。prewarm は default radial reactor case を使い、HYSYS case を開いたうえで separator まで1回実行する。

ログは簡易ログと詳細ログを分ける。簡易ログは親 process の study 開始、trial 開始、prune、完了を追う用途とする。詳細ログは worker process 内で HYSYS case open、反応器詳細、plant run summary、recycle/product component summary、plant convergence、post convergence control、機器読み取り、prewarm の開始・終了・例外を追う用途とする。

検証は以下を実行した。

```powershell
uv --cache-dir .uv-cache run ruff check src/process_sim/optimization/runner/whole_plant_optuna_v2.py src/process_sim/separator/hysys_io.py src/process_sim/plant/const.py
uv --cache-dir .uv-cache run pyright
```

いずれもエラーなしである。HYSYS を起動する探索実行は行っていない。
