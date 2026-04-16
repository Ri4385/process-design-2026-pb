# 20260416_01_reactor-docs-policy-and-hysys-bridge

## 主題

反応器まわりの文書運用と、現在の HYSYS ブリッジ実装の最小範囲を整理する。

## 今回の方針

- 恒久的に参照する内容は `docs/reactor.md` に集約する。
- `docs/reactor.md` は追記で増やすのではなく、同じファイルを上書き更新する。
- `docs/reports/` は PR 単位の作業記録だけを書く。
- 同一 PR で反応器に関する記録が増えても、`docs/reports/` は 1 ファイルにまとめる。

## 現在の HYSYS ブリッジ実装

- Python 側で `StyreneReactorModel` を実行する。
- HYSYS 側とは `ReactorService` のタグ入出力で接続する。
- 現在の入口タグは `EB`、`steam`、`pressure`、`temperature` のみである。
- 入口の `styrene`、`hydrogen`、`benzene`、`toluene`、`co2` は `ReactorService.run_once()` 内で 0.0 固定で与えている。
- 現在の出口タグは各成分出口流量と `EB` 転化率である。

## 補足

- 反応器モデルの現状仕様、入出力、出力の意味、既定条件での出力例は `docs/reactor.md` に整理した。
- このファイルは今回の PR における運用整理の記録として残す。
