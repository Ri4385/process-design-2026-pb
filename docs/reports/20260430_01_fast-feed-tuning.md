# 初期 fresh/recycle feed 設計

## 目的

SM product の目標流量に対応する初期 fresh feed と recycle 初期値を、HYSYS 実行結果の流量そのものではなく、設計上の比率から作る。

以前の実装では、1 回目を recycle なしで流し、2 回目から前回 recycle を足しながら fresh feed を secant 法で動かしていた。この方法では、fresh feed と recycle が同時に変わるため、fresh feed と SM product の対応が崩れる。さらに HYSYS の異常値を recycle として使う危険があった。

## 目標 SM 流量

`docs/overview.md` の設定値を根拠にする。

```text
SM 生産量 = 200,000 ton/year
稼働時間 = 8000 h/year
```

この値から、実装上の目標 SM product 流量は以下に固定する。

```text
DEFAULT_TARGET_SM_KMOL_H = 240.033 kmol/h
```

許容誤差は既存どおり `1.0 kmol/h` とし、勝手に広げない。

ここでいう `error` は以下である。

```text
error = SM product 中の Styrene 流量 - target SM
```

したがって正の値は目標より多く、負の値は目標より少ないことを表す。

## 初期値生成の定数

初期 fresh/recycle は以下の定数から作る。

```text
single_pass_sm_yield_from_eb = 0.50
eb_recycle_fraction = 0.99
h2o_recycle_fraction = 0.99
steam_to_eb_ratio = 5.0
```

`single_pass_sm_yield_from_eb` は初期値生成用の仮定であり、検証済み反応率ではない。`eb_recycle_fraction` は未反応 EB のうち recycle に戻る割合として扱う。`h2o_recycle_fraction` は反応器入口に必要な水のうち recycle で賄う割合として扱う。

## 初期値計算

目標 SM を `S` とする。

```text
reactor_inlet_EB = S / single_pass_sm_yield_from_eb
unreacted_EB = reactor_inlet_EB * (1 - single_pass_sm_yield_from_eb)
recycle_EB = unreacted_EB * eb_recycle_fraction
fresh_EB = reactor_inlet_EB - recycle_EB

reactor_inlet_H2O = reactor_inlet_EB * steam_to_eb_ratio
recycle_H2O = reactor_inlet_H2O * h2o_recycle_fraction
fresh_H2O = reactor_inlet_H2O - recycle_H2O
```

`S = 240.033 kmol/h` のとき、初期値は以下になる。

```text
reactor_inlet_EB = 480.066 kmol/h
unreacted_EB = 240.033 kmol/h
recycle_EB = 237.633 kmol/h
fresh_EB = 242.433 kmol/h

reactor_inlet_H2O = 2400.330 kmol/h
recycle_H2O = 2376.327 kmol/h
fresh_H2O = 24.003 kmol/h
```

初期 reactor feed は次の合計で作る。

```text
reactor EB = fresh_EB + recycle_EB
reactor H2O = fresh_H2O + recycle_H2O
```

## 実装方針

`src/process_sim/plant/production_target.py` に初期値生成用の定数と `InitialRecycleGuessPolicy`、`InitialFeedGuess` を置く。

`FreshFeedPolicy.steam_to_fresh_eb_ratio` で fresh steam を `fresh EB * 5` とする経路は、初期 recycle 付き feed では使わない。水は `reactor_inlet_H2O` を fresh と recycle に分けて決める。

secant 法は使わない。1 回目は比率から作った初期 fresh/recycle を使い、2 回目以降は直前 run の実効値を固定した直接解として次回 fresh/recycle を計算する。

直前 run から使う実効値は以下である。

```text
EB基準SM製品収率 = SM product / reactor inlet EB
EB単通未反応率 = reactor outlet EB / reactor inlet EB
EB recycle回収率 = EB recycle / reactor outlet EB

実効steam/EB比 = reactor inlet H2O / reactor inlet EB
H2O単通残存率 = reactor outlet H2O / reactor inlet H2O
H2O recycle回収率 = H2O recycle / reactor outlet H2O
```

次回値は以下で計算する。

```text
next reactor inlet EB = target SM / EB基準SM製品収率
next reactor outlet EB = next reactor inlet EB * EB単通未反応率
next EB recycle = next reactor outlet EB * EB recycle回収率
next fresh EB = next reactor inlet EB - next EB recycle

next reactor inlet H2O = next reactor inlet EB * 実効steam/EB比
next reactor outlet H2O = next reactor inlet H2O * H2O単通残存率
next H2O recycle = next reactor outlet H2O * H2O recycle回収率
next fresh H2O = next reactor inlet H2O - next H2O recycle
```

収束判定は以下をすべて満たす場合とする。

```text
0 <= SM margin <= 0.1 kmol/h
abs(EB recycle error) <= 0.1 kmol/h
abs(H2O recycle error) <= 0.1 kmol/h
```

ここで `SM margin = SM product - target SM`、`recycle error = output recycle - input recycle` である。

## 異常値の扱い

HYSYS から以下が出た場合は、正常な recycle として使わない。

```text
None
負流量
-32767
主要成分が存在しない
```

この場合は、その run の recycle を次回入力に採用せず、エラーとして停止する。

## visible の扱い

`tune-plant-feed` は複数回 HYSYS 実行になりうるため、HYSYS の表示は `False` を既定にする。手動確認用の `run-plant-once` とは別扱いにする。

## logging

CLI 実行時には、以下を標準エラーへ出す。

- target SM、SM margin 許容幅、EB/H2O recycle 許容幅、最大実行回数
- 初期 fresh EB、recycle EB、fresh H2O、recycle H2O
- 各 run 後の累積表

途中ログと最後の `Feed Tuning Summary` は、以下の 2 表で出す。

```text
[Feed and SM]
run freshEB freshH2O recEB recH2O reactorEB reactorH2O SM margin conv

[Recycle Consistency]
run comp input output error tol
```

## テスト

`tests/test_plant_feed_tuning.py` で以下を確認する。

- `target_sm = 240.033` から、上記の fresh/recycle 初期値が計算されること。
- SM margin、EB recycle、H2O recycle の許容幅がそれぞれ `1.0 kmol/h` であること。
- 初期値生成と直前 run の実効係数から次回 fresh/recycle を計算すること。
- HYSYS 異常値で停止すること。
