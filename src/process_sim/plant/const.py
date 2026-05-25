"""Plant-level constants shared by runner, feed tuning, and convergence."""

from __future__ import annotations

from pathlib import Path


DEFAULT_HYSYS_CASE_PATH = Path("data/hysys/process_design_0525v1.hsc")  # 既定の HYSYS case path
DEFAULT_HYSYS_RUN_TIMEOUT_SECONDS = 120.0  # HYSYS 実行 timeout 秒
HOURS_PER_YEAR = 8000.0  # 年間稼働時間 h/year

DEFAULT_TARGET_SM_KMOL_H = 240.033  # 目標 SM product total 流量 kmol/h
DEFAULT_SM_PRODUCT_STYRENE_MOL_FRACTION = 0.998  # SM product の Styrene mol 分率

DEFAULT_SM_MARGIN_TOLERANCE_KMOL_H = 0.1  # SM product 目標超過側の許容幅 kmol/h
DEFAULT_EB_RECYCLE_TOLERANCE_KMOL_H = 0.1  # EB recycle 自己一致許容幅 kmol/h
DEFAULT_H2O_RECYCLE_TOLERANCE_KMOL_H = 0.1  # H2O recycle 自己一致許容幅 kmol/h
DEFAULT_PLANT_CONVERGENCE_MAX_ITERATIONS = 10  # plant recycle 収束計算の最大 iteration 数

FLOAT_ABS_TOLERANCE = 1e-9  # 浮動小数点数比較用の絶対許容幅
HYSYS_INVALID_SENTINEL = -32767.0  # HYSYS が返す異常値 sentinel
