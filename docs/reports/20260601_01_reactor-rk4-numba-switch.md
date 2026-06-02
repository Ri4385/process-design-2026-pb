# 反応器 RK4 Numba 切り替え基盤

## 目的

radial と axial PFR の反応器計算を高速化するため、既存 Python 経路を残したまま、微分評価と RK4 segment ループを Numba で実行する高速経路を追加した。

## ディレクトリ構成

```text
src/process_sim/reactor/
  core/
    config.py       # 反応器中核計算経路の切り替え
    integrator.py   # 通常の RK4 積分
    numba_reactor.py # 既定6反応の微分評価と segment ループ
  types/
    pfr_adiabatic.py     # axial PFR から高速経路を呼ぶ
    radial_adiabatic.py  # radial から高速経路を呼ぶ
```

## 実装

`src/process_sim/reactor/core/config.py` に次の設定を置く。

```python
USE_NUMBA_REACTOR_CORE = True
```

`USE_NUMBA_REACTOR_CORE = True` の場合は、既定の6反応ネットワークと既定物性を使う反応器計算について、微分評価と segment ループを Numba で実行する。

高速経路は固定順序の配列を使う。

```text
EB, H2O, SM, H2, BZ, TL, CO2, C2H4, CH4, CO, temperature, pressure
```

カスタム反応ネットワーク、カスタム物性、カスタム普遍定数を使う場合は、従来の Python 経路へ自動的に戻る。

## 既存仕様を維持する理由

既存の Python 経路は削除しない。`src/process_sim/reactor/core/config.py` の設定だけで高速経路を無効化できる。

profile、出口状態、ログの型は変更しない。高速積分後に既存の明示的なモデルへ変換する。

Numba には pyright 用 stub がないため、Numba 固有の型チェック抑制は `numba_reactor.py` 内だけに限定する。高速積分の公開結果は Python の `list` に変換し、NumPy 配列型を通常経路へ漏らさない。

## 比較結果

既定ケースと既定の積分分割数で、通常経路と Numba 高速経路を比較した。Numba の初回コンパイル時間は warmup として分離した。

| 反応器 | 通常経路 | Numba 高速経路 | 高速化倍率 |
|---|---:|---:|---|
| axial PFR | 8.872 s | 0.097 s | 91.46 倍 |
| radial | 6.675 s | 0.066 s | 101.87 倍 |

出口圧力、出口温度、EB 転化率、SM 選択率、元素収支誤差は通常経路と Numba 数値演算経路で一致した。

## 判断

RK4 更新式だけの Numba 化では、実用的な高速化は得られなかった。

反応速度、熱収支、圧力損失を含む微分評価を固定順序の配列ベース関数へ分離し、RK4 segment ループと合わせてコンパイルする高速経路を採用する。

## 未確定事項

- Pareto runner の実運用時間を確認する。
