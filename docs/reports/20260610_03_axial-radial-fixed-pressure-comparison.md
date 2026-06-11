# Axial/Radial 固定条件圧力損失比較 script

## 背景

`scripts/axial-radial-comparison/` には既存の圧力プロファイル比較 script があるが、入口 stream に微量生成物が含まれており、図の表示もスライド掲載には情報が多い。1段反応器、固定触媒体積、Steam/EB 比 5.0 の条件で axial と radial の圧損を比較する専用 script を追加する。

## 作成ファイル

```text
scripts/
  axial-radial-comparison/
    compare_fixed_1stage_pressure_drop.py  # 1段 axial/radial 固定条件圧損比較
    media/
      pressure_profile_axial_vs_radial_fixed_1stage.png  # script 実行時の出力先
```

## 比較条件

- 反応器段数は 1 段とする。
- EB 入口流量は `400.0 kmol/h` とする。
- Steam/EB モル比は `5.0` に固定し、steam 入口流量は `2000.0 kmol/h` とする。
- 入口 stream は EB と steam のみで定義する。
- 入口温度は `600 ℃` とする。
- 入口圧力は `101.3 kPa abs` とする。
- 触媒体積は `56.0 m3` とする。
- 触媒粒径は `3 mm`、空隙率は `0.431` とする。
- Ergun 係数は既存 script と同じ `a=1.75`, `b=150.0` とする。
- ガス粘度は既存比較 script と同じ `4.0e-5 Pa s` とする。
- 触媒 bulk density は既存 script と同じ `1422.0 kg/m3` とする。

## 幾何条件

Radial flow 反応器は、内側半径 `1.0 m`、高さ `6.0 m` を固定し、触媒体積 `56.0 m3` を満たすように触媒層厚みを逆算する。

Axial flow 反応器は、入口空塔速度 `2.0 m/s` を満たすように断面積と直径を決め、触媒体積 `56.0 m3` を満たすように長さを決める。

## 図の方針

- `japanize_matplotlib` を使用し、日本語軸ラベルを使う。
- x 軸は `累積触媒体積 / m3` とする。
- y 軸は `圧力 / kPa` とする。
- 凡例は `Axial flow` と `Radial flow` のみとし、圧損値は入れない。
- 凡例、軸ラベル、目盛文字はスライド掲載を想定して既存比較 script より大きくする。
- 図中注記は置かず、圧損値、出口圧、転化率、選択率は標準出力の summary に出す。

## 採用理由

入口 stream を script 内で `EB=400.0 kmol/h`, `Steam/EB=5.0` と明示することで、比較条件を図や標準出力から追いやすくする。圧損比較図では線の差を読むことを優先し、圧損値や転化率を図中に入れない。

## 未確認点

- この script は HYSYS を使用しない Python 反応器モデルの比較である。
- 本作業時点では script の実行確認は行っていない。
