# 全体最適化向けコスト評価の最小設計

## 目的

最終的には、`fast-plant-convergence` の収束後に `Final Plant Summary` と次の年間収支を出せるようにする。

- 原料費
- 製品収入
- 装置費と年換算装置費
- utility cost
- 経済収支

コスト式と単価は `docs/cost.md` を参照する。本書では全体最適化へ接続するための最小構成だけを定める。

第一段階では、既存の `fast-plant-convergence` と接続し、収束後の状態からコスト計算とログ出力を行う。入口条件は既存 HYSYS case に入っている値を使い、Python から書き込まない。第二段階で入口条件の書き込みを追加する。

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

通常は SM 生産量が上限を超える条件で運転するため、SM 収入は基本的に `200,000 ton/year` 分で固定される。第二段階の全体最適化では、`200,000 ton/year` 未満の条件を有効な解として扱わない。

BZ と TL の販売量には上限を設けない。

第一段階では、SM 生産量が `200,000 ton/year` 未満の場合もコスト計算を行い、警告を出す。

### 装置費

- 反応器
- 反応器段間加熱器
- HYSYS から `separator/equipment_reader/` で読める蒸留塔、デカンター、熱交換器、ポンプ、コンプレッサー
- 反応器後流体と入口 H2O の熱交換器

装置費は `docs/cost.md` の方法で年換算する。個別機器費をどの式へ対応付けるかは、コスト計算 module の実装時に定義する。

全体最適化では、加熱炉本体の装置費は考えない。

### Utility cost

外部 utility は次のように割り当てる。

| 対象 | utility | 備考 |
|---|---|---|
| SM、BZ、TL 製品冷却 | 冷却水 | 製品冷却後温度は `40 ℃`、冷却水は `30 ℃ -> 45 ℃` とする。向流熱交換器として扱う。 |
| デカンター冷却 | 冷却水、必要に応じてプロピレン冷媒 | 冷却水は `30 ℃ -> 45 ℃` とする。 |
| SM 分離塔リボイラ | 130 ℃ steam | 確定とする。 |
| EB 分離塔、BZTL 分離塔リボイラ | 130 ℃ steam または 250 ℃ steam | 塔底温度に対して `ΔTmin = 20 ℃` を満たす低温側の steam を使う。 |
| 蒸留塔コンデンサ | 冷却水、必要に応じてプロピレン冷媒 | 冷却水は `30 ℃ -> 45 ℃` とし、`ΔTmin = 10 ℃` を満たせない場合はプロピレン冷媒を使う。 |
| EB recycle 加熱 | 130 ℃ steam | 確定とする。 |
| 入口 H2O 加熱 | 反応器後流体との熱交換、加熱炉 | 熱回収後の不足分を加熱炉で補う。 |
| 反応器前加熱、段間加熱 | 加熱炉 | オフガス燃焼と不足分のヘキサン燃焼で補う。 |
| ポンプ、コンプレッサー | 電力 | HYSYS から読む動力を使う。 |

反応器後流体との熱交換で回収した熱は、外部 utility cost に入れない。

冷却水は基本的に `30 ℃ -> 45 ℃` とする。製品冷却後温度は `40 ℃` とする。

製品冷却器は向流熱交換器として扱う。製品流体入口が `70 ℃` 超の場合、製品流体出口 `40 ℃` と冷却水入口 `30 ℃` の端で `ΔT = 10 ℃`、製品流体入口と冷却水出口 `45 ℃` の端で `ΔT > 25 ℃` となる。したがって、最小接近温度差 `10 ℃` を満たす。

## Heat integration の範囲

全体最適化で考慮するプロセス間熱交換は、反応器後流体と入口 H2O の熱交換だけとする。

反応器後流体には SM が含まれる。高温の反応器後流体を EB recycle の加熱や SM を含む蒸留塔リボイラの加熱へ使うと、重合や炭素析出の問題が生じうる。そのため、これらへの熱回収は対象に含めない。

第一段階では、熱回収を次の組み合わせに限定する。

```text
hot side : C-11 デカンター1基目冷却器 ガス
cold side: H-22 入口 H2O 蒸発
```

HYSYS 上の C-11 と H-22 は別 operation だが、コスト計算ではこの組み合わせを 1 基の熱回収器として扱う。H-21、H-23、C-12 は熱回収対象に含めない。

回収可能 duty は次の最小値とする。

```text
heat_recovery_duty
  = min(
      C11_duty,
      H22_duty,
      C11_temperature_limited_duty
    )
```

`C11_temperature_limited_duty` は、C-11 outlet 側で `ΔTmin` を満たす範囲まで冷却できる熱量とする。回収しきれない C-11 duty は外部冷却、H-22 の不足分は加熱炉側の duty として扱う。

最小接近温度差は `data/chem_contest.md` に記載された次の条件を使う。

- Shell 側と Tube 側の両方がガスの場合は、`ΔTmin = 20 ℃` とする。
- プロセス流体が凝縮域で、utility 側が冷却水または冷媒の場合は、`ΔTmin = 10 ℃` とする。
- utility steam でプロセス流体を加熱する場合は、`ΔTmin = 20 ℃` とする。
- 蒸留塔リボイラは、`ΔTmin = 20 ℃` とする。
- 蒸留塔コンデンサは、`ΔTmin = 10 ℃` とする。

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

燃焼熱は次を使う。

- H2: `241.795 MJ/kmol`
- CH4: `802.854 MJ/kmol`
- ヘキサン: `44.73 MJ/kg`

## 実装段階

### 第一段階

`fast-plant-convergence` と接続し、収束後の状態からコスト計算とログ出力を行う。HYSYS case への入口条件の書き込みは行わない。

1. production target と recycle convergence を既存どおり実行する。
2. 収束後に、既存の `read_process_equipment(simulation_case)` から `ProcessEquipment` を取得する。
3. `PlantConvergenceResult`、最終 iteration の `ReactorResult`、`ProcessEquipment` からコスト入力を作る。
4. 費目別の年間金額と `annual_profit` を計算する。
5. コスト内訳を出力する。

`convergence.py` はコスト計算を直接呼ばない。コスト付きの entry point から convergence を実行し、その結果を `plant/cost/` へ渡す。

```text
cost entry point
  -> OpenHysysPlantRunner
  -> run_production_target_convergence()
  -> runner.read_process_equipment()
  -> plant/cost/evaluation.py
```

### 第二段階

第一段階の確認後、入口条件を Python から HYSYS case へ書き込めるようにする。

入口条件として何を書き込むかは別途決める。

## ディレクトリ構成

```text
src/process_sim/
  separator/
    equipment.py                        # HYSYS から読んだ機器状態
    equipment_reader/
      process_equipment.py              # ProcessEquipment 読み取り
  plant/
    fast_convergence.py                 # convergence とコスト評価を呼ぶ CLI 入口
    session_runner.py                   # 収束後の ProcessEquipment 取得を接続
    economics.py                        # 既存の暫定経済計算。段階的に整理する
    cost/
      models.py                         # コスト入力と費目別評価結果
      evaluation.py                     # 年間経済収支の組み立て
      equipment.py                      # 装置費と年換算
      utility.py                        # 外部 utility と燃料費
      revenue.py                        # 原料費と製品収入
docs/
  cost.md                               # コスト式と単価
  reports/
    20260602_01_whole-plant-cost-evaluation-minimum-design.md
```

`separator/` は HYSYS 参照先と読み取った機器状態だけを扱う。費目分類と金額計算は `plant/cost/` に置く。

## HYSYS 読み取り

第一段階では、既存の `separator/equipment_reader/` を利用する。`read_process_equipment(simulation_case)` は次の `ProcessEquipment` を返す。

```text
ProcessEquipment
  distillation_columns
  decanters
  coolers
  heaters
  pumps
  compressors
```

stream は `ProcessEquipment` に含まれない。第一段階では convergence が保持する `PlantConvergenceResult` もコスト計算へ渡す。

既存の `PlantConvergenceResult` から取得できる主な値は次の通りである。

```text
PlantConvergenceResult
  feed_plan.steady_fresh_feed            # fresh EB、fresh H2O
  final_iteration.reactor_feed           # 反応器入口流量
  final_iteration.sm_product_kmol_h       # SM product 流量
  final_iteration.plant_record.streams    # 主要 stream
```

`plant_record.streams` に含まれる既存 stream は次の通りである。

```text
reactor_outlet
separator_feed
off_gas
water_recycle
eb_recycle
sm_product
bz_product
tl_product
```

入口条件は既存 HYSYS case に設定済みの値を使い、Python から書き込まない。

第一段階では HYSYS 読み取り処理を追加しない。既存 reader と convergence から取得できない値がある場合は、不足値として整理してから扱いを決める。

## ReactorResult の保持

現状の `PlantConvergenceResult` は全 iteration を保持している。

```text
PlantConvergenceResult
  feed_plan
  iterations: tuple[PlantConvergenceIteration, ...]
  final_iteration -> iterations[-1]
```

コスト計算では最終 iteration の反応器寸法、段間再加熱 duty、反応器出口条件が必要になる。そのため、`PlantConvergenceIteration` に `reactor_result` を追加する。

```text
PlantConvergenceIteration
  reactor_feed
  plant_record
  reactor_result
```

コスト評価では主に次を使う。

```text
result.feed_plan.steady_fresh_feed
result.final_iteration.plant_record
result.final_iteration.reactor_result
equipment
```

`ReactorResult` は radial と axial/PFR で共通の型である。radial 固有寸法と axial/PFR 固有寸法は `ReactorStageLog` の optional field として保持されているため、反応器装置費は埋まっている寸法 field に応じて計算する。

HYSYS case 上の heater と cooler は duty と温度を取得するための表現であり、実際の熱交換器コストを表すものではない。熱交換器面積と装置費は Python 側で計算する。

反応器後流体と入口 H2O の熱交換器も、既存の `ProcessEquipment` に含まれる前提にはしない。HYSYS case 上の heater と cooler から取得した duty と温度を使い、Python 側で熱交換器面積と装置費を計算する。

熱交換器面積は、`docs/cost.md` の流体組合せ別の総括熱伝達係数と、入口出口温度から求める対数平均温度差を使って計算する。成立判定には本書の `ΔTmin` を使う。

機器とコスト式の対応は次の通りとする。

| 機器 | コスト式 |
|---|---|
| heater、cooler、蒸留塔コンデンサ | `docs/cost.md` ①の熱交換器式、`K = 1` |
| 蒸留塔リボイラ | `docs/cost.md` ①の熱交換器式、`K = 2` |
| 蒸留塔本体 | `docs/cost.md` ② |
| 反応器本体 | `docs/cost.md` ③ |
| コンプレッサー | `docs/cost.md` ⑤。入力は動力 `kW` |
| ポンプ、デカンター | `docs/cost.md` ⑥ |

バルブなどは個別計算せず、`docs/cost.md` ⑦の一括費用で扱う。加熱炉本体の装置費は全体最適化に含めない。

製品純度は HYSYS 側の制約で満たす前提とする。Python 側では、規格未満の場合も計算は継続し、警告だけを出す。

## ログ

ログの詳細設計は未確定とする。

第一段階では、収束後に読み取った値と計算結果を検証できる出力が必要である。第二段階では、最適化結果を比較するためのログが必要になる。出力項目、粒度、形式、保存先は別途決める。

## オフガスの扱い

- 燃焼対象は H2 と CH4 のみとする。
- 余剰オフガスの販売価値は考えない。
- EB と SM は燃焼対象にしない。重合や炭素析出による運転上の問題を避けるためである。

## 未確定要素

### 第一段階

- 既存 reader と convergence から取得できる値だけで、第一段階のコスト計算に必要な入力が揃うか。
- 第一段階のログ設計。

### 第二段階

- Python から HYSYS case へ書き込む入口条件の一覧。
- 入口条件を書き込むタイミング。
- 全体最適化で比較用に保存するログ設計。
