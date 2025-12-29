#!/usr/bin/env python3
"""Rich を使用した進捗表示モジュール

TTY 環境では Rich による視覚的な進捗表示を行い、
非 TTY 環境（CI/CD パイプラインなど）では logging にフォールバックします。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import rich.console
import rich.live
import rich.progress
import rich.table
import rich.text

# ステータスバーの色定義（メルカリレッド）
STATUS_STYLE_NORMAL = "bold #FFFFFF on #E72121"
STATUS_STYLE_ERROR = "bold white on red"

# プログレスバーのラベル
PROGRESS_ITEM = "アイテム処理"


class _DisplayRenderable:
    """Live 表示用の動的 renderable クラス"""

    def __init__(self, display: ProgressDisplay) -> None:
        self._display = display

    def __rich__(self) -> Any:
        """Rich が描画時に呼び出すメソッド"""
        return self._display._create_display()


@dataclass
class ProgressDisplay:
    """Rich による進捗表示を管理するクラス

    ProgressObserver Protocol を実装し、iter_items_on_display に渡して使用します。

    Examples:
        progress = ProgressDisplay()
        progress.start()
        try:
            progress.set_status("ログイン中...")
            my_lib.store.mercari.login.execute(...)

            progress.set_status("アイテム処理中...")
            my_lib.store.mercari.scrape.iter_items_on_display(
                driver, wait, debug_mode, [handler], progress_observer=progress
            )

            progress.set_status("完了")
        finally:
            progress.stop()

    """

    # Rich 関連
    _console: rich.console.Console = field(default_factory=rich.console.Console)
    _progress: rich.progress.Progress | None = field(default=None, repr=False)
    _live: rich.live.Live | None = field(default=None, repr=False)
    _start_time: float = field(default_factory=time.time)
    _status_text: str = ""
    _status_is_error: bool = False
    _display_renderable: _DisplayRenderable | None = field(default=None, repr=False)
    _item_task_id: rich.progress.TaskID | None = field(default=None, repr=False)

    @property
    def is_terminal(self) -> bool:
        """TTY 環境かどうかを返す"""
        return self._console.is_terminal

    def start(self) -> None:
        """進捗表示を開始する"""
        if not self._console.is_terminal:
            return

        self._progress = rich.progress.Progress(
            rich.progress.TextColumn("[bold]{task.description:<20}"),
            rich.progress.BarColumn(bar_width=None),
            rich.progress.TaskProgressColumn(),
            rich.progress.TextColumn("{task.completed:>3} / {task.total:<3}"),
            rich.progress.TimeElapsedColumn(),
            console=self._console,
            expand=True,
        )
        self._start_time = time.time()
        self._display_renderable = _DisplayRenderable(self)
        self._live = rich.live.Live(
            self._display_renderable,
            console=self._console,
            refresh_per_second=4,
        )
        self._live.start()

    def stop(self) -> None:
        """進捗表示を停止する"""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def set_status(self, status: str, is_error: bool = False) -> None:
        """ステータスを更新する

        Args:
            status: 表示するステータステキスト
            is_error: エラー状態かどうか（True の場合は赤色で表示）

        """
        self._status_text = status
        self._status_is_error = is_error

        # 非 TTY 環境では logging で出力
        if not self._console.is_terminal:
            if is_error:
                logging.error(status)
            else:
                logging.info(status)
            return

        self._refresh_display()

    def _create_status_bar(self) -> rich.table.Table:
        """ステータスバーを作成（左: タイトル、中央: 進捗、右: 時間）"""
        style = STATUS_STYLE_ERROR if self._status_is_error else STATUS_STYLE_NORMAL
        elapsed = time.time() - self._start_time
        elapsed_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"

        table = rich.table.Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=0,
            expand=True,
            style=style,
        )
        table.add_column("title", justify="left", ratio=1, no_wrap=True, style=style)
        table.add_column("status", justify="center", ratio=3, no_wrap=True, style=style)
        table.add_column("time", justify="right", ratio=1, no_wrap=True, style=style)

        table.add_row(
            rich.text.Text(" メルカリ ", style=style),
            rich.text.Text(self._status_text, style=style),
            rich.text.Text(f" {elapsed_str} ", style=style),
        )

        return table

    def _create_display(self) -> Any:
        """表示内容を作成"""
        status_bar = self._create_status_bar()
        if self._progress is not None and len(self._progress.tasks) > 0:
            return rich.console.Group(status_bar, self._progress)
        return status_bar

    def _refresh_display(self) -> None:
        """表示を強制的に再描画"""
        if self._live is not None:
            self._live.refresh()

    # --- ProgressObserver Protocol の実装 ---
    def on_total_count(self, count: int) -> None:
        """アイテム総数が判明したときに呼ばれる"""
        if self._progress is None:
            return

        self._item_task_id = self._progress.add_task(PROGRESS_ITEM, total=count)
        self._refresh_display()

    def on_item_start(self, index: int, total: int, item: dict[str, Any]) -> None:
        """各アイテムの処理開始時に呼ばれる"""
        name = item.get("name", "不明")
        # 名前が長い場合は省略
        if len(name) > 20:
            name = name[:17] + "..."
        self.set_status(f"処理中: {name}")

    def on_item_complete(self, index: int, total: int, item: dict[str, Any]) -> None:
        """各アイテムの処理完了時に呼ばれる"""
        if self._progress is not None and self._item_task_id is not None:
            self._progress.update(self._item_task_id, advance=1)
            self._refresh_display()


def create_progress_display() -> ProgressDisplay:
    """ProgressDisplay インスタンスを作成する

    Returns:
        ProgressDisplay インスタンス

    """
    return ProgressDisplay()
