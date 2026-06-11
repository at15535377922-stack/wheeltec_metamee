#!/usr/bin/env python
# -*- coding: utf-8 -*-
import rospy
import json
import yaml
import os
import io
import threading
from flask import Flask, render_template, request, jsonify
from nav_manager import get_default_manager
import traceback
from rorate import get_steering_odom_node
import websocket
import signal
import logging
import datetime
from logging.handlers import RotatingFileHandler
from simple_websocket_server import WebSocketServer, WebSocket

WS_PORT = 8083

WAYPOINT_DIR = "map"


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
        with io.open(waypoint_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("加载配置文件失败: %s", str(e))
        return []


def handle_ws_method(method, args):
    logger.info("%s,%s", method, args)
    if method == "list":
        waypoints = load_waypoints()
        names = [item.get("name") for item in waypoints]
        return True, str(names)
    elif method == "stop":
        get_default_manager().cancel_navigation()
        return True, u"停止成功"
    elif method == "goto":
        args = json.loads(args)
        goal_id = args.get("name", u"") or args.get("goal", u"")
        # ✅ 统一转换为 unicode 再比较，避免 ascii 编码错误
        if not isinstance(goal_id, unicode):
            goal_id = goal_id.decode("utf-8")
        for item in load_waypoints():
            name = item.get("name", u"") or item.get("label", u"")
            if not isinstance(name, unicode):
                name = name.decode("utf-8")
            if name == goal_id:
                get_default_manager().navigate_to_goal(
                    item.get("x"), item.get("y"), item.get("theta")
                )
                return True, u"导航成功"
        return False, u"导航失败，未找到导航点"
    else:
        return False, u"未知方法: " + method.decode("utf-8") if isinstance(method, str) else u"未知方法: " + method
def _handle_ws_method(method, args):
    logger.info("%s,%s",method,args)
    if method == "list":
        waypoints=load_waypoints()
        names=[item.get("name") for item in waypoints]
        return True,str(names)
    elif method == "stop":
        get_default_manager().cancel_navigation()
        return True,u"停止成功"
    elif method == "goto":
        args=json.loads(args)
        goal_id = args.get("name", "") or args.get("goal", "")
        for item in load_waypoints():
            name = item.get("name", "") or item.get("label", "")
            if str(name) == str(goal_id):
                get_default_manager().navigate_to_goal(
                    item.get("x"), item.get("y"), item.get("theta")
                )
                return True, u"导航成功"
        return False,u"导航失败，未找到导航点"
    else:
        return False,u"未知方法: " + method


class RosWebSocket(WebSocket):
    def connected(self):
        logger.info("WebSocket client connected: %s", self.address)

    def handle_close(self):
        logger.info("WebSocket client disconnected: %s", self.address)

    def handle(self):
        try:
            data = json.loads(self.data)
            method = data.get("method", "")
            args = data.get("args", {})
            status,result = handle_ws_method(method, args)
            self.send_message(json.dumps({"method": method,"status":status, "result": result},ensure_ascii=False))
        except Exception as e:
            traceback.print_exc()
            logger.error("WebSocket handle error: %s", str(e))
            self.send_message(json.dumps({"method": "","status":False, "result": "error: " + str(e)}))


def start_ws_server():
    server = WebSocketServer("0.0.0.0", WS_PORT, RosWebSocket)
    logger.info("Starting WebSocket server on port %d...", WS_PORT)
    server.serve_forever()


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


@app.route("/api/goal/stop", methods=["POST"])
def stop_navigation():
    get_default_manager().cancel_navigation()
    return "停止成功"


@app.route("/api/rotate", methods=["POST"])
def rotate_angle():
    data = request.get_json()
    angle = data.get("angle", 0)
    if angle == 0:
        return {}
    get_steering_odom_node().angle_callback(angle)
    return {}


def main():
    try:
        start_ws_server()

    except Exception as e:
        logger.error("Failed to start Flask application: {0}".format(str(e)))
    except rospy.ROSInterruptException:
        logger.info("ROS node interrupted")
    finally:
        logger.info("Shutting down...")


if __name__ == "__main__":
    main()
