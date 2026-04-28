# プロセス設計

エチルベンゼンの脱水素によるスチレンモノマー製造プロセス

エチルベンゼン(EB), スチレン(SM), ベンゼン(BZ), トルエン(TL)とする。

## 1\. 設定条件\[1\]

1.1 設定目標  
純度99.8 mol％以上スチレンモノマー200,000 ton/year  
参考：昨年度(2025年度)のスチレンモノマー国内生産量1,332,046 ton/year\[2\]  
→国内生産量の約15 %を目標値として設定した。

1.2 原料条件  
	原料組成：EB 99.5 mol%, B 0.5 mol%, 温度 30℃, 圧力 101.3 kPa  
	EBとの希釈・反応水：H2O 100 mol%, 温度 30℃, 圧力 300kPa 

1.3 製品条件  
	SM 99.8 mol%以上, 圧力 101.3 kPa, 温度 38℃  
	BZ 99.5 mol%以上, 圧力 101.3 kPa, 温度 38℃  
	TL 99.0 mol%以上, 圧力 101.3 kPa, 温度 38℃  
	燃焼ガス(H2, CO2等) 圧力 400.0 kPa, 温度 38℃

1.4 稼働時間  
年間8000時間

## 

## 

## 2\. 粗利計算

市場価格

1) 原料

EB\[3\]：198.63  円/kg (8525.00  元/ton)  
H2O\[1\]：5 円/kg

2) 製品

SM\[4\]：232.231 円/kg (9967.00 元/ton)  
BZ\[5\]：149.269 円/kg (6406.38 元/ton)  
TL\[6\]：184.07 円/kg (7900.00 元/ton)  
(23.3 円/元, 元価格は2026/4/1 \- 2026/4/20の平均)

| 項目 | 計算内容 | 金額 \[億円/year\] |
| :---- | :---- | :---- |
| 売上高 (SM) | 200,000 ton × 232.231 円/kg | 464.46 |
| 原料費 (EB) | 204,884 ton × 198.63 円/kg | 406.96 |
| 原料費 (H2O) | 3460 ton × 5 円/kg (補給率10%仮定) | 0.17 |
| 原料費合計 |  | 407.13 |
| 年間粗利益 | 売上高 \- 原料費合計 | 57.33 |

※収率100%（EB \-\> SMのみ）とし、水は10%補給（リサイクル率90%）と仮定

## 3\. 物性値\[7\]

[プロセス設計 物性値.pdf](https://drive.google.com/file/d/1S60ZmQY6wL0IAEMfg5YwHqpng0_e8eg4/view?usp=drive_link)  
[プロセス設計 物性値.docx](https://docs.google.com/document/d/1zdL6ooX-R5r5m4-_muHrrBuFoWZtsKXv/edit?usp=drive_link&ouid=106005778602105613204&rtpof=true&sd=true)

## 4\. 反応器

　4.1. 反応式  
反応1		C6H5\-CH2CH3 (EB) ⇄ C6H5\-CH=CH2 (SM) \+ H2  
反応2		C6H5\-CH2CH3 (EB) → C6H6 (BZ) \+ C2H4  
反応3		C6H5\-CH2CH3 (EB) \+ H2 → C6H5\-CH3 (TL) \+ CH4  
反応4		2H2O \+ C2H4 → 2CO \+ 4H2  
反応5		H2O \+ CH4 → CO \+ 3H2  
反応6		H2O \+ CO → CO2 \+ H2

入口条件 feed  
\- 総流量: 3635.58 kmol/h  
\- 入口 EB: 605.90 kmol/h  
\- 入口 Steam: 3029.50 kmol/h  
\- 入口 Styrene: 0.06 kmol/h  
\- 入口 Hydrogen: 0.00 kmol/h  
\- 入口 Benzene: 0.06 kmol/h  
\- 入口 Toluene: 0.06 kmol/h  
\- 入口 CO2: 0.00 kmol/h

全体サマリー  
\- 出口温度: 568.91 degC  
\- 圧力: 101.325 kPa  
\- EB転化率: 53.91 %  
\- スチレン選択率: 88.24 %  
\- 反応器断面積: 35.1461 m2  
\- 第1段入口体積流量: 67.8319 m3/s

出口流量  
\- 総流量: 4024.01 kmol/h  
\- 出口 EB: 279.24 kmol/h  
\- 出口 Steam: 2929.31 kmol/h  
\- 出口 Styrene: 288.30 kmol/h  
\- 出口 Hydrogen: 438.52 kmol/h  
\- 出口 Benzene: 11.73 kmol/h  
\- 出口 Toluene: 26.82 kmol/h  
\- 出口 CO2: 50.09 kmol/h

## 5\. 分離器

\- feedを上でデカンター(三相分離器)で分ける  
(終われば適当にプロセスをパクって作ってみる)

## 6\. 最適化(?)

調整できそうなパラメータをまとめたい

\- 三相分離器に入れる手前の温度

## 参考文献

\[1\] 化学工学会. 第7回学生コンテスト(SCEJ第40回秋季大会). 2008\.   
[https://altair.chem-eng.kyushu-u.ac.jp/scej\_contest2008/contest2008\_process\_rev2.pdf](https://altair.chem-eng.kyushu-u.ac.jp/scej_contest2008/contest2008_process_rev2.pdf)

\[2\] 日本スチレン工業会. 2025年(令和7年)スチレンモノマー生産出荷実績表 . 2026\.  
[https://www.jsia.jp/data/images/monthly/2025/12/SM.pdf](https://www.jsia.jp/data/images/monthly/2025/12/SM.pdf) 

\[3\] (エチルベンゼン)乙苯价格. Chemical Book.  
[https://m.chemicalbook.com/priceindex\_cb4672779.htm](https://m.chemicalbook.com/priceindex_cb4672779.htm)

\[4\] (スチレン)苯乙烯价格. Chemical Book.  
[https://m.chemicalbook.com/priceindex\_cb3415111.htm](https://m.chemicalbook.com/priceindex_cb3415111.htm)

\[5\] (ベンゼン)纯苯价格. Chemical Book.  
[https://m.chemicalbook.com/priceindex\_cb6854153.htm](https://m.chemicalbook.com/priceindex_cb6854153.htm)

\[6\] (トルエン)甲苯价格. Chemical Book.  
[https://m.chemicalbook.com/priceindex\_cb4233905.htm](https://m.chemicalbook.com/priceindex_cb4233905.htm)

\[7\] 日本化学会編. 化学便覧 基礎編 改訂6 版. 丸善, 2021\.   
