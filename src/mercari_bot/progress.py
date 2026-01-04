#!/usr/bin/env python3
"""Rich を使用した進捗表示モジュール

TTY 環境では Rich による視覚的な進捗表示を行い、
非 TTY 環境（CI/CD パイプラインなど）では logging にフォールバックします。
Null Object パターンを使用して TTY 分岐をシンプルにしています。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, ClassVar

import rich.console
import rich.live
import rich.progress
import rich.table
import rich.text

# ステータスバーの色定義（メルカリレッド）
_STATUS_STYLE_NORMAL = "bold #FFFFFF on #E72121"
_STATUS_STYLE_ERROR = "bold white on red"

# プログレスバーのラベル
_PROGRESS_ITEM = "アイテム処理"


class _NullProgress:
    """非TTY環境用の何もしない Progress（Null Object パターン）"""

    tasks: ClassVar[list[rich.progress.Task]] = []

    def add_task(self, description: str, total: float | None = None) -> rich.progress.TaskID:
        return rich.progress.TaskID(0)

    def update(self, task_id: rich.progress.TaskID, advance: float = 1) -> None:
        pass

    def __rich__(self) -> rich.text.Text:
        """Rich プロトコル対応（空のテキストを返す）"""
        return rich.text.Text("")


class _NullLive:
    """非TTY環境用の何もしない Live（Null Object パターン）"""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def refresh(self) -> None:
        pass


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
    Null Object パターンにより、TTY/非TTY の分岐を各メソッド内で行わずに済みます。

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
    _progress: rich.progress.Progress | _NullProgress = field(default_factory=_NullProgress, repr=False)
    _live: rich.live.Live | _NullLive = field(default_factory=_NullLive, repr=False)
    _start_time: float = field(default_factory=time.time)
    _status_text: str = ""
    _status_is_error: bool = False
    _display_renderable: _DisplayRenderable | None = field(default=None, repr=False)
    _item_task_id: rich.progress.TaskID = field(default=rich.progress.TaskID(0), repr=False)

    @property
    def is_terminal(self) -> bool:
        """TTY 環境かどうかを返す"""
        return self._console.is_terminal

    def start(self) -> None:
        """進捗表示を開始する"""
        self._start_time = time.time()

        # 非TTY環境では Null Object を使用（デフォルト値のまま）
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
        self._display_renderable = _DisplayRenderable(self)
        self._live = rich.live.Live(
            self._display_renderable,
            console=self._console,
            refresh_per_second=4,
        )
        self._live.start()

    def stop(self) -> None:
        """進捗表示を停止する（Null Object の場合は何もしない）"""
        self._live.stop()
        self._live = _NullLive()

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
        style = _STATUS_STYLE_ERROR if self._status_is_error else _STATUS_STYLE_NORMAL
        elapsed = time.time() - self._start_time
        elapsed_str = f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d}"

        # ターミナル幅を取得し、明示的に幅を制限
        # NOTE: tmux 環境では幅計算が実際と異なることがあるため、余裕を持たせる
        terminal_width = self._console.width
        if os.environ.get("TMUX"):
            terminal_width -= 2

        table = rich.table.Table(
            show_header=False,
            show_edge=False,
            box=None,
            padding=0,
            expand=True,
            width=terminal_width,
            style=style,
        )
        # 左右のカラムに min_width を設定して幅を安定させる
        table.add_column(
            "title", justify="left", ratio=1, min_width=12, no_wrap=True, overflow="ellipsis", style=style
        )
        table.add_column("status", justify="center", ratio=3, no_wrap=True, overflow="ellipsis", style=style)
        table.add_column(
            "time", justify="right", ratio=1, min_width=8, no_wrap=True, overflow="ellipsis", style=style
        )

        table.add_row(
            rich.text.Text(" メルカリ ", style=style),
            rich.text.Text(self._status_text, style=style),
            rich.text.Text(f" {elapsed_str}  ", style=style),  # 末尾にスペース追加で -1 を補正
        )

        return table

    def _create_display(self) -> Any:
        """表示内容を作成"""
        status_bar = self._create_status_bar()
        # NullProgress の場合 tasks は常に空なのでこの条件で十分
        if len(self._progress.tasks) > 0:
            return rich.console.Group(status_bar, self._progress)
        return status_bar

    def _refresh_display(self) -> None:
        """表示を強制的に再描画（Null Object の場合は何もしない）"""
        self._live.refresh()

    def _get_max_item_name_length(self) -> int:
        """ステータスバーに表示可能な商品名の最大長を計算する"""
        # ターミナル幅を取得
        terminal_width = self._console.width

        # ステータスバーは ratio 1:3:1 で分割
        # 中央（ステータス）は全体の 3/5
        status_width = (terminal_width * 3) // 5

        # プレフィックス「🏷️ 処理中: 」の分を引く（絵文字は2文字分として計算）
        prefix_length = len("🏷️ 処理中: ") + 1  # 絵文字の表示幅補正

        return max(status_width - prefix_length, 10)

    def _truncate_name(self, name: str, max_length: int) -> str:
        """商品名を指定した長さに省略する"""
        if len(name) <= max_length:
            return name
        return name[: max_length - 3] + "..."

    # --- ProgressObserver Protocol の実装 ---
    def on_total_count(self, count: int) -> None:
        """アイテム総数が判明したときに呼ばれる（Null Object の場合は何もしない）"""
        self._item_task_id = self._progress.add_task(_PROGRESS_ITEM, total=count)
        self._refresh_display()

    def on_item_start(self, index: int, total: int, item: dict[str, Any]) -> None:
        """各アイテムの処理開始時に呼ばれる"""
        name = item.get("name", "不明")
        max_length = self._get_max_item_name_length()
        name = self._truncate_name(name, max_length)
        self.set_status(f"🏷️ 処理中: {name}")

    def on_item_complete(self, index: int, total: int, item: dict[str, Any]) -> None:
        """各アイテムの処理完了時に呼ばれる（Null Object の場合は何もしない）"""
        self._progress.update(self._item_task_id, advance=1)
        self._refresh_display()


def create_progress_display() -> ProgressDisplay:
    """ProgressDisplay インスタンスを作成する

    Returns:
        ProgressDisplay インスタンス

    """
    return ProgressDisplay()
