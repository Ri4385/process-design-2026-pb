# ラジアルフロー反応器詳細設計

## 目的

本資料は、エチルベンゼン脱水素によるスチレン製造プロセスに対して、ラジアルフロー固定床反応器を導入するための詳細設計を整理するものである。

対象範囲は、`docs/overview.md` の反応工程、特に 4.4 反応器の選定と 4.5 ラジアルフロー反応器の設計である。Leite et al. 2021 は、ラジアルフロー反応器を採用する工業的理由、幾何モデル、触媒量と半径の関係、圧力損失の扱いを参考にする。ただし、反応速度式は Leite et al. の不均一系速度式へ置き換えず、現行 repository に実装済みのコンテスト由来 6 反応モデルを維持する。

## 結論

本設計では、内側流入・外側流出の多段断熱ラジアルフロー固定床反応器を採用する。

採用理由は次の通りである。

- EB 脱水素の主反応は `EB ⇄ SM + H2` であり、反応進行により気相モル数が増加する。
- 体積流量が増加する系では、環状触媒層の内側から外側へ流すことで、流れ方向に対して有効断面積が増加し、線速と圧力損失の増大を抑えやすい。
- EB 脱水素は平衡上、低圧が有利であるため、軸方向固定床より圧力損失を小さくしやすいラジアルフロー反応器が適している。
- 既存の 6 反応モデル、熱物性計算、段間再加熱の考え方を活かしたまま、幾何と圧力損失を追加できる。

## 参照した情報

### 現行 repository

現行の反応器実装は、多段断熱 PFR である。

- `src/process_sim/reactor/types/staged_adiabatic_pfr.py`
  - `StagedAdiabaticPfrModel` を置く。
  - 各段を軸方向 1 次元 PFR として RK4 で積分する。
- `src/process_sim/reactor/core/balance.py`
  - 物質収支と断熱熱収支を計算する。
  - 現在の形は概ね $\frac{dF_j}{dz} = A_c \sum_i \nu_{ij} r_i$、$\frac{dT}{dz} = -\frac{A_c \sum_i r_i \Delta H_i}{\sum_j F_j C_{p,j}}$ である。
- `src/process_sim/constants/reaction_networks.py`
  - コンテスト由来の 6 反応ネットワークを定義する。
- `src/process_sim/reactor/core/kinetics.py`
  - 分圧と Arrhenius 式から反応速度を計算する。
- `src/process_sim/reactor/core/thermodynamics.py`
  - 成分エンタルピー、反応エンタルピー、Cp を計算する。
- `src/process_sim/reactor/cases/styrene_default.py`
  - 既定 feed と既定反応器条件を置く。

現行実装では圧力は `pressure_kpa` として固定されており、反応器内の圧力損失は計算していない。断面積は入口体積流量と入口空塔速度から逆算している。

### Leite et al. 2021 から採用する内容

Leite et al. 2021 から採用する内容は、ラジアルフロー反応器の構造と運動量収支に限定する。

- ラジアルフロー反応器は EB 脱水素の商用断熱反応器として一般的である。
- 主反応で気相モル数が増加するため、環状触媒層の内側から外側へ向かう外向き流れが使われる。
- 軸方向固定床に比べて圧力損失を小さくでき、低圧が有利な EB 脱水素に適する。
- 触媒床内半径、高さ、触媒量または触媒層厚みによって、触媒床外半径を決める。
- 圧力損失は Ergun 式で評価する。
- Ergun 式係数は、$\mathrm{Re}/(1 - \varepsilon_b) < 500$ の範囲では $a = 1.75$、$b = 150$ を使う。

### Leite et al. 2021 から採用しない内容

Leite et al. 2021 の反応モデルは、現行 repository の 6 反応モデルと一致しないため、本設計では採用しない。

Leite et al. 2021 では、Lee & Froment 系の不均一触媒反応と thermal reaction を分け、反応速度の単位も触媒質量基準と反応器体積基準が混在する。本 repository では、すでにコンテスト資料由来の 6 反応を体積基準速度として実装している。ここで Leite et al. の速度式に置き換えると、反応ネットワーク、単位系、有効係数、粒子内拡散、妥当性確認基準が大きく変わる。

したがって、本段階では反応速度式を維持し、ラジアルフロー固有の幾何、圧損、制約条件を追加する。

## 反応器選定

### 候補

候補は、軸方向固定床反応器とラジアルフロー固定床反応器である。

| 項目 | 軸方向固定床 | ラジアルフロー固定床 |
|---|---|---|
| 流れ方向 | 反応器高さ方向 | 半径方向 |
| 流通断面積 | 原則一定 | 半径とともに増加 |
| 圧力損失 | 大きくなりやすい | 小さくしやすい |
| EB 脱水素への適性 | 比較用モデルとして扱いやすい | 低圧運転に適する |
| 実装上の位置づけ | 現行実装済み | 追加実装対象 |

### 採用判断

最終設計の主反応器としては、ラジアルフロー固定床反応器を採用する。

ただし、現行 PFR 実装は削除しない。軸方向 PFR は、ラジアルフロー導入前の基準ケース、反応速度式の検証、概算感度解析に使えるためである。新規実装は `StagedAdiabaticPfrModel` と並列の反応器型として追加する。

## 触媒設計方針

触媒は、商用 EB 脱水素で一般的な酸化鉄系触媒を想定する。

Leite et al. 2021 の基準値には粒子径 $0.055\ \mathrm{m}$ が含まれるが、これは本設計で採用する商用触媒粒子径としては大きすぎる可能性がある。`docs/overview.md` では BASF S6-62 を参考に粒子径 $3\ \mathrm{mm}$ を採用する方針が書かれているため、本設計の初期値は $d_p = 0.003\ \mathrm{m}$ とする。

粒子径は Ergun 式の圧力損失に強く影響する。したがって、$d_p = 0.003\ \mathrm{m}$ は最終確定値ではなく、感度解析の対象として扱う。

## ラジアルフロー反応器モデル

### 幾何

各段を環状触媒層として扱う。

| 記号 | 意味 |
|---|---|
| $r_0$ | 触媒床内半径 |
| $\delta_i$ | 第 i 段の触媒層厚み |
| $r_{\mathrm{out},i}$ | 第 i 段の触媒床外半径 |
| $z$ | 触媒床高さ |
| $r$ | 半径方向位置 |
| $A_r(r)$ | ラジアル流れに垂直な流通断面積 |

外半径は次式で与える。

$$
r_{\mathrm{out},i} = r_0 + \delta_i
$$

ラジアル流れに垂直な流通断面積は、円筒面積として定義する。

$$
A_r(r) = 2 \pi r z
$$

微小触媒体積は次式で表す。

$$
dV = A_r(r)\,dr
$$

第 i 段の触媒体積と触媒質量は次式で計算する。

$$
V_{\mathrm{cat},i} = \pi z\{(r_0 + \delta_i)^2 - r_0^2\}
$$

$$
W_i = \rho_b V_{\mathrm{cat},i}
$$

ここで、$\rho_b$ は触媒床バルク密度である。

この定義は、Leite et al. 2021 の触媒量と半径の関係 $W = \pi z \rho_b(r^2 - r_0^2)$ と整合する。一方で、Ergun 式に入れる断面積は、ラジアル流れの物理的な流通面積である $A_r(r) = 2 \pi r z$ を使う。

### 積分方向

積分方向は、半径方向位置 $r$ または触媒層厚み方向 $x = r - r_0$ とする。

実装上は $x$ を使う方が各段の積分区間を $0 \le x \le \delta_i$ と書けるため扱いやすい。ただし、断面積と触媒体積の計算では $r = r_0 + x$ を使う。

## 設計方程式

### 物質収支

反応速度 $r_i$ は、現行実装と同じく触媒層体積基準の $\mathrm{kmol/(m^3\,s)}$ として扱う。

第 j 成分の物質収支は次式とする。

$$
\frac{dF_j}{dr} = A_r(r)\sum_i \nu_{ij}r_i
$$

ここで、$F_j$ は第 j 成分のモル流量、$\nu_{ij}$ は第 i 反応における第 j 成分の化学量論係数である。

### エネルギー収支

各段は断熱とする。熱損失は考慮しない。

$$
\frac{dT}{dr} =
-\frac{A_r(r)\sum_i r_i \Delta H_i}{\sum_j F_j C_{p,j}}
$$

段間再加熱は現行 PFR と同様に反応器外部で行うものとし、各段入口温度を入力条件として与える。再加熱器の詳細構造は、この反応器モデルには含めない。

### 運動量収支

圧力は状態変数として積分する。各点の局所圧力から各成分の分圧を計算し、反応速度評価へ渡す。

Ergun 式は、Leite et al. 2021 の触媒質量基準式を、半径方向積分に変換して使う。

$$
\frac{dP}{dW}
= -10^{-5}
\frac{1}{A_r \rho_b}
\frac{G}{\rho_g d_p}
\frac{1 - \varepsilon_b}{\varepsilon_b^3}
\left[
b\frac{(1 - \varepsilon_b)\mu}{d_p}
+ aG
\right]
$$

ここで、$P$ は bar、$W$ は kg-cat、$G$ は空塔質量速度、$\rho_g$ はガス密度、$d_p$ は粒子径、$\mu$ は混合ガス粘度、$\varepsilon_b$ は触媒床空隙率である。

半径方向で積分するため、次式で変換する。

$$
\frac{dW}{dr} = \rho_b A_r(r)
$$

$$
\frac{dP}{dr} = \frac{dP}{dW}\frac{dW}{dr}
$$

圧力の内部単位は、既存コードとの整合を優先して kPa とする。ただし、Leite et al. の式を使う部分では bar へ変換し、計算後に kPa へ戻す。

## 固定条件

本設計で使う固定条件は次の通りである。

| 項目 | 記号 | 初期値 | 根拠と扱い |
|---|---:|---:|---|
| 触媒床内半径 | $r_0$ | $1.0\ \mathrm{m}$ | `docs/overview.md` の案。Leite et al. の $1.5\ \mathrm{m}$ をそのまま採用した値ではなく、本設計の固定値とする。 |
| 触媒床高さ | $z$ | $5.0\ \mathrm{m}$ | `docs/overview.md` の案。Leite et al. の $7\ \mathrm{m}$ をそのまま採用した値ではなく、本設計の固定値とする。 |
| 触媒粒子径 | $d_p$ | $0.003\ \mathrm{m}$ | BASF S6-62 参考として採用する。圧力損失への影響が大きいため、時間があれば感度解析する。 |
| 触媒床空隙率 | $\varepsilon_b$ | $0.4312$ | Leite et al. 2021 参考。 |
| 触媒床バルク密度 | $\rho_b$ | $1422\ \mathrm{kg/m^3}$ | Leite et al. 2021 参考。 |
| Ergun 係数 | $a, b$ | $1.75, 150$ | $\mathrm{Re}/(1 - \varepsilon_b) < 500$ の範囲で使う係数。 |
| 混合ガス粘度 | $\mu$ | 固定値 | Steam 大過剰であることを踏まえ、初期設計では固定値として扱う。 |
| 熱損失 | - | なし | 断熱段として扱う。 |
| 段間物質注入 | - | なし | 段間では間接加熱による再加熱のみを行う。 |
| 再加熱方式 | - | 間接加熱 | 本設計では間接加熱を扱う。直接加熱は時間がある場合の比較対象に留める。 |

## 設計変数

初期探索の設計変数は次の通りである。

| 項目 | 記号 | 範囲 | 備考 |
|---|---:|---:|---|
| 反応器段数 | $N$ | $2$ または $3$ | 商用・課題文脈で現実的な範囲として扱う。 |
| 各段入口温度 | $T_{\mathrm{in},i}$ | $590–650\ ^\circ\mathrm{C}$ | コンテスト資料と現行最適化メモに合わせる。段ごとに独立変数とする。 |
| 反応器列入口圧力 | $P_{\mathrm{in}}$ | $30–150\ \mathrm{kPa\ abs}$ | Leite et al. の低圧運転傾向を参考にしつつ、初期探索範囲として置く。 |
| Steam/EB 比 | $S/EB$ | $5–8$ | 5 未満は炭素析出リスクから外す。Leite et al. の $11$ は本設計ではエネルギー消費が大きい候補として扱う。 |
| 各段触媒層厚み | $\delta_i$ | $0.3–1.2\ \mathrm{m}$ | Leite et al. の触媒量最適化に対応する変数として、厚みを直接探索する。 |

Leite et al. 2021 では各段触媒量 $W_i$ を最適化変数としている。一方、本設計では実機寸法として理解しやすい $\delta_i$ を設計変数にする。触媒量は $W_i = \rho_b \pi z\{(r_0 + \delta_i)^2 - r_0^2\}$ により従属変数として計算する。

## 制約条件

初期実装で判定する制約条件は次の通りである。

| 項目 | 制約 |
|---|---:|
| 反応器列出口圧力 | $P_{\mathrm{out}} \ge 50\ \mathrm{kPa\ abs}$ |
| 圧力正値 | 全積分点で $P > 0$ |
| Ergun 係数の適用範囲 | 全積分点で $\mathrm{Re}/(1 - \varepsilon_b) < 500$ |
| 入口温度 | $T_{\mathrm{in},i} \le 650\ ^\circ\mathrm{C}$ |
| 計算結果 | EB 転化率、SM 選択率、温度、圧力が有限値であること |
| 流れ方向 | 各段で内側流入・外側流出であること |

$\mathrm{Re}/(1 - \varepsilon_b) \ge 500$ となった場合は、計算自体は中断せず、制約違反としてログに残す扱いがよい。これは、境界付近のケースを比較対象から外す判断を後段の最適化側で行うためである。

## 実装方針

### 追加するディレクトリ構成

現行構成を壊さず、次のように追加する。

```text
src/process_sim/reactor/
  core/
    radial_geometry.py          # ラジアル流れの幾何計算
    pressure_drop.py            # Ergun式とRe判定
  types/
    staged_adiabatic_radial.py  # 多段断熱ラジアルフロー反応器
  cases/
    styrene_radial_default.py   # ラジアルフロー用の既定ケース
src/process_sim/optimization/
  reactor/
    parameters.py               # ラジアル用探索範囲を追加
    constraints.py              # ラジアル用制約を追加
docs/
  reactor.md                    # 実装後に恒久メモを更新
```

この構成は実装予定であり、現時点で全て存在するわけではない。

### ファイル責務

`src/process_sim/reactor/core/radial_geometry.py`

- `RadialBedGeometry` を定義する。
- 内半径、高さ、層厚みから外半径、流通断面積、触媒体積、触媒質量を計算する。
- 反応計算や速度式には依存しない。

`src/process_sim/reactor/core/pressure_drop.py`

- `ErgunParameters` を定義する。
- 空塔質量速度、混合ガス密度、混合ガス粘度、粒子径から $dP/dr$ を計算する。
- $\mathrm{Re}/(1 - \varepsilon_b)$ を計算する。
- 圧力損失計算に必要な単位変換をこの module 内に閉じる。

`src/process_sim/reactor/types/staged_adiabatic_radial.py`

- `StagedAdiabaticRadialFlowModel` を定義する。
- 既存の `StagedAdiabaticPfrModel` と同じ反応ネットワーク、熱物性、ストリームモデルを使う。
- 状態変数に圧力を含め、各段を半径方向に積分する。
- 段間再加熱負荷、圧力損失、線速、Re 判定、触媒量をログに残す。

`src/process_sim/reactor/cases/styrene_radial_default.py`

- ラジアルフロー反応器用の既定 feed と条件を置く。
- 既存の `styrene_default.py` を直接書き換えない。

`src/process_sim/optimization/reactor/parameters.py`

- 既存 PFR 用探索範囲を壊さず、ラジアルフロー用の探索範囲を追加する。
- `bed_thicknesses_m`、`bed_inner_radius_m`、`bed_height_m` を扱えるようにする。

`src/process_sim/optimization/reactor/constraints.py`

- $P_{\mathrm{out}} \ge 50\ \mathrm{kPa\ abs}$、$\mathrm{Re}/(1 - \varepsilon_b) < 500$、圧力正値などの制約値を追加する。

`docs/reactor.md`

- 実装後に、現行実装範囲としてラジアルフロー反応器を追記する。
- 未実装の予定と実装済み機能を混同しないように分けて記録する。

## クラス設計

### `RadialBedGeometry`

```python
@dataclass(frozen=True)
class RadialBedGeometry:
    inner_radius_m: float
    bed_height_m: float
    bed_thickness_m: float
    catalyst_bulk_density_kg_m3: float

    @property
    def outer_radius_m(self) -> float: ...

    def radius_at(self, bed_fraction: float) -> float: ...

    def flow_area_m2(self, radius_m: float) -> float: ...

    @property
    def catalyst_volume_m3(self) -> float: ...

    @property
    def catalyst_mass_kg(self) -> float: ...
```

このクラスは純粋な幾何計算だけを担当する。反応、温度、圧力には依存させない。

### `ErgunParameters`

```python
@dataclass(frozen=True)
class ErgunParameters:
    pellet_diameter_m: float
    bed_void_fraction: float
    catalyst_bulk_density_kg_m3: float
    ergun_a: float = 1.75
    ergun_b: float = 150.0
    gas_viscosity_pa_s: float = 3.0e-5
```

混合ガス粘度は、Steam 大過剰であることを踏まえ、初期実装では固定値として扱う。Leite et al. 2021 では、純成分粘度を推算した上で混合粘度を扱っている。本設計ではその方針を背景として残すが、初期実装では粘度推算を作り込まない。

Leite et al. 2021 で使われた純成分粘度の推算法は次の通りである。

| 成分 | 純成分粘度の推算法 |
|---|---|
| EB, ST, CH4, BZ, TO, C2H4 | Thodos の対応状態法 |
| H2, H2O | Chapman-Enskog 式 |
| H2O | Chapman-Enskog 式に Stockmayer 補正 |

### `RadialReactorRunConditions`

```python
@dataclass(frozen=True)
class RadialReactorRunConditions:
    inlet_pressure_kpa: float
    stage_inlet_temperatures_c: tuple[float, ...]
    bed_inner_radius_m: float
    bed_height_m: float
    bed_thicknesses_m: tuple[float, ...]
    pellet_diameter_m: float
    bed_void_fraction: float
    catalyst_bulk_density_kg_m3: float
    ergun_a: float
    ergun_b: float
    gas_viscosity_pa_s: float
    segments_per_stage: int
    profile_points_per_stage: int
```

既存の `ReactorRunConditions` は PFR 用として残す。ラジアルフローでは圧力を状態変数として扱うため、`pressure_kpa` ではなく `inlet_pressure_kpa` を使う。

### `StagedAdiabaticRadialFlowModel`

```python
class StagedAdiabaticRadialFlowModel:
    def run(
        self,
        feed: ReactorFeed,
        conditions: RadialReactorRunConditions,
    ) -> RadialReactorResult: ...
```

主な処理は次の通りである。

1. 入力条件の段数、温度数、触媒層厚み数が一致することを確認する。
2. 第 1 段入口 stream、入口温度、入口圧力を初期状態にする。
3. 各段について、$x = 0$ から $x = \delta_i$ まで RK4 で積分する。
4. 各積分点で $r = r_0 + x$、$A_r(r)$、局所圧力、局所分圧を計算する。
5. 既存の反応速度式と熱物性計算から $dF/dr$、$dT/dr$ を計算する。
6. Ergun 式から $dP/dr$ を計算する。
7. 段出口状態、圧力損失、温度低下、転化率、選択率、線速、Re 判定をログ化する。
8. 最終段以外では、間接加熱により次段入口温度まで再加熱したとみなし、再加熱負荷を計算する。

## 出力ログ設計

ラジアルフロー反応器では、既存 PFR ログに加えて圧力・幾何・Re 判定を出す。

### 全体ログ

- 反応器列入口圧力
- 反応器列出口圧力
- 全圧力損失
- EB 転化率
- SM 選択率
- 全触媒体積
- 全触媒質量
- 最大 $\mathrm{Re}/(1 - \varepsilon_b)$
- 出口圧力制約の合否
- Ergun 適用範囲制約の合否

### 各段ログ

- 段番号
- 入口温度、出口温度
- 入口圧力、出口圧力
- 圧力損失
- 触媒床内半径
- 触媒床外半径
- 触媒床高さ
- 触媒層厚み
- 触媒体積
- 触媒質量
- 入口線速、出口線速
- 最小および最大 $\mathrm{Re}/(1 - \varepsilon_b)$
- EB 転化率
- SM 選択率
- 段間再加熱負荷

### profile

- `stage_index`
- `radial_position_m`
- `bed_fraction`
- `temperature_c`
- `pressure_kpa`
- `eb_conversion`
- `styrene_selectivity`
- 各成分流量
- `superficial_velocity_m_per_s`
- `re_over_one_minus_void`

## 最適化との接続

ラジアルフロー実装後の探索変数は、PFR 用の `stage_lengths_m` ではなく、`bed_thicknesses_m` を中心にする。

初期探索範囲は次を基本とする。

| パラメータ | 初期範囲 |
|---|---:|
| 段数 | $2$ または $3$ |
| 各段入口温度 | $590–650\ ^\circ\mathrm{C}$ |
| 入口圧力 | $30–150\ \mathrm{kPa\ abs}$ |
| Steam/EB 比 | $5–8$ |
| 各段触媒層厚み | $0.3–1.2\ \mathrm{m}$ |
| 触媒床内半径 | 固定 $1.0\ \mathrm{m}$ |
| 触媒床高さ | 固定 $5.0\ \mathrm{m}$ |

Leite et al. 2021 では、最適化結果として後段ほど入口温度が高くなる傾向が示されている。そのため、本設計でも各段入口温度は独立変数として扱い、全段同一温度に固定しない。

## 既存 PFR 実装との差分

| 項目 | 現行 PFR | ラジアルフロー |
|---|---|---|
| 積分方向 | 軸方向 $z$ | 半径方向 $r$ または $x = r - r_0$ |
| 流通断面積 | 一定 | $A_r(r) = 2\pi rz$ |
| 圧力 | 固定 | 状態変数として積分 |
| 分圧 | 固定圧力から計算 | 局所圧力から計算 |
| 反応速度式 | 6 反応モデル | 同じ 6 反応モデル |
| 幾何 | 断面積と段長 | 内半径、高さ、層厚み、外半径 |
| 触媒量 | 明示しない | 幾何とバルク密度から計算 |
| 圧損 | なし | Ergun 式 |
| 制約 | 探索範囲中心 | 出口圧力、圧力正値、Re 範囲 |
| ログ | 温度、流量、転化率、選択率 | PFR ログに圧力、圧損、線速、Re、触媒量を追加 |

## 意思決定の理由

### 6 反応モデルを維持する理由

本 repository は、コンテスト資料由来の 6 反応モデルを前提に、反応器、分離器、プラント接続を進めている。Leite et al. の反応モデルへ置き換えると、反応数、反応種、速度式の単位、触媒有効係数の扱いが変わり、既存の分離系や最適化メモとの整合が崩れる。

したがって、本作業では反応モデルを変えず、反応器型だけを追加する。

### 触媒層厚みを設計変数にする理由

Leite et al. では触媒量を設計変数としている。一方、本設計では実機形状として説明しやすく、ラジアル流れの断面積変化を直接扱えるため、触媒層厚みを設計変数とする。

触媒量は厚みから一意に計算できるため、最適化上の自由度は失われない。

### $A_r(r) = 2\pi rz$ を使う理由

ラジアル流れでは、流れに垂直な面は半径 $r$ の円筒面である。そのため、圧力損失と空塔速度に使う断面積は $2\pi rz$ とするのが物理的に自然である。

Leite et al. の触媒量と半径の関係は $W = \pi z \rho_b(r^2 - r_0^2)$ として採用するが、Ergun 式の流通断面積はラジアル流れに対応した円筒面積を使う。

### 粘度を固定値で扱う理由

混合ガス粘度 $\mu$ は Ergun 式の粘性抵抗項に必要である。圧力損失式では、$b(1-\varepsilon_b)\mu/d_p$ の項として現れる。

本プロセスでは Steam/EB 比が大きく、反応器内の気相は Steam 大過剰である。そのため、初期設計では混合ガス粘度を固定値として扱う。Leite et al. 2021 のように純成分粘度を推算して混合粘度を計算する方法は、時間がある場合の精密化として位置づける。

### 間接加熱を扱う理由

本設計では、段間再加熱を間接加熱として扱う。直接加熱では高温 Steam の投入により Steam/EB 比や段間流量が変化し、反応器モデルと下流分離条件の両方に影響する。現段階では反応器幾何、圧力損失、段間再加熱負荷を整理することを優先し、段間物質注入を伴わない間接加熱を採用する。

直接加熱は、時間がある場合に比較対象として扱う。

## 未確定要素

- 混合ガス粘度 $\mu$ は Steam 大過剰を踏まえて固定値とする。固定値そのものの採用値は、実装時に文献値または代表温度の推算値から決める必要がある。
- $P_{\mathrm{out}} \ge 50\ \mathrm{kPa\ abs}$ は Leite et al. の最適化制約を参考にした初期制約であり、下流のデカンター、冷却、HYSYS 分離系との整合確認が必要である。
- 反応器を単一基で設計するか、並列基数を導入するかは保留する。必要触媒体積と許容径・高さの関係を見て判断する。
