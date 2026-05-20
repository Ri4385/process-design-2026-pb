# PFR 圧力損失・ログ改善 詳細設計

## 目的

本資料は、既存の多段断熱 PFR 実装に対して、圧力損失、段間再加熱器圧力損失、ログ出力を追加するための詳細設計である。

現在の PFR は比較用モデルとして残しているが、圧力を全段一定として扱っており、ラジアルフロー反応器と同じ条件で比較するには不足がある。今後は PFR でも反応器内圧力損失と段間再加熱器圧力損失を明示的に扱い、ログも radial と同じ粒度で読めるようにする。

主な目的は、将来的に PFR 1 基と radial 1 基を同条件で比較し、圧力損失の分布を可視化できる状態にすることである。さらに、同じ staged 構成でも PFR と radial の圧力分布を比較できるようにする。ただし、可視化機能そのものは今回の変更スコープには含めない。今回の対象は、可視化に必要な profile 情報とログ情報を PFR 側にも持たせるところまでである。

## 結論

PFR は、1 基分の PFR と staged PFR を分けて実装する。1 基分の PFR は、radial の `RadialAdiabaticReactor` と比較できる単位として扱う。staged PFR は、1 基分の PFR を段数分呼び出し、段間再加熱と段間圧力損失を管理する。

主な変更は次の通りである。

- 各段の PFR 収支式に圧力を追加し、Ergun 式で `dP/dz` を計算する。
- 1 基分の PFR クラスを新設し、既存の `StagedAdiabaticPfrModel` から段内計算を切り出す。
- 段間再加熱器では、radial と同じく再加熱 1 回あたり `20 kPa` の固定圧力損失を差し引く。
- 反応速度評価では、固定圧力ではなく局所圧力から分圧を計算する。
- PFR の既定入口圧力は、radial と比較しやすくするため `200 kPa abs` にする。
- `run-reactor-case --reactor-model pfr` では、PFR 専用の完全な `[PFR Reactor Summary]` を標準出力に出す。
- `run-plant-once --reactor-model pfr` では、HYSYS に渡す直前に同じ PFR summary を logging に出す。
- `tune-plant-feed` と `run-plant-convergence` では、複数回実行時に長すぎるログを避けるため、既定では簡易 reactor summary にする。

## 現状

現在の PFR 実装は次の構成である。

```text
src/process_sim/
  cli.py                              # run-reactor-case の入口と既存の PFR 向け表示
  reactor/
    cases/
      styrene_default.py              # PFR の既定ケース
    core/
      balance.py                      # PFR と radial の収支式
      integrator.py                   # RK4 積分
      models.py                       # 反応器条件、ログ、結果モデル
      pressure_drop.py                # radial 用に追加済みの Ergun 関連処理
      stream.py                       # 反応器 stream
      thermodynamics.py               # 熱物性、反応エンタルピー
    types/
      staged_adiabatic_pfr.py         # 多段断熱 PFR
  plant/
    runner.py                         # plant one-pass 実行
    production_target.py              # feed tuning
    convergence.py                    # plant convergence
    summary.py                        # plant と reactor summary
tests/
  test_reactor_simulator.py           # 反応器単体テスト
  test_plant_feed_tuning.py           # feed tuning と CLI 経路テスト
```

現在の `StagedAdiabaticPfrModel` は、1 基分の PFR と staged PFR の責務が同じ class にまとまっている。`ReactorRunConditions.pressure_kpa` は全段固定圧力として使われ、`pfr_adiabatic_derivatives` も `pressure_kpa` から分圧を計算している。状態変数に圧力は含まれていない。

既存ログは PFR 由来の簡易表示であり、圧力損失、段間再加熱器圧力損失、元素収支、制約判定を体系的に出していない。

## 採用する設計

### PFR の圧力損失

PFR では、軸方向位置 `z` に沿って Ergun 式を適用する。

反応器断面積は、指定した総触媒体積と総段長から決める。

```text
A_c = V_cat,total / L_total
```

局所の superficial mass velocity は、局所 stream の質量流量を一定断面積で割って求める。

```text
G(z) = m_dot(z) / A_c
```

ガス密度は radial と同じ方針で、局所の温度、圧力、組成から理想気体として計算する。

```text
rho_g(z) = P(z) * M_bar(z) / (R * T(z))
M_bar(z) = sum(y_i(z) * M_i)
```

Ergun 式は SI 単位で扱う。

```text
dP/dz = -[
  b * (1 - eps)^2 * mu * G / (eps^3 * dp^2 * rho_g)
  + a * (1 - eps) * G^2 / (eps^3 * dp * rho_g)
]
```

ここで、`a = 1.75`、`b = 150`、`eps` は触媒床空隙率、`dp` は触媒粒子径、`mu` は混合ガス粘度である。実装では既存の `pressure_drop.py` にある `ergun_pressure_gradient_pa_per_m` を共用できる。

### 収支式

PFR の状態変数を次の形に変更する。

```text
[F_eb, F_h2o, F_sm, ..., F_co, T, P]
```

物質収支とエネルギー収支は現行のまま、一定断面積 `A_c` を使う。

```text
dF_j/dz = A_c * sum(nu_ij * r_i)

dT/dz = - A_c * sum(r_i * DeltaH_i) / sum(F_j * Cp_j)
```

分圧は固定圧力ではなく、状態変数の `P(z)` から計算する。

```text
P_j(z) = y_j(z) * P(z)
```

### 段間再加熱器圧力損失

段間再加熱では radial と同じく、再加熱 1 回あたり `20 kPa` の固定圧力損失を与える。

- 2 段 PFR では、再加熱が 1 回なので合計 `20 kPa` を差し引く。
- 3 段 PFR では、再加熱が 2 回なので合計 `40 kPa` を差し引く。

反応器内の Ergun 圧損と、段間再加熱器圧損はログ上で分ける。

### 触媒量

PFR では反応器断面積 `A_c` と段長 `L_i` から各段の触媒体積を計算する。

```text
V_cat,i = A_c * L_i
W_i = rho_b * V_cat,i
```

`catalyst_bulk_density_kg_m3` は、PFR 本体の反応速度計算には使わない。現行の反応速度式は体積基準として扱っているためである。PFR でも radial と同様に、触媒質量はログ表示と比較用指標として扱う。この扱いは未確定事項ではなく、今回の実装方針として固定する。

### 既定条件

PFR の既定入口圧力は、radial と比較しやすくするため、一旦 `200 kPa abs` に揃える。

PFR の段長は、現行値 `1.5, 3.0, 3.0 m` のままでは radial の staged 条件と比較したときに意図が読み取りにくい。したがって、比較用条件として `2.5, 2.5, 2.5 m` に揃える。この値は最終設計値ではなく、PFR と radial の圧損分布を比較するための条件である。

反応器断面積は入口空塔速度から逆算しない。radial 既定ケースの総触媒体積と同じ `99.313 m3` を PFR にも与え、総段長 `7.5 m` で割って断面積を決める。反応器径を独立した設計変数にはしない。ただし、断面積と等価直径はログに明示する。

```text
A_c = V_cat,total / L_total
D_eq = sqrt(4 * A_c / pi)
```

## 変更するモデル

### `ReactorRunConditions`

PFR 用の `ReactorRunConditions` に、圧損計算に必要な条件を追加する。

```python
@dataclass(frozen=True)
class ReactorRunConditions:
    pressure_kpa: float
    stage_inlet_temperatures_c: tuple[float, ...]
    stage_lengths_m: tuple[float, ...]
    total_catalyst_volume_m3: float
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

`pressure_kpa` は既存互換のため名前を維持する。ただし、圧損追加後の意味は「反応器列入口圧力」である。実装上は段内計算の開始時に Pa へ変換する。

将来的に radial と完全に単位系を揃えるなら、`pressure_kpa` を `inlet_pressure_pa` に移行する余地はある。ただし今回の変更では、既存 CLI と既存 JSON 入力への影響を小さくするため、名前変更は行わない。

### `ReactorBalanceContext`

PFR の収支 context に Ergun パラメータを追加する。

```python
@dataclass(frozen=True)
class ReactorBalanceContext:
    cross_section_area_m2: float
    network: ReactionNetwork
    properties: dict[str, SpeciesPhysicalProperty]
    universal: UniversalConstants
    ergun_parameters: ErgunParameters
```

`pressure_kpa` は context から外し、状態変数の `P` を使う。これにより、PFR と radial の分圧評価方針が揃う。

### `pfr_adiabatic_derivatives`

現在は `[F..., T]` を受け取り、`[dF/dz..., dT/dz]` を返している。

変更後は `[F..., T, P]` を受け取り、`[dF/dz..., dT/dz, dP/dz]` を返す。

処理順序は次の通りである。

1. 成分流量、温度、圧力を state vector から読む。
2. 局所圧力から分圧を計算する。
3. 既存の `reaction_rates` を呼ぶ。
4. 既存の物質収支と熱収支を計算する。
5. 局所密度と質量速度を計算する。
6. `ergun_pressure_gradient_pa_per_m` で `dP/dz` を計算する。

### `PfrAdiabaticReactor`

1 基分の PFR を表す `PfrAdiabaticReactor` を新設する。

```python
class PfrAdiabaticReactor:
    def run(
        self,
        inlet: ReactorStream,
        feed: ReactorFeed,
        stage_index: int,
        inlet_temperature_k: float,
        inlet_pressure_pa: float,
        cross_section_area_m2: float,
        stage_length_m: float,
        ergun_parameters: ErgunParameters,
        catalyst_bulk_density_kg_m3: float,
        segments: int,
        profile_points: int,
    ) -> PfrReactorStageResult: ...
```

この class は、1 基分の断熱 PFR だけを担当する。段間再加熱、次段入口温度への調整、複数段のログ集約は行わない。

主な責務は次の通りである。

1. 入口 stream、入口温度、入口圧力を状態変数に変換する。
2. `z = 0` から `z = L` まで RK4 で軸方向に積分する。
3. 各積分点で局所圧力、局所分圧、局所ガス密度、質量速度を計算する。
4. 既存の反応速度式と熱物性計算から `dF/dz`、`dT/dz` を計算する。
5. Ergun 式から `dP/dz` を計算する。
6. 出口 stream、出口温度、出口圧力、圧力損失、線速、Re 判定、1 基分の profile と stage log を返す。

この分離により、PFR 1 基と radial 1 基の profile を同じ粒度で比較できる。

### `StagedAdiabaticPfrModel`

`StagedAdiabaticPfrModel.run()` は、段ごとに次の圧力を引き継ぐ。

1. 第 1 段入口圧力を `conditions.pressure_kpa` から作る。
2. 各段で `PfrAdiabaticReactor.run()` を呼ぶ。
3. 段出口圧力を次段の基準圧力にする。
4. 最終段以外では、次段入口温度まで再加熱負荷を計算し、同時に `interstage_reheater_pressure_drop_pa` を差し引く。
5. 各段の `ReactorStageLog` に、入口圧力、出口圧力、反応器内圧力損失、再加熱器圧力損失、触媒体積、触媒質量、Re 範囲、元素収支誤差を入れる。
6. `ReactorRunLog` に、反応器内圧力損失合計、再加熱器圧力損失合計、全圧力損失、全触媒体積、全触媒質量、最大 `Re/(1-eps)`、元素収支、制約判定を入れる。

## ログ設計

PFR 用に `format_pfr_reactor_report` を追加する。radial の `format_radial_reactor_report` と同じ表構成にするが、幾何項目は PFR に合わせる。

### `run-reactor-case --reactor-model pfr`

標準出力に完全な `[PFR Reactor Summary]` を出す。

```text
[PFR Reactor Summary]

[Feed]
  total        : 3635.58 kmol/h
  EB           : 605.90 kmol/h
  steam        : 3029.50 kmol/h
  Steam/EB     : 5.00 mol/mol

[Overall]
  outlet T     : 527.00 degC
  inlet P      : 200.000 kPa abs
  outlet P     : 120.000 kPa abs
  reactor pressure drop : 40.000 kPa
  reheat pressure drop  : 40.000 kPa
  total pressure drop   : 80.000 kPa
  cross section area: 1.000 m2
  equivalent diameter: 1.128 m
  EB conversion: 45.00 %
  SM selectivity: 92.00 %
  catalyst volume: 50.00 m3
  catalyst mass  : 71,100 kg
  max Re/(1-eps): 320.0
  atom balance:
    C error : 0.000 %
    H error : 0.000 %
  constraints:
    outlet pressure >= 30 kPa : OK
    Re/(1-eps) < 500         : OK
    pressure positive        : OK
    atom balance             : OK

[Stage Summary]
  item                               stage 1        stage 2        stage 3
  inlet T [degC]                      550.00         550.00         550.00
  outlet T [degC]                     510.00         508.00         528.00
  inlet P [kPa abs]                  200.000        165.000        132.000
  outlet P [kPa abs]                 185.000        152.000        120.000
  reactor pressure drop [kPa]         15.000         13.000         12.000
  reheat pressure drop [kPa]          20.000         20.000              -
  stage length [m]                     2.500          2.500          2.500
  cross section area [m2]             13.242         13.242         13.242
  equivalent diameter [m]              4.106          4.106          4.106
  catalyst volume [m3]                33.104         33.104         33.104
  catalyst mass [kg]                 47,074         47,074         47,074
  inlet velocity [m/s]                 1.930          2.100          2.300
  outlet velocity [m/s]                2.050          2.250          2.500
  min Re/(1-eps) [-]                  250.0          270.0          290.0
  max Re/(1-eps) [-]                  280.0          300.0          320.0
  EB conversion [%]                    16.00          35.00          45.00
  SM selectivity [%]                   97.00          94.00          92.00
  reheat duty [MW]                      3.30           3.60              -
  C balance error [%]                 0.0000         0.0000         0.0000
  H balance error [%]                 0.0000         0.0000         0.0000

[Stage Outlet Molar Flows, kmol/h]
  component          inlet    stage 1 out    stage 2 out    stage 3 out
  EB               605.900        509.000        394.000        333.000
  H2O             3029.500       3029.000       3026.000       3021.000
  SM                 0.061         94.000        200.000        252.000
```

### `run-plant-once --reactor-model pfr`

HYSYS に渡す直前に、同じ PFR summary を logging に出す。最後の plant summary は別物として残す。

### `tune-plant-feed` と `run-plant-convergence`

既定では完全な PFR summary を毎 run 出さない。複数回実行では、現在の `format_reactor_calculation_summary` 相当の簡易 summary を使う。

詳細表示フラグを後で追加する場合は、PFR と radial の両方に共通の `--reactor-detail-log` のような引数を検討する。ただし今回の設計では、既定挙動を明確にするだけでよい。

## 影響範囲

変更範囲は、ファイル単位の羅列ではなく、現行 directory 構成に対して次のように整理する。

```text
src/process_sim/
  cli.py                              # 必ず変更
  reactor/
    cases/
      styrene_default.py              # 必ず変更
    core/
      balance.py                      # 必ず変更
      integrator.py                   # 変更なし
      models.py                       # 必ず変更
      pressure_drop.py                # 変更可能性あり
      stream.py                       # 変更なし
      thermodynamics.py               # 変更なし
    types/
      pfr_adiabatic.py                # 新規追加
      staged_adiabatic_pfr.py         # 必ず変更
  plant/
    runner.py                         # 必ず変更
    production_target.py              # 変更なし
    convergence.py                    # 変更なし
    summary.py                        # 必ず変更
tests/
  test_reactor_simulator.py           # 必ず変更
  test_plant_feed_tuning.py           # 変更可能性あり
docs/
  pfr.md                              # 必ず変更
  reports/
    20260520_01_pfr-pressure-drop-log-design.md  # 本設計書
README.md                             # 変更可能性あり
```

### `src/process_sim/cli.py`

必ず変更する。`run-reactor-case --reactor-model pfr` で、旧 PFR ログではなく `format_pfr_reactor_report` を標準出力に出す。JSON 出力の経路は維持する。

### `src/process_sim/reactor/cases/styrene_default.py`

必ず変更する。PFR 既定条件に、総触媒体積、粒子径、空隙率、バルク密度、Ergun 係数、粘度、段間再加熱器圧力損失を追加する。初期値は radial と同じ値を使う。入口圧力は `200 kPa abs` にする。段長は比較用に `2.5, 2.5, 2.5 m` へ揃える。

### `src/process_sim/reactor/core/balance.py`

必ず変更する。`pfr_adiabatic_derivatives` を圧力状態つきへ変更し、局所圧力から分圧を計算する。さらに、局所ガス密度と質量速度から `dP/dz` を返す。

### `src/process_sim/reactor/core/models.py`

必ず変更する。`ReactorRunConditions` に PFR 圧損用の条件を追加する。`ReactorProfilePoint`、`ReactorStageLog`、`ReactorRunLog` は既に radial 用の圧損・触媒量・元素収支フィールドを持つため、PFR でも同じフィールドを埋める。

### `src/process_sim/reactor/core/pressure_drop.py`

変更可能性がある。既存の `ErgunParameters` と `ergun_pressure_gradient_pa_per_m` は PFR にも使えるため、基本的には変更不要である。ただし、`catalyst_bulk_density_kg_m3` は Ergun 式本体では使っていないため、後で責務を整理する可能性がある。今回の実装では不要な整理は避ける。

### `src/process_sim/reactor/types/pfr_adiabatic.py`

新規追加する。1 基分の断熱 PFR を担当する `PfrAdiabaticReactor` と `PfrReactorStageResult` を置く。PFR 1 基と radial 1 基の比較をしやすくするため、段間再加熱を含めない。

### `src/process_sim/reactor/types/staged_adiabatic_pfr.py`

必ず変更する。段内計算を `PfrAdiabaticReactor` に移し、この class は staged PFR の管理に寄せる。段間再加熱器圧力損失、段ごとの圧力引き継ぎ、全体ログの集約を担当する。

### `src/process_sim/plant/runner.py`

必ず変更する。`selected_model == "pfr"` かつ `log_reactor_detail=True` のとき、HYSYS へ渡す直前に `format_pfr_reactor_report` を logging に出す。複数回実行から呼ばれる場合は、既存通り簡易 summary にする。

### `src/process_sim/plant/production_target.py`

変更しない予定である。すでに `run_plant_once(..., log_reactor_detail=False)` を通す構成なら、PFR の詳細ログ抑制は runner 側で処理できる。

### `src/process_sim/plant/convergence.py`

変更しない予定である。`production_target.py` 経由で PFR の詳細ログ抑制が効くため、convergence 側で PFR 固有処理は追加しない。

### `src/process_sim/plant/summary.py`

必ず変更する。`format_pfr_reactor_report` を追加する。radial と PFR で共通化できる横持ち表関数は使い回す。PFR summary では、反応器断面積と等価直径を全体ログと段別ログに出す。`format_reactor_calculation_summary` は複数回実行用の簡易 summary として残す。

### `tests/test_reactor_simulator.py`

必ず変更する。PFR で圧力損失ログが埋まること、PFR summary に `[PFR Reactor Summary]`、`[Stage Summary]`、`[Stage Outlet Molar Flows, kmol/h]`、`atom balance`、`constraints` が含まれること、PFR 出口圧力が入口圧力より低いことを確認する。

### `tests/test_plant_feed_tuning.py`

変更可能性がある。CLI 引数や runner 呼び出しの期待値に PFR 詳細ログ抑制が関係する場合だけ更新する。

### `docs/pfr.md`

必ず変更する。実装後に、圧損あり PFR、1 基 PFR と staged PFR の責務分離、新ログ仕様を反映する。

### `README.md`

変更可能性がある。実行方法やログ仕様の説明が古くなる場合だけ更新する。

## 可視化との関係

可視化機能は今回の変更では実装しない。ただし、後続の可視化に必要な情報を PFR 側の profile に残す。

PFR 1 基と radial 1 基の比較では、次の profile 情報が必要になる。

- 位置座標
  - PFR は `axial_position_m`
  - radial は `radial_position_m` または `bed_fraction`
- 圧力 `pressure_kpa`
- 温度 `temperature_c`
- 空塔速度 `superficial_velocity_m_per_s`
- `Re/(1-eps)`
- EB 転化率
- SM 選択率
- 各成分流量

staged PFR と staged radial の比較では、段ごとの入口・出口圧力、段内圧損、段間再加熱器圧損を同じ構造で取り出せる必要がある。今回の変更では、そのために PFR 側も `ReactorProfilePoint`、`ReactorStageLog`、`ReactorRunLog` を radial と同じ粒度で埋める。

## 採用しない案

### PFR の圧力損失を固定値にする案

採用しない。radial と同じ Ergun 式で比較したいという目的に対して、PFR だけ固定圧損にすると比較条件が不揃いになる。

### PFR を旧ログのまま残す案

採用しない。PFR を比較用に残すなら、radial と同じ粒度のログが必要である。旧ログは読みづらく、圧損追加後の確認にも不足する。

### `pressure_kpa` をすぐ `inlet_pressure_pa` に改名する案

今回は採用しない。単位名としては `inlet_pressure_pa` の方が明確だが、既存の JSON 入力、テスト、PFR ケースへの影響が大きい。今回の目的は PFR への圧損追加とログ改善であるため、名前変更は後続の整理対象に留める。

## 検証方針

最低限、次を確認する。

- `uv run run-reactor-case --reactor-model pfr` が `[PFR Reactor Summary]` を出す。
- PFR の既定入口圧力が `200 kPa abs` でログに出る。
- PFR の出口圧力が入口圧力より低い。
- 3 段 PFR では `reheat pressure drop` 合計が `40 kPa` になる。
- 2 段 PFR では `reheat pressure drop` 合計が `20 kPa` になる。
- C と H の元素収支誤差が十分小さい。
- `Re/(1-eps)` の最大値がログに出る。
- 反応器断面積と等価直径がログに出る。
- `run-plant-once --reactor-model pfr` では HYSYS に渡す前に詳細 PFR summary が出る。
- `tune-plant-feed --reactor-model pfr` と `run-plant-convergence --reactor-model pfr` では、既定では完全な PFR summary を毎 run 出さない。
- `ruff`、`pyright`、`pytest` を通す。

## 未確定事項

- PFR の段長は比較用に `2.5, 2.5, 2.5 m` とする。最終的な設計条件として適切かは、PFR と radial の圧損分布比較後に確認する。
- PFR の断面積は総触媒体積と総段長から決める。反応器径を独立した設計変数にはしないが、断面積と等価直径はログに明示する。
