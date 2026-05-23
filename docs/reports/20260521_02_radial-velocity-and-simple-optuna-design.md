# radial 空塔速度固定と簡易 Optuna tuning 詳細設計

## 目的

本資料は、次の2点を実装する前の詳細設計である。

1. radial flow 反応器で、入口空塔速度を `2.0 m/s` に合わせて内径を調整する。
2. 原料費、収入、反応器装置コストだけを使う簡易 Optuna tuning を追加する。

本設計では、最初の実装を反応器出口までの簡易評価に限定する。HYSYS 分離系はこの後すぐ接続対象になるが、今回の詳細設計では、まず反応器条件と簡易経済評価を独立に動かせる形を作る。

## 変更するディレクトリ概略

今回変更または追加するファイルは次の通りである。

```text
src/process_sim/reactor/
  cases/
    styrene_radial_default.py        # radial 既定条件。入口空塔速度2.0 m/sを固定値として持つ。
  core/
    models.py                        # RadialReactorRunConditions から bed_inner_radius_m を外す。
    radial_geometry.py               # 内半径、外半径、流通面積、触媒体積を計算する。
  types/
    radial_adiabatic.py              # 1基分の radial 反応器。渡された幾何で計算する。
    staged_adiabatic_radial.py       # 多段 radial 反応器。各段入口条件から各段の内半径を計算する。
src/process_sim/plant/
  economics.py                       # 既存価格、反応器コスト関数を置く。
  const.py                           # 年間稼働時間など既存の plant 固定値を使う。
src/process_sim/optimization/
  reactor/
    parameters.py                    # radial 用の触媒層厚み範囲と候補条件を追加する。
    constraints.py                   # radial 用の制約値を追加する。
  runner/
    radial_simple_optuna.py          # ファイル内定数を直接編集して Optuna を実行する。
docs/
  cost.md                            # 価格とコスト推算式の根拠。既存文書を参照する。
  radial-flow-reactor.md             # radial 実装メモを更新する。
  optimization.md                    # 簡易 tuning の実装範囲を更新する。
```

現行の `RadialReactorRunConditions` は `bed_inner_radius_m` を固定値として持つ。今回の変更では、固定内半径を条件から外し、入口空塔速度から一意に計算する。

## radial 内径調整

### 結論

radial flow では、入口空塔速度 `2.0 m/s` を設計値として使い、各段入口条件から各段の触媒床内半径を逆算する。

流通断面積は radial flow の円筒面積なので、通常の円断面積ではなく次式を使う。

```text
A_in = Q_in / u_in
A_in = 2π r_in H
r_in = A_in / (2πH)
D_in = 2 r_in
```

ここで、`Q_in` は各段入口の体積流量、`u_in` は入口空塔速度、`H` は触媒床高さである。

### 変更する型

`src/process_sim/reactor/core/models.py`

```python
@dataclass(frozen=True)
class RadialReactorRunConditions:
    inlet_pressure_pa: float
    stage_inlet_temperatures_k: tuple[float, ...]
    inlet_superficial_velocity_m_per_s: float
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

`bed_inner_radius_m` は削除する。`inlet_superficial_velocity_m_per_s` は必須値とし、`None` や fallback は持たせない。これにより、内半径の出所が常に入口空塔速度からの計算に限定される。

### 計算責務

`src/process_sim/reactor/types/staged_adiabatic_radial.py`

- `StagedAdiabaticRadialFlowModel.run()` の各段計算直前に、その段で使う `bed_inner_radius_m` を計算する。
- 各段入口 stream、各段入口温度、各段入口圧力、触媒床高さから入口体積流量を計算する。
- `conditions.inlet_superficial_velocity_m_per_s` から、各段入口空塔速度が `2.0 m/s` になる内半径を計算する。
- 各段の `RadialBedGeometry` には、計算後の `bed_inner_radius_m` を渡す。

`src/process_sim/reactor/types/radial_adiabatic.py`

- 1基分の計算ロジックは変更しない。
- `RadialBedGeometry` として渡された内半径を使って、従来通り profile、圧損、触媒体積を計算する。

### 既定ケース

`src/process_sim/reactor/cases/styrene_radial_default.py`

```python
DEFAULT_STAGED_ADIABATIC_RADIAL_CONDITIONS = RadialReactorRunConditions(
    inlet_pressure_pa=130_000.0,
    stage_inlet_temperatures_k=(900.0, 900.0, 900.0),
    inlet_superficial_velocity_m_per_s=2.0,
    bed_height_m=5.0,
    ...
)
```

内半径は既定ケースに置かない。既定実行でも探索実行でも、入口空塔速度 `2.0 m/s` と各段入口体積流量から段ごとに計算する。

### ログ表示

`src/process_sim/plant/summary.py`

- 既存の stage summary に `inner diameter [m]` を追加する。
- `inner diameter [m]` は `2 * inner_radius_m` で表示する。
- `inlet velocity [m/s]` は既存通り表示し、各段入口が `2.0 m/s` 付近になることを確認できるようにする。

## 簡易 Optuna tuning

### 結論

初期版は Python 反応器単体を評価対象にする。HYSYS 分離系は後続で接続する前提とし、今回のファイル構成では目的関数を差し替えやすくしておく。

目的関数は次の形にする。

```text
objective = revenue - feed_cost - annualized_reactor_cost
```

価格と年間稼働時間は既存文書と既存コードの値を使う。価格推算方法は `docs/cost.md`、年間稼働時間は `src/process_sim/plant/const.py` の `HOURS_PER_YEAR = 8000.0` を正とする。

### 実装構成

```text
src/process_sim/plant/
  economics.py                     # 価格、反応器コスト、年間価値計算
src/process_sim/optimization/
  runner/
    radial_simple_optuna.py        # ファイル冒頭の定数と専用目的関数を編集して実行する Optuna runner
```

### ファイル責務

`src/process_sim/plant/economics.py`

- 既存の `FEED_PRICE_YEN_PER_KG` と `PRODUCT_PRICE_YEN_PER_KG` を使う。
- `docs/cost.md` の反応器コスト式を関数化する。
- SM 収入、EB と steam の原料費、反応器年換算コストに必要な共通関数を置く。

想定する型は次の通りである。

```python
@dataclass(frozen=True)
class SimpleProfitBreakdown:
    revenue_yen_per_year: float
    feed_cost_yen_per_year: float
    reactor_annual_cost_yen_per_year: float
    objective_yen_per_year: float
```

反応器コスト式は `docs/cost.md` の次式を使う。

```text
Cost [yen] = 20,000,000 * D^1.066 * H^0.82 + heat_exchanger_assumed_cost
```

今回の簡易 tuning では、反応器本体コストだけを使う。`heat_exchanger_assumed_cost` は、反応器まわりの加熱器や段間再加熱器を熱交換器扱いで足す項と考えられるが、現時点では扱いが十分に整理できていない。後で追加する場合も別項目として足せるため、初期実装には含めない。

```text
revenue = styrene_out_kg_h * operating_hours_per_year * styrene_price
feed_cost =
  fresh_eb_kg_h * operating_hours_per_year * ethylbenzene_price
  + steam_feed_kg_h * operating_hours_per_year * steam_price
reactor_capital_cost =
  sum(20,000,000 * D_i^1.066 * H^0.82 for each reactor stage)
annualized_reactor_cost = reactor_capital_cost / 7
```

2026-05-22 の修正で、`radial_simple_optuna.py` 専用の EB 原料費は反応器入口 EB 全量ではなく、未反応 EB の 99% をリサイクルできる前提で必要な fresh EB だけに変更した。計算式は次の通りである。

```text
fresh_eb = max(reactor_feed_eb - 0.99 * reactor_outlet_eb, 0)
feed_cost = fresh_eb_cost + steam_feed_cost
```

この変更は反応器単体の簡易評価 runner に限定する。共通の `src/process_sim/plant/economics.py` には 99% recycle 前提を置かない。HYSYS を通す `radial_fast_plant_optuna.py` では、plant 側の収束計算から得た steady fresh feed を使うため、この簡易式は使わない。

`src/process_sim/optimization/runner/radial_simple_optuna.py`

- Optuna trial から radial 反応器候補を作る。
- `RadialReactorCase` に変換する。
- `StagedAdiabaticRadialFlowModel` を実行する。
- Optuna study を作成する。
- `from optuna.samplers import TPESampler` で TPE sampler を使う。
- trial 数、seed、探索範囲はファイル冒頭の定数として直接編集する。
- best trial と主要内訳だけを標準出力に出す。

## 探索変数

初期版の探索変数は次の通りにする。

| 項目 | 範囲または値 | 扱い |
|---|---:|---|
| 段数 | 2 または 3 | categorical |
| 各段入口温度 | 590 から 650 degC | 各段独立 |
| 反応器列入口圧力 | 50 から 200 kPa abs | `docs/reports/20260518_01_radial-flow-reactor-design.md` の radial 設計範囲 |
| Steam/EB 比 | 5 から 11 | 文献側の条件を含める radial 設計範囲 |
| 各段触媒層厚み | 0.3 から 1.2 m | 各段独立 |
| 入口空塔速度 | 2.0 m/s | 固定値 |

空塔速度は探索変数にしない。今回の主目的が「空塔速度 2.0 m/s に合わせて内径を調整すること」であるため、ここを同時に探索すると設計意図が曖昧になる。

反応器列入口圧力は、既存 `docs/optimization.md` の旧範囲 `10.1 から 152.0 kPa abs` ではなく、radial 詳細設計で整理済みの `50 から 200 kPa abs` を使う。3段構成では段間再加熱器圧損が合計 `40 kPa` 加わるため、`150 kPa abs` 上限では探索範囲が狭くなる。

### 段数ごとの study 分割

2段と3段は探索次元が異なるため、同一 study には混ぜない。`N=2` の第2段入口温度と、`N=3` の第2段入口温度は、後段の有無が違うため同じ意味にはならない。

runner では 2段用 study と 3段用 study を別々に作る。

```text
study_radial_2stage
  stage_1_temperature_c
  stage_2_temperature_c
  stage_1_bed_thickness_m
  stage_2_bed_thickness_m

study_radial_3stage
  stage_1_temperature_c
  stage_2_temperature_c
  stage_3_temperature_c
  stage_1_bed_thickness_m
  stage_2_bed_thickness_m
  stage_3_bed_thickness_m
```

入口圧力と Steam/EB 比は、それぞれの study 内で同じ範囲から探索する。最終比較では、2段 study の best trial と 3段 study の best trial を同じ objective 値で比較する。

## 制約処理

次の場合は、目的関数値を採用しない。

- 反応器計算で例外が出る。
- `pressure_positive_ok` が `False` である。
- `atom_balance_ok` が `False` である。
- `ergun_range_ok` が `False` である。
- `outlet_pressure_ok` が `False` である。
- styrene 生成量が正でない。

制約違反や計算失敗は `optuna.TrialPruned` にする。ペナルティ関数は初期実装では作らない。

## 実行方法

毎回 CLI 引数を付ける構成にはしない。探索条件は `src/process_sim/optimization/runner/radial_simple_optuna.py` の冒頭定数を直接編集する。

```text
N_TRIALS = 30
SEED = 42
STUDY_CONFIGS = (
    ("radial_2stage_simple_profit", TWO_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG),
    ("radial_3stage_simple_profit", THREE_STAGE_RADIAL_REACTOR_PARAMETER_CONFIG),
)
```

実行は module を直接指定して行う。

```powershell
uv run python -m process_sim.optimization.runner.radial_simple_optuna
```

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

### 価格を新しい設定ファイルで二重管理する

採用しない。価格は `docs/cost.md` と `src/process_sim/plant/economics.py` に既に整理されているため、別 JSON や別 dataclass で重複管理しない。

### 空塔速度も探索変数にする

採用しない。今回の設計指示は `2.0 m/s` に合わせて内径を調整することであり、空塔速度を探索対象にすると目的が変わるためである。

## 未確定要素

現時点ではなし。HYSYS 分離系を目的関数へ接続する段階で、別途 runner と目的関数を設計する。
