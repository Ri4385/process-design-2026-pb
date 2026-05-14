# Plant recycle convergence 実装

## 目的

Production target で求めた feed 条件を使い、EB recycle と H2O recycle の自己一致を確認する正式な plant recycle 収束計算を追加した。

## 実装方針

Plant 共通の固定値は `src/process_sim/plant/const.py` に集約した。対象は HYSYS case path、目標 SM 流量、recycle 許容幅、HYSYS timeout、HYSYS 異常値 sentinel である。

収束計算本体は `src/process_sim/plant/convergence.py` に置いた。`PlantFeedPlan` は実装量が小さく、`feed.py` と役割が混ざるのを避けるため、この module 内に定義した。

## 収束手順

`run_production_target_convergence()` は以下の順で動く。

```text
1. tune_fresh_feed_fast() で production target 計算を行う
2. 最終 run から PlantFeedPlan を作る
3. run_plant_convergence() で recycle 収束計算を行う
```

反復は以下で行う。

```text
初回:
  reactor feed = startup_reactor_feed
  recycle input = 0

2回目以降:
  reactor feed = steady_fresh_feed + previous recycle output
```

収束判定は以下を両方満たす場合である。

```text
abs(output EB recycle - input EB recycle) <= 0.1 kmol/h
abs(output H2O recycle - input H2O recycle) <= 0.1 kmol/h
```

SM product は各 iteration で記録するが、recycle convergence の判定には使わない。

## Production target 判定修正

Production target 側の SM 判定は、浮動小数点数誤差で微小な負値になった場合に未収束扱いにならないようにした。

```text
SM margin >= -1e-9
SM margin <= tolerance + 1e-9
```

## 実行入口

確認用 CLI は以下である。

```powershell
uv run run-plant-convergence
```

固定 feed plan を自分で書いて動かす用途には `scripts/run_fixed_plant_convergence.py` を追加した。

## テスト

重い反応器計算や HYSYS 実行は避け、fake runner で収束ロジックの要点だけを確認する。
