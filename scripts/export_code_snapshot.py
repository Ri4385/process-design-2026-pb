"""src と scripts の Python コードを1つのテキストにまとめる。"""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_OUTPUT_PATH = Path("data/code_snapshot/source_snapshot.txt")
SRC_OUTPUT_PATH = Path("data/code_snapshot/src_snapshot.txt")
SOURCE_ROOTS = (Path("src"), Path("scripts"))
SRC_ROOTS = (Path("src"),)
EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv"}


def parse_args() -> argparse.Namespace:
    """CLI 引数を読む。"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="出力先テキストファイル",
    )
    return parser.parse_args()


def iter_python_files(root: Path) -> list[Path]:
    """指定 root 配下の Python ファイルを相対パス順で返す。"""
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.as_posix())


def collect_source_files(roots: tuple[Path, ...] = SOURCE_ROOTS) -> list[Path]:
    """対象 root 群から snapshot 対象ファイルを集める。"""
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(iter_python_files(root))
    return sorted(files, key=lambda path: path.as_posix())


def render_file(path: Path) -> str:
    """1ファイル分を Markdown 風のコードブロックとして返す。"""
    relative_path = path.as_posix()
    content = path.read_text(encoding="utf-8")
    return f"{relative_path}\n```python\n{content.rstrip()}\n```\n"


def build_snapshot(files: list[Path]) -> str:
    """複数ファイルを1つの snapshot 文字列にまとめる。"""
    return "\n".join(render_file(path) for path in files)


def write_snapshot(output_path: Path, roots: tuple[Path, ...]) -> None:
    """指定 root 群のコード snapshot を生成する。"""
    files = collect_source_files(roots=roots)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_snapshot(files), encoding="utf-8")
    print(f"wrote {len(files)} files to {output_path.as_posix()}")


def write_src_snapshot(output_path: Path = SRC_OUTPUT_PATH) -> None:
    """src の Python コードだけを snapshot として生成する。"""
    write_snapshot(output_path=output_path, roots=SRC_ROOTS)


def main() -> None:
    """コード snapshot を生成する。"""
    args = parse_args()
    write_snapshot(output_path=args.output, roots=SOURCE_ROOTS)
    write_src_snapshot()


if __name__ == "__main__":
    main()
