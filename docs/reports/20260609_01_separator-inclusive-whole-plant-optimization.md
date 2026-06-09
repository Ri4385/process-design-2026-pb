# 分離器込み全体最適化の設計

## 目的

全体最適化に、分離器側の主要操作条件を追加する。

今回動かす変数は次の2つに限定する。

| 変数 | 対象 | 探索範囲 | 位置づけ |
|---|---|---:|---|
| 1基目デカンター温度 | `separator_feed` stream の温度 | `55` から `80 ℃` | デカンター前冷却条件 |
| SM分離塔還流比 | `sm_column`、HYSYS operation `T-1` | `6.3` から `8.5` | SM分離性能とリボイラ負荷の調整 |

反応器条件だけの全体最適化では、分離コストと分離性能の寄与を固定条件として扱っていた。今回は、HYSYS の安定性を優先しつつ、評価関数への寄与が大きい操作条件だけを探索変数に加える。

## 背景

既存の全体最適化 v1 から v3 では、反応器条件を探索し、HYSYS 分離系へ接続した後、全体年収支を目的関数として評価している。一方で、デカンター温度と蒸留塔還流比は固定されていた。

分離器側の全変数を同時に動かすと、HYSYS 収束が不安定になりやすく、探索の失敗原因も追いにくくなる。そのため、最初の分離器込み最適化では次の2変数だけを追加する。

- 1基目デカンター温度
- SM分離塔還流比

1基目デカンター温度は、油水分離、オフガス損失、後段冷却負荷、水リサイクル再加熱負荷に影響する。SM分離塔還流比は、SM製品純度、EB回収、コンデンサ負荷、リボイラ負荷、塔内流量に影響する。

## 探索範囲

### 1基目デカンター温度

操作対象は HYSYS material stream の `separator_feed` である。

```text
stream_name = separator_feed
write item = Temperature
unit = C
```

`separator_feed` に温度だけを書き込む。上流 cooler は、この stream の設定温度になるように反応器後流体を冷却する前提である。

探索範囲は次を基本とする。

```text
55 ℃ <= T_decanter_1 <= 80 ℃
```

下限は、既存の全体コスト評価で使っている冷却水条件 `30 ℃ -> 45 ℃` と、プロセス流体との最小接近温度差 `10 ℃` から決める。

```text
T_process,out,min = T_CW,out + DeltaT_min
                  = 45 + 10
                  = 55 ℃
```

既存の2基デカンター検討では、冷却水出口を `40 ℃` とした場合に `50 ℃` まで冷却可能としていた。しかし、全体プラントの現行コスト評価では冷却水を `30 ℃ -> 45 ℃` と扱っているため、今回の初期探索では `55 ℃` を下限にする。

上限はベンゼンの常圧沸点に近い `80 ℃` とする。`80 ℃` 端点でも HYSYS は安定するが、オフガスへの有価成分損失が大きく、コストも高くなる条件として扱う。

### SM分離塔還流比

操作対象は HYSYS 上の SM分離塔 `T-1` である。Python 側の識別子は、既存の `DISTILLATION_COLUMNS` に合わせて `sm_column` とする。

既存の参照定義から、SM分離塔の operation 名は次のように分かる。

```text
src/process_sim/separator/hysys_equipment_reference.py
  sm_column -> T-1
```

還流比の読み取りは既に `src/process_sim/separator/equipment_reader/distillation.py` で実装されており、経路は次である。

```text
operation = T-1
column_flowsheet = operation.ColumnFlowsheet
reflux_ratio = column_flowsheet.RefluxRatio
```

`T-1.ColumnFlowsheet.RefluxRatio` は読み取り結果であり、直接代入はできない。書き込み対象は `T-1.ColumnFlowsheet.Specifications` 内の `Reflux Ratio` spec とする。還流比は HYSYS の単位付き物理量ではなく無次元比であるため、単位は使わない。

探索範囲は次とする。

```text
6.3 <= R_SM <= 8.5
```

下限は、手元で仕様を満たす最低限の装置コスト条件として確認済みの `6.312` 付近である。Optuna の探索範囲としては、丸めて `6.3` を下限にする。

還流比を上げると、一般に SM 分離性能は改善する。一方で、コンデンサ負荷、リボイラ負荷、塔内液流量が増え、用役費と設備費が増える。そのため、評価関数上は分離性能改善とコスト増加の釣り合いを見る。

## 評価関数

目的関数は、既存の全体最適化と同じく `WholePlantCostResult.annual_profit_yen_per_year` の最大化とする。

```text
objective = annual_profit_yen_per_year
direction = maximize
```

分離器操作条件の変更によって、主に次の費目が変わる。

| 操作変数 | 変化しやすい項目 |
|---|---|
| 1基目デカンター温度 | デカンター冷却負荷、冷却器面積、オフガス有価成分損失、水相再加熱負荷、後段 stream 条件 |
| SM分離塔還流比 | SM製品純度、EB recycle、塔コンデンサ負荷、塔リボイラ負荷、塔径評価、utility cost |

評価関数自体は新設しない。既存の `evaluate_whole_plant_cost()` で、HYSYS 収束後かつ分離操作条件を書き込んだ後の機器情報を読み取り、年収支を計算する。

## 計算フロー

1 trial の流れは次とする。

```text
Optuna trial
  -> 反応器候補条件を生成
  -> 分離器候補条件を生成
  -> production target と recycle convergence を実行
  -> 収束後の入口条件 control plan を作成
  -> separator_feed 温度と SM分離塔還流比を control plan に追加
  -> HYSYS case へ control plan を適用
  -> HYSYS solver を更新
  -> ProcessEquipment を読み取る
  -> evaluate_whole_plant_cost()
  -> annual_profit_yen_per_year を返す
```

入口条件、デカンター温度、還流比は、すべて収束後に一度だけ書き込む。recycle 収束 iteration ごとには書き込まない。

この方針は、既存の `HysysControlPlan` の設計に合わせる。recycle 自己一致に直接使うのは、反応器出口を分離系へ渡した結果である。分離器操作条件まで iteration ごとに変えると、HYSYS 計算回数が増え、失敗時の原因切り分けも難しくなる。

## 実装対象ディレクトリ

今回の実装で想定する構成は次である。

```text
src/process_sim/
  optimization/
    separator/
      __init__.py                         # 空または docstring のみ
      parameters.py                       # 分離器操作条件の探索範囲
      hysys_controls.py                   # 分離器候補条件から HysysControlPlan を作る
    runner/
      whole_plant_optuna_v4.py             # 分離器込み全体最適化 runner
  plant/
    hysys_controls.py                     # HysysControlPlan と stream/operation 書き込み spec
  separator/
    hysys_io.py                           # HYSYS COM への低レベル書き込み
    hysys_equipment_reference.py          # T-1 など既存 HYSYS 参照先
scripts/
  whole_plant_optuna_v4/
    plot_results.py                       # v4 探索結果の描画
    media/                                # 図
    results/                              # 上位 trial 表
  distillation/
    check_sm_column_reflux_write.py        # SM分離塔還流比の書き込み確認
    inspect_sm_column_reflux_spec.py       # Reflux Ratio spec の COM 属性調査
data/
  optuna/
    whole_plant_optuna_v4.db              # Optuna storage
docs/
  reports/
    20260609_01_separator-inclusive-whole-plant-optimization.md
```

## ファイル責務

### `src/process_sim/optimization/separator/parameters.py`

分離器操作条件の探索範囲を置く。

想定するモデルは次である。

```python
class SeparatorOperatingCandidate(BaseModel):
    """分離器操作条件の候補。"""

    decanter_1_temperature_c: float
    sm_column_reflux_ratio: float
```

探索範囲は次の定数として定義する。

```python
DECANTER_1_TEMPERATURE_RANGE_C = ParameterRange(lower=55.0, upper=80.0)
SM_COLUMN_REFLUX_RATIO_RANGE = ParameterRange(lower=6.3, upper=8.5)
```

### `src/process_sim/optimization/separator/hysys_controls.py`

Optuna trial で得た `SeparatorOperatingCandidate` を、HYSYS 書き込み用の `HysysControlPlan` に変換する。

`separator_feed` の温度は `TemperatureMaterialStreamWriteSpec` として扱う。

```text
TemperatureMaterialStreamWriteSpec(
  stream_name="separator_feed",
  temperature_c=decanter_1_temperature_c,
)
```

SM分離塔還流比は、既存の `OperationWriteSpec` をそのまま使うより、蒸留塔専用の書き込み spec と writer を追加する方が自然である。

```text
DistillationRefluxRatioWriteSpec(
  column_id="sm_column",
  operation_name="T-1",
  reflux_ratio=sm_column_reflux_ratio,
)
```

低レベル writer では、`T-1` operation を取得し、`operation.ColumnFlowsheet.Specifications` 内の `Reflux Ratio` spec の指定値へ無次元値を書き込む。

既存の `OperationWriteSpec` は `unit: str` を持ち、`set_quantity()` 経由で `SetValue()` を試す設計である。還流比は単位付きの量ではないため、`OperationWriteSpec.unit` を必須にしたまま流用するのは不自然である。必要なら、`OperationWriteSpec.unit` を `str | None` にするか、還流比専用 writer に分ける。

### `src/process_sim/optimization/runner/whole_plant_optuna_v4.py`

既存の `whole_plant_optuna_v3.py` を直接変更せず、分離器込み探索用の runner として新規作成する。

v4 runner の主な違いは次である。

- `SeparatorOperatingCandidate` を trial で生成する。
- `build_inlet_control_plan()` の結果に、分離器操作条件の書き込み spec を追加する。
- trial の `user_attrs` に `decanter_1_temperature_c` と `sm_column_reflux_ratio` を保存する。
- prune 時にも、生成済みの分離器操作条件を保存する。

### `scripts/whole_plant_optuna_v4/plot_results.py`

v4 storage から探索結果を描画する。

既存 v3 の出力に加え、最低限次を確認できるようにする。

```text
objective_slice_plot_decanter_1_temperature_c
objective_slice_plot_sm_column_reflux_ratio
top_trials.md
top_trials.csv
```

図の目的は、最適条件が探索範囲の端に張り付いているか、分離器操作条件が評価関数に効いているかを見ることである。

### `scripts/distillation/check_sm_column_reflux_write.py`

SM分離塔還流比を書き込めるかを先行確認する script である。既定 HYSYS case を開き、`T-1.ColumnFlowsheet.Specifications` 内の `Reflux Ratio` spec へ `7.0` を書き込んだ後、`read_process_equipment()` で `sm_column.reflux_ratio` として読めるかを表示する。

この script は確認用であり、HYSYS case は保存せずに閉じる。

想定実行コマンドは次である。

```powershell
uv --cache-dir .uv-cache run python scripts/distillation/check_sm_column_reflux_write.py
```

HYSYS を起動するため、実行はユーザーが行う。

### `scripts/distillation/inspect_sm_column_reflux_spec.py`

`Reflux Ratio` spec の COM 属性を調査する script である。既存 diagnosis から、`ColumnFlowsheet.RefluxRatio` は読み取り結果であり、書き込み対象は `Specifications` 内の `Reflux Ratio` spec であることまでは分かる。一方で、spec の目標値を表す属性名は既存 diagnosis だけでは確定できない。

この script は、`Reflux Ratio` spec の属性名、現在値、同値書き込み可否を JSON に出す。

想定実行コマンドは次である。

```powershell
uv --cache-dir .uv-cache run python scripts/distillation/inspect_sm_column_reflux_spec.py
```

出力先は次である。

```text
scripts/distillation/diagnostics/sm_column_reflux_spec_probe.json
```

## 採用理由

### 操作変数を2つに絞る理由

HYSYS の安定性を優先するためである。デカンター温度、複数塔の還流比、圧力、段数、feed 段などを同時に動かすと、失敗 trial が増え、探索結果が「物理的に悪い条件」なのか「HYSYS が不安定な条件」なのかを切り分けにくい。

今回の2変数は、評価関数への寄与が比較的大きく、かつ操作対象が明確である。初期の分離器込み探索として妥当である。

### `separator_feed` の温度を書き込む理由

1基目デカンター温度は、decanter operation 自体ではなく、デカンターへ入る `separator_feed` stream の温度で制御できる。cooler がこの stream の設定温度になるように冷却するため、stream 温度だけを書き込む方が、HYSYS case の既存構造に合う。

### 下限を55 ℃にする理由

現行の全体コスト評価では、冷却水条件を `30 ℃ -> 45 ℃` と扱っている。向流熱交換器で最小接近温度差 `10 ℃` を満たすなら、冷却水だけで到達できるプロセス流体出口温度の下限は `55 ℃` である。

`50 ℃` は、冷却水出口を `40 ℃` と置くデカンター個別検討では整合する。しかし、今回の全体最適化では全体コスト評価の前提に合わせ、`55 ℃` を下限にする。下限 `50 ℃` の感度解析は実施しない。

### SM分離塔だけを動かす理由

SM分離塔は、最終 SM 製品の品質と EB recycle に直接関係する。還流比を上げると分離性能は上がるが、リボイラ負荷やコンデンサ負荷も上がるため、全体評価関数上の trade-off が出やすい。

EB分離塔、BZTL分離塔まで同時に動かすと探索空間が広がり、初期段階では HYSYS 安定性の確認が難しくなる。今回は SM分離塔に限定する。

## 採用しない案

### デカンター温度を50 ℃から探索する案

初期探索では採用しない。冷却水出口 `45 ℃`、最小接近温度差 `10 ℃` の前提では、冷却水のみで `50 ℃` まで冷やすことは整合しないためである。

下限 `50 ℃` の感度解析は行わない。

### SM分離塔以外の還流比も同時に動かす案

採用しない。初期探索では、変数を増やすよりも HYSYS の安定性と評価関数への寄与確認を優先する。

### recycle 収束 iteration ごとに分離器操作条件を書き込む案

採用しない。分離器操作条件は trial 固有の設計条件として、収束後のコスト評価前に一度だけ反映する。iteration ごとに書くと HYSYS 計算回数が増え、収束失敗の原因も複雑になる。

## 保存する trial 属性

既存 v3 の属性に加えて、次を保存する。

```text
decanter_1_temperature_c
sm_column_reflux_ratio
```

分離器込み探索の結果解釈では、少なくとも次を top trial 表へ出す。

```text
rank
study_name
trial_number
annual_profit_yen_per_year
decanter_1_temperature_c
sm_column_reflux_ratio
stage_count
stage temperatures
inlet_pressure_kpa_abs
steam_to_eb_ratio
bed_thicknesses_m
eb_conversion
styrene_selectivity
sm_product_kmol_h
fresh_eb_kmol_h
fresh_h2o_kmol_h
eb_recycle_kmol_h
h2o_recycle_kmol_h
utility_yen_per_year
annualized_equipment_yen_per_year
```

## 既知の制約

- `separator_feed` の温度 readback は stream 温度として確認できるが、cooler 側の指定温度や duty が期待通り変わったかは、機器読み取り結果で別途確認する必要がある。
- SM分離塔還流比の読み取りは、既存実装どおり `T-1.ColumnFlowsheet.RefluxRatio` を使う。
- SM分離塔還流比の書き込みは、`T-1.ColumnFlowsheet.Specifications` 内の `Reflux Ratio` spec を使う。
- 還流比は無次元であり、書き込み時に単位は使わない。
- 還流比 `6.3` 以上では、製品仕様を満たすことと HYSYS が収束することはほぼ同義として扱う。`6.2` 程度まで下げると回収率が低下し、製品仕様を満たそうとして収束しにくくなる。
- デカンター温度 `80 ℃` 端点は HYSYS 上は安定する。ただしオフガスへの有価成分損失が大きく、コストも高くなる。
- 下限 `55 ℃` は、冷却水出口 `45 ℃` を前提にした保守的な値である。

## 未確定事項

- `Reflux Ratio` spec の指定値を表す COM 属性名。
- `OperationWriteSpec` を無次元操作にも使えるように変更するか、蒸留塔還流比専用 writer を追加するか。

## 実装結果

以下を追加した。

```text
scripts/
  distillation/
    check_sm_column_reflux_write.py
    inspect_sm_column_reflux_spec.py
```

`check_sm_column_reflux_write.py` は、既定 HYSYS case の `T-1.ColumnFlowsheet.Specifications` 内にある `Reflux Ratio` spec に `7.0` を書き込み、直接 readback と `read_process_equipment()` による機器読み取り結果の両方を表示する。

`inspect_sm_column_reflux_spec.py` は、`Reflux Ratio` spec の属性名と同値書き込み可否を `scripts/distillation/diagnostics/sm_column_reflux_spec_probe.json` に出力する。

HYSYS 実行、`uv run`、テストは本作業では行っていない。
