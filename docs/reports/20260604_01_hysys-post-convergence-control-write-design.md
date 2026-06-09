# HYSYS 収束後操作条件書き込みの設計

## 目的

第一段階では、`fast-plant-convergence-cost` で recycle 収束後に HYSYS 側の機器情報を読み取り、全体コスト評価へ渡すところまでを対象にした。第二段階では、収束計算後、コスト評価前に HYSYS case へ入口加熱系と一部の分離操作条件を書き込む。

対象は次である。

1. 収束後の fresh EB、recycle EB、fresh water、recycle water の stream 条件を書き込む。
2. 反応器入口圧力と温度から、入口ポンプ後 stream と heater 後 stream の指定値を書き込む。
3. 後続の全体最適化で、蒸留塔の還流比とデカンター1基目の温度も同じ仕組みで書き込めるようにする。

この段階では、HYSYS の収束計算ごとに入口条件を書き込まない。recycle 収束計算が終わった後、機器情報とコストを読む直前に一度だけ書き込む。

原料条件は確定条件として扱う。

| 対象 | 組成 | 温度 | 圧力 |
|---|---|---:|---:|
| 原料 EB | EB 99.5 mol%、B 0.5 mol% | 30 ℃ | 101.3 kPa |
| 原料水 | H2O 100 mol% | 30 ℃ | 300 kPa |

## 背景

現行 HYSYS case では、分離器系と入口加熱系が独立して存在している。分離器系には反応器出口を書き込み、分離計算を繰り返して recycle 収束を取っている。一方で、入口加熱系は既存 case に固定された状態を読んでいる。

入口加熱系をコスト評価に含めるには、最終的に収束した fresh feed と recycle 条件を HYSYS 側の入口 stream へ反映した状態で、加熱器、熱交換器、ポンプなどの duty や動力を読む必要がある。

ただし、入口加熱系は recycle 収束の自己一致には直接関与させない。各 iteration で書き込むと HYSYS 計算時間と不安定化要因だけが増え、収束判定の意味は変わらない。そのため、入口条件の書き込みは収束後に限定する。

## 書き込みタイミング

第二段階の処理順序は次とする。

```text
fast-plant-convergence-cost
  -> OpenHysysPlantRunner
  -> run_production_target_convergence()
  -> runner.apply_post_convergence_controls(control_plan)
  -> runner.read_process_equipment()
  -> plant/cost/evaluation.py
```

`run_production_target_convergence()` の内部では、従来どおり反応器出口 stream だけを書き込む。入口加熱系の stream、蒸留塔還流比、デカンター温度は書き込まない。

`runner.apply_post_convergence_controls()` は、収束済みの `PlantConvergenceResult` と最終反応器条件から `control_plan` を作り、HYSYS case に一度だけ適用する。適用後に HYSYS solver を走らせ、計算完了後の状態から `read_process_equipment()` を呼ぶ。

書き込み後は、対象 stream を HYSYS から読み直す。書き込んだ温度、圧力、成分モル流量が readback 結果と一致することを確認してから、機器情報の読み取りとコスト評価へ進む。

## 書き込み対象

### 入口 stream

書き込む stream は次である。

| HYSYS stream | 書き込み内容 | 入力元 |
|---|---|---|
| `fresh_eb` | 組成、圧力、温度 | `PlantConvergenceResult.feed_plan.steady_fresh_feed` と入口条件設定 |
| `eb_recycle_to_mixer` | 組成、圧力、温度 | 最終 iteration の `eb_recycle` stream |
| `fresh_water` | 組成、圧力、温度 | `PlantConvergenceResult.feed_plan.steady_fresh_feed` と入口条件設定 |
| `water_recycle_to_mixer` | 組成、圧力、温度 | 最終 iteration の `water_recycle` stream |
| `eb2` | 圧力 | 反応器入口前の圧力 + 20 kPa |
| `water2` | 圧力 | 反応器入口前の圧力 + 20 kPa |
| `reactor_inlet` | 温度 | 反応器入口温度 |

`eb2` と `water2` はポンプ後 stream である。ここで圧力を指定することでポンプ吐出圧を指定する。入口加熱系の熱交換で 20 kPa 落ちる前提のため、反応器入口圧力より 20 kPa 高い圧力を書き込む。

`reactor_inlet` は heater 後 stream である。ここで反応器入口温度を指定し、必要な加熱量を HYSYS 側で計算させる。

### 後続の最適化操作

全体最適化では、入口条件に加えて次の分離条件も操作する予定である。

| 操作対象 | 書き込み内容 | 備考 |
|---|---|---|
| 蒸留塔 | 還流比 | 対象塔と HYSYS operation 名は既存の `DISTILLATION_COLUMNS` を使う |
| デカンター1基目 | 温度 | 1基目の冷却温度を将来の操作変数にする |

これらは入口 stream とは種類が異なるが、同じ `HysysControlPlan` に入れてまとめて適用する。入口条件専用の実装にすると、後続の最適化で再度書き込み基盤を作る必要があるためである。

ただし、第二段階で実装するのは入口条件の書き込みまでとする。蒸留塔還流比とデカンター1基目温度は、クラス設計と拡張点だけを用意し、実際の書き込み実装は入口書き込み確認後に行う。

## 採用方針

HYSYS 書き込みは、`separator/hysys_io.py` に低レベル関数、`plant/hysys_controls.py` に plant 意味論を置く。

低レベル関数は、COM の属性名、単位、MaterialStream や Operation の取得を扱う。plant 側は、`fresh_eb` や `reactor_inlet` などのプロセス上の意味、収束結果からの値の作り方、最適化変数からの制御計画生成を扱う。

この分離により、HYSYS COM オブジェクトを application boundary の外へ直接出さない。外側の処理は、明示的な Python model だけを受け渡す。

## 型設計

### 基本モデル

`pydantic.BaseModel` を使い、書き込み指示を明示的なモデルとして表す。

```python
class ComponentMolarFlowSpec(BaseModel):
    """HYSYS stream へ書き込む成分モル流量。"""

    values: dict[str, float]


class FullMaterialStreamWriteSpec(BaseModel):
    """Material stream へ組成、温度、圧力を書き込む条件。"""

    stream_name: str
    temperature_c: float
    pressure_kpa: float
    component_molar_flow: ComponentMolarFlowSpec


class PressureMaterialStreamWriteSpec(BaseModel):
    """Material stream へ圧力だけを書き込む条件。"""

    stream_name: str
    pressure_kpa: float


class TemperatureMaterialStreamWriteSpec(BaseModel):
    """Material stream へ温度だけを書き込む条件。"""

    stream_name: str
    temperature_c: float


class OperationWriteSpec(BaseModel):
    """HYSYS operation への書き込み条件。"""

    operation_name: str
    variable_name: str
    value: float
    unit: str


class HysysControlPlan(BaseModel):
    """収束後に HYSYS case へ適用する操作条件一式。"""

    full_material_streams: tuple[FullMaterialStreamWriteSpec, ...] = ()
    pressure_material_streams: tuple[PressureMaterialStreamWriteSpec, ...] = ()
    temperature_material_streams: tuple[TemperatureMaterialStreamWriteSpec, ...] = ()
    operations: tuple[OperationWriteSpec, ...] = ()
```

書き込み対象ごとに別クラスを使い、`None` で「書き込まない項目」を表現しない。組成、温度、圧力をまとめて書く stream は `FullMaterialStreamWriteSpec`、圧力だけの stream は `PressureMaterialStreamWriteSpec`、温度だけの stream は `TemperatureMaterialStreamWriteSpec` に分ける。

モル分率を書き込む予定はないため、成分指定は成分モル流量だけに限定する。

### 入口条件モデル

入口系の操作条件は、最適化変数と収束結果から導ける値に分ける。

```python
class InletConditionSettings(BaseModel):
    """入口加熱系へ書き込む設計条件。"""

    reactor_inlet_temperature_c: float
    reactor_inlet_pressure_kpa: float
    pump_discharge_margin_kpa: float = 20.0
```

fresh EB と fresh water の条件は確定値として別定数に置く。recycle EB と recycle water の温度、圧力、組成は、最終 iteration の `eb_recycle`、`water_recycle` stream から読む。recycle 圧力は入口 mixer 側へ合わせず、recycle stream の圧力をそのまま使う。圧力を合わせると、ポンプや圧力調整に関するコスト計算の前提が崩れるためである。

`reactor_inlet_pressure_kpa` と `reactor_inlet_temperature_c` は、反応器 case の入口条件を正とする。radial では `RadialReactorRunConditions.inlet_pressure_pa` と `stage_inlet_temperatures_k[0]` から変換する。PFR でも対応する入口圧力と第1段入口温度から変換する。

## 値の作り方

### fresh EB

`fresh_eb` は fresh feed の EB 成分を HYSYS stream に書き込む。

```text
component molar flow:
  EB = steady_fresh_feed.hydrocarbon_kmol_h * 0.995
  Benzene = steady_fresh_feed.hydrocarbon_kmol_h * 0.005
  others = 0

temperature:
  30 C

pressure:
  101.3 kPa
```

HYSYS 成分名は case 側の成分一覧から取得し、既存の `normalized_component_name()` と同じ正規化で `Ethylbenzene`、`EBenzene`、`EB` などを EB に対応付ける。

### fresh water

`fresh_water` は fresh feed の H2O 成分を HYSYS stream に書き込む。

```text
component molar flow:
  H2O = steady_fresh_feed.steam
  others = 0

temperature:
  30 C

pressure:
  300 kPa
```

Python 側では反応器 feed の水を `steam` と呼ぶが、HYSYS stream 上では `H2O` または `Water` として対応付ける。

### recycle EB

`eb_recycle_to_mixer` は、最終 iteration の `eb_recycle` stream から成分モル流量をそのまま移す。

```text
component molar flow:
  final_iteration.plant_record.streams["eb_recycle"].component_molar_flow_kmol_h

temperature:
  final_iteration.plant_record.streams["eb_recycle"].temperature_c

pressure:
  final_iteration.plant_record.streams["eb_recycle"].pressure_kpa
```

recycle stream は EB 以外の微量成分を含みうるため、EB だけに丸めない。HYSYS の成分名と `PlantStreamRecord` の成分名が一致しない場合は、正規化した成分名で対応付ける。

### recycle water

`water_recycle_to_mixer` は、最終 iteration の `water_recycle` stream から成分モル流量をそのまま移す。

```text
component molar flow:
  final_iteration.plant_record.streams["water_recycle"].component_molar_flow_kmol_h

temperature:
  final_iteration.plant_record.streams["water_recycle"].temperature_c

pressure:
  final_iteration.plant_record.streams["water_recycle"].pressure_kpa
```

### eb2 と water2

`eb2` と `water2` は、ポンプ吐出圧を指定するために圧力だけを書き込む。

```text
pressure_kpa = reactor_inlet_pressure_kpa + pump_discharge_margin_kpa
```

温度と組成は書き込まない。圧力だけに限定することで、HYSYS 側のポンプ、混合、熱交換の自由度を残す。

### reactor_inlet

`reactor_inlet` は、heater 後の温度指定 stream として扱う。

```text
temperature_c = reactor_inlet_temperature_c
```

圧力と組成は書き込まない。圧力は `eb2` と `water2` の指定、および熱交換器側の圧力損失で決まる前提とする。

## 実装配置

```text
src/process_sim/
  separator/
    hysys_io.py                         # HYSYS COM への低レベル読み書き
    hysys_control_reference.py           # operation 名、stream 名、変数名の固定参照
  plant/
    hysys_controls.py                    # 収束結果と設定から HysysControlPlan を生成
    session_runner.py                    # 開いている HYSYS session へ control plan を適用
    fast_convergence_cost.py             # 収束後、機器読み取り前に control plan を適用
  optimization/
    separator/
      parameters.py                      # 還流比、デカンター温度などの探索範囲
      hysys_controls.py                  # trial 変数から OperationWriteSpec を生成
docs/
  reports/
    20260604_01_hysys-post-convergence-control-write-design.md
```

`separator/hysys_io.py` は、次の低レベル関数を追加する。

```text
write_material_stream_spec(flowsheet, spec)
write_operation_spec(flowsheet, spec)
apply_hysys_control_plan(simulation_case, plan)
readback_hysys_control_plan(simulation_case, plan)
validate_hysys_control_readback(plan, readback)
set_component_molar_flows_from_mapping(stream, component_names, values)
```

`plant/hysys_controls.py` は、次の関数を持つ。

```text
build_inlet_control_plan(
  convergence_result,
  base_reactor_case,
  inlet_settings,
) -> HysysControlPlan
```

`session_runner.py` は、開いている session に対して次の method を追加する。

```text
OpenHysysPlantRunner.apply_post_convergence_controls(plan: HysysControlPlan)
```

この method は `HysysSeparationSession` の `simulation_case` property を使い、COM オブジェクトを runner の外へ出さずに `apply_hysys_control_plan()` を呼ぶ。

## 参照定義

stream 名は当面固定文字列として扱うが、散在させない。

```python
class InletStreamNames(BaseModel):
    """入口加熱系の HYSYS stream 名。"""

    fresh_eb: str = "fresh_eb"
    eb_recycle_to_mixer: str = "eb_recycle_to_mixer"
    fresh_water: str = "fresh_water"
    water_recycle_to_mixer: str = "water_recycle_to_mixer"
    eb2: str = "eb2"
    water2: str = "water2"
    reactor_inlet: str = "reactor_inlet"
```

蒸留塔の HYSYS operation 名は、既存の `separator/hysys_equipment_reference.py` の `DISTILLATION_COLUMNS` を使う。

```python
class DistillationRefluxRatioWriteSpec(BaseModel):
    """蒸留塔の還流比操作条件。"""

    column_id: str
    operation_name: str
    reflux_ratio: float
```

`operation_name` は `sm_column -> T-1`、`eb_column -> T-2`、`bztl_column -> T-3` とする。COM 上で還流比を書き込む具体的な属性名は、還流比実装時に低レベル writer 側で確認する。

デカンター1基目温度は、入口条件の後に拡張する予定である。現時点では class 設計だけ残し、実際の書き込みと読み取りは実装しない。

```python
class DecanterTemperatureWriteSpec(BaseModel):
    """デカンターの温度操作条件。"""

    decanter_id: str
    operation_name: str
    temperature_c: float
```

HYSYS operation の属性名が単純な `SetValue` で書けない場合は、operation 専用 writer を `separator/hysys_io.py` に閉じ込める。plant 側には COM の詳細を出さない。

## エラー処理

必須 stream が取得できない場合、または必須値が欠落している場合は例外にする。入口条件が不完全なままコスト評価すると、誤った utility cost と装置費をもっともらしく出すためである。

対象は次である。

- `fresh_eb`
- `fresh_water`
- `eb_recycle_to_mixer`
- `water_recycle_to_mixer`
- `eb2`
- `water2`
- `reactor_inlet`
- 最終 iteration の `eb_recycle`
- 最終 iteration の `water_recycle`
- 反応器入口温度
- 反応器入口圧力

第二段階では、分離操作条件は `HysysControlPlan` に入れない。入口条件の書き込み確認後、還流比とデカンター温度を実装する段階で、指定された operation が見つからない場合は例外にする。

書き込み後の readback で、plan と HYSYS 側の値が一致しない場合も例外にする。判定対象は、各 spec で書き込んだ項目だけとする。例えば `eb2` と `water2` は圧力だけ、`reactor_inlet` は温度だけを確認する。

## ログ

書き込み後、少なくとも次を標準エラーまたはコスト詳細ログに出す。

```text
[Post Convergence HYSYS Controls]
material streams
  fresh_eb                T=... C  P=... kPa  total=... kmol/h
  eb_recycle_to_mixer     T=... C  P=... kPa  total=... kmol/h
  fresh_water             T=... C  P=... kPa  total=... kmol/h
  water_recycle_to_mixer  T=... C  P=... kPa  total=... kmol/h
  eb2                     P=... kPa
  water2                  P=... kPa
  reactor_inlet           T=... C

operations
  sm_column reflux_ratio=...
  eb_column reflux_ratio=...
  bztl_column reflux_ratio=...
  decanter_1 temperature=... C
```

ログは、実際に書き込んだ plan と readback 結果を表示する。HYSYS が計算後に返した結果値は、既存の `read_material_stream_record()` を使って読み取る。

## 採用しなかった案

### 収束 iteration ごとに入口条件を書き込む案

採用しない。入口加熱系は recycle 自己一致の計算に使っていないため、iteration ごとに書き込んでも収束計算の意味は変わらない。一方で HYSYS solver の計算回数が増え、COM 連携の失敗確率も上がる。

### コスト計算側で入口条件を仮想的に計算する案

採用しない。入口加熱器、ポンプ、熱交換器の duty や動力は HYSYS case 側に既にモデルがある。Python 側で仮想計算すると、HYSYS case とコスト評価がずれる。今回は、HYSYS case に条件を書き込んだ後の機器読み取りを正とする。

### stream 書き込み専用 API だけを作る案

採用しない。全体最適化では還流比とデカンター温度も操作する予定であり、stream 専用 API ではすぐに拡張が必要になる。`HysysControlPlan` に stream と operation を併存させ、入口条件も分離条件も同じ apply 処理に載せる。

## 既知の制約

- HYSYS operation の還流比、デカンター温度の COM 属性名は、実装時に既存 case で確認する必要がある。
- recycle stream の温度と圧力は、最終 iteration の分離結果を使う。入口側の熱交換・混合後に HYSYS が返す温度とは別である。
- `eb2`、`water2` の 20 kPa margin は、入口熱交換で 20 kPa 落ちるという現行前提に基づく。HYSYS case 側の圧力損失設定を変えた場合は、この値も見直す必要がある。
- HYSYS solver が書き込み後に収束しなかった場合、Python 側では詳細原因を完全には判定できない。まずは例外または timeout として扱う。

## 今後の拡張方針

全体最適化では、Optuna trial から次の流れで HYSYS 操作条件を生成する。

```text
trial parameters
  -> SeparatorOptimizationSettings
  -> HysysControlPlan.operations
  -> post convergence apply
  -> ProcessEquipment read
  -> whole plant cost evaluation
```

入口条件は、反応器 case と収束結果に従属する条件として扱う。還流比、デカンター温度は探索変数として扱う。両者を同じ `HysysControlPlan` にまとめることで、コスト評価入口は「収束後に control plan を適用してから読む」という単純な形に保つ。

## 未確定要素

- デカンター1基目の温度を書き込む HYSYS operation 名。
- 蒸留塔還流比とデカンター温度を書き込む低レベル COM writer の詳細。
