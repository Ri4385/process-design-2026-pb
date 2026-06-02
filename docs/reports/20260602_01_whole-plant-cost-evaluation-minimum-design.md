# 全体最適化向けコスト評価の最小設計

## 目的

最終的には、`fast-plant-convergence` の収束後に `Final Plant Summary` と次の年間収支を出せるようにする。

- 原料費
- 製品収入
- 装置費と年換算装置費
- utility cost
- 経済収支

コスト式と単価は `docs/cost.md` を参照する。本書では全体最適化へ接続するための最小構成だけを定める。

第一段階では、既存 HYSYS case の読み取り、コスト計算、ログ出力を独立した script で確認する。収束計算との統合は第二段階で行う。

## 評価対象とするプロセス

全体最適化では、次の簡略化した加熱系を対象とする。

1. recycle H2O と fresh H2O を混合する。
2. 反応器後流体との熱交換により、混合 H2O を HYSYS case 上で設定済みの温度まで加熱する。
3. 沸点付近まで加熱した EB と混合する。
4. 反応器前の加熱器で反応器入口温度まで加熱する。

蒸留塔、製品冷却器など、上記の熱交換以外に必要な加熱と冷却は外部 utility で補う。

## 収支の基本形

年間経済収支は次で評価する。

```text
annual_profit
  = product_revenue
  - raw_material_cost
  - annualized_equipment_cost
  - utility_cost
```

### 原料費

- fresh EB
- fresh H2O
- 補助燃料のヘキサン

### 製品収入

- SM
- BZ
- TL

SM は年間販売量の上限を `200,000 ton/year` とする。生産量が上限を超えても、超過分は販売できない。

```text
sm_sales_ton_per_year
  = min(sm_production_ton_per_year, 200_000)
```

通常は SM 生産量が上限を超える条件で運転するため、SM 収入は基本的に `200,000 ton/year` 分で固定される。

### 装置費

- 反応器
- 反応器段間加熱器
- HYSYS から `separator/equipment_reader/` で読める蒸留塔、デカンター、熱交換器、ポンプ、コンプレッサー
- 反応器後流体と入口 H2O の熱交換器
- 反応器前の加熱炉または加熱器

装置費は `docs/cost.md` の方法で年換算する。個別機器費をどの式へ対応付けるかは、コスト計算 module の実装時に定義する。

### Utility cost

- 蒸留塔と製品冷却などの外部冷却
- 蒸留塔リボイラなどの外部加熱
- ポンプ、コンプレッサーの電力
- 入口 H2O 加熱、反応器前加熱、段間加熱で不足する燃料

反応器後流体との熱交換で回収した熱は、外部 utility cost に入れない。

## 燃料の扱い

入口 H2O 加熱、反応器前加熱、段間加熱では、オフガス中の H2 と CH4 を燃料として優先的に使う。不足熱量はヘキサン燃焼で補う。加熱炉効率は `0.8` とする。燃焼効率は別項目として設けない。

```text
required_furnace_duty
  = water_heating_shortage_duty
  + reactor_inlet_heating_duty
  + interstage_reheating_duty

required_fuel_heat
  = required_furnace_duty / 0.8

hexane_fuel_heat
  = max(required_fuel_heat - offgas_h2_ch4_combustion_heat, 0)
```

ヘキサン費は `hexane_fuel_heat` から求める。余剰オフガスの販売価値は考えない。

## 実装段階

### 第一段階

既存の HYSYS case を読み、コスト計算とログ出力ができることを確認する script を作る。HYSYS case への値の書き込みは行わない。

1. 既存 HYSYS case から `ProcessEquipment` と必要な stream を読む。
2. 読み取った値からコスト入力を作る。
3. 費目別の年間金額と `annual_profit` を計算する。
4. コスト内訳を標準出力へ出す。

### 第二段階

第一段階の確認後、`fast-plant-convergence` の収束後に同じコスト評価を呼び出す。

1. production target と recycle convergence を既存どおり実行する。
2. 収束した場合だけ、最終 HYSYS case から `ProcessEquipment` と必要な stream を読む。
3. コスト評価を行い、plant summary の後にコスト内訳を出す。

収束途中では装置費を読まない。

## ディレクトリ構成

```text
src/process_sim/
  separator/
    equipment.py                        # HYSYS から読んだ機器状態
    equipment_reader/
      process_equipment.py              # ProcessEquipment 読み取り
  plant/
    fast_convergence.py                 # 収束後にコスト評価を呼ぶ CLI 入口
    economics.py                        # 既存の暫定経済計算。段階的に整理する
    cost/
      models.py                         # コスト入力と費目別評価結果
      evaluation.py                     # 年間経済収支の組み立て
      equipment.py                      # 装置費と年換算
      utility.py                        # 外部 utility と燃料費
      revenue.py                        # 原料費と製品収入
scripts/
  read_hysys_cost_breakdown.py           # 第一段階のコスト計算とログ確認
docs/
  cost.md                               # コスト式と単価
  reports/
    20260602_01_whole-plant-cost-evaluation-minimum-design.md
```

`separator/` は HYSYS 参照先と読み取った機器状態だけを扱う。費目分類と金額計算は `plant/cost/` に置く。

## HYSYS 読み取り対象

第一段階では、既存 HYSYS case 上にある operation、energy stream、material stream を読む。HYSYS case の変更と Python からの値の書き込みは行わない。

入口 H2O 加熱をコスト評価できるように、次を読む。

- 反応器後流体と入口 H2O の熱交換器 duty
- 熱交換器の両側の入口温度と出口温度
- 反応器前加熱器の duty
- EB 加熱に外部 utility が必要な場合は、その duty

既存の `separator/equipment_reader/heat_exchanger.py` で読めるように、既存 operation と energy stream の参照先を `separator/hysys_equipment_reference.py` に登録する。

## ログ

ログの詳細設計は未確定とする。

第一段階では、読み取った値と計算結果を検証できる標準出力が必要である。第二段階では、収束後の経済収支と、最適化結果を比較するためのログが必要になる。出力項目、粒度、形式、保存先は別途決める。

## オフガスの扱い

- 燃焼対象は H2 と CH4 のみとする。
- 余剰オフガスの販売価値は考えない。
- EB と SM は燃焼対象にしない。重合や炭素析出による運転上の問題を避けるためである。

## 未確定要素

### 第一段階

- 既存 HYSYS case から読む operation、energy stream、material stream の一覧。
- fresh EB、fresh H2O、SM、BZ、TL、off gas の流量を読む stream 名。
- 反応器後流体と入口 H2O の熱交換器について、HYSYS から直接読む値と Python 側で計算する値の分担。
- 各熱交換器の面積計算に使う総括熱伝達係数と温度差の扱い。
- 各加熱 duty と冷却 duty に割り当てる外部 utility の種類。
- H2、CH4、ヘキサンの発熱量に低位発熱量と高位発熱量のどちらを使うか。
- 加熱炉の装置費を計算するための燃料流量の扱い。
- ポンプ、コンプレッサー、デカンターの Bare Module Cost に使う補正係数。
- 工事費を含めた総建設費の係数と、個別機器費の年換算方法。
- BZ と TL の販売量に上限を設けるか。
- 製品純度が規格を満たさない場合の扱い。
- 第一段階の確認 script で計算対象に含める反応器本体費と段間加熱器費の入力方法。
- 第一段階のログ設計。

### 第二段階

- `fast-plant-convergence` からコスト評価へ渡す反応器計算結果と fresh feed の保持方法。
- 収束後の HYSYS session から equipment と stream を読むインターフェイス。
- 全体最適化で比較用に保存するログ設計。
