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

import logging
import pathlib
import sys

import my_lib.notify.mail
import my_lib.notify.slack

import mercari_bot.mercari_price_down

SCHEMA_CONFIG = "config.schema"


def execute(config, notify_log, debug_mode, log_str_io):
    ret_code = 0

    logging.info("Start")

    for profile in config["profile"]:
        ret_code += mercari_bot.mercari_price_down.execute(
            config,
            profile,
            pathlib.Path(config["data"]["selenium"]),
            pathlib.Path(config["data"]["dump"]),
            debug_mode,
        )

    logging.info("Finish!")

    if notify_log:
        if "mail" in config:
            my_lib.notify.mail.send(config["mail"], "<br />".join(log_str_io.getvalue().splitlines()))
        if "slack" in config:
            my_lib.notify.slack.info(
                config["slack"]["bot_token"],
                config["slack"]["info"]["channel"]["name"],
                "Mercari price change",
                log_str_io.getvalue(),
            )

    return ret_code


######################################################################
if __name__ == "__main__":
    import docopt
    import my_lib.config
    import my_lib.logger

    args = docopt.docopt(__doc__)

    config_file = args["-c"]
    notify_log = args["-l"]
    debug_mode = args["-D"]

    log_level = logging.DEBUG if debug_mode else logging.INFO

    log_str_io = my_lib.logger.init("bot.mercari.inventory", level=log_level, is_str_log=True)

    config = my_lib.config.load(config_file, pathlib.Path(SCHEMA_CONFIG))

    ret_code = execute(config, notify_log, debug_mode, log_str_io)

    logging.info("Finish.")

    sys.exit(ret_code)
