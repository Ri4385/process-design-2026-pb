# Project Context for AI Agents

## Project Overview
京大プロセス設計課題: PFR反応器(Python)と蒸留塔(HYSYS)を組み合わせたプロセスシミュレーション。

## Tech Stack
- Package Manager: `uv`
- Architecture: `src-layout`
- Configuration: `Pydantic v2`
- Optimization: `Optuna`
- Integration: `pywin32` (COM interface for HYSYS)

## Critical Rules (Strictly Enforce)
1. **Type Safety**: 
   - 全ての関数に型ヒントを付ける。
   - `TypedDict` は禁止。`pydantic.BaseModel` を使用。
2. **Path Handling**:
   - `pathlib.Path` を使用し、文字列の結合や `os.path` は避ける。
   - Windows環境だが、コード内は `/` を使用。
3. **Module Responsibility**:
   - `src/process_sim/reactor/`: 反応器の物理モデル。
   - `src/process_sim/separator.py`: HYSYS操作の隠蔽化。
   - `src/process_sim/flowsheet.py`: プロセス全体の接続。
   - `scripts/`: 実行および最適化スクリプト。
4. **HYSYS Interaction**:
   - COMオブジェクトを直接返さない。必ず Python の `MaterialStream` クラス等に変換して返す。

## Expected File Structure
下記のような構ディレクトリ構造を予定しています。
├── src/
│   └── process_sim/         # Core package
│       ├── reactor/         # PFR logic (kinetics.py, solver.py, etc.)
│       ├── separator.py     # HYSYS COM Wrapper
│       ├── constants/       # Physical constants (frozen dataclass)
│       ├── config.py        # Pydantic models for simulation parameters
│       ├── models/          # Common data structures (MaterialStream, etc.)
│       └── simulator.py     # Process integration logic
├── scripts/                 # Execution scripts (Entry points)
├── docs/                    # Technical documentation
└── models/                  # HYSYS case files (.hsc)