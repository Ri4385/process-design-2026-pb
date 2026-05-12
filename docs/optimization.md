# Optimization

## 目的

この文書は、最適化まわりの恒久的な設計メモとして使う。
現時点では、反応器最適化に必要な探索範囲、候補条件、制約値の表現を定義する。
Optuna 実行、目的関数、分離器最適化、ヒートインテグレーション、経済評価はまだ実装対象外である。

## 現在の実装範囲

現在の実装範囲は、反応器まわりの最適化入力を表す型と初期値の定義に限定する。

- `src/process_sim/optimization/models.py`
  - 共通の探索範囲型 `ParameterRange` を置く。
- `src/process_sim/optimization/reactor/parameters.py`
  - 反応器の探索空間 `ReactorParameterConfig` を置く。
  - 探索で生成された 1 ケース分の具体値 `ReactorCandidate` を置く。
  - 初期探索範囲として、温度、圧力、Steam/EB 比、段長を定数として置く。
  - 2段用と3段用の初期探索空間を `TWO_STAGE_REACTOR_PARAMETER_CONFIG` と `THREE_STAGE_REACTOR_PARAMETER_CONFIG` として置く。
- `src/process_sim/optimization/reactor/constraints.py`
  - 反応器候補に対する物理・設計上の制約値 `ReactorOptimizationConstraints` を置く。

## コード記述ルール

最適化まわりの Python コードでは、既存リポジトリの文体に合わせて docstring を日本語で書く。

定数、変数、dataclass フィールドには、その値がプロセス上で何を意味するかを日本語コメントで残す。
ただし、横に長い右端コメントは避け、原則として対象行の直前にコメントを書く。
フィールド一覧や定数一覧が横に長くなると読み落としやすいためである。

```python
# 反応器列入口圧力範囲。
# 0.1 atm から 1.5 atm 相当として置く。
INITIAL_INLET_PRESSURE_RANGE_KPA_ABS = ParameterRange(
    lower=10.1,
    upper=152.0,
)
```

短い補足であっても、今後は上の形式を基本とする。
単に変数名を日本語に直訳するだけのコメントは避け、設計上の意味や暫定値であることを必要に応じて書く。

## 探索範囲型

`ParameterRange` は、連続値の探索範囲を表す共通型である。

```python
@dataclass(frozen=True)
class ParameterRange:
    # 探索範囲の下限値。
    lower: float
    # 探索範囲の上限値。
    upper: float
```

`ParameterRange` は `src/process_sim/optimization/models.py` に置く。
反応器だけでなく、直後に追加する分離器側の温度、圧力、還流比などでも同じ型を使う可能性が高いため、初期実装から共通 module として扱う。

`ParameterRange.__post_init__` では、`lower < upper` だけを確認する。
これは探索範囲そのものの整合性確認であり、プロセス制約の判定ではない。

## 反応器探索空間

`ReactorParameterConfig` は、反応器最適化で探索する変数の範囲をまとめる型である。

```python
@dataclass(frozen=True)
class ReactorParameterConfig:
    # 各段の反応器入口温度範囲。
    stage_inlet_temperatures_c: tuple[ParameterRange, ...]
    # 反応器列入口圧力範囲。
    inlet_pressure_kpa_abs: ParameterRange
    # Steam/EB モル比範囲。
    steam_to_eb_ratio: ParameterRange
    # 各段の反応器長さ範囲。
    stage_lengths_m: tuple[ParameterRange, ...]
```

段数は、`stage_inlet_temperatures_c` の要素数から決める。
初期実装で許可する段数は 2 段または 3 段である。
`stage_inlet_temperatures_c` と `stage_lengths_m` の要素数は一致していなければならない。
この構造整合性は `ReactorParameterConfig.__post_init__` で検証する。

## 反応器候補条件

`ReactorCandidate` は、探索範囲そのものではなく、探索によって生成された 1 ケース分の具体的な反応器条件を表す型である。

```python
@dataclass(frozen=True)
class ReactorCandidate:
    # 各段の反応器入口温度。
    stage_inlet_temperatures_c: tuple[float, ...]
    # 反応器列入口圧力。
    inlet_pressure_kpa_abs: float
    # Steam/EB モル比。
    steam_to_eb_ratio: float
    # 各段の反応器長さ。
    stage_lengths_m: tuple[float, ...]
```

`ReactorCandidate` は `ReactorParameterConfig` から生成される前提で扱う。
そのため、初期実装では候補値が探索範囲内にあるかどうかの個別検証は行わない。
手動作成した候補や外部ファイルから読み込んだ候補を評価する用途が必要になった場合に、範囲検証を追加する。

EB 入口流量は `ReactorCandidate` に含めない。
目標 SM 生産量が固定されており、EB 入口流量は条件ごとに目標生産量へ合わせる調整値だからである。
探索変数ではなく、feed tuning または目的関数評価の内側で決まる値として扱う。

## 初期探索範囲

現時点の初期探索範囲は次の通りである。

| 項目 | 初期範囲 | 内部単位 | 備考 |
|---|---:|---|---|
| 各段入口温度 | 590 から 650 | degC | コンテスト資料を優先する。 |
| 反応器入口圧力 | 10.1 から 152.0 | kPa abs | 0.1 atm から 1.5 atm 相当として置く。 |
| Steam/EB 比 | 5 から 8 | mol/mol | 5 未満は炭素析出リスクの根拠があるため初期探索に入れない。 |
| 段数 | 2 または 3 | - | 別々の探索空間として扱う。 |
| 各段長 | 0.5 から 5.0 | m | 暫定値として置く。 |

段長の探索範囲は、現時点では `0.5 m` から `5.0 m` の暫定値として置く。
この範囲は最終的な設計判断ではなく、反応器最適化の実装を進めるための初期探索範囲である。

2段用と3段用の探索空間は、次の定数インスタンスとして明示する。

- `TWO_STAGE_REACTOR_PARAMETER_CONFIG`
- `THREE_STAGE_REACTOR_PARAMETER_CONFIG`

この2つは、2段と3段で探索変数の数が異なることを明示するためのものである。
2つの study を必ず並列実行するという意味ではない。

## 反応器制約

探索変数の上下限と、物理・設計上の制約は分ける。

探索変数の上下限は `ParameterRange` に持たせる。
物理・設計上の制約値は `ReactorOptimizationConstraints` にまとめる。

```python
@dataclass(frozen=True)
class ReactorOptimizationConstraints:
    # 反応器列出口圧力の下限。
    min_outlet_pressure_kpa_abs: float
    # 反応器1基あたりの圧力損失。
    pressure_drop_kpa_per_reactor: float
    # Steam/EB モル比の下限。
    min_steam_to_eb_ratio: float
    # 各段の反応器入口温度の上限。
    max_stage_inlet_temperature_c: float
```

初期制約値は次の通りである。

| 項目 | 値 | 単位 | 備考 |
|---|---:|---|---|
| 反応器列出口圧力の下限 | 10.1 | kPa abs | 0.1 atm 相当として置く。 |
| 反応器1基あたりの圧力損失 | 20.0 | kPa/reactor | コンテスト資料の 0.2 bar/reactor を基準にする。 |
| Steam/EB 比の下限 | 5.0 | mol/mol | 初期探索範囲の下限と同じ値で置く。 |
| 各段入口温度の上限 | 650.0 | degC | 初期探索範囲の上限と同じ値で置く。 |

初期実装では、制約値の定義に留める。
候補条件を生成し、評価関数へ接続する段階で、出口圧力の簡易推算などの制約判定を追加する。

## 圧力損失の扱い

圧力は、反応器列入口から各段で順に低下するものとして扱う。

```text
第 i 段入口圧力 = 反応器列入口圧力 - (i - 1) × 反応器1基あたり圧損
第 i 段出口圧力 = 反応器列入口圧力 - i × 反応器1基あたり圧損
反応器列出口圧力 = 反応器列入口圧力 - 段数 × 反応器1基あたり圧損
```

現行の `ReactorRunConditions` は単一の `pressure_kpa` しか持たないため、段ごとの圧力低下を反応速度計算へ厳密には渡せない。
このため、初期実装では候補の実現性判定として反応器列出口圧力を推算するに留める。
圧力プロファイルを反応器計算へ反映する場合は、先に反応器モデル側の入力を拡張する。

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
  models.py
  reactor/
    parameters.py
    constraints.py
  separator/
    parameters.py
    constraints.py
    hysys_controls.py
  heat_integration/
    models.py
    composite_curve.py
    evaluation.py
  economics/
    revenue.py
    operating_cost.py
    equipment_cost.py
  objective/
    profit.py
  runner/
    optuna_runner.py
```

この将来構成は予定であり、現時点で存在する実装とは区別する。
