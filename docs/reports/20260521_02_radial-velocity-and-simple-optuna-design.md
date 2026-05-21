# radial 空塔速度固定と簡易 Optuna tuning 詳細設計

## 目的

本資料は、次の2点を実装する前の詳細設計である。

1. radial flow 反応器で、入口空塔速度を `2.0 m/s` に合わせて内径を調整する。
2. 原料費、収入、反応器装置コストだけを使う簡易 Optuna tuning を追加する。

本設計では、HYSYS 分離系の操作条件最適化、recycle 収束、用役費、蒸留塔コスト、ヒートインテグレーションは対象外とする。

## 現状確認

現行 radial 実装は次の構成である。

```text
src/process_sim/reactor/
  cases/
    styrene_radial_default.py        # radial 既定ケース
  core/
    models.py                        # RadialReactorRunConditions など
    radial_geometry.py               # radial 触媒床幾何
  types/
    radial_adiabatic.py              # 1基分の radial 反応器
    staged_adiabatic_radial.py       # 多段 radial 反応器
src/process_sim/optimization/
  models.py                          # ParameterRange
  reactor/
    parameters.py                    # 反応器探索範囲
    constraints.py                   # 反応器制約
```

現行の `RadialReactorRunConditions` は `bed_inner_radius_m` を固定値として持つ。既定値は `src/process_sim/reactor/cases/styrene_radial_default.py` で `1.0 m` である。

## radial 内径調整

### 結論

radial flow では、入口空塔速度 `2.0 m/s` を設計値として使い、第1段入口条件から触媒床内半径を逆算する。

流通断面積は radial flow の円筒面積なので、通常の円断面積ではなく次式を使う。

```text
A_in = Q_in / u_in
A_in = 2π r_in H
r_in = A_in / (2πH)
D_in = 2 r_in
```

ここで、`Q_in` は第1段入口の体積流量、`u_in` は入口空塔速度、`H` は触媒床高さである。

### 変更する型

`src/process_sim/reactor/core/models.py`

```python
@dataclass(frozen=True)
class RadialReactorRunConditions:
    inlet_pressure_pa: float
    stage_inlet_temperatures_k: tuple[float, ...]
    bed_inner_radius_m: float
    target_inlet_superficial_velocity_m_per_s: float | None
    bed_height_m: float
    bed_thicknesses_m: tuple[float, ...]
    pellet_diameter_m: float
    bed_void_fraction: float
    catalyst_bulk_density_kg_m3: float
    ergun_a: float
    ergun_b: float
    gas_viscosity_pa_s: float
    interstage_reheater_pressure_drop_pa: float
    segments_per_stage: int
    profile_points_per_stage: int
```

`target_inlet_superficial_velocity_m_per_s` が `None` の場合は、既存通り `bed_inner_radius_m` を使う。値がある場合は、実行時に `bed_inner_radius_m` を再計算する。

### 計算責務

`src/process_sim/reactor/types/staged_adiabatic_radial.py`

- `StagedAdiabaticRadialFlowModel.run()` の冒頭で、実際に使う `effective_bed_inner_radius_m` を決める。
- 第1段入口 stream、第1段入口温度、反応器列入口圧力、触媒床高さから入口体積流量を計算する。
- `target_inlet_superficial_velocity_m_per_s` が指定されている場合は、上式で `effective_bed_inner_radius_m` を計算する。
- 各段の `RadialBedGeometry` には、計算後の `effective_bed_inner_radius_m` を渡す。

`src/process_sim/reactor/types/radial_adiabatic.py`

- 1基分の計算ロジックは変更しない。
- `RadialBedGeometry` として渡された内半径を使って、従来通り profile、圧損、触媒体積を計算する。

### 既定ケース

`src/process_sim/reactor/cases/styrene_radial_default.py`

```python
DEFAULT_STAGED_ADIABATIC_RADIAL_CONDITIONS = RadialReactorRunConditions(
    inlet_pressure_pa=130_000.0,
    stage_inlet_temperatures_k=(900.0, 900.0, 900.0),
    bed_inner_radius_m=1.0,
    target_inlet_superficial_velocity_m_per_s=2.0,
    bed_height_m=5.0,
    ...
)
```

`bed_inner_radius_m=1.0` は fallback 値として残す。実際の既定実行では `target_inlet_superficial_velocity_m_per_s=2.0` により内半径を再計算する。

### ログ表示

`src/process_sim/plant/summary.py`

- 既存の stage summary に `inner diameter [m]` を追加する。
- `inner diameter [m]` は `2 * inner_radius_m` で表示する。
- `inlet velocity [m/s]` は既存通り表示し、既定ケースで第1段入口が `2.0 m/s` 付近になることを確認できるようにする。

## 簡易 Optuna tuning

### 結論

初期版は Python 反応器単体を評価対象にする。HYSYS 分離系を含めない。

目的関数は次の形にする。

```text
objective = revenue - feed_cost - annualized_reactor_cost
```

ただし、価格、運転時間、装置費係数は未確定であるため、実装時に固定値として勝手に入れない。値は設定 dataclass または JSON 入力で与える設計にする。

### 追加する構成

```text
src/process_sim/optimization/
  economics/
    __init__.py                    # package docstring のみ
    models.py                      # 経済評価の入力値と内訳モデル
    simple_profit.py               # 収入、原料費、反応器年換算コスト
  objective/
    __init__.py                    # package docstring のみ
    radial_simple_profit.py        # trial から radial case を作って評価
  runner/
    __init__.py                    # package docstring のみ
    optuna_runner.py               # Optuna study 実行入口
```

### ファイル責務

`src/process_sim/optimization/economics/models.py`

- `SimpleEconomicConfig` を定義する。
- `SimpleProfitBreakdown` を定義する。
- 価格、運転時間、装置費係数など、目的関数に必要な数値を明示的な入力として持つ。

想定する型は次の通りである。

```python
@dataclass(frozen=True)
class SimpleEconomicConfig:
    operating_hours_per_year: float
    styrene_price_yen_per_kg: float
    ethylbenzene_price_yen_per_kg: float
    steam_price_yen_per_kg: float
    reactor_base_cost_yen: float
    reactor_reference_volume_m3: float
    reactor_cost_exponent: float
    capital_recovery_factor_per_year: float


@dataclass(frozen=True)
class SimpleProfitBreakdown:
    revenue_yen_per_year: float
    feed_cost_yen_per_year: float
    reactor_annual_cost_yen_per_year: float
    objective_yen_per_year: float
```

`src/process_sim/optimization/economics/simple_profit.py`

- styrene 収入を計算する。
- EB と steam の原料費を計算する。
- 反応器装置コストを年換算する。
- 計算式はこの module に閉じる。

初期式は次の通りである。

```text
revenue = styrene_out_kg_h * operating_hours_per_year * styrene_price
feed_cost =
  eb_feed_kg_h * operating_hours_per_year * ethylbenzene_price
  + steam_feed_kg_h * operating_hours_per_year * steam_price
reactor_capital_cost =
  reactor_base_cost * (total_catalyst_volume / reactor_reference_volume) ** reactor_cost_exponent
annualized_reactor_cost = reactor_capital_cost * capital_recovery_factor
```

`src/process_sim/optimization/objective/radial_simple_profit.py`

- Optuna trial から radial 反応器候補を作る。
- `RadialReactorCase` に変換する。
- `StagedAdiabaticRadialFlowModel` を実行する。
- 制約違反または計算失敗時は trial を失敗扱いにする。
- `SimpleProfitBreakdown` を返す。

`src/process_sim/optimization/runner/optuna_runner.py`

- Optuna study を作成する。
- AutoSampler を使う。
- trial 数、seed、経済条件ファイル、出力 JSON の引数を読む。
- best trial と主要内訳だけを標準出力に出す。

## 探索変数

初期版の探索変数は次の通りにする。

| 項目 | 扱い |
|---|---|
| 段数 | 2 または 3 |
| 各段入口温度 | 既存 `optimization/reactor/parameters.py` の範囲を使う |
| 反応器列入口圧力 | 既存 `optimization/reactor/parameters.py` の範囲を使う |
| Steam/EB 比 | 既存 `optimization/reactor/parameters.py` の範囲を使う |
| 各段触媒層厚み | radial 用に新規追加する |
| 入口空塔速度 | `2.0 m/s` 固定 |

空塔速度は探索変数にしない。今回の主目的が「空塔速度 2.0 m/s に合わせて内径を調整すること」であるため、ここを同時に探索すると設計意図が曖昧になる。

## 制約処理

次の場合は、目的関数値を採用しない。

- 反応器計算で例外が出る。
- `pressure_positive_ok` が `False` である。
- `atom_balance_ok` が `False` である。
- `ergun_range_ok` が `False` である。
- `outlet_pressure_ok` が `False` である。
- styrene 生成量が正でない。

Optuna 側で `TrialPruned` にするか、明示的に大きな負の値を返すかは実装前に決める。初期設計としては、失敗理由を残しやすい `TrialPruned` を候補とする。

## CLI

CLI 名は未確定である。実装前に確認する。

候補は次のどちらかである。

```text
tune-simple-profit
tune-radial-simple-profit
```

引数候補は次の通りである。

```text
--n-trials
--seed
--economic-config
--output-json
```

`--economic-config` を必須にするか、未設定時にリポジトリ内の既定値を使うかは未確定である。価格と装置費係数を勝手に固定しないため、必須にする方が安全である。

## README と docs 更新

コード変更時は次を更新する。

```text
README.md
  実行コマンドと簡単な説明を追加する。
docs/radial-flow-reactor.md
  入口空塔速度 2.0 m/s による内径逆算を記録する。
docs/optimization.md
  簡易 Optuna tuning の実装範囲を記録する。
```

## 採用しない案

### HYSYS 分離系を目的関数に含める

採用しない。今回の簡易 tuning は原料費、収入、反応器装置コストだけを扱うためである。HYSYS を含めると、分離条件、収束、recycle、HYSYS 実行失敗の扱いを先に決める必要がある。

### 価格と装置費係数をコードに直書きする

採用しない。現時点で根拠が未確認であり、AGENTS.md の「勝手に仮定して進めない」に反するためである。

### 空塔速度も探索変数にする

採用しない。今回の設計指示は `2.0 m/s` に合わせて内径を調整することであり、空塔速度を探索対象にすると目的が変わるためである。

## 未確定要素

- 経済評価に使う styrene、EB、steam の価格。
- 年間運転時間。
- 反応器装置コストの相関式、基準コスト、指数、年換算係数。
- Optuna AutoSampler をどの import 経路で使うか。
- CLI 名。
- 経済条件ファイルを必須にするかどうか。
- 失敗 trial を `TrialPruned` にするか、ペナルティ値にするか。

