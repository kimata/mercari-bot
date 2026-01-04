#!/usr/bin/env python3
"""
静的型チェックテスト

mypy を使用してソースコードの型チェックを実行します。
"""
# ruff: noqa: S603

import subprocess
import sys


def test_mypy_src() -> None:
    """src ディレクトリの型チェック"""
    result = subprocess.run(
        [sys.executable, "-m", "mypy"],
        capture_output=True,
        text=True,
    )

    # エラーメッセージを表示（デバッグ用）
    if result.returncode != 0:
        print("mypy stdout:")
        print(result.stdout)
        print("mypy stderr:")
        print(result.stderr)

    assert result.returncode == 0, f"mypy found type errors:\n{result.stdout}"
