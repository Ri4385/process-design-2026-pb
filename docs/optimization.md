# Optimization

## 目的

この文書は、最適化まわりの恒久的な設計メモとして使う。
現時点では、反応器最適化に必要な探索範囲、候補条件、制約値、radial 反応器の簡易 Optuna tuning を定義する。
分離器最適化、ヒートインテグレーション、HYSYS 接続後の経済評価はまだ実装対象外である。

## 現在の実装範囲

現在の実装範囲は、反応器まわりの最適化入力を表す型と初期値の定義に限定する。

現在のディレクトリ構成は次の通りである。

```text
src/process_sim/optimization/
  models.py          # 共通の探索範囲型
  reactor/
    parameters.py    # 反応器パラメータ範囲と候補条件
    constraints.py   # 反応器制約
  runner/
    radial_simple_optuna.py  # radial 反応器の簡易利益 Optuna runner
    reactor_pareto_v2_optuna.py  # radial・axial 反応器の選択率・単通反応率 Pareto front 探索 runner
```

- `src/process_sim/optimization/models.py`
  - 共通の探索範囲型 `ParameterRange` を置く。
- `src/process_sim/optimization/reactor/parameters.py`
  - radial の探索空間 `RadialReactorParameterConfig` と候補値 `RadialReactorCandidate` を置く。
  - axial PFR の探索空間 `AxialParetoParameterConfig` と候補値 `AxialParetoCandidate` を置く。
  - radial は触媒層厚み、axial PFR は段別 `L/D` を探索する。
- `src/process_sim/optimization/reactor/constraints.py`
  - 反応器候補に対する物理・設計上の制約値 `ReactorOptimizationConstraints` を置く。
- `src/process_sim/optimization/runner/radial_simple_optuna.py`
  - 2段 radial study と 3段 radial study を別々に実行する。
  - `from optuna.samplers import TPESampler` を使う。
  - 各 trial の候補条件、制約結果、簡易利益内訳を logging へ出す。
- `src/process_sim/optimization/runner/reactor_pareto_v2_optuna.py`
  - radial 2段、radial 3段、axial 2段、axial 3段を別 study として実行する。
  - `from optuna.samplers import NSGAIISampler` を使う。
  - SM 選択率と EB 単通反応率を同時に最大化する。
  - `data/optuna/reactor_pareto_v2_optuna.db` を使い、中断後に探索を再開できるようにする。

## コード記述ルール

最適化まわりの Python コードでは、既存リポジトリの文体に合わせて docstring を日本語で書く。

定数には、その値がプロセス上で何を意味するかを直前の日本語コメントで残す。
定数コメントは横に長くなりやすいため、右端コメントではなく対象行の直前に書く。

```python
# Pareto v2 radial 2 段の反応器列入口圧力範囲。
TWO_STAGE_RADIAL_INLET_PRESSURE_RANGE_KPA_ABS = ParameterRange(
    lower=80.0,
    upper=200.0,
)
```

dataclass のフィールドは一覧性を優先し、短い日本語コメントを右端に書く。
右端コメントの列は可能な範囲で揃える。

```python
@dataclass(frozen=True)
class AxialParetoCandidate:
    stage_inlet_temperatures_c: tuple[float, ...]  # 各段の反応器入口温度
    steam_to_eb_ratio: float                       # Steam/EB モル比
    stage_ld_ratios: tuple[float, ...]             # 各段の L/D
```

単に変数名を日本語に直訳するだけのコメントは避け、設計上の意味や暫定値であることを必要に応じて書く。

## 探索範囲型

`ParameterRange` は、連続値の探索範囲を表す共通型である。

```python
@dataclass(frozen=True)
class ParameterRange:
    lower: float  # 探索範囲の下限値
    upper: float  # 探索範囲の上限値
```

`ParameterRange` は `src/process_sim/optimization/models.py` に置く。
反応器だけでなく、直後に追加する分離器側の温度、圧力、還流比などでも同じ型を使う可能性が高いため、初期実装から共通 module として扱う。

`ParameterRange.__post_init__` では、`lower < upper` だけを確認する。
これは探索範囲そのものの整合性確認であり、プロセス制約の判定ではない。

## 反応器探索空間

radial と axial PFR は、寸法決定方法が異なるため別の探索空間型で扱う。

```python
@dataclass(frozen=True)
class RadialReactorParameterConfig:
    stage_inlet_temperatures_c: tuple[ParameterRange, ...]  # 各段の反応器入口温度範囲
    inlet_pressure_kpa_abs: ParameterRange                  # 反応器列入口圧力範囲
    steam_to_eb_ratio: ParameterRange                       # Steam/EB モル比範囲
    bed_thicknesses_m: tuple[ParameterRange, ...]           # 各段の触媒層厚み範囲

@dataclass(frozen=True)
class AxialParetoParameterConfig:
    stage_inlet_temperatures_c: tuple[ParameterRange, ...]  # 各段の反応器入口温度範囲
    steam_to_eb_ratio: ParameterRange                       # Steam/EB モル比範囲
    stage_ld_ratios: tuple[ParameterRange, ...]             # 各段の L/D 範囲
```

段数は、`stage_inlet_temperatures_c` の要素数から決める。
初期実装で許可する段数は 2 段または 3 段である。
温度と、反応器型に応じた段別探索変数の要素数は一致していなければならない。
この構造整合性は各 config の `__post_init__` で検証する。

## 反応器候補条件

候補条件型は、探索範囲そのものではなく、探索によって生成された 1 ケース分の具体的な反応器条件を表す。

```python
@dataclass(frozen=True)
class RadialReactorCandidate:
    stage_inlet_temperatures_c: tuple[float, ...]  # 各段の反応器入口温度
    inlet_pressure_kpa_abs: float                  # 反応器列入口圧力
    steam_to_eb_ratio: float                       # Steam/EB モル比
    bed_thicknesses_m: tuple[float, ...]           # 各段の触媒層厚み

@dataclass(frozen=True)
class AxialParetoCandidate:
    stage_inlet_temperatures_c: tuple[float, ...]  # 各段の反応器入口温度
    steam_to_eb_ratio: float                       # Steam/EB モル比
    stage_ld_ratios: tuple[float, ...]             # 各段の L/D
```

候補条件は対応する config から生成される前提で扱う。
そのため、初期実装では候補値が探索範囲内にあるかどうかの個別検証は行わない。
手動作成した候補や外部ファイルから読み込んだ候補を評価する用途が必要になった場合に、範囲検証を追加する。

EB 入口流量は `ReactorCandidate` に含めない。
目標 SM 生産量が固定されており、EB 入口流量は条件ごとに目標生産量へ合わせる調整値だからである。
探索変数ではなく、feed tuning または目的関数評価の内側で決まる値として扱う。

## Pareto v2 探索範囲

現行の radial・axial PFR 比較用探索範囲は次の通りである。

| 項目 | radial | axial PFR |
|---|---:|---:|
| 各段入口温度 | 550 から 650 degC | 550 から 650 degC |
| 反応器入口圧力 | 2段は 80 から 200 kPa abs、3段は 100 から 200 kPa abs | 2段は 80 から 300 kPa abs、3段は 100 から 300 kPa abs |
| Steam/EB 比 | 5 から 11 mol/mol | 5 から 11 mol/mol |
| 段数 | 2 または 3 | 2 または 3 |
| 段別寸法探索値 | 触媒層厚み 0.3 から 1.2 m | `L/D` 0.2 から 1.0 |
| 各段入口空塔速度 | 2.0 m/s 固定 | 2.0 m/s 固定 |

radial の高さと axial PFR の直径、長さ、触媒体積は入力ではなく計算結果である。

## ラジアル反応器の簡易 Optuna tuning

radial 反応器では、PFR 用の段長ではなく、触媒層厚みを探索変数にする。

初期探索範囲は次の通りである。

| 項目 | 初期範囲 | 内部単位 | 備考 |
|---|---:|---|---|
| 各段入口温度 | 590 から 650 | degC | 各段独立に探索する。 |
| 反応器入口圧力 | 50 から 200 | kPa abs | 段間再加熱器圧損を見込む。 |
| Steam/EB 比 | 5 から 11 | mol/mol | 文献側の条件を含める。 |
| 段数 | 2 または 3 | - | 2段 study と3段 study を別々に作る。 |
| 各段触媒層厚み | 0.3 から 1.2 | m | 各段独立に探索する。 |
| 入口空塔速度 | 2.0 | m/s | 探索変数にせず固定値とする。 |

2段と3段は探索次元が異なるため、同一 study には混ぜない。`N=2` の第2段入口温度と、`N=3` の第2段入口温度は後段の有無が違うため同じ意味にならない。したがって、2段用と3段用の best trial を最後に同じ目的関数値で比較する。

目的関数は次である。

```text
objective = styrene revenue - EB and steam feed cost - annualized reactor body cost
```

価格は `docs/cost.md` と `src/process_sim/plant/economics.py` に記録済みの値を使う。年間稼働時間は `src/process_sim/plant/const.py` の `HOURS_PER_YEAR = 8000.0` を使う。反応器本体費は `docs/cost.md` の反応器式を使い、熱交換器と仮定したコストは初期実装では含めない。

制約違反や計算失敗は `optuna.TrialPruned` とする。ペナルティ関数は初期実装では作らない。

各 trial の反応器詳細ログは、既存のラジアル反応器レポート形式で標準出力に出す。これは Optuna の内部ログではなく、反応器計算の値を確認するための出力である。

実行時は、`src/process_sim/optimization/runner/radial_simple_optuna.py` の冒頭定数を直接編集し、次で実行する。

```powershell
uv run python -m process_sim.optimization.runner.radial_simple_optuna
```

## 反応器制約

探索変数の上下限と、反応器計算後に判定する制約は分ける。

| 項目 | radial | axial PFR |
|---|---:|---:|
| 反応器列出口圧力の下限 | 60 kPa abs | 60 kPa abs |
| 圧力正値 | 必須 | 必須 |
| 元素収支 | 必須 | 必須 |
| Ergun 適用範囲 | 必須 | 必須 |
| 触媒層出口空塔速度 | 1.0 m/s 以上 | - |
| profile 上の空塔速度 | - | 1.0 から 3.0 m/s |
| 各段長 | - | 10 m 以下 |

Peclet 数制約は現時点では入れない。

元素収支は、入口と出口の C 原子流量、H 原子流量について、それぞれ次の相対誤差が `1e-8` 未満であることを要求する。

```text
abs(outlet atom flow - inlet atom flow) / abs(inlet atom flow) < 1e-8
```

## 圧力損失の扱い

圧力は、触媒層内で Ergun 式を使って局所的に積分する。段間では再加熱器 1 基あたり `20 kPa` を差し引く。

反応器列出口圧力の下限は `60 kPa abs` とする。後段熱交換器の圧力損失 `10 kPa` を見込み、デカンターで `50 kPa abs` を保つためである。

## 今後の接続方針

Optuna 依存は、探索範囲や候補条件の型には入れない。
将来 Optuna を使う場合は、`ParameterRange` を `trial.suggest_float` へ変換する薄い関数を別に作る。

`ReactorCandidate` から既存の `ReactorRunConditions` へ変換する処理は、候補条件を実際に反応器計算へ渡す段階で追加する。
この変換では候補条件を既存モデルが受け取れる形に変換するだけにし、feed tuning、HYSYS 分離器の実行、経済評価は行わない。

分離器側は、HYSYS で Python から制御可能な項目を確認した後に、`optimization/separator/parameters.py` と `optimization/separator/constraints.py` として追加する。

## 将来の設計像

最適化まわりは、最終的に反応器、分離器、ヒートインテグレーション、経済評価をまたぐ上位レイヤーとして扱う。
現時点では反応器まわりの型と初期値だけを実装し、分離器、ヒートインテグレーション、経済評価、runner は後続作業で追加する。

想定する将来構成は次の通りである。

```text
src/process_sim/optimization/
  models.py          # 共通の探索範囲型
  reactor/
    parameters.py      # 反応器パラメータ範囲と候補条件
    constraints.py     # 反応器制約
  separator/
    parameters.py      # 分離パラメータ範囲
    constraints.py     # 分離制約
    hysys_controls.py  # HYSYS操作条件への変換
  heat_integration/
    models.py          # 熱流・温度範囲の型
    composite_curve.py # 与熱/受熱複合線の作成
    evaluation.py      # HI後の外部負荷評価
  economics/
    revenue.py         # 製品・副生成物収入の計算
    operating_cost.py  # 原料・用役・電力費の計算
    equipment_cost.py  # 機器費の年換算計算
  objective/
    profit.py          # 経済収支の評価関数
  runner/
    optuna_runner.py   # Optuna study の実行入口
```

この将来構成は予定であり、現時点で存在する実装とは区別する。
