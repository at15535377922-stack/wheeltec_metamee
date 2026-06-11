#!/usr/bin/env python
# -*- coding: utf-8 -*-
import rospy
import json
import yaml
import os
import threading
import time
from flask import Flask, render_template, request, jsonify
from nav_manager import get_default_manager
import websocket
import signal
import logging
import datetime
from logging.handlers import RotatingFileHandler

WAYPOINT_DIR = os.path.dirname(os.path.abspath(__file__))


# 配置日志
def setup_logger():
    # 创建logs目录
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # 配置根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
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


# 初始化日志
setup_logger()
logger = logging.getLogger(__name__)


def signal_handler(signum, frame):
    print("收到信号 %d，准备强制退出..." % signum)
    os.kill(os.getpid(), signal.SIGKILL)


# 捕获 SIGTERM 和 SIGINT 信号
# 引入rospy.Publisher之后就无效了
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

app = Flask(__name__)


def load_waypoints():
    try:
        waypoint_path = os.path.join(WAYPOINT_DIR, "waypoints.json")
        if not os.path.exists(waypoint_path):
            return []
        with open(waypoint_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error("加载配置文件失败: %s", str(e))
        return []


@app.route("/api/goal/<goal_id>", methods=["POST"])
def goto_goal(goal_id):
    waypoint_list = load_waypoints()
    for item in waypoint_list:
        name = item.get("name", "") or item.get("label", "")
        if name == goal_id:
            get_default_manager().navigate_to_goal(
                item.get("x"), item.get("y"), item.get("theta")
            )
            return "导航成功"
    return "导航失败，未找到导航点"


@app.route("/api/goal/list", methods=["GET"])
def list_goal():
    return load_waypoints()


@app.route("/api/stop", methods=["POST"])
def stop_navigation():
    get_default_manager().cancel_navigation()
    return "停止成功"


def main():
    try:
        # 启动Flask应用
        logger.info("Starting Flask application on port 8082...")
        app.run(host="0.0.0.0", port=8082, threaded=True)
    except Exception as e:
        logger.error("Failed to start Flask application: {0}".format(str(e)))
    except rospy.ROSInterruptException:
        logger.info("ROS node interrupted")
    finally:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
