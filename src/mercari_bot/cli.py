#!/usr/bin/env python3
"""
メルカリに出品中のアイテムの価格を自動的に値下げします。

Usage:
  mercari-bot [-c CONFIG] [-l] [-D] [-R]

Options:
  -c CONFIG         : CONFIG を設定ファイルとして読み込んで実行します。 [default: config.yaml]
  -l                : 動作ログを Slack やメールで通知します。
  -D                : デバッグモードで動作します。(価格変更は行いません)
  -R                : ブラウザ起動失敗時にプロファイルを削除します。
"""

from __future__ import annotations

import io
import logging
import pathlib
import sys

import docopt
import my_lib.logger
import my_lib.notify.mail
import my_lib.notify.slack

import mercari_bot.config
import mercari_bot.mercari_price_down
import mercari_bot.progress
from mercari_bot.config import AppConfig

# NOTE: CWD に依存せず、リポジトリルート基準でスキーマを解決する
_SCHEMA_CONFIG = pathlib.Path(__file__).parents[2] / "schema" / "config.schema"


def execute(
    config: AppConfig,
    notify_log: bool,
    debug_mode: bool,
    log_str_io: io.StringIO | None,
    clear_profile_on_browser_error: bool = False,
) -> int:
    failed_count = 0

    logging.info("Start")

    # 設定内容をログ出力
    mercari_bot.config.log_config_summary(config)

    progress = mercari_bot.progress.create_progress_display()
    progress.start()

    try:
        for profile in config.profile:
            success = mercari_bot.mercari_price_down.execute(
                config,
                profile,
                debug_mode,
                progress=progress,
                clear_profile_on_browser_error=clear_profile_on_browser_error,
            )
            if not success:
                failed_count += 1

        if failed_count == 0:
            progress.set_status("🎉  全プロファイル完了")
        else:
            progress.set_status(
                f"⚠️  {failed_count}/{len(config.profile)} プロファイルでエラーが発生しました",
                is_error=True,
            )
    finally:
        progress.stop()

    logging.info(
        "%d/%d プロファイル成功",
        len(config.profile) - failed_count,
        len(config.profile),
    )
    logging.info("Finish!")

    if notify_log and log_str_io is not None:
        my_lib.notify.mail.send(
            config.mail,
            "<br />".join(log_str_io.getvalue().splitlines()),
        )
        my_lib.notify.slack.info(
            config.slack,
            "Mercari price change",
            log_str_io.getvalue(),
        )

    return 1 if failed_count else 0


def main() -> None:
    """CLI エントリポイント"""
    if __doc__ is None:
        raise RuntimeError("__doc__ is not set")
    args = docopt.docopt(__doc__)

    config_file = args["-c"]
    notify_log = args["-l"]
    debug_mode = args["-D"]
    clear_profile_on_browser_error = args["-R"]

    log_level = logging.DEBUG if debug_mode else logging.INFO

    # TTY環境ではシンプルなログフォーマットを使用（Rich の表示と干渉しないため）
    log_format = my_lib.logger.SIMPLE_FORMAT if sys.stdout.isatty() else None

    log_str_io = my_lib.logger.init(
        "bot.mercari.inventory", level=log_level, is_str_log=True, log_format=log_format
    )

    config = mercari_bot.config.load(config_file, _SCHEMA_CONFIG)

    ret_code = execute(config, notify_log, debug_mode, log_str_io, clear_profile_on_browser_error)

    logging.info("Finish.")

    sys.exit(ret_code)


if __name__ == "__main__":
    main()
