# 20260507_01_optimization-implementation-plan

## 主題

最適化まわりの実装に入る前に、現時点で採用するコード構成、探索変数の表現、制約の扱い、Optuna との接続方針、将来の分離器・ヒートインテグレーション・経済評価への拡張方針を整理する。

この文書は、現時点の実装予定を固定するための作業記録であり、最終仕様書ではない。恒久化すべき内容は、後で `docs/optimization.md` に反映する。

---

## 1. 結論

最適化まわりは、最終的に反応器、分離器、ヒートインテグレーション、経済評価をまたぐ上位レイヤーとして扱う。

ただし初回実装では、反応器まわりの探索変数、候補条件、制約をコード化するところまでに限定する。Optuna 実行、目的関数、分離器変数、ヒートインテグレーション、経済評価はまだ実装しない。

初回のコード構成案は次の通りとする。

```text
src/process_sim/optimization/
  __init__.py
  reactor/
    __init__.py
    models.py
    definitions.py
    validation.py
    conditions.py
```

`models.py` には dataclass のみを置き、変換や検証の関数は置かない。model と logic を分ける。
`definitions.py` には、現時点で採用する反応器探索変数と制約値の初期定義を置く。
`validation.py` には候補条件の検証だけを置く。
`conditions.py` には既存反応器モデルの `ReactorRunConditions` へ変換する処理だけを置く。

---

## 2. 採用しない方針

### 2.1 `src/process_sim/optimization.py` の単一ファイル

採用しない。

反応器だけでなく、今後は分離器、ヒートインテグレーション、経済評価、探索 runner が増える見込みである。単一ファイルでは寿命が短く、後で大きな再配置が必要になる。

### 2.2 汎用最適化 DSL

採用しない。

`DecisionSpace`、`DecisionVariable`、`NumericBounds` のような汎用抽象を大きく作るのは現時点では過剰である。まだ分離器側や経済評価側の制御可能変数が確定していないため、汎用化の根拠が弱い。

### 2.3 Pydantic `Field` 制約を探索空間として使う方針

採用しない。

`Field(ge=..., le=...)` は入力値の検証には向いているが、探索空間の定義としては不足がある。たとえば step、log scale、categorical、sampler 固有の扱いを自然に表現しにくい。

また、Optuna だけでなく、グリッド探索、ランダム探索、Nelder-Mead 法などを使う可能性がある。したがって探索変数は、特定ライブラリのバリデーション機構ではなく、自前の軽い dataclass で表現する。

### 2.4 単位変換モジュール

作らない。

コード内の圧力単位は `kPa abs` に統一する。文献や課題資料上の `200 mmHg abs` は、文書で根拠として扱い、コードでは対応する `kPa abs` の値を直接持つ。

本プロジェクト内で同じ物理量を複数単位で持ち回る必要はない。単位変換モジュールを作ると、むしろどの単位を正とするかが曖昧になりやすいため、今後も作らない。

---

## 3. 探索変数の表現

探索変数は、自前の軽い dataclass で表現する。

想定する基本形は次の通り。

```python
@dataclass(frozen=True)
class FloatSearchParameter:
    name: str
    lower: float
    upper: float
    unit: str
    step: float | None = None
    description: str = ""
```

離散値が必要になった場合は、別型として追加する。

```python
@dataclass(frozen=True)
class CategoricalSearchParameter:
    name: str
    choices: tuple[int | float | str, ...]
    unit: str
    description: str = ""
```

反応器側では、探索変数をまとめる型を作る。

```python
@dataclass(frozen=True)
class ReactorSearchDefinition:
    stage_count: int
    stage_inlet_temperature_c: tuple[FloatSearchParameter, ...]
    inlet_pressure_kpa_abs: FloatSearchParameter
    steam_to_eb_ratio: FloatSearchParameter
    stage_length_m: tuple[FloatSearchParameter, ...]
```

ここでの `stage_count` は 2 または 3 を想定する。2段と3段は同じ探索に押し込まず、別々に扱う。

---

## 4. 反応器候補条件

探索によって生成された 1 ケースは、探索空間とは別の型で持つ。

```python
@dataclass(frozen=True)
class ReactorCandidate:
    stage_inlet_temperatures_c: tuple[float, ...]
    inlet_pressure_kpa_abs: float
    steam_to_eb_ratio: float
    stage_lengths_m: tuple[float, ...]
```

EB入口流量は `ReactorCandidate` に含めない。

理由は、目標 SM 生産量が固定されており、EB入口流量は条件ごとに目標生産量へ合わせる調整値だからである。探索変数ではなく、feed tuning または目的関数評価の内側で決まる値として扱う。

---

## 5. 制約の表現

探索変数の上下限と、物理・設計上の制約は分ける。

探索変数の上下限は `FloatSearchParameter` に持たせる。

物理・設計上の制約は、反応器用の制約 dataclass にまとめる。

```python
@dataclass(frozen=True)
class ReactorOptimizationConstraints:
    min_outlet_pressure_kpa_abs: float
    pressure_drop_kpa_per_reactor: float
    min_steam_to_eb_ratio: float
    max_stage_inlet_temperature_c: float
```

制約違反は、軽い記録型で返す。

```python
@dataclass(frozen=True)
class ConstraintViolation:
    name: str
    message: str
```

制約判定は `validation.py` に置く。

```python
def validate_reactor_candidate(
    candidate: ReactorCandidate,
    definition: ReactorSearchDefinition,
    constraints: ReactorOptimizationConstraints,
) -> tuple[ConstraintViolation, ...]:
    ...
```

初期に判定する内容は次を想定する。

- 段数と温度 tuple の長さが一致する。
- 段数と段長 tuple の長さが一致する。
- 温度、圧力、Steam/EB 比、段長が探索範囲内にある。
- 簡易推算した出口圧力が下限以上である。

出口圧力は、初期段階では次の簡易式で扱う。

```text
出口圧力 = 入口圧力 - 段数 × 反応器1基あたり圧損
```

圧損はコンテスト資料の `0.2 bar/反応器` を基準にする。ただし、コードでは `kPa/reactor` として保持する。

---

## 6. Optuna との接続

Optuna 依存は、探索変数の model には入れない。

将来 Optuna を使う場合は、探索変数定義を Optuna trial に変換する薄い関数を別に作る。

```python
def suggest_float_parameter(
    trial: optuna.Trial,
    parameter: FloatSearchParameter,
) -> float:
    return trial.suggest_float(
        parameter.name,
        parameter.lower,
        parameter.upper,
        step=parameter.step,
    )
```

これにより、探索変数の定義は Optuna に依存しない。グリッド探索、ランダム探索、Nelder-Mead 法を使う場合にも同じ探索変数定義を再利用できる。

Optuna の実行 runner は初回実装では作らない。将来 `src/process_sim/optimization/runner/` または `src/process_sim/optimization/optuna_runner.py` として追加する。

---

## 7. 既存反応器モデルへの接続

反応器候補を既存の `ReactorRunConditions` に変換する処理は `conditions.py` に置く。

```python
def build_reactor_run_conditions(
    candidate: ReactorCandidate,
    inlet_superficial_velocity_m_per_s: float,
    segments_per_stage: int,
    profile_points_per_stage: int,
) -> ReactorRunConditions:
    ...
```

ここでは、候補条件を既存モデルが受け取れる形に変換するだけにする。feed tuning や HYSYS 分離器の実行は行わない。

---

## 8. 反応器の初期探索範囲

現時点の初期範囲は次を想定する。

| 項目 | 初期範囲 | 内部単位 | 備考 |
|---|---:|---|---|
| 各段入口温度 | 590から650 | degC | コンテスト資料を優先する。 |
| 反応器入口圧力 | 未確定 | kPa abs | 出口圧力下限と圧損から決める。 |
| Steam/EB比 | 5から8 | mol/mol | 5未満は炭素析出リスクの根拠があるため初期探索に入れない。 |
| 段数 | 2または3 | - | 別々の study または別々の探索として扱う。 |
| 各段長 | 未確定 | m | 現行ケースを基準にするか、別途範囲を決める必要がある。 |

圧力の具体的な探索範囲と段長の探索範囲は、まだ確定していない。無理に固定せず、次の検討項目として残す。

---

## 9. L/D の扱い

L/D は初期の探索制約には入れない。

単一反応器を前提に寸法化する場合、L/D は重要な実現性指標である。しかし、並列化を許すなら、総反応器体積を複数基に分割することで L/D を調整できる。

したがって、L/D は最適化候補を生成する段階の必須制約ではなく、機器寸法化段階の実現性確認項目として扱う。

---

## 10. 将来の全体構成

将来、最適化まわりは次のように拡張する想定である。

```text
src/process_sim/optimization/
  reactor/
    models.py
    definitions.py
    validation.py
    conditions.py
  separator/
    models.py
    definitions.py
    validation.py
    hysys_controls.py
  heat_integration/
    models.py
    composite_curve.py
    evaluation.py
  economics/
    operating_cost.py
    equipment_cost.py
    revenue.py
  objective/
    profit.py
  runner/
    optuna_runner.py
```

この構成では、以下のように責務を分ける。

| パス | 置く内容 |
|---|---|
| `optimization/reactor/models.py` | 反応器最適化で使う dataclass。探索変数、制約、候補条件、制約違反の型だけを置く。 |
| `optimization/reactor/definitions.py` | 2段・3段反応器の初期探索変数と制約値を作る関数を置く。過去資料やコンテスト条件に基づく初期値はここに集約する。 |
| `optimization/reactor/validation.py` | 反応器候補が探索範囲と制約を満たすか判定する。出口圧力の簡易推算もここに置く。 |
| `optimization/reactor/conditions.py` | `ReactorCandidate` を既存の `ReactorRunConditions` に変換する。反応計算や feed tuning は行わない。 |
| `optimization/separator/models.py` | デカンター、蒸留塔など分離器最適化で使う dataclass を置く。 |
| `optimization/separator/definitions.py` | 分離器側の探索変数候補を置く。HYSYS で操作可能か未確認の値は、固定候補として区別する。 |
| `optimization/separator/validation.py` | 分離器候補の範囲、製品仕様、HYSYS で扱える値かを検証する。 |
| `optimization/separator/hysys_controls.py` | HYSYS 側へ渡せる操作条件への変換を置く。Python から制御不能な項目はここに置かない。 |
| `optimization/heat_integration/models.py` | TQ 線図や熱回収評価に使うストリーム、温度範囲、熱負荷の型を置く。 |
| `optimization/heat_integration/composite_curve.py` | 与熱・受熱複合線を作る処理を置く。 |
| `optimization/heat_integration/evaluation.py` | HI 後の外部加熱・外部冷却負荷を見積もる処理を置く。 |
| `optimization/economics/revenue.py` | SM、BZ、TL などの収入計算を置く。副生成物を売る/売らない比較もここで扱う。 |
| `optimization/economics/operating_cost.py` | 原料費、ユーティリティ費、電力費などのランニングコストを置く。 |
| `optimization/economics/equipment_cost.py` | 反応器、分離器、熱交換器、圧縮機などの年換算装置コストを置く。 |
| `optimization/objective/profit.py` | 収入、原料費、ユーティリティコスト、装置コストを合成し、最終評価値を返す。 |
| `optimization/runner/optuna_runner.py` | Optuna に依存する探索実行入口を置く。2段・3段は別 study として扱う想定。 |

この時点では `separator/`、`heat_integration/`、`economics/`、`objective/`、`runner/` は作らない。

---

## 11. 評価関数の扱い

評価関数は、ユーザー方針と過去レポート7の考え方に基づき、経済収支型を基本候補とする。

```text
評価値 = 収入 - 原料費 - ユーティリティコスト - 年換算装置コスト
```

ただし、初回実装では評価関数をコード化しない。

まずは反応器候補を表現し、既存反応器計算へ渡せるようにする。その後、分離器・ヒートインテグレーション・経済評価と接続する。

---

## 12. ヒートインテグレーションの扱い

ヒートインテグレーションは、最初から完全に目的関数へ入れない。

初期方針は次の通り。

1. HI なしの簡易ユーティリティ評価で候補を生成する。
2. 上位候補に対して TQ 線図または簡易ピンチ解析を行う。
3. HI 後の外部ユーティリティを再評価する。
4. HI なし最適と HI あり再評価で順位が変わるか確認する。

過去レポート7では、ヒートインテグレーションによりユーティリティコストが大きく下がっているため、後段再評価の有無で最適条件が変わる可能性がある。この点はレポート上の重要な比較軸になる。

---

## 13. 分離器の扱い

分離器側は、HYSYS で Python から制御可能な項目と、手動または固定値として扱う項目を分ける必要がある。

候補になる変数は次の通り。

- デカンター入口温度。
- デカンター圧力。
- 蒸留塔圧力。
- 蒸留塔段数。
- 還流比。
- フィード段。
- 製品仕様または回収率。

ただし、初回実装では分離器変数はコード化しない。まず HYSYS 側で制御可能な項目を確認してから設計する。

---

## 14. テスト方針

現段階では、数値条件がまだ揺れる可能性があるため、数値そのものを強く固定するテストは避ける。

将来テストを書く場合は、次の構造確認に留める。

- 2段候補は2段分の温度・段長を持つ。
- 3段候補は3段分の温度・段長を持つ。
- 2段・3段以外は拒否する。
- 範囲外候補に対して制約違反が返る。
- `ReactorCandidate` から `ReactorRunConditions` に変換できる。

圧力下限の具体値、Steam/EB 比の具体値、L/D を含まないことなどは、初期テストで固定しない。

---

## 15. 次に詰めるべき未確定事項

1. 反応器入口圧力の探索範囲。
2. 各段長または体積の探索範囲。
3. `FloatSearchParameter` に `step` を持たせるか、探索手法側に任せるか。
4. Optuna 変換関数をどの段階で実装するか。
5. 2段・3段の比較を同一 runner で扱うか、別 study として扱うか。
6. HYSYS 分離器で Python から制御可能な変数の確認。
