# デカンター2基案の冷却評価 詳細設計

## 目的

本資料は、`scripts/decanter/hysys/decanter_0522v1.hsc` を用いた2基デカンター案の解析を、既存の1基デカンター温度 sweep 設計とは分けて整理するための詳細設計である。

前回の整理では、冷却水出口温度を45 ℃としていた。しかし、最小接近温度差10 ℃を確保し、プロセス流体を冷却水で50 ℃まで冷却する場合、冷却水出口温度は40 ℃とするのが整合的である。したがって、本検討では冷却水条件を30 ℃入口、40 ℃出口に修正する。

## 結論

今回の検討は、既存の `docs/reports/20260521_01_decanter-optimization-script-design.md` とは別レポートとして扱う。

対象は次である。

```text
scripts/
  decanter/
    decanter_two_stage_analysis.py         # 新規想定。2基デカンター案の解析
    inspect_decanter_case.py               # HYSYS case 調査
    diagnostics/
      decanter_0522v1_inspection.json      # 新規想定
      decanter_0522v1_focus.json           # 新規想定
    hysys/
      decanter_0522v1.hsc                  # 2基デカンター case
    media/
src/process_sim/
  plant/
    economics.py                           # 共通経済計算関数
  separator/
    hysys_io.py                            # HYSYS COM 読み取り helper
docs/
  reports/
    20260524_01_decanter-two-stage-cooling-design.md
```

`decanter_0522v1.hsc` は2基デカンター case として扱う。ただし、stream 名、operation 名、duty の取得可否、デカンター体積の取得可否は HYSYS case 調査で確認するまで固定しない。

## 冷却水条件の修正

冷却水条件は次のようにする。

```text
冷却水入口温度: 30 ℃
冷却水出口温度: 40 ℃
最小接近温度差: 10 ℃
冷却水で到達可能なプロセス流体温度: 50 ℃
```

理由は、冷却水出口が40 ℃の場合、冷却水クーラー出口側で次を満たすためである。

```text
T_process,out - T_CW,out = 50 - 40 = 10 ℃
```

冷却水出口を45 ℃とすると、プロセス流体を50 ℃まで冷却した場合の出口側接近温度差は5 ℃となり、最小接近温度差10 ℃と矛盾する。

## 温度区間

反応器出口流体の冷却は、温度区間ごとに次のように扱う。

```text
T > 80 ℃
```

この区間は、最終的なヒートインテグレーションで原料、リサイクル EB、リサイクル水などの予熱に利用可能な高温側熱として扱う。デカンター部分最適化では、外部冷却用役費および冷却器設備費に含めない。

```text
80 ℃ -> 50 ℃
```

この区間は冷却水で冷却する。冷却水は30 ℃から40 ℃まで昇温するとして評価する。

```text
50 ℃ -> 15 ℃
```

この区間は0 ℃プロピレン冷媒で冷却する。

## 2基デカンター案の評価対象

2基デカンター案では、1基目デカンター温度を `T1`、2基目デカンター温度を15 ℃とする。

```text
T2 = 15 ℃
T1 = 50, 55, 60, 65, 70, 75, 80 ℃
```

ただし、ベンゼンの沸点80.2 ℃に近いため、80 ℃は感度確認点として扱い、最終採用候補としては75 ℃程度を上限候補にする。

## 評価関数

2基デカンター案の評価関数は次とする。

```text
J_2
= C_loss,2
+ C_cool,CW,1
+ C_cool,CW,2
+ C_cool,ref,2
+ C_reheat,steam,2
+ C_CW cooler,1,annual
+ C_CW cooler,2,annual
+ C_ref cooler,2,annual
+ C_decanter,1,annual
+ C_decanter,2,annual
```

すべての単位は `円/year` とする。

1基目デカンターから出る気相は2基目でさらに冷却されるため、1基目気相中の EB、SM、BZ、TL はこの時点では損失として数えない。有価成分損失は、2基目デカンター後の最終オフガスだけを対象とする。

## 冷却器構成

2基デカンター案の冷却器構成は、`50 ℃ <= T1 <= 80 ℃` の範囲では基本的に3基である。

```text
80 ℃ -> T1      1基目前冷却水クーラー
T1 -> 50 ℃      2基目前冷却水クーラー
50 ℃ -> 15 ℃    2基目前プロピレン冷媒クーラー
```

`T1 = 50 ℃` の場合、2基目前冷却水クーラーの負荷は0である。この場合は、実装上 `Q = 0` の冷却器を設備費計算から除外する。

`T1 < 50 ℃` の場合は1基目前にもプロピレン冷媒が必要になるが、本検討では探索範囲外とする。

## 冷却水用役費

冷却水は30 ℃から40 ℃まで昇温するとして必要量を求める。

```text
m_CW = Q_CW / (Cp_water * (40 - 30))
```

冷却水単価は次を用いる。

```text
10 円/ton
```

年間冷却水費は次で計算する。

```text
C_cool,CW = m_CW * 10 * HOURS_PER_YEAR
```

実装では、`Q_CW` の単位と `Cp_water` の単位をそろえる。例えば `Q_CW` を `kW = kJ/s` として読む場合、`kg/s` または `ton/h` に変換してから年間費用へ換算する。

## プロピレン冷媒用役費

プロピレン冷媒は0 ℃冷媒とし、単価は次を用いる。

```text
0.8 円/MJ
```

年間冷媒費は次で計算する。

```text
C_cool,ref = Q_ref,MJ/year * 0.8
```

## 冷却器設備費

各冷却器について、伝熱面積を次で計算する。

```text
A_j = abs(Q_j,kW) * 3600 / (U_j * DeltaT_lm,j)
```

冷却器機器費は次で計算する。

```text
C_cooler,j = 1.5e6 * A_j^0.65
```

冷却器年換算費は次である。

```text
C_cooler,annual = 2.5 * sum(C_cooler,j) / 7
```

係数 2.5 は、機器費から建設費を概算するための係数として扱う。

冷却水クーラーの LMTD では、冷却水入口30 ℃、冷却水出口40 ℃を使う。プロピレン冷媒クーラーの LMTD では、0 ℃冷媒を使う。

総括伝熱係数は次を初期値とする。

| 対象 | U |
|---|---:|
| 冷却水クーラー | 3600 kJ/(m2 K h) |
| プロピレン冷媒クーラー | 5400 kJ/(m2 K h) |

## 水リサイクル再加熱用役費

デカンターで分離された水相は反応器入口へリサイクルされるため、各デカンター出口温度から80 ℃まで再加熱する負荷を評価する。

```text
Q_reheat,2
= m_water,1 * Cp_water * (80 - T1)
+ m_water,2 * Cp_water * (80 - 15)
```

`T1 = 80 ℃` の場合、1基目水相の80 ℃までの再加熱負荷は0である。

再加熱は2.46 atm 飽和スチームで供給すると仮定する。

```text
T_steam = 130 ℃
c_steam = 1.0 円/MJ
```

再加熱用役費は次で計算する。

```text
C_reheat,steam = Q_reheat,MJ/year * 1.0
```

再加熱器の設備費も評価に含める。再加熱器は、水相を2.46 atm 飽和スチームで80 ℃まで加熱する熱交換器として扱う。

```text
A_reheat = Q_reheat / (U_reheat * DeltaT_lm,reheat)
C_reheater,annual = 2.5 * 1.5e6 * A_reheat^0.65 / 7
```

`U_reheat` は、受熱側が水相、与熱側が飽和スチーム凝縮であるため、表 C.1 の「液 - ガス(凝縮)」相当として次を用いる。

```text
U_reheat = 3600 kJ/(m2 K h)
```

## デカンター設備費

デカンター設備費は、1基目と2基目を別々に計算して合計する。

```text
C_decanter,annual
= 2.5 * (C_decanter,1 + C_decanter,2) / 7
```

HYSYS からデカンター体積を直接読めない場合は、油相と水相の体積流量、滞留時間から外部推算する。

初期条件は次である。

| 項目 | 値 | 備考 |
|---|---:|---|
| デカンター液相滞留時間 | 10 min | 初期設計仮定 |
| 償却年数 | 7年 | 冷却器と同じ |

## 実装ファイルと責務

### `scripts/decanter/decanter_two_stage_analysis.py`

2基デカンター案の解析本体である。汎用 CLI にはしない。

責務は次の通りである。

- `decanter_0522v1.hsc` を開く。
- 対象 stream と operation を取得する。
- `T1 = 50, 55, 60, 65, 70, 75, 80 ℃` を探索する。
- 2基目温度は15 ℃に固定する。
- HYSYS を solve する。
- 2基目後の最終オフガス中の EB、SM、BZ、TL 流量を読む。
- 1基目と2基目の水相流量と温度を読む。
- 冷却水区間 duty とプロピレン冷媒区間 duty を読む。
- 1基目と2基目のデカンター体積、または体積推算に必要な液相体積流量を読む。
- HYSYS から読める値と読めない値を実装中に確認し、読めない値は外部推算に切り替える。
- 評価関数と内訳を計算する。
- 図を `scripts/decanter/media/` に保存する。
- 各 `T1` の主要値を標準出力に表示する。

script 冒頭に置く定数候補は次である。

```python
CASE_PATH = Path(__file__).parent / "hysys" / "decanter_0522v1.hsc"
MEDIA_DIR = Path(__file__).parent / "media"

T1_DECANTER_LIST_C = [50, 55, 60, 65, 70, 75, 80]
T2_DECANTER_C = 15.0

COOLING_WATER_INLET_C = 30.0
COOLING_WATER_OUTLET_C = 40.0
COOLING_WATER_PROCESS_LIMIT_C = 50.0
HOT_SIDE_EVALUATION_START_C = 80.0
REFRIGERANT_C = 0.0
```

stream 名と operation 名は、`decanter_0522v1_focus.json` を作成して確認するまで固定しない。

### `scripts/decanter/decanter_temperature_sweep.py`

既存の1基デカンター温度 sweep script である。評価関数は2基案と比較できるように、次の費目へ合わせる。

- 有価成分損失
- 冷却水費
- プロピレン冷媒費
- 水リサイクル再加熱費
- 熱交換器年換算費
- デカンター年換算費

熱交換器年換算費には、冷却水クーラー、プロピレン冷媒クーラー、水相再加熱器を含める。冷却器は、80 ℃から50 ℃までを冷却水、50 ℃からデカンター温度までをプロピレン冷媒として分けて評価する。デカンター温度が50 ℃より高い場合は、冷却水区間だけを評価し、プロピレン冷媒費とプロピレン冷媒クーラー設備費は0とする。

### `scripts/decanter/inspect_decanter_case.py`

`decanter_0522v1.hsc` の COM 調査に使う。出力候補は次である。

```text
scripts/decanter/diagnostics/decanter_0522v1_inspection.json
scripts/decanter/diagnostics/decanter_0522v1_focus.json
```

focused JSON で確認する対象候補は次である。

```text
material streams:
  reactor_outlet
  first decanter feed
  first decanter vapor
  first decanter water
  first decanter oil
  second decanter feed
  final off gas
  second decanter water
  second decanter oil
  tower1_feed

operations:
  first cooling water cooler
  second cooling water cooler
  refrigerant cooler
  first decanter
  second decanter
```

実際の名称は HYSYS case 調査結果に従う。

### `src/process_sim/plant/economics.py`

HYSYS 非依存の経済計算を置く。追加候補は次である。

```python
def cooling_water_cost_yen_per_year(
    duty_kw: float,
    cp_water_kj_kg_k: float,
    cooling_water_delta_t_k: float,
    cooling_water_yen_per_ton: float,
    hours_per_year: float,
) -> float:
    """冷却 duty から年間冷却水費を計算する。"""


def steam_heating_cost_yen_per_year(
    duty_kw: float,
    steam_yen_per_mj: float,
    hours_per_year: float,
) -> float:
    """加熱 duty から年間スチーム費を計算する。"""
```

既存の `cooling_utility_cost_yen_per_year()`、`component_loss_cost_yen_per_year()`、`cooler_capital_cost_yen()`、`decanter_capital_cost_yen()`、`heat_exchanger_area_m2()`、`log_mean_temperature_difference_k()` は再利用する。

## 作図

図は `scripts/decanter/media/` に保存する。

初期実装で必要な図は次である。

```text
two_stage_decanter_cost_vs_t1.png
decanter_best_case_cost_breakdown.png
```

`two_stage_decanter_cost_vs_t1.png` は、横軸を `T1`、縦軸を年間コストとして、2基案の総コストと主要内訳を1基案の温度 sweep 図と同じ折れ線で重ねる。主要内訳は、有価成分損失、冷却水費、プロピレン冷媒費、再加熱費、熱交換器年換算費、デカンター年換算費とする。

`decanter_best_case_cost_breakdown.png` は、1基案と2基案の最適条件を比較する棒グラフとする。1基案は15 ℃固定の結果を用いる。2基案は `T1` sweep の中で最小の `J_2` を与える条件を用いる。棒グラフは総コストだけでなく、主要内訳を積み上げて表示する。

CSV は初期実装では作らない。数値は標準出力に表形式で表示する。

## 実行手順

想定する実行は次である。

```powershell
uv run python scripts/decanter/decanter_two_stage_analysis.py
```

処理フローは次である。

```text
1. decanter_0522v1.hsc の path を確認する
2. 必要なら decanter_0522v1_focus.json を作成する
3. HYSYS case を開く
4. 対象 stream と operation を取得する
5. 各 T1 について1基目デカンター温度を設定する
6. 2基目デカンター温度を15 ℃に設定する
7. HYSYS を solve する
8. 必須値を読む
9. 有価成分損失、冷却費、再加熱費、設備費を計算する
10. 有効点を整理する
11. 図を保存する
12. 標準出力にサマリを出す
```

HYSYS の起動、solve、収束、値の取得は、ユーザーがローカルで返した出力だけを根拠に扱う。

## 採用理由

### 冷却水出口温度を40 ℃にする理由

冷却水でプロセス流体を50 ℃まで冷却する場合、最小接近温度差10 ℃を満たすには、冷却水出口温度は40 ℃以下である必要がある。冷却水出口45 ℃では接近温度差が5 ℃となり、設定条件と矛盾する。

### 2基案を別レポートにする理由

2基案では、HYSYS case、対象 stream、冷却器数、水相再加熱費、最終オフガスの定義が1基案と異なる。既存の1基案温度 sweep 設計に追記すると責務が混ざるため、別レポートとして管理する。

### 冷却水クーラーと冷媒クーラーを分ける理由

冷却水と0 ℃プロピレン冷媒では、単価、温度条件、LMTD、到達可能温度が異なる。冷却用役費と設備費を別々に計算することで、2基化による設備費増加と再加熱費低減を同一基準で比較できる。

### 作図を2種類に絞る理由

今回確認したいのは、1基目温度に対する総コストと内訳の変化、および1基案と2基案の最適条件の比較である。個別費目ごとの図を分けると確認対象が増えすぎるため、温度 sweep 図と最適条件の積み上げ棒グラフに集約する。

## 採用しない案

### 冷却水出口45 ℃のまま評価する案

採用しない。プロセス流体出口50 ℃、冷却水出口45 ℃では最小接近温度差が5 ℃となり、10 ℃の条件と整合しない。

### 既存の1基案詳細設計をさらに編集する案

採用しない。今回の変更範囲は2基デカンター案の冷却構成と評価関数に広がるため、既存レポートとは分ける。

### 1基目気相を損失として数える案

採用しない。1基目気相は2基目でさらに冷却されるため、損失として評価するのは2基目後の最終オフガスである。

## 検証方針

HYSYS 非依存では、以下をテストする。

- 冷却水出口40 ℃、入口30 ℃の条件で冷却水費を計算できる。
- 冷媒 duty から年間プロピレン冷媒費を計算できる。
- プロピレン冷媒クーラーの U として 5400 kJ/(m2 K h) を使える。
- 水相流量と温度から再加熱費を計算できる。
- `Q = 0` の冷却器を設備費計算から除外できる。
- 最終オフガスだけを有価成分損失に使える。
- 作図が `two_stage_decanter_cost_vs_t1.png` と `decanter_best_case_cost_breakdown.png` の2種類に集約されている。

HYSYS 依存の確認は、ユーザーがローカルで実行した結果だけを根拠にする。

## 未確定事項

- `decanter_0522v1.hsc` 内の2基デカンターに対応する stream 名。
- 冷却水クーラーとプロピレン冷媒クーラーの operation 名。
- 各冷却区間の duty を HYSYS operation から直接読めるか。
- duty を直接読めない場合に、stream enthalpy 差から外部計算できるか。
- 1基目、2基目のデカンター体積を HYSYS から読めるか。
- 水相流量を質量流量として読めるか。
- `T1 = 80 ℃` の solve が安定するか。
