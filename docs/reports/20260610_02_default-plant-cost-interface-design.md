# default 条件 plant cost interface 設計

## 目的

基底条件で全体コスト計算を実行する入口を整理する。

現状は、反応器条件、Steam/EB 比、分離器操作条件、コスト評価の入口が複数 module に分散している。

特に問題になる点は次である。

| 項目 | 現状 | 問題 |
|---|---|---|
| Steam/EB 比 | `production_target.py` の初期値生成用定数 | 反応器条件や最適化 runner と独立して見え、default 条件として追いにくい |
| 反応器規定ケース | `reactor/cases/` と各 runner | default cost 実行でどの reactor case を使うかが入口から明示されない |
| separator 条件 | `optimization/separator/` と一部 runner | default cost 実行で separator 条件を選ぶ経路がない |
| 実行 script | `fast-plant-convergence-cost` | HYSYS session 再利用の実装都合が名前に出ており、default 条件の cost 評価入口としては分かりにくい |

今回の目的は、探索用 runner ではなく、現在採用している default 条件を一箇所にまとめ、その条件で plant convergence と cost 評価を実行する interface を用意することである。

HYSYS case path は default 条件 model には含めない。既存どおり `plant/const.py` の `DEFAULT_HYSYS_CASE_PATH` から import して使う。

## 結論

script 名は次を採用する。

```text
run-default-cost
```

`base` は使わない。ここで扱うのは抽象的な基底ではなく、現時点で採用する default 条件である。

case model の定義は次へ置く。

```text
src/process_sim/plant/cases/models.py
```

default 条件の実体は次へ置く。

```text
src/process_sim/plant/cases/default.py
```

実行入口は次へ置く。

```text
src/process_sim/plant/default_case_runner.py
```

## 実装対象ディレクトリ

```text
src/process_sim/
  plant/
    cases/
      __init__.py                  # 空または docstring のみ
      models.py                    # plant cost case の model 定義
      default.py                   # default 条件の実体
    default_case_runner.py         # default case で convergence と cost 評価を実行
docs/
  reports/
    20260610_02_default-plant-cost-interface-design.md
pyproject.toml                     # CLI script を追加
README.md                          # 実行入口と責務の説明を更新
```

`cases/` は plant 条件の置き場として使う。ここでいう default case は、Steam/EB 比、反応器条件、分離器条件をまとめたものとする。

## ファイル責務

### `src/process_sim/plant/cases/models.py`

default 条件に限らず、plant cost 評価に必要な case model を定義する。

想定する model は次である。反応器条件用の新しい model は作らない。既存の `RadialReactorCase` を使う。

```python
class SeparatorCondition(BaseModel):
    """default case で使う分離器条件。"""

    decanter_1_temperature_c: float
    sm_column_reflux_ratio: float


class DefaultCase(BaseModel):
    """default 条件として扱う操作条件一式。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    steam_to_eb_ratio: float
    reactor: RadialReactorCase
    separator: SeparatorCondition
```

ここには default 値を置かない。`models.py` は型と構造だけを持つ。

case model を `plant/default_case_runner.py` に直接置かない理由は、実行入口と設定構造を分けるためである。今後、default 以外に report 用条件や比較条件を追加する場合も、同じ model を使える。

case model を `optimization/` に置かない理由は、この interface が探索用ではないためである。Optuna trial ではなく、指定済み条件で plant cost を評価する責務は `plant/` 側にある。

`RadialReactorCase` は既に `reactor/cases/styrene_radial_default.py` にあるため、ここで `RadialReactorCondition` のような重複 model は作らない。

### `src/process_sim/plant/cases/default.py`

現時点で採用する default 条件を置く。

このファイルを見れば、Steam/EB 比、反応器条件、分離器条件が分かる状態にする。`DEFAULT_STYRENE_RADIAL_REACTOR_CASE` をそのまま代入すると reactor 条件の中身が見えないため、採用しない。

想定する定数は次である。

```python
DEFAULT_RADIAL_REACTOR_CONDITIONS = RadialReactorRunConditions(
    inlet_pressure_pa=105_070.0,
    stage_inlet_temperatures_k=(273.15 + 594.443, 273.15 + 649.667),
    inlet_superficial_velocity_m_per_s=2.0,
    center_channel_radius_m=1.0,
    bed_height_m=6.0,
    bed_thicknesses_m=(0.716521, 0.799649),
    pellet_diameter_m=0.003,
    bed_void_fraction=0.4312,
    catalyst_bulk_density_kg_m3=1422.0,
    ergun_a=1.75,
    ergun_b=150.0,
    gas_viscosity_pa_s=2.6e-5,
    interstage_reheater_pressure_drop_pa=20_000.0,
    segments_per_stage=50000,
    profile_points_per_stage=12,
    min_outlet_pressure_kpa_abs=60.0,
    min_bed_outlet_velocity_m_per_s=1.0,
)

DEFAULT_RADIAL_REACTOR_CASE = RadialReactorCase(
    feed=DEFAULT_STYRENE_FEED,
    conditions=DEFAULT_RADIAL_REACTOR_CONDITIONS,
)

DEFAULT_CASE = DefaultCase(
    steam_to_eb_ratio=5.0,
    reactor=DEFAULT_RADIAL_REACTOR_CASE,
    separator=SeparatorCondition(
        decanter_1_temperature_c=55.0,
        sm_column_reflux_ratio=6.312,
    ),
)
```

`steam_to_eb_ratio` はここで明示する。これにより、default cost 実行時の Steam/EB 比が `production_target.py` の内部定数に隠れない。

反応器条件はこのファイル内で明示して `RadialReactorCase` を組み立てる。反応器条件の型は新しく作らず、反応器計算そのものは既存の `RadialReactorCase` と `RadialReactorRunConditions` に従う。

separator 条件もここで明示する。これにより、default cost 実行時にどのデカンター温度と SM分離塔還流比を使ったかを、case 定義から追える。

HYSYS case path はここに置かない。使用する HYSYS case は `plant/const.py` の `DEFAULT_HYSYS_CASE_PATH` を使う。

### `src/process_sim/plant/default_case_runner.py`

`DefaultCase` を受け取り、convergence と cost 評価を実行する。

想定する主関数は次である。

```python
def run_default_cost(case: DefaultCase = DEFAULT_CASE) -> WholePlantCostResult:
    """default plant 条件で収束計算と cost 評価を行う。"""
```

CLI 入口は次である。

```python
def run_default_cost_main() -> None:
    """CLI から default plant cost 評価を実行する。"""
```

処理の流れは次とする。

```text
DEFAULT_CASE
  -> case.reactor
  -> InitialRecycleGuessPolicy(steam_to_eb_ratio=case.steam_to_eb_ratio)
  -> OpenHysysPlantRunner(DEFAULT_HYSYS_CASE_PATH, "radial")
  -> run_production_target_convergence()
  -> build_inlet_control_plan()
  -> build_separator_control_plan()
  -> merge_hysys_control_plans()
  -> runner.apply_post_convergence_controls()
  -> runner.read_process_equipment()
  -> evaluate_whole_plant_cost()
  -> format_plant_convergence_result()
  -> format_whole_plant_cost_report()
```

`fast_plant_convergence_cost.py` のように module 内で Steam/EB 比や反応器条件を固定しない。Steam/EB 比、reactor case、separator 条件は `DEFAULT_CASE` から渡す。

`build_separator_control_plan()` は既存の `optimization/separator/hysys_controls.py` を利用する。ここは編集対象ではない。default case から既存の `SeparatorOperatingCandidate` 相当の値へ変換して使うだけである。

### `pyproject.toml`

CLI script を追加する。

```toml
[project.scripts]
run-default-cost = "process_sim.plant.default_case_runner:run_default_cost_main"
```

想定実行コマンドは次である。

```powershell
uv --cache-dir .uv-cache run run-default-cost
```

HYSYS を起動するため、実行はユーザーが行う。

## 採用理由

### `default` を使う理由

この interface は、抽象的な基底 case を表すものではない。現時点で採用する代表条件を使って、cost 評価を再現するための入口である。

そのため、`base` より `default` が適切である。

### `run-default-cost` を使う理由

既存の `fast-plant-convergence-cost` は、HYSYS session を開いたまま使い回すという実装上の特徴を名前にしている。しかしユーザーが知りたいのは、default 条件で plant cost を実行する入口である。

`run-default-cost` は、対象と動作が明確である。

```text
run     実行入口
default 採用済み既定条件
cost    評価対象
```

### model 定義を `plant/cases/models.py` に置く理由

case model は runner 固有ではなく、plant cost 評価条件の構造である。

`plant/default_case_runner.py` に置くと、実行処理と条件定義が混ざる。`plant/cases/default.py` に置くと、default 条件の実体と model 定義が混ざる。`optimization/` に置くと、探索用の条件に見える。

したがって、型は `plant/cases/models.py`、default 実体は `plant/cases/default.py`、実行は `plant/default_case_runner.py` に分ける。

### separator 条件を case に含める理由

default cost 実行では、separator 条件も設計条件の一部である。反応器条件だけを default として持ち、separator 条件を runner 内で固定すると、後から cost 結果を再現しにくい。

そのため、`DefaultCase.separator` として、1基目デカンター温度と SM分離塔還流比を明示する。

## 採用しない案

### `base_cost_case.py` を作る案

採用しない。`base` は抽象的な基底条件に見えるが、今回必要なのは現在採用している default 条件である。

### `fast-plant-convergence-cost` を正式入口にする案

採用しない。既存入口は残してよいが、名前が実装都合に寄っている。default 条件の再現用入口としては、`run-default-cost` を新設する方が分かりやすい。

### case model を `optimization/separator/parameters.py` に拡張して置く案

採用しない。separator の探索候補と、plant cost 実行全体の case は責務が違う。

`SeparatorOperatingCandidate` は再利用してもよいが、plant 全体の case model は `plant/` 側に置く。

## 既知の制約

- HYSYS 実行はユーザーが行う。
- `DefaultCase` は、HYSYS case path、target SM、visible、初期 feed guess の詳細を持たない。
- HYSYS case path は `DEFAULT_HYSYS_CASE_PATH` から import する。
- target SM は既存の `DEFAULT_TARGET_SM_KMOL_H` を使う。
- HYSYS 表示設定は既存の自動実行方針に合わせ、runner 側で `False` 固定にする。
- `DefaultCase` は、HYSYS case 内部の stream 名や operation 名までは直接持たない。stream 名と operation 名は既存の `optimization/separator/hysys_controls.py` と `separator/hysys_equipment_reference.py` に従う。
- default 条件の値は、現時点の採用値であり、最終設計値として固定されたものではない。
- `reactor/cases/` の default reactor case には、過去条件のコメントが多く残っている。今回の interface ではそこを整理対象にしない。

## 未確定事項

- `DefaultCase.reactor` は既存の `RadialReactorCase` を使うため、現時点では radial 専用である。PFR も同じ interface に含めるかは未確定である。
- `fast-plant-convergence-cost` を README 上で非推奨扱いにするか、互換入口として残すだけにするか。

## 実装結果

以下を追加した。

```text
src/process_sim/
  plant/
    cases/
      __init__.py
      models.py
      default.py
    default_case_runner.py
pyproject.toml
README.md
```

`plant/cases/models.py` には、分離器条件の `SeparatorCondition` と、default 条件一式の `DefaultCase` を追加した。反応器条件用の新しい model は作らず、`DefaultCase.reactor` は既存の `RadialReactorCase` を受ける。

`plant/cases/default.py` には、Steam/EB 比、radial 反応器条件、分離器条件を明示した。`DEFAULT_STYRENE_RADIAL_REACTOR_CASE` をそのまま代入せず、`RadialReactorRunConditions` と `RadialReactorCase` をこのファイル内で組み立てる。

`plant/default_case_runner.py` は、`DEFAULT_CASE` を使って production target、recycle convergence、入口条件と分離器条件の HYSYS 書き込み、機器読み取り、全体コスト評価を行う。HYSYS case path は `DEFAULT_HYSYS_CASE_PATH`、目標 SM 流量は `DEFAULT_TARGET_SM_KMOL_H` を import して使う。

CLI 入口として `run-default-cost` を追加した。

```powershell
uv --cache-dir .uv-cache run run-default-cost
```

本作業では、HYSYS を起動する実行は行っていない。
