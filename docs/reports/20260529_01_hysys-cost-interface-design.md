# HYSYS 連携コスト計算の初期設計

## 目的

HYSYS からコスト計算に必要な値を読み取り、経済収支の評価関数へ渡せるようにする。

今回の設計は、実装を一気に作り込むための詳細仕様ではなく、次にどの範囲から進めるかを確認するための初期整理である。特に、HYSYS COM から値を読む汎用インターフェイスと、どの HYSYS stream や operation がプロセス上のどの費目に対応するかを知る層を分けるかを検討対象にする。

## 今回の作業範囲案

初期実装の範囲は、HYSYS から値を読む部分の整理に限定するのが適切である。

理由は次の通りである。

- `src/process_sim/separator/hysys_io.py` は、COM 接続、stream 読み書き、plant 固定 stream の意味付けが同じファイルに集まり始めている。
- コスト計算では material stream、energy stream、operation、spreadsheet、column hydraulics を読む必要があり、現状のまま追加すると `hysys_io.py` がさらに肥大化する。
- Heat integration は今後必要になるが、必要な温度範囲や熱流リストの整理が先であり、今回の最小設計に含めると判断点が増えすぎる。

したがって、今回の第一段階では次を扱う。

```text
1. HYSYS から必要な raw value を読む汎用インターフェイス
2. HYSYS 上の stream/operation 名を、コスト計算上の費目へ対応付ける mapping
3. mapping と raw value から Python 側の明示的なモデルへ変換する薄い reader
```

コスト式そのものの本格実装、Heat integration、最適化目的関数への接続は次段階で確認する。

## ディレクトリ構成案

最小変更の場合は、既存の `separator/` と `plant/economics.py` を壊さず、HYSYS 読み取りと費目 mapping だけを追加する。

```text
src/process_sim/
  separator/
    hysys_io.py              # HYSYS COM 接続、stream/operation/energy/spreadsheet の汎用読み取り
    hysys_cost_map.py        # HYSYS 名とコスト費目の対応表
    hysys_cost_reader.py     # 対応表を使って CostInputRecord に変換
  plant/
    economics.py             # 既存の経済計算関数。式の追加は次段階で検討
    cost_models.py           # コスト計算入力と内訳の Pydantic model
docs/
  cost.md                    # コスト式と単価の根拠
  reports/
    20260529_01_hysys-cost-interface-design.md
```

各ファイルの責務は次の通りである。

- `separator/hysys_io.py`
  - HYSYS COM オブジェクトへの低レベルアクセスを担当する。
  - stream が製品、オフガス、デカンター後などの意味を持つことは知らない。
  - material stream、energy stream、operation、spreadsheet cell を指定名で読む関数を提供する。
- `separator/hysys_cost_map.py`
  - `T-1`、`TQ-11`、`CQ-1` など、HYSYS 上の名前とコスト費目の対応を持つ。
  - プロセス上の意味を知る層である。
- `separator/hysys_cost_reader.py`
  - `hysys_io.py` と `hysys_cost_map.py` を使い、HYSYS 由来の値を Python 側のモデルへ変換する。
  - COM オブジェクトは外へ出さない。
- `plant/cost_models.py`
  - HYSYS から読んだ値、機器費、用役費、年間収支などの明示的な `pydantic.BaseModel` を置く。
- `plant/economics.py`
  - コスト式と評価関数を担当する。
  - 既存の暫定関数をすぐに壊さず、次段階で整理する。

## 必要情報

経済収支の評価関数を考える必要がある

リボイラ、コンデンサはQ,U, ΔT\_lmからAを求め、熱交換器として計算。

| 項目 | 対象のHYSYS | エネルギーフロー | 備考 |
| :---- | :---- | :---- | :---- |
| 入口加熱 steam |  | E-heat-water |  |
| 入口加熱 EB |  | E-heat-EB |  |
| 入口加熱 反応器前のtrim heater |  | QE-2 |  |
| 入口加圧 ポンプ水 |  | PQ-2 |  |
| 入口加圧 ポンプEB |  | PQ-1 |  |
| 反応器機器費(反応器の台数分) | Python実装 |  |  |
| 反応器の熱交換器 装置費 | Python実装 |  |  |
| 反応器 熱交換器　用役費 | Python実装 |  |  |
| デカンター 装置費 | SPRDSHT-1（デカンター1基目） SPRDSHT-2（デカンター2基目） |  | A2：半径 A3：長さ |
| デカンター 冷却用役費 |  | CQ-1 CQ-2 | CQ-n：n基目 |
| デカンター 冷却熱交換器装置費 |  |  |  |
| SM分離塔前 バルブ減圧 | VLV-1-2 VLV-2 |  | コスト不明→圧力によるコストはなさそう バルブ自体の装置コストは無視？ \[7\] 貯槽、バルブ、配管、ポンプ、電気・計装、建屋など \[1\]～\[6\]までの機器費合計の1.0倍とする。これで最後にするから無視でよい？ |
| SM分離塔 装置費 | T-1 |  | 液密度,蒸気密度,蒸気流量→直径、段数→高さ |
| SM分離塔 リボイラ装置費 |  |  |  |
| SM分離塔 リボイラ用役費 |  | TQ-12 |  |
| SM分離塔 コンデンサ装置費 |  |  |  |
| SM分離塔 コンデンサ用役費 |  | TQ-11 |  |
| SM分離塔後 ポンプ加圧 |  | PQ-3 |  |
| SM分離塔後 排ガスコンプレッサー加圧 |  | KQ-2 |  |
| EB分離塔 装置費 | T-2 |  | 液密度,蒸気密度,蒸気流量→直径、段数→高さ |
| EB分離塔 リボイラ装置費 |  |  |  |
| EB分離塔 リボイラ用役費 |  | TQ-22 |  |
| EB分離塔 コンデンサ装置費 |  |  |  |
| EB分離塔 コンデンサ用役費 |  | TQ-21 |  |
| BZTL分離塔 装置費 | T-3 |  | 液密度,蒸気密度,蒸気流量→直径、段数→高さ |
| BZTL分離塔 リボイラ装置費 |  |  | Q,UからAを求め計算 |
| BZTL分離塔 リボイラ用役費 |  | TQ-32 |  |
| BZTL分離塔 コンデンサ装置費 |   |  |  |
| BZTL分離塔 コンデンサ用役費 |  | TQ-31 |  |
| ストリッパーコンデンサ用役費 | \- |  | 無視？ |
| ストリッパーリボイラ用役費 | \- |  | 無視？ |
| 製品加圧ポンプ SM |  | PQ-4 |  |
| 製品冷却 SM |  | CQ-3 |  |
| 製品冷却 BZ |  | CQ-4 |  |
| 製品冷却 TL |  | CQ-5 |  |
| 建設費 |  |  | 建設費含めたコストが全装置費の2.5倍 つまり、建設費単体だと装置費の1.5倍 |

## 初期モデル案

HYSYS から読んだ値は、すぐに cost 式へ渡さず、まず入力モデルにまとめる。

```text
CostInputRecord
  energy_duties
  pumps
  compressors
  decanters
  distillation_columns
  heat_exchangers
  products
  feeds
```

この段階では、値が取れない項目を無理に仮定で埋めない。取得不可、未実装、無視候補を区別して記録する。

## 判断理由

`hysys_io.py` を完全に分割するより、まず低レベル関数は残し、コスト用の mapping と reader を外出しする方が変更量を抑えられる。既存の plant convergence や分離計算の動作に触れずに、コスト計算用の読み取りだけを増やせるためである。

Heat integration は、温度区間付きの熱流リストが必要になる。現時点では HYSYS から読むべき heat stream と、Python 実装側の反応器熱交換器を同じ形式で表すことが先である。そのため、今回の設計では HI を直接実装対象にせず、将来 `heat_integration/` へ渡せる入力形式を意識するに留める。

## 今回は作らない範囲

- HYSYS の起動を伴う検証
- コスト評価関数の本実装
- Heat integration の実装
- Optuna など最適化 runner への接続
- `separator/hysys_io.py` の大規模分割
- scripts 配下のテスト追加

## 未確定要素

- 第一段階で読む対象を、表の全項目にするか、分離系と製品冷却までに限定するか。
- `hysys_io.py` から cost 用の低レベル読み取りも分離するか、まずは mapping と reader だけを追加するか。
- デカンターの `SPRDSHT-1`, `SPRDSHT-2` は spreadsheet cell から半径と長さを読む方針でよいか。
- バルブは個別機器費を無視し、⑦の一括費用に含める扱いでよいか。
- ストリッパーコンデンサ、ストリッパーリボイラは今回の cost scope から外す扱いでよいか。
- リボイラ、コンデンサの `ΔT_lm` は HYSYS から読むのではなく、流体温度と用役温度から Python 側で計算する方針でよいか。
- Heat integration 前の評価関数では、外部加熱・外部冷却をそのまま用役費に入れる扱いでよいか。
