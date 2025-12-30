#!/usr/bin/env python3
"""
メルカリに出品中のアイテムの価格を自動的に値下げします。

Usage:
  app.py [-c CONFIG] [-l] [-D]

Options:
  -c CONFIG         : CONFIG を設定ファイルとして読み込んで実行します。 [default: config.yaml]
  -l                : 動作ログを Slack やメールで通知します。
  -D                : デバッグモードで動作します。(価格変更は行いません)
"""

from __future__ import annotations

import io
import logging
import pathlib
import sys

import my_lib.notify.mail
import my_lib.notify.slack

import mercari_bot.mercari_price_down
import mercari_bot.progress
from mercari_bot.config import AppConfig

SCHEMA_CONFIG = "schema/config.schema"


def execute(config: AppConfig, notify_log: bool, debug_mode: bool, log_str_io: io.StringIO | None) -> int:
    ret_code = 0

    logging.info("Start")

    progress = mercari_bot.progress.create_progress_display()
    progress.start()

    try:
        for profile in config.profile:
            ret_code += mercari_bot.mercari_price_down.execute(
                config,
                profile,
                pathlib.Path(config.data.selenium),
                pathlib.Path(config.data.dump),
                debug_mode,
                progress=progress,
            )

        progress.set_status("🎉 全プロファイル完了")
    finally:
        progress.stop()

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

    return ret_code


######################################################################
if __name__ == "__main__":
    import docopt

    import my_lib.logger

    import mercari_bot.config

    assert __doc__ is not None
    args = docopt.docopt(__doc__)

    config_file = args["-c"]
    notify_log = args["-l"]
    debug_mode = args["-D"]

    log_level = logging.DEBUG if debug_mode else logging.INFO

    # TTY環境ではシンプルなログフォーマットを使用（Rich の表示と干渉しないため）
    log_format = my_lib.logger.SIMPLE_FORMAT if sys.stdout.isatty() else None

    log_str_io = my_lib.logger.init(
        "bot.mercari.inventory", level=log_level, is_str_log=True, log_format=log_format
    )

    config = mercari_bot.config.load(config_file, SCHEMA_CONFIG)

    ret_code = execute(config, notify_log, debug_mode, log_str_io)

    logging.info("Finish.")

    sys.exit(ret_code)
