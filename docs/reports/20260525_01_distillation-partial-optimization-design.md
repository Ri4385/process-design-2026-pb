# 蒸留塔部分最適化仕様

## 目的

3 本の蒸留塔について、段数を変えた HYSYS ファイルを複数用意し、塔ごとに装置コスト、用役コスト、評価関数を比較する。

段数は HYSYS COM から変更しない。段数は HYSYS ファイル側で固定し、Python は対象ディレクトリ内の `.hsc` をすべて順番に開いて評価する。

一方で、feed 段は Python から変更して sweep する。1 つの HYSYS ファイルを開いたら、その case を閉じずに feed 段を順に変更し、各 feed 段で solve して評価する。その HYSYS ファイルの代表コストは、feed 段 sweep の中で最も評価関数が小さい条件のコストとする。

## 対象

```text
tower1: SM 分離塔
tower2: EB 分離塔
tower3: BZ/TL 分離塔
```

HYSYS operation 名の初期値は次とする。

```python
TOWER_OPERATION_NAMES: dict[TargetTower, str] = {
    "tower1": "T-1",
    "tower2": "T-2",
    "tower3": "T-3",
}
```

## ディレクトリ構成

```text
scripts/distillation/
  distillation_stage_sweep.py
  hysys/
    tower1/
      coarse/
      fine/
    tower2/
      coarse/
      fine/
    tower3/
      coarse/
      fine/
  media/
```

実行ファイルは `scripts/distillation/distillation_stage_sweep.py` の 1 つだけである。

`coarse` は荒めの段数候補、`fine` は細かめの段数候補を置くディレクトリである。実行時は、選択した `tower/grid` ディレクトリにある `.hsc` をすべて対象にする。case 一覧は定数で個別定義しない。

## 実行条件の指定

実行対象は script 冒頭の定数で指定する。CLI は作らない。

```python
from typing import Literal

TargetTower = Literal["tower1", "tower2", "tower3"]
GridLevel = Literal["coarse", "fine"]

TARGET_TOWER: TargetTower = "tower1"
GRID_LEVEL: GridLevel = "coarse"
DETAILED_FEED_LOG = True
```

対象 case は次で取得する。

```python
case_dir = HYSYS_DIR / TARGET_TOWER / GRID_LEVEL
case_paths = tuple(sorted(case_dir.glob("*.hsc")))
```

段数は HYSYS から読む。対象塔の `ColumnFlowsheet.ColumnStages` を優先し、読めない場合だけファイル名からの推定を検討する。

## 編集範囲

実装時の編集範囲は次とする。

```text
scripts/distillation/distillation_stage_sweep.py
src/process_sim/separator/hysys_io.py
src/process_sim/plant/economics.py
docs/cost.md
```

責務は次の通りである。

- `scripts/distillation/distillation_stage_sweep.py`
  - 対象ディレクトリ内の `.hsc` をすべて実行する。
  - 各 `.hsc` を開いたまま feed 段を sweep する。
  - HYSYS から必要値を読む。
  - 装置コスト、用役コスト、評価関数を計算する。
  - 塔ごとに 1 枚の図を保存する。
- `src/process_sim/separator/hysys_io.py`
  - 必要なら `distillation` operation、`ColumnFlowsheet`、energy stream、cooler operation の読み取り関数を追加する。
  - HYSYS COM オブジェクトをアプリケーション境界の外に直接出さない。
- `src/process_sim/plant/economics.py`
  - 必要なら蒸留塔、コンデンサー、リボイラー、冷却、加熱の共通コスト関数を追加する。
- `docs/cost.md`
  - HYSYS ファイルに依存しない塔径、高さ、L/D 比の式を記録する。

テストは作らない。

## HYSYS から読む値

対象塔の `ColumnFlowsheet` から次を読む。

```text
ColumnStages
FeedColumnStages
NetMassVapourFlowsValue
NetMassLiquidFlowsValue
NetMolarVapourFlowsValue
TemperaturesValue
PressuresValue
NetLiqVolLiquidFlowsValue
```

既存の診断結果では、T-1、T-2、T-3 のすべてで上記 key は存在している。

単位は次を前提にする。

```text
NetMassVapourFlowsValue: kg/s
NetMassLiquidFlowsValue: kg/s
NetMolarVapourFlowsValue: kmol/s
TemperaturesValue: degC
PressuresValue: kPa
NetLiqVolLiquidFlowsValue: m3/s
```

## feed 段 sweep

段数は HYSYS ファイルごとに固定だが、feed 段は Python から変更する。

対象塔の `ColumnFlowsheet.FeedColumnStages` は現在段の読み取りに使う。調査結果では `FeedColumnStages` item の `StageNumberValue` は読めるが書き込み不可だったため、feed 段の変更には対象 `traysection` の `SpecifyFeedLocation(feed_object, stage)` を使う。

初期実装では、塔ごとに feed が 1 本である前提で、最初の feed stage を sweep 対象にする。

feed 段候補は、`ColumnStages` から次の範囲を作る。HYSYS が受け付ける feed 段はすべて試す。

$$
1 \leq f \leq N
$$

特定の feed 段が HYSYS 側で受け付けられない場合は、その feed 段だけ invalid として扱い、同じ case の次の feed 段に進む。

実行順序は次とする。

1. HYSYS ファイルを開く。
2. 対象塔の段数 $N$ を読む。
3. feed 段候補を作る。
4. 同じ HYSYS case を開いたまま、feed 段を 1 つずつ設定する。
5. 各 feed 段で solve する。
6. コスト、制約、L/D を評価する。
7. その HYSYS ファイル内で最小の $J$ を与える feed 段を選ぶ。
8. case を保存せず閉じる。

段数 $N$ に対する代表値は、最良 feed 段の値を使う。

$$
J_N = \min_f J_{N,f}
$$

$$
f_N^{*} = \operatorname*{arg\,min}_f J_{N,f}
$$

ログには、通常は各 HYSYS ファイルについて最良 feed 段を出す。`DETAILED_FEED_LOG = True` の場合は、feed 段ごとに、段数、feed 段、塔径、高さ、L/D、塔頂温度、塔底温度、condenser duty、reboiler duty、装置コスト、用役コスト、評価関数、invalid 理由を出す。

## 塔径計算

各段の蒸気質量流量が最大になる段を設計基準段とする。

$$
MN = \operatorname*{arg\,max}_j V_{\mathrm{mass},j}
$$

$$
V_{\mathrm{mass}} = \mathrm{NetMassVapourFlowsValue}_{MN}
$$

最大蒸気負荷段で次を読む。

$$
L_{\mathrm{mass}} = \mathrm{NetMassLiquidFlowsValue}_{MN}
$$

$$
n_v = \mathrm{NetMolarVapourFlowsValue}_{MN}
$$

$$
T = \mathrm{TemperaturesValue}_{MN}
$$

$$
P = \mathrm{PressuresValue}_{MN}
$$

$$
Q_l = \mathrm{NetLiqVolLiquidFlowsValue}_{MN}
$$

蒸気体積流量は理想気体式で計算する。

$$
Q_v =
\frac{
n_v \times 8.314 \times 1000 \times (273.15 + T)
}{
P \times 1000
}
$$

密度は次で計算する。

$$
\rho_v = \frac{V_{\mathrm{mass}}}{Q_v}
$$

$$
\rho_l = \frac{L_{\mathrm{mass}}}{Q_l}
$$

許容質量速度は次で計算する。

$$
G^{*} = SF \cdot K \cdot \sqrt{\rho_v(\rho_l - \rho_v)}
$$

$$
SF = 0.8
$$

$$
K = 0.05\ \mathrm{m/s}
$$

塔径は次を満たす最小値とする。

$$
D = \sqrt{\frac{4 V_{\mathrm{mass}}}{\pi G^{*}}}
$$

この式は添付資料と明石さん方式を踏襲する。単位換算の再整理はこの実装では行わない。

## 塔高さ計算

高さは次で計算する。

$$
H = 0.6(N - 1) + 2 + 4 + 1
$$

ここで、$N$ は `ColumnStages` から読んだ段数である。

内訳は次の通りである。

```text
段間隔: 0.6 m
塔頂間隔: 2 m
塔底部間隔: 4 m
原料供給段間隔: 1 m
```

## L/D 比

L/D 比は警告扱いにする。評価関数には入れない。

ログには、すべての case で L/D を出す。

基準は次を優先する。

$$
\frac{H}{D} \leq 15
$$

`H/D > 15` の case は invalid にはしない。ログ上で `ld_warning` として表示する。

## 装置コスト

蒸留塔装置コストは、塔胴体、コンデンサー、リボイラーを含める。

塔胴体コストは `docs/cost.md` の式を使う。

$$
C_{\mathrm{shell}}
=
1{,}500{,}000
D^{1.066}
H^{0.82}
$$

コンデンサーとリボイラーの装置費は、明石さん方式に合わせて HYSYS から duty と塔頂・塔底温度を読み、熱交換器式で計算する。

$$
C_{\mathrm{hx}}
=
1{,}500{,}000
A^{0.65}
K_{\mathrm{hx}}
$$

$$
K_{\mathrm{hx}} =
\begin{cases}
1 & \text{condenser} \\
2 & \text{reboiler}
\end{cases}
$$

初期実装では、対象塔の condenser/reboiler duty を HYSYS の energy stream から読む。

```python
TOWER_COLUMN_ENERGY_STREAMS: dict[TargetTower, dict[str, str]] = {
    "tower1": {"condenser": "TQ-11", "reboiler": "TQ-12"},
    "tower2": {"condenser": "TQ-21", "reboiler": "TQ-22"},
    "tower3": {"condenser": "TQ-31", "reboiler": "TQ-32"},
}
```

HYSYS から読む値は次である。

```text
Q_cond = ColumnFlowsheet.EnergyStreams.Item(0).HeatFlowValue
Q_reb = ColumnFlowsheet.EnergyStreams.Item(1).HeatFlowValue
T_top = ColumnFlowsheet.TemperaturesValue[0]
T_bottom = ColumnFlowsheet.TemperaturesValue[N + 1]
```

`TQ-11` などの energy stream 名は、上記 `EnergyStreams.Item(0/1)` が読めない場合の fallback とする。

リボイラーは塔底側を等温の沸騰側とみなし、低圧または中圧スチームとの単純温度差で面積を計算する。塔底温度が 120 ℃未満なら 130 ℃スチーム、120 ℃以上なら 250 ℃スチームを使う。

$$
T_{\mathrm{steam}}
=
\begin{cases}
130 & T_{\mathrm{bottom}} < 120 \\
250 & T_{\mathrm{bottom}} \geq 120
\end{cases}
$$

$$
c_{\mathrm{steam}}
=
\begin{cases}
1.0 & T_{\mathrm{bottom}} < 120 \\
1.4 & T_{\mathrm{bottom}} \geq 120
\end{cases}
$$

$$
\Delta T_{\mathrm{reb}}
=
T_{\mathrm{steam}} - T_{\mathrm{bottom}}
$$

$$
A_{\mathrm{reb}}
=
\frac{|Q_{\mathrm{reb}}| \times 1000}{1500 \Delta T_{\mathrm{reb}}}
$$

ここで、$Q_{\mathrm{reb}}$ は kW、$1500$ は $\mathrm{W/(m^2 K)}$ とする。$\Delta T_{\mathrm{reb}} \leq 0$ の場合、その feed 段条件は invalid とする。

コンデンサーは塔頂側を等温凝縮側、冷却水を 30 ℃ から 45 ℃ とみなし、対数平均温度差を計算する。対数平均温度差は HYSYS から直接読む値ではない。

$$
\Delta T_{\mathrm{cond}}
=
\frac{
(T_{\mathrm{top}} - 30) - (T_{\mathrm{top}} - 45)
}{
\ln((T_{\mathrm{top}} - 30)/(T_{\mathrm{top}} - 45))
}
$$

$$
A_{\mathrm{cond}}
=
\frac{|Q_{\mathrm{cond}}| \times 1000}{1000 \Delta T_{\mathrm{cond}}}
$$

ここで、$Q_{\mathrm{cond}}$ は kW、$1000$ は $\mathrm{W/(m^2 K)}$ とする。$T_{\mathrm{top}} \leq 45^\circ \mathrm{C}$ の場合、冷却水 30→45 ℃では成り立たないため、その feed 段条件は invalid とする。

コンデンサーとリボイラーの装置費は次で計算する。

$$
C_{\mathrm{condenser}}
=
1{,}500{,}000 A_{\mathrm{cond}}^{0.65}
$$

$$
C_{\mathrm{reboiler}}
=
1{,}500{,}000 A_{\mathrm{reb}}^{0.65} \times 2
$$

リボイラー用スチーム費は用役コストには含めない。今回の用役コストは、tower1 の C-3、tower2 の EB recycle 200 ℃加熱概算、tower3 の C-4/C-5 に限定する。

年換算は 7 年定額償却とする。

$$
C_{\mathrm{equipment,year}}
=
\frac{
C_{\mathrm{shell}}
+
C_{\mathrm{condenser}}
+
C_{\mathrm{reboiler}}
}{7}
$$

## 用役コスト

塔ごとに用役評価対象を変える。

```text
tower1: C-3 による SM 製品冷却
tower2: EB recycle を 200 ℃まで再加熱するための加熱
tower3: C-4, C-5 による BZ, TL 製品冷却
```

製品冷却器の operation 名は次を使う。

```python
TOWER_PRODUCT_COOLERS: dict[TargetTower, tuple[str, ...]] = {
    "tower1": ("C-3",),
    "tower2": (),
    "tower3": ("C-4", "C-5"),
}
```

冷却後の製品温度は 38 ℃ とする。

$$
T_{\mathrm{product,target}} = 38^\circ \mathrm{C}
$$

### 冷却用役

C-3、C-4、C-5 の duty を HYSYS から読む。これらは既に HYSYS 上にある冷却器なので、stream 名から手計算せず、冷却器 operation または接続 energy stream から duty を読む。

冷却は次の 2 段に分ける。

```text
50 ℃までは冷却水
50 ℃から 38 ℃までは 0 ℃プロピレン冷媒
```

最小接近温度は 10 ℃ とする。冷却水戻り温度を 40 ℃ とする場合、冷却水で到達できるプロセス温度の下限は 50 ℃である。

$$
T_{\mathrm{cw,limit}} = 50^\circ \mathrm{C}
$$

$$
T_{\mathrm{prop}} = 0^\circ \mathrm{C}
$$

HYSYS duty を冷却水分とプロピレン冷媒分に分けるため、冷却器入口温度と出口温度を読む。入口温度が $T_{\mathrm{in}}$、出口温度が 38 ℃であるとき、熱容量流量一定と仮定し、冷却 duty の絶対値を温度差比で分割する。

$$
Q_{\mathrm{cw}}
=
|Q_{\mathrm{total}}|
\frac{
\max(T_{\mathrm{in}} - 50, 0)
}{
\max(T_{\mathrm{in}} - 38, 0)
}
$$

$$
Q_{\mathrm{prop}}
=
|Q_{\mathrm{total}}| - Q_{\mathrm{cw}}
$$

入口温度が 50 ℃以下の場合は、全量をプロピレン冷媒とする。入口温度が 38 ℃以下の場合は、冷却 duty は 0 とする。

冷却水費とプロピレン冷媒費は次で計算する。

$$
C_{\mathrm{cw,year}}
=
\mathrm{cooling\_water\_cost}(Q_{\mathrm{cw}})
$$

$$
C_{\mathrm{prop,year}}
=
|Q_{\mathrm{prop}}|
\times 3.6
\times \mathrm{HOURS\_PER\_YEAR}
\times 0.8
$$

### tower2 の EB recycle 加熱

tower2 の HYSYS case には該当 heater は無いため、HYSYS から heater duty は読まない。EB recycle stream の温度、質量流量、質量熱容量を読み、200 ℃まで加熱する duty を Python 側で概算する。

$$
T_{\mathrm{EB,target}} = 200^\circ \mathrm{C}
$$

$$
Q_{\mathrm{heat,EB}}
=
\frac{
\dot{m}_{EB} C_{p,EB} \max(200 - T_{EB}, 0)
}{
3600
}
$$

用役費は `docs/cost.md` の加熱用飽和中圧スチーム単価を用いて概算する。

$$
c_{\mathrm{steam,MP}} = 1.4\ \mathrm{yen/MJ}
$$

$$
C_{\mathrm{heat,EB,year}}
=
Q_{\mathrm{heat,EB}}
\times 3.6
\times \mathrm{HOURS\_PER\_YEAR}
\times c_{\mathrm{steam,MP}}
$$

## 評価関数

評価関数はコスト最小化とする。

$$
J
=
C_{\mathrm{equipment,year}}
+
C_{\mathrm{utility,year}}
$$

$$
C_{\mathrm{utility,year}}
=
C_{\mathrm{cw,year}}
+
C_{\mathrm{prop,year}}
+
C_{\mathrm{heating,year}}
$$

対象塔で使わない項は 0 とする。計算に必要な費目が計算不能な場合、その feed 段条件は invalid とする。

## 制約

tower1 では SM 製品、または tower1 bottom の温度が 100 ℃以下であることを制約にする。

$$
T_{\mathrm{SM}} \leq 100^\circ \mathrm{C}
$$

これは SM の重合防止のためである。

制約違反 case は invalid とし、図には含めない。ログには制約違反理由を出す。

## 読む stream と operation

初期実装で読む operation は次である。

```text
tower1:
  T-1
  C-3
  TQ-11
  TQ-12

tower2:
  T-2
  TQ-21
  TQ-22
  eb_recycle

tower3:
  T-3
  C-4
  C-5
  TQ-31
  TQ-32
```

冷却器から読む値は次である。

```text
Duty
FeedTemperature または inlet stream TemperatureValue
ProductTemperature または outlet stream TemperatureValue
```

energy stream から duty が読める場合は、energy stream の `HeatFlowValue` または該当 quantity を使う。

## 出力図

塔ごとに 1 枚だけ作る。

横軸は HYSYS から読んだ段数、縦軸は億円/year とする。

1 枚の図に次の 3 系列を plot する。

```text
装置コスト
用役コスト
評価関数 J
```

図ファイル名は次とする。

```text
scripts/distillation/media/tower1_cost_summary.png
scripts/distillation/media/tower2_cost_summary.png
scripts/distillation/media/tower3_cost_summary.png
```

## ログ

標準出力ログは、feed 段探索中の進行確認にも使う。

ファイルログは `logs/distillation_stage_sweep.log` に追記する。ファイルログには、実行条件、case ごとの最良 feed 段、全体 summary だけを残し、feed 段ごとの探索ログは含めない。

ログは `DETAILED_FEED_LOG = False` の場合、case 1 つにつき 1 回から 2 回程度に抑える。

例は次の通りである。

```text
[start] tower=tower1 grid=coarse cases=5
[case] 1/5 file=tower1_a.hsc N=20 best_feed=9 L/D=13.2 J=1.2345 equipment=0.9000 utility=0.3345 oku-yen/year valid
[case] 2/5 file=tower1_b.hsc N=25 best_feed=11 L/D=16.1 ld_warning invalid: T_SM=105.2 C > 100 C
[done] tower=tower1 best_N=20 best_feed=9 best_J=1.2345 oku-yen/year figure=scripts/distillation/media/tower1_cost_summary.png
```

`DETAILED_FEED_LOG = True` の場合は、次のような feed 段ごとの詳細ログも出す。

```text
[feed] file=tower1_a.hsc N=20 feed=9 D=2.345 H=18.400 L/D=7.846 Ttop=60.000 Tbottom=95.000 Qcond=100.000 Qreb=120.000 equipment=0.9000 utility=0.3345 J=1.2345 valid
```

HYSYS case open、solve、close などの細かいログは出さない。

## 未確定要素

- tower1 の制約に使う温度は、まず C-3 入口側の `sm_outlet` または塔底製品温度を使う。
- feed 段の書き換え経路は `traysection.SpecifyFeedLocation(feed_object, stage)` を使う。
- condenser/reboiler の面積推算では、対数平均温度差を直接読むのではなく、`T_top`, `T_bottom`, duty から上記の簡略式で計算する。
- tower2 の加熱用役費は、EB recycle を 200 ℃まで加熱する概算である。反応器入口までの正式な加熱評価は別途整理する。
- L/D 比は警告扱いにする。評価からは除外する。
- `D` の式は添付式と明石さん方式に合わせる。単位整合の再整理は別作業とする。
