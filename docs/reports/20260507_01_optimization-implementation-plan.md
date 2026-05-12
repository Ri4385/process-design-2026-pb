# 20260507_01_optimization-implementation-plan

## 主題

最適化まわりの実装に入る前に、現時点で採用するコード構成、探索変数の表現、制約の扱い、Optuna との接続方針、将来の分離器・ヒートインテグレーション・経済評価への拡張方針を整理する。

この文書は、現時点の実装予定を固定するための作業記録であり、最終仕様書ではない。恒久化すべき内容は、`docs/optimization.md` に反映して管理する。

---

## 1. 結論

最適化まわりは、最終的に反応器、分離器、ヒートインテグレーション、経済評価をまたぐ上位レイヤーとして扱う。

ただし初回実装では、反応器まわりの探索変数、候補条件、制約をコード化するところまでに限定する。Optuna 実行、目的関数、分離器変数、ヒートインテグレーション、経済評価はまだ実装しない。

初回のコード構成案は次の通りとする。

```text
src/process_sim/optimization/
  __init__.py        # package docstring のみ
  models.py          # 共通の探索範囲型
  reactor/
    __init__.py      # reactor package docstring のみ
    parameters.py    # 反応器パラメータ範囲と候補条件
    constraints.py   # 反応器制約
```

初回実装では、反応器の「探索するパラメータ群」「探索で生成される候補条件」「制約条件」を定義するところまでに留める。候補条件の生成、制約チェック、既存反応器モデルへの変換、Optuna 実行はまだ実装しない。

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

探索変数の上下範囲は、自前の軽い dataclass で表現する。

想定する基本形は次の通り。

```python
@dataclass(frozen=True)
class ParameterRange:
    # 探索範囲の下限値。
    lower: float
    # 探索範囲の上限値。
    upper: float

    def __post_init__(self) -> None:
        if self.lower >= self.upper:
            raise ValueError("lower must be smaller than upper")
```

`ParameterRange` は `src/process_sim/optimization/models.py` に置く。反応器だけでなく、直後に追加する分離器側の探索変数でも同じ範囲型を使う可能性が高いため、初期実装から共通 module に置く。

変数名に `_c`、`_kpa_abs`、`_m` などを含め、単位はフィールド名で表す。`unit`、`name`、`description`、`step` は初期実装では持たせない。

反応器側では、探索対象の範囲をまとめる型を作る。

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

    def __post_init__(self) -> None:
        stage_count = len(self.stage_inlet_temperatures_c)

        if stage_count not in {2, 3}:
            raise ValueError("stage_count must be 2 or 3")

        if len(self.stage_lengths_m) != stage_count:
            raise ValueError(
                "stage_lengths_m must have the same length as "
                "stage_inlet_temperatures_c"
            )

    @property
    def stage_count(self) -> int:
        return len(self.stage_inlet_temperatures_c)
```

`ReactorParameterConfig` は `src/process_sim/optimization/reactor/parameters.py` に置く。

探索空間そのものの構造整合性は、制約判定ではなく、探索空間インスタンスの生成時に検証する。具体的には、`ReactorParameterConfig.__post_init__` で段数を `stage_inlet_temperatures_c` の要素数から決め、`stage_lengths_m` の要素数と一致することを確認する。初期実装で許可する段数は、2段または3段に限定する。

これらは、生成された候補条件に対する物理・設計制約ではなく、探索空間定義そのものの不整合である。そのため、`constraints.py` ではなく `parameters.py` 内の `ReactorParameterConfig.__post_init__` で検出する。

探索変数や候補条件を表す dataclass では、各フィールド定義の直前に日本語コメントを付ける。右端コメントは横に長くなりやすいため、原則として使わない。コメントでは、単位を含むフィールド名を補足し、その変数がプロセス上で何を意味するかを説明する。単にフィールド名を日本語に直訳するだけのコメントは避ける。

2段と3段は探索変数の数が異なるため、別々の定数インスタンスとして定義する。

```python
TWO_STAGE_REACTOR_PARAMETER_CONFIG = ReactorParameterConfig(...)
THREE_STAGE_REACTOR_PARAMETER_CONFIG = ReactorParameterConfig(...)
```

これは2つの study を必ず並列実行するという意味ではない。2段用と3段用の探索範囲を明示的に分けて持つためである。

---

## 4. 反応器候補条件

`ReactorCandidate` は、探索範囲そのものではなく、探索によって生成された 1 ケース分の具体的な反応器条件を表す型である。

たとえば `ReactorParameterConfig` が「温度は 590 から 650 degC の範囲で探索する」という探索空間を表すのに対し、`ReactorCandidate` は「第1段入口温度 620 degC、第2段入口温度 610 degC、入口圧力 80 kPa abs、Steam/EB 比 6.0」のような、実際に評価関数へ渡す 1 組の候補値を表す。

探索によって生成された 1 ケースは、`ReactorCandidate` として表す。`ReactorCandidate` は `src/process_sim/optimization/reactor/parameters.py` に置く。

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

EB入口流量は `ReactorCandidate` に含めない。

理由は、目標 SM 生産量が固定されており、EB入口流量は条件ごとに目標生産量へ合わせる調整値だからである。探索変数ではなく、feed tuning または目的関数評価の内側で決まる値として扱う。

---

## 5. 制約の表現

探索変数の上下限と、物理・設計上の制約は分ける。

探索変数の上下限は `ParameterRange` に持たせる。

物理・設計上の制約は、反応器用の制約 dataclass にまとめる。

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

制約判定は、候補条件を実際に生成する段階で追加する。初回実装では制約値の定義に留める。

初期に判定する内容は次を想定する。

- 簡易推算した出口圧力が下限以上である。

温度、圧力、Steam/EB 比、段長が探索範囲内にあるかどうかは、初期実装では個別の制約判定として扱わない。`ReactorCandidate` は `ReactorParameterConfig` から生成する前提であり、探索範囲外の候補を手動作成して評価する用途は現時点では想定しないためである。

圧力は、反応器列入口から各段で順に低下するものとして扱う。

```text
第 i 段入口圧力 = 反応器列入口圧力 - (i - 1) × 反応器1基あたり圧損
第 i 段出口圧力 = 反応器列入口圧力 - i × 反応器1基あたり圧損
反応器列出口圧力 = 反応器列入口圧力 - 段数 × 反応器1基あたり圧損
```

圧損はコンテスト資料の `0.2 bar/反応器` を基準にする。ただし、コードでは `kPa/reactor` として保持する。

現行の `ReactorRunConditions` は単一の `pressure_kpa` しか持たないため、段ごとの圧力低下を反応速度計算へ厳密には渡せない。このため、初期実装では候補の実現性判定として反応器列出口圧力を推算するに留める。圧力プロファイルを反応器計算へ反映する場合は、先に反応器モデル側の入力を拡張する必要がある。

---

## 6. Optuna との接続

Optuna 依存は、探索変数の model には入れない。

将来 Optuna を使う場合は、探索変数定義を Optuna trial に変換する薄い関数を別に作る。

```python
def suggest_parameter_range(
    trial: optuna.Trial,
    parameter_name: str,
    parameter_range: ParameterRange,
) -> float:
    return trial.suggest_float(
        parameter_name,
        parameter_range.lower,
        parameter_range.upper,
    )
```

これにより、探索変数の定義は Optuna に依存しない。グリッド探索、ランダム探索、Nelder-Mead 法を使う場合にも同じ探索変数定義を再利用できる。

Optuna の実行 runner は初回実装では作らない。将来 `src/process_sim/optimization/runner/` または `src/process_sim/optimization/optuna_runner.py` として追加する。

---

## 7. 既存反応器モデルへの接続

反応器候補を既存の `ReactorRunConditions` に変換する処理は、反応器候補を実際に実行する段階で追加する。初回実装では作らない。

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

ただし、現行の `ReactorRunConditions` は段ごとの圧力を表現できない。したがって候補変換処理を追加しても、それだけでは圧力低下を反応器計算へ反映できない。圧力低下を反応速度に効かせる場合は、`ReactorRunConditions` と反応器本体の拡張を別作業として行う。

---

## 8. 反応器の初期探索範囲

現時点の初期範囲は次を想定する。

| 項目 | 初期範囲 | 内部単位 | 備考 |
|---|---:|---|---|
| 各段入口温度 | 590から650 | degC | コンテスト資料を優先する。 |
| 反応器入口圧力 | 10.1から152.0 | kPa abs | 0.1 atm から 1.5 atm 相当として置く。 |
| Steam/EB比 | 5から8 | mol/mol | 5未満は炭素析出リスクの根拠があるため初期探索に入れない。 |
| 段数 | 2または3 | - | 別々の study または別々の探索として扱う。 |
| 各段長 | 0.5から5.0 | m | 暫定値として置く。 |

段長の探索範囲は、現時点では暫定値として固定する。これは最終的な設計判断ではなく、反応器最適化の実装を進めるための初期探索範囲である。

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
- `ReactorCandidate` から `ReactorRunConditions` に変換できる。

圧力下限の具体値、Steam/EB 比の具体値、L/D を含まないことなどは、初期テストで固定しない。

---

## 15. 次に詰めるべき未確定事項

1. Optuna 変換関数をどの段階で実装するか。
2. 2段・3段の比較を同一 runner で扱うか、別 study として扱うか。
3. HYSYS 分離器で Python から制御可能な変数の確認。
