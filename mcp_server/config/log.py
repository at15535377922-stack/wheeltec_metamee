import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from config.config import load_config


def setup_logger():
    # 创建logs目录
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # 配置根日志记录器
    logger = logging.getLogger()
    logger.setLevel(load_config().logger.level)

    # 创建控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(load_config().logger.level)
    console_format = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_format)

    # 创建文件处理器 - 按日期和大小滚动
    log_file = os.path.join(
        "logs", "app_{}.log".format(datetime.datetime.now().strftime("%Y%m%d"))
    )
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s"
    )
    file_handler.setFormatter(file_format)

    # 添加处理器到日志记录器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger
