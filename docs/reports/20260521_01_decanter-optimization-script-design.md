# デカンター部分最適化スクリプト 詳細設計

## 目的

本資料は、HYSYS 上のデカンター周りについて、デカンター入口温度を振って部分最適化するための使い捨て寄りスクリプトの詳細設計である。

今回の対象は、恒久的な最適化パッケージの実装ではない。`scripts/` 配下にデカンター検討用の作業ディレクトリを切り、HYSYS case、作図結果、実行 script を同じ場所で管理する。

一方で、コスト計算に使う固定値や分子量など、後から他の plant 計算でも使う値は script に閉じ込めない。再利用する値は `src/process_sim/plant/` または既存の `src/process_sim/constants/` 側に置く。

## 結論

今回の実装単位は次とする。

```text
scripts/
  decanter/
    decanter_temperature_sweep.py     # デカンター温度探索の本体
    inspect_decanter_case.py          # 必要になった場合だけ作る case 調査用 script
    hysys/                            # デカンター検討用 HYSYS case を置く
    media/                            # 作図結果を置く
```

CSV 出力は作らない。CLI も作らない。探索条件、HYSYS case path、対象 stream 名、コスト条件は script 冒頭の定数として直接編集する。

ただし、次の値や関数は script に直書きしない。

- EB、SM、BZ、TL の分子量
- 年間稼働時間
- 製品または損失評価に使う価格
- 冷媒単価
- 装置費や用役費の計算式のうち、plant 全体でも使う可能性が高いもの

分子量は既存の `src/process_sim/constants/physical_properties.py` を使う。plant 共通の経済評価定数と簡単なコスト関数は、必要に応じて `src/process_sim/plant/` 側に追加する。

## 現状

現在の関連構成は次の通りである。

```text
scripts/
  inspect_hysys_case.py               # 汎用の HYSYS case 調査 script
  run_reactor_to_decanter.py          # 反応器からデカンターへの接続試行
  axial-radial-comparison/
    compare.py
    compare_2_stage.py
    media/
src/process_sim/
  constants/
    physical_properties.py            # 分子量を含む成分物性値
  plant/
    const.py                          # plant 共通固定値
    runner.py                         # plant one-pass 実行
  separator/
    hysys_io.py                       # HYSYS COM 接続と stream 読み書き
docs/
  reports/
```

`scripts/axial-radial-comparison/` は、比較用 script と `media/` を同じ作業ディレクトリに置いている。今回のデカンター検討もこれに近い扱いにする。

`data/hysys/` には plant 全体の HYSYS case が置かれているが、今回のデカンター用 case は後で `scripts/decanter/hysys/` に置く。現時点では対象 case が未配置であるため、実装前に case 名を固定しない。

## ディレクトリ構成

今回作る構成は次とする。

```text
scripts/
  decanter/
    decanter_temperature_sweep.py
    hysys/
      .gitkeep
    media/
      .gitkeep
```

必要になった場合だけ、同じディレクトリに調査用 script を追加する。

```text
scripts/
  decanter/
    inspect_decanter_case.py
```

`inspect_decanter_case.py` は、汎用の `scripts/inspect_hysys_case.py` で十分なら作らない。デカンター case 固有に、`CQ-1`、`V-1`、`VLV-1`、`tower1_feed` の読み取り可否だけを短く確認したい場合に限って作る。

## 責務分担

### `scripts/decanter/decanter_temperature_sweep.py`

デカンター温度探索の本体である。使い捨て寄りのため、汎用 CLI にはしない。

責務は次の通りである。

- HYSYS case を開く。
- 対象 stream と unit を取得する。
- デカンター入口温度を 15 から 80 ℃の範囲で振る。
- 必要なら、デカンター圧力を反応器出口圧力に合わせる。
- `tower1_feed` または `VLV-1` の圧力を固定する。
- HYSYS を solve する。
- オフガス損失、冷却用役費、装置費相当を計算する。
- 有効点だけから最小コスト点を選ぶ。
- 図を `scripts/decanter/media/` に保存する。
- 最適点と各温度の主要値を標準出力に表示する。

script 冒頭に置く定数は、作業条件として毎回編集されるものに限る。

```python
CASE_PATH = Path(__file__).parent / "hysys" / "decanter.hsc"
MEDIA_DIR = Path(__file__).parent / "media"

T_DEC_LIST_C = [15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
TOWER1_PRESSURE_KPA = 10.0
MAX_TOWER1_FEED_VAPOR_FRAC = 0.05

STREAM_REACTOR_OUTLET = "reactor_outlet"
STREAM_SEPARATOR_FEED = "separator_feed"
STREAM_OFF_GAS = "off_gas"
STREAM_WATER_RECYCLE = "water_recycle"
STREAM_DECANTER_OIL = "decanter_outlet"
STREAM_TOWER1_FEED = "tower1_feed"

ENERGY_COOLER = "CQ-1"
UNIT_DECANTER = "V-1"
UNIT_VALVE = "VLV-1"
```

一方で、分子量や価格などは script 内で定義しない。

### `src/process_sim/plant/const.py`

既に plant 共通定数がある。年間稼働時間や HYSYS timeout など、plant 全体で使う固定値はここに追加する。

追加候補は次である。

```python
HOURS_PER_YEAR = 8000.0
```

既存の `DEFAULT_TARGET_SM_KMOL_H` などと同じく、plant 全体の前提として扱う。

### `src/process_sim/plant/economics.py`

必要になった場合に追加する。script から再利用したい経済計算だけを置く。

責務は次の通りである。

- 冷却用役費の計算
- オフガス中の EB、SM、BZ、TL 損失額の計算
- 冷却器装置費の簡易計算
- デカンター装置費の簡易計算

想定する関数は次である。

```python
def cooling_utility_cost_yen_per_year(
    duty_kw: float,
    refrigerant_yen_per_mj: float,
    hours_per_year: float,
) -> float:
    """冷却 duty から年間冷却用役費を計算する。"""


def component_loss_cost_yen_per_year(
    component_flow_kmol_h: dict[str, float],
    price_yen_per_kg: dict[str, float],
    hours_per_year: float,
) -> float:
    """有価成分の流出損失額を計算する。"""
```

分子量は `SPECIES_PHYSICAL_PROPERTIES` から取得する。

```python
SPECIES_PHYSICAL_PROPERTIES["eb"].molecular_weight
SPECIES_PHYSICAL_PROPERTIES["styrene"].molecular_weight
SPECIES_PHYSICAL_PROPERTIES["benzene"].molecular_weight
SPECIES_PHYSICAL_PROPERTIES["toluene"].molecular_weight
```

価格は plant 側の経済評価定数として管理する。`docs/overview.md` には市場価格の記録があるため、実装時はそこに書かれた値との整合を確認する。

### `src/process_sim/separator/hysys_io.py`

HYSYS COM の共通処理だけを追加する。

追加候補は次である。

```python
def get_energy_stream(flowsheet: Any, stream_name: str) -> Any:
    """指定名の energy stream を取得する。"""


def get_operation(flowsheet: Any, operation_name: str) -> Any:
    """指定名の operation を取得する。"""


def get_vapor_fraction(stream: Any) -> float | None:
    """material stream の vapor fraction を読む。"""
```

デカンター最適化固有の探索ロジックは `hysys_io.py` に入れない。ここはあくまで COM I/O の共通関数だけにする。

## 最適化対象

主な設計変数は、デカンター入口温度である。

```text
T_dec_C = separator_feed の温度
```

探索範囲は次とする。

```text
15 <= T_dec_C <= 80
```

圧力は自由な最適化変数にしない。コンプレッサーを置かない方針では、デカンター圧力は反応器出口圧力と一致させる。

```text
P_dec_kPa = reactor_outlet.P
```

反応器出口圧力が未確定の場合でも、この script では多数の圧力候補を CLI で渡す設計にはしない。必要なら script 冒頭の `P_DEC_KPA` を一時的に編集して比較する。

## 固定条件

蒸留塔 1 入口圧力は、初期検討では 10 kPa とする。

```text
tower1_feed pressure = 10 kPa
```

設定対象は HYSYS case の状態に依存する。まず `VLV-1` の outlet pressure が設定できるか試し、難しければ `tower1_feed.P` を直接設定する。

この設定可否は実際の case で確認する。未確認のまま、`VLV-1` の属性名を断定しない。

## 有効点判定

各温度点について、次を満たす場合だけ有効点とする。

```text
HYSYS の solve 後に必須値が読める
tower1_feed_vapor_frac <= 0.05
off_gas が読める
decanter_outlet が読める
water_recycle が読める
```

収束 flag が HYSYS COM から明確に読める場合は使う。読めない場合は、必須値が読めたかどうかを最低限の判定にする。ただし、その場合は「収束確認済み」とは書かない。

## 評価関数

評価関数は次を基本とする。

```text
J_yen_y
= cooling_utility_cost_yen_y
+ offgas_loss_yen_y
+ cooler_annual_cost_yen_y
+ decanter_annual_cost_yen_y
```

冷却器やデカンターの装置費を入れるかは、HYSYS から面積や体積が読めるかに依存する。読めない場合は、まず用役費とオフガス損失だけで温度依存を見る。

装置費を読めないのに、滞留時間や LMTD を勝手に仮定して補完しない。補完する場合は、別途その仮定を明示してから行う。

### 冷却用役費

`CQ-1` の duty を読み、絶対値を使う。

```text
cooling_utility_cost_yen_y
= abs(Q_CQ1_kW) * 3.6 * HOURS_PER_YEAR * refrigerant_yen_per_mj
```

`HOURS_PER_YEAR` は plant 共通定数を使う。

### オフガス損失

対象は EB、SM、BZ、TL とする。

```text
offgas_loss_yen_y
= HOURS_PER_YEAR * sum(F_i_kmol_h * MW_i_kg_kmol * price_i_yen_kg)
```

分子量は `src/process_sim/constants/physical_properties.py` から読む。

BZ と TL の価格評価は未確定である。副製品販売として扱うか、燃料価値として扱うかで結果が変わるため、script に勝手な固定値を書かない。

## HYSYS から読む値

最低限読む値は次である。

```text
reactor_outlet:
  pressure
  EB, SM, BZ, TL molar flow

separator_feed:
  temperature
  pressure

CQ-1:
  duty

off_gas:
  total molar flow
  EB, SM, BZ, TL molar flow

decanter_outlet:
  total molar flow
  EB, SM, BZ, TL molar flow

water_recycle:
  total molar flow

tower1_feed:
  temperature
  pressure
  vapor fraction
```

読める場合だけ追加で読む値は次である。

```text
CQ-1:
  area

V-1:
  vessel volume
```

`CQ-1` area と `V-1` volume は、読めない可能性がある。読めない場合に script 全体を止める必要はないが、装置費を含めた評価関数は使わない。

## 作図

図は `scripts/decanter/media/` に保存する。

初期実装で必要な図は次である。

```text
cost_vs_temperature.png
offgas_loss_vs_temperature.png
recovery_vs_temperature.png
tower1_vapor_fraction_vs_temperature.png
cooling_duty_vs_temperature.png
```

CSV は作らない。必要な数値は標準出力に表形式で表示する。詳細な数値が必要になった場合は、後から JSON や Markdown の出力を検討するが、初期設計には入れない。

## 実行手順

想定する実行は次である。

```powershell
uv run python scripts/decanter/decanter_temperature_sweep.py
```

引数は使わない。HYSYS case を変える場合は script 冒頭の `CASE_PATH` を編集する。

処理フローは次である。

```text
1. scripts/decanter/hysys/ の HYSYS case を開く
2. 対象 stream と unit を取得する
3. reactor_outlet.P を読む
4. 各 T_dec_C について separator_feed.T を設定する
5. separator_feed.P を reactor_outlet.P に設定する
6. tower1_feed または VLV-1 を 10 kPa に設定する
7. HYSYS を solve する
8. 必要な値を読む
9. コストと制約を計算する
10. 有効点から最小点を選ぶ
11. 図を media に保存する
12. 標準出力にサマリを出す
```

## 採用しない案

### `src/process_sim/optimization/separator/` に本体を置く案

採用しない。今回のデカンター温度探索は、恒久的な最適化パッケージではなく、HYSYS case と一緒に動かす使い捨て寄りの検討 script である。

### 汎用 CLI にする案

採用しない。引数を増やすと、今回の用途に対して過剰である。条件は script 冒頭を編集する。

### CSV 出力を作る案

採用しない。今回必要なのは、温度に対する傾向図と最適点の確認である。初期実装では図と標準出力で足りる。

### コスト固定値を script に直書きする案

採用しない。価格、分子量、年間稼働時間、冷媒単価などは、後から plant 全体の経済評価でも使う可能性が高い。script に閉じ込めると、後で条件が分裂する。

### HYSYS case 名を現時点で固定する案

採用しない。デカンター用ファイルは後で `scripts/decanter/hysys/` に置くため、現時点ではファイル名を固定しない。

## 検証方針

HYSYS を使わない範囲では、plant 側に追加したコスト関数だけをテストする。

確認項目は次である。

- 分子量を `SPECIES_PHYSICAL_PROPERTIES` から取得して損失額を計算できる。
- 冷却 duty から年間冷却用役費を計算できる。
- 正の area から冷却器装置費を計算できる。
- 正の volume からデカンター装置費を計算できる。

HYSYS を使う動作確認は、ユーザーがローカルで実行した結果だけを根拠にする。script を作っただけで、HYSYS case が開けた、収束した、値が読めたとは扱わない。

## 未確定事項

- デカンター用 HYSYS case のファイル名。
- `scripts/decanter/hysys/` に置く case が、既存の `inspect_hysys_case.py` で十分調査できるか。
- `CQ-1` の duty、area の COM 属性。
- `V-1` の volume の COM 属性。
- `VLV-1` の outlet pressure を直接設定できるか。
- `tower1_feed` の vapor fraction の COM 属性。
- `decanter_outlet` が油相として妥当か。
- BZ と TL を副製品価格で評価するか、燃料価値で評価するか。
- 装置費を評価関数に含めるか、参考値に留めるか。
