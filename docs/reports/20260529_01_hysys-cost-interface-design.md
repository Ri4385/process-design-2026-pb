# HYSYS 連携コスト計算の初期設計

## 目的

HYSYS からコスト計算に必要な値を読み取り、経済収支の評価関数へ渡せるようにする。

今回の設計は、実装を一気に作り込むための詳細仕様ではなく、次にどの範囲から進めるかを確認するための初期整理である。特に、HYSYS COM から値を読む汎用インターフェイス、HYSYS 上の参照先定義、読み取った後の機器モデル、コスト計算を分けることを検討対象にする。

## 今回の作業範囲案

初期実装の範囲は、HYSYS から値を読む部分の整理に限定するのが適切である。

理由は次の通りである。

- `src/process_sim/separator/hysys_io.py` は、COM 接続、stream 読み書き、plant 固定 stream の意味付けが同じファイルに集まり始めている。
- コスト計算では material stream、energy stream、operation、spreadsheet、column hydraulics を読む必要があり、現状のまま追加すると `hysys_io.py` がさらに肥大化する。
- Heat integration は今後必要になるが、必要な温度範囲や熱流リストの整理が先であり、今回の最小設計に含めると判断点が増えすぎる。

したがって、今回の第一段階では次を扱う。

```text
1. HYSYS から必要な raw value を読む汎用インターフェイス
2. Python 側の機器モデルを作るために参照する HYSYS object/stream/cell の定義
3. HYSYS から読み取った値を、分離系の機器モデルへ変換する reader
```

コスト式そのものの本格実装、Heat integration、最適化目的関数への接続は次段階で確認する。

## ディレクトリ構成案

最小変更の場合は、既存の `separator/` と `plant/economics.py` を壊さず、HYSYS 読み取り、HYSYS 参照先定義、読み取り後の機器モデルを追加する。

```text
src/process_sim/
  separator/
    hysys_io.py              # HYSYS COM 接続、stream/operation/energy/spreadsheet の汎用読み取り
    equipment.py             # 読み取った後の分離系機器モデル
    hysys_equipment_reference.py # HYSYS 上の参照先定義
    equipment_log.py         # equipment model の読み取り確認用標準出力を整形
    equipment_reader/
      __init__.py            # docstring のみ
      common.py              # HYSYS COM 読み取り共通 helper
      process_equipment.py   # ProcessEquipment 全体の組み立て
      distillation.py        # 蒸留塔 reader と塔径・塔高計算
      decanter.py            # デカンター spreadsheet 寸法の読み取り
      heat_exchanger.py      # cooler / heater operation の読み取り
  plant/
    economics.py             # 既存互換の経済計算関数。後で薄くする
    cost/
      models.py              # コスト入力、機器費、用役費、評価結果
      equipment.py           # 機器費
      utility.py             # 用役費
      revenue.py             # 製品収入、原料費
      objective.py           # 評価関数
scripts/
  read_hysys_equipment.py    # 既定 HYSYS case から equipment model を読み、標準出力へ表示
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
- `separator/equipment.py`
  - HYSYS から読み取った後の機器状態を `pydantic.BaseModel` として定義する。
  - 蒸留塔、デカンター、冷却器、加熱器、ポンプ、コンプレッサーなどを置く。
  - 塔径、高さ、feed 段、還流比、塔頂・塔底温度、duty など、分離系の装置情報を持つ。
  - stream 系統や purity は持たない。
- `separator/hysys_equipment_reference.py`
  - `T-1`、`TQ-11`、`CQ-1`、`SPRDSHT-1` など、HYSYS 上の参照先を定義する。
  - 参照先の model と、固定 HYSYS ケースに対するインスタンス定義を同じファイルに置く。
  - コスト計算法や費目名は持たない。
- `separator/equipment_reader/`
  - `hysys_io.py` と `hysys_equipment_reference.py` を使い、HYSYS 由来の値を `equipment.py` のモデルへ変換する。
  - `process_equipment.py` は `ProcessEquipment` 全体を組み立てる。
  - `distillation.py` は蒸留塔の読み取り、塔径、塔高計算を担当する。
  - `decanter.py` は `SPRDSHT-1`、`SPRDSHT-2` からデカンター寸法を読む。
  - `heat_exchanger.py` は `C-*`、`H-*` operation から duty と入口出口温度を読む。
  - `common.py` は必須属性取得や数値配列取得などの小さい共通 helper だけを持つ。
  - COM オブジェクトは package の外へ出さない。
- `separator/equipment_log.py`
  - `ProcessEquipment` 全体の読み取り状況を標準出力向けに整形する。
  - 実装済みの蒸留塔、デカンター、冷却器、加熱器は詳細を出し、未実装の機器種別は件数で確認する。
- `scripts/read_hysys_equipment.py`
  - `plant/const.py` の `DEFAULT_HYSYS_CASE_PATH` を使って HYSYS case を開く。
  - CLI 入口、コマンドライン引数、ファイル出力は持たない。
- `plant/cost/`
  - `separator/equipment.py` のモデルを受け取り、機器費、用役費、収入、評価関数を計算する。
  - HYSYS COM の参照先は知らない。
- `plant/economics.py`
  - 既存の暫定関数をすぐに壊さず、次段階で整理する。

## 簡単なコード例

`hysys_equipment_reference.py` では、HYSYS 上の参照先だけを定義する。

```python
from pydantic import BaseModel


class DistillationColumnReference(BaseModel):
    """HYSYS 上の蒸留塔参照先を定義する。"""

    id: str
    operation_name: str
    condenser_energy_name: str
    reboiler_energy_name: str


SM_COLUMN = DistillationColumnReference(
    id="sm_column",
    operation_name="T-1",
    condenser_energy_name="TQ-11",
    reboiler_energy_name="TQ-12",
)
```

`equipment.py` では、読み取った後の機器状態を定義する。

```python
from pydantic import BaseModel


class DistillationColumn(BaseModel):
    """HYSYS から読み取った蒸留塔の状態を表す。"""

    id: str
    operation_name: str
    stage_count: int
    feed_stage: int
    diameter_m: float
    height_m: float
    reflux_ratio: float
    top_temperature_c: float
    bottom_temperature_c: float
    condenser_duty_kw: float
    reboiler_duty_kw: float
```

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

HYSYS から読んだ値は、すぐに cost 式へ渡さず、まず `separator/equipment.py` の機器モデルにまとめる。

```text
ProcessEquipment
  distillation_columns
  decanters
  coolers
  heaters
  pumps
  compressors
```

この段階では、値が取れない項目を無理に仮定で埋めない。取得不可、未実装、無視候補を区別して記録する。

ただし、コスト計算用の機器モデルでは、原則として `None` を許容しない。コスト計算は recycle 収束途中の不安定な HYSYS case ではなく、収束後に安定した case を対象に行うためである。必要値が読めない場合は、欠損値を保持して後段へ流すのではなく、reader 側で明示的に失敗させる。

一方で、既存の plant 実行や収束計算中に読む stream record は、Toluene/Benzene 塔などが不安定な場合もあるため、従来通り `None` を許容する余地を残す。

## 読み取り確認ログ

HYSYS から equipment model を正しく作れているか確認するため、読み取り結果を人間向けに書き起こす補助 module を追加する方針とする。

```text
src/process_sim/separator/
  equipment_log.py     # ProcessEquipment の読み取り結果を日本語で整形する
  equipment_reader/
    process_equipment.py # ProcessEquipment を組み立てる
    distillation.py      # 蒸留塔のみを読む
    decanter.py          # デカンター寸法を読む
    heat_exchanger.py    # 冷却器、加熱器を読む
scripts/
  read_hysys_equipment.py # 既定 case を読み、標準出力へ表示する
```

この module は、コスト計算や通常実行で常に出すログではなく、実装確認用の診断出力として使う。ファイルには出力せず、標準出力だけに表示する。対象は `DistillationColumn` 単体ではなく `ProcessEquipment` 全体である。現在は、`distillation_columns`、`decanters`、`coolers`、`heaters` を読む。`pumps`、`compressors` は空 tuple として件数だけ確認する。

実行は次のように行う。

```powershell
uv run python scripts/read_hysys_equipment.py
```

case path は `src/process_sim/plant/const.py` の `DEFAULT_HYSYS_CASE_PATH` を使い、script 側では指定しない。

通常実行時の logging 方針は、コスト計算本体の実装時に別途決める。

## 判断理由

`hysys_io.py` を完全に分割するより、まず低レベル関数は残し、HYSYS 参照先定義、機器モデル、reader を外出しする方が変更量を抑えられる。既存の plant convergence や分離計算の動作に触れずに、HYSYS からの読み取り対象だけを増やせるためである。

`separator/` は、HYSYS 上のどの object を読むかと、読み取った値が分離系のどの機器状態を表すかを知ってよい。一方で、どのコスト式を使うか、どの費目に入れるかは `plant/cost/` 側の責務にする。

Heat integration は、温度区間付きの熱流リストが必要になる。現時点では HYSYS から読むべき heat stream と、Python 実装側の反応器熱交換器を同じ形式で表すことが先である。そのため、今回の設計では HI を直接実装対象にせず、将来 `heat_integration/` へ渡せる入力形式を意識するに留める。

## 今回は作らない範囲

- HYSYS の起動を伴う検証
- コスト評価関数の本実装
- Heat integration の実装
- Optuna など最適化 runner への接続
- `separator/hysys_io.py` の大規模分割
- scripts 配下のテスト追加

## 決定事項

- 第一段階では、最終的に表の全項目を読む前提にする。ただし作業は、まず model 定義、次に HYSYS 読み取り実装の 2 回に分ける。
- 現時点では、`hysys_io.py` から機器読み取り用の低レベル関数を分離しない。まずは `equipment.py`、`hysys_equipment_reference.py`、`equipment_reader.py` の 3 file 追加を考える。
- `hysys_equipment_reference.py` は、reference model と固定 HYSYS ケースに対するインスタンス定義を同居させる。HYSYS model は固定済みのため、このファイルをさらに分割する予定はない。
- デカンターの `SPRDSHT-1`, `SPRDSHT-2` は spreadsheet cell から半径と長さを読む。実装時には、既存の `scripts/distillation/` や関連 script の HYSYS 読み取り方法を参照する可能性がある。
- バルブは個別機器費を無視し、⑦の一括費用に含める。
- ストリッパーコンデンサ、ストリッパーリボイラは今回の cost scope から外す。
- リボイラ、コンデンサの `ΔT_lm` は model 定義と HYSYS 読み取りの段階では扱わない。熱交換器面積とコスト式を実装する段階で決める。
- Heat integration 前の評価関数はまだ作らない。
- `equipment_log.py` は `separator/` に置く。
- equipment 読み取り確認用 script は `scripts/read_hysys_equipment.py` に置く。`scripts/distillation/` は部分最適化用であり、今回の入口は置かない。
- equipment 読み取り確認用 script は CLI 化しない。引数も持たせず、case path は `plant/const.py` から読む。
- 読み取り確認結果は `logs/` などへ保存しない。標準出力だけに出す。

## 未確定要素

- リボイラ、コンデンサの `ΔT_lm` 計算で使う用役温度を、機器ごとに固定値として持つか、cost 側の設定として持つか。
