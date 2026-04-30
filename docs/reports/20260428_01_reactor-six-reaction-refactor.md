# 反応器6反応モデルへの再構成

## 目的

反応器モデルを、今後複数の反応器型を試せる構成へ整理した。
併せて、3 反応モデルを削除し、`data/chem_contest.md` の 6 反応モデルへ切り替えた。

## 変更内容

- 物性値を `src/process_sim/constants/physical_properties.py` に集約した。
- 反応ネットワークを `src/process_sim/constants/reaction_networks.py` に定義した。
- 普遍定数と単位換算を `src/process_sim/constants/universal.py` に分離した。
- 反応器共通計算を `src/process_sim/reactor/core/` に分離した。
- 具体的な多段断熱 PFR を `src/process_sim/reactor/types/staged_adiabatic_pfr.py` に置いた。
- 既定 feed と運転条件を `src/process_sim/reactor/cases/styrene_default.py` に置いた。
- CLI から feed と条件の直書きを削除した。

## 反応熱の扱い

反応熱は固定値ではなく、反応の化学量論と各成分のエンタルピーから算出する。
各成分のエンタルピーは、標準生成エンタルピーと Cp 積分から計算する。

基準温度の標準反応熱は、`docs/physical_property.md` の物性値から次の値として計算される。

| 反応 | 標準反応熱 [kJ/kmol] |
| :--- | ---: |
| EB ⇆ SM + H2 | 117700 |
| EB -> BZ + C2H4 | 105500 |
| EB + H2 -> TL + CH4 | -54700 |
| 2H2O + C2H4 -> 2CO + 4H2 | 210500 |
| H2O + CH4 -> CO + 3H2 | 206300 |
| H2O + CO -> CO2 + H2 | -41200 |

## 確認結果

- `uv run pytest` で 9 件のテストが通った。
- `uv run run-reactor-case` で人間向けログを出力できることを確認した。
- `uv run run-reactor-case --json` で JSON 出力できることを確認した。

## 注意点

- 既定ケースの計算結果は、6 反応モデルへの切り替えにより以前の 3 反応モデルと大きく異なる。
- 現時点では HYSYS 結果、文献値、手計算のどれに合わせるかは未確定である。
- この作業では、6 反応モデルの実装整合性のみを確認し、設計値としての妥当性確認は行っていない。
