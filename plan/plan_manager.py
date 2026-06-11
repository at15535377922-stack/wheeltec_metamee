#!/usr/bin/env python
# -*- coding: utf-8 -*-
import rospy
import json
import yaml
import os
import threading
import time
from flask import Flask, render_template, request, jsonify
from nav_manager import NavigationManager
import websocket
from waypoints_manager import WaypointsManager
import signal
import logging
import datetime
from logging.handlers import RotatingFileHandler
from std_msgs.msg import String


# 配置日志
def setup_logger():
    # 创建logs目录
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # 配置根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)

    # 创建文件处理器 - 按日期和大小滚动
    log_file = os.path.join('logs', 'app_{}.log'.format(datetime.datetime.now().strftime('%Y%m%d')))
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
    file_handler.setLevel(logging.INFO)
    file_format = logging.Formatter(
        '%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s')
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


# 加载配置文件
def load_config():
    try:
        logger.debug("加载配置文件")
        with open('../config.yaml', 'r') as f:
            config = yaml.safe_load(f)
            logger.debug("加载的配置: %s", config)
            return config
    except Exception as e:
        logger.error("加载配置文件失败: %s", str(e))
        return {}


class PlanStep(object):
    def __init__(self, step_type, name, params=None):
        self.step_type = step_type  # 'navigation' 或 'speech'
        self.name = name
        self.params = params or {}
        self.status = 'pending'  # pending, running, completed, failed
        self.error = None

    def to_dict(self):
        """转换为字典，不包含状态信息"""
        return {
            'step_type': self.step_type,
            'name': self.name,
            'params': self.params
        }

    def to_dict_with_status(self):
        """转换为字典，包含状态信息"""
        return {
            'step_type': self.step_type,
            'name': self.name,
            'params': self.params,
            'status': self.status,
            'error': self.error
        }

    @classmethod
    def from_dict(cls, data):
        """从字典创建步骤，重置状态"""
        step = cls(
            step_type=data['step_type'],
            name=data['name'],
            params=data.get('params', {})
        )
        # 状态信息在加载时重置
        step.status = 'pending'
        step.error = None
        return step


class PlanManager(object):
    def __init__(self):
        existing_handlers = logging.root.handlers[:]
        rospy.init_node('plan_manager', anonymous=True)
        logging.root.handlers = existing_handlers
        # Suppress unnecessary rospy logs by setting their log level to WARNING
        rospy_logger = logging.getLogger('rospy')
        rospy_logger.setLevel(logging.WARNING)
        # Disable propagation to prevent duplicate log messages
        rosout_logger = logging.getLogger('rosout')
        rosout_logger.propagate = False

        # 初始化导航管理器
        self.nav_manager = NavigationManager()

        # 初始化导航点管理器
        self.waypoints_manager = WaypointsManager()
        self.force_stop_requested = False  # 新增：强制停止标志
        # 初始化WebSocket客户端
        self.ws = None
        self.ws_connected = False
        self.ws_thread = None
        self.heartbeat_timer = None

        # 当前计划
        self.current_plan = []
        self.current_step_index = -1
        self.is_running = False
        # 新增：暂停状态控制
        self.is_paused = False
        self.pause_condition = threading.Condition()  # 用于暂停/继续的线程同步

        # 新增：用于语音播报同步的状态变量
        self.speech_waiting_for_completion = False  # 是否正在等待播报完成
        self.speech_completion_received = False  # 是否已收到播报完成消息
        self.speech_completion_condition = threading.Condition()  # 用于等待播报完成的条件变量
        self.current_speech_text_id = None  # 当前正在等待的播报文本ID

        self.plan_thread = None
        self.lock = threading.Lock()

        # 创建plans目录
        self.plans_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plans')
        if not os.path.exists(self.plans_dir):
            os.makedirs(self.plans_dir)

        self.status_pub = rospy.Publisher('/metamee/status_command', String, queue_size=10)
        self.navigation_paused = False  # 新增：导航暂停状态
        logger.info("Plan manager initialized")

    def pub_status(self, status):
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)

    def connect_websocket(self):
        """连接到WebSocket服务器"""
        try:
            logger.info("Attempting to connect to WebSocket server...")
            # 使用文档中指定的WebSocket地址
            websocket.enableTrace(True)
            self.ws = websocket.WebSocketApp(
                load_config().get('metamee_ws', 'ws://192.168.0.156:8080/metamee/ws'),
                on_message=self.on_ws_message,
                on_error=self.on_ws_error,
                on_close=self.on_ws_close,
                on_open=self.on_ws_open
            )
            # 在新线程中运行WebSocket
            self.ws_thread = threading.Thread(target=self.ws.run_forever)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            logger.info("WebSocket connection thread started")
        except Exception as e:
            logger.error("WebSocket connection error: {0}".format(str(e)))
            self.ws_connected = False

    def disconnect_websocket(self):
        """断开WebSocket连接"""
        try:
            if self.heartbeat_timer:
                self.heartbeat_timer.cancel()
                self.heartbeat_timer = None

            if self.ws:
                self.ws.close()
                self.ws = None
                self.ws_connected = False

            if self.ws_thread and self.ws_thread.is_alive():
                self.ws_thread.join(timeout=1)
                self.ws_thread = None

            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error("Error closing WebSocket connection: {0}".format(str(e)))

    def start_heartbeat(self):
        """启动心跳定时器"""

        def send_heartbeat():
            if self.ws_connected:
                self.send_heartbeat()
                self.heartbeat_timer = threading.Timer(30, send_heartbeat)
                self.heartbeat_timer.start()

        self.heartbeat_timer = threading.Timer(30, send_heartbeat)
        self.heartbeat_timer.start()

    def on_ws_message(self, ws, message):
        """处理WebSocket消息"""
        try:
            logger.debug("Received WebSocket message: {0}".format(message))
            data = json.loads(message)
            msg_type = data.get('type')

            if msg_type == 'text_broadcast_response':
                # 处理播报响应
                status = data['data']['status']
                if status == 'rejected':
                    logger.error("Speech request rejected: {0}".format(data['data'].get('error_message')))
            elif msg_type == 'broadcast_started':
                # 处理播报开始通知
                logger.debug("Speech started for text_id: {0}".format(data['data']['text_id']))
            elif msg_type == 'broadcast_completed':
                # 处理播报完成通知
                text_id = data['data']['text_id']
                logger.debug("Speech completed for text_id: {0}".format(text_id))

                # 检查是否正在等待这个播报完成
                with self.speech_completion_condition:
                    if (self.speech_waiting_for_completion and
                            self.current_speech_text_id == text_id):
                        self.speech_completion_received = True
                        self.speech_completion_condition.notify_all()
                        logger.info("收到播报完成确认，继续执行计划")

            elif msg_type == 'pause':
                logger.info("收到数字人暂停指令")
                self.pause_plan()

            elif msg_type == 'resume':
                logger.info("收到数字人恢复指令")
                self.resume_plan()

            elif msg_type == 'error':
                # 处理错误消息
                logger.error("WebSocket error: {0}".format(data['data']['message']))
            elif msg_type == 'heartbeat':
                # 处理心跳消息
                logger.debug("Received heartbeat")
                self.send_heartbeat()
            elif msg_type == 'clear':
                logger.info("收到数字人清理指令")
                self.clear_before_step(need_send=False)
                # 唤醒可能正在等待的线程
                with self.pause_condition:
                    self.pause_condition.notify_all()

                # 唤醒可能正在等待语音完成的线程
                with self.speech_completion_condition:
                    self.speech_waiting_for_completion = False
                    self.speech_completion_received = True
                    self.speech_completion_condition.notify_all()

        except ValueError as e:
            logger.error("Error parsing WebSocket message: {0}".format(str(e)))
        except Exception as e:
            logger.error("Error processing WebSocket message: {0}".format(str(e)))

    def on_ws_error(self, ws, error):
        """处理WebSocket错误"""
        logger.error("WebSocket error: {0}".format(str(error)))
        self.ws_connected = False

    def on_ws_close(self, ws):
        """处理WebSocket关闭"""
        logger.debug("WebSocket connection closed")
        self.ws_connected = False

    def on_ws_open(self, ws):
        """处理WebSocket连接打开"""
        logger.debug("WebSocket connection established")
        self.ws_connected = True

    def send_heartbeat(self):
        """发送心跳消息"""
        try:
            heartbeat_msg = {
                "type": "heartbeat",
                "message_id": "hb-{0}".format(int(time.time() * 1000)),
                "timestamp": int(time.time() * 1000),
                "data": {}
            }
            self.ws.send(json.dumps(heartbeat_msg))
        except Exception as e:
            logger.error("Error sending heartbeat: {0}".format(str(e)))

    def send_speech_command(self, text):
        """发送语音命令，返回text_id"""

        if not self.ws_connected:
            #logger.info("connecting to WebSocket...")
            #self.connect_websocket()
            # 等待连接建立
            for _ in range(10):  # 最多等待5秒
                if self.ws_connected:
                    break
                time.sleep(0.5)

            #if not self.ws_connected:
                #raise Exception("Failed to connect to WebSocket server")
            # 启动心跳
            #self.start_heartbeat()

        try:
            # 生成唯一的消息ID和文本ID
            message_id = "req-{0}".format(int(time.time() * 1000))
            text_id = "text-{0}".format(int(time.time() * 1000))

            # 构造播报请求消息
            command = {
                "type": "text_broadcast_request",
                "message_id": message_id,
                "timestamp": int(time.time() * 1000),
                "data": {
                    "text": text,
                    "text_id": text_id,
                    "priority": 1
                }
            }

            #self.ws.send(json.dumps(command))
            return text_id  # 返回text_id
        except Exception as e:
            logger.error("Error sending speech command: {0}".format(str(e)))
            return None

    def clear_before_step(self,need_send=True):
        """清理步骤前的状态"""
        if need_send:
            self.send_pause_resume_message("clear")

        # 立即中断当前导航（如果是导航步骤）
        if (self.current_step_index >= 0 and
                self.current_step_index < len(self.current_plan)):
            current_step = self.current_plan[self.current_step_index]
            if current_step.step_type == 'navigation':
                self.nav_manager.cancel_navigation()


        #self.pub_status("PAUSED")


    def execute_step(self, step):
        """执行单个步骤"""
        """执行单个步骤（保持原有逻辑）"""

        #recived_step_index=self.current_plan.index(step)
        #if  recived_step_index != self.current_step_index and self.current_step_index > -1:
        #    self.clear_before_step()
        try:
            logger.debug("Executing step: {0}".format(step.step_type))

            # 在执行前检查暂停状态
            if self.is_paused:
                step.status = 'paused'
                return False

            #step.status = 'running'

            if step.step_type == 'navigation':
                step.status='running'
                self.pub_status("NAVIGATING")
                # 从导航点管理器获取导航点信息
                waypoint_name = step.params['waypoint_name']
                waypoint = None
                for wp in self.waypoints_manager.waypoints_cache:
                    if wp.name == waypoint_name:
                        waypoint = wp
                        break

                if not waypoint:
                    step.status = 'failed'
                    step.error = "导航点不存在"
                    return False

                # 执行导航（支持暂停）
                success = self.nav_manager.navigate_to_goal(
                    waypoint.x, waypoint.y, waypoint.theta
                )

                # 如果导航返回False且计划处于暂停状态，标记为暂停
                if not success and self.is_paused:
                    step.status = 'paused'
                    return False
                elif not success:
                    step.status = 'failed'
                    step.error = "导航失败"
                    self.pub_status("FAILED")
                    return False

            elif step.step_type == 'speech':
                self.pub_status("SPEECHING")
                # 播报任务 - 修改为等待完成模式
                if self.is_paused:
                    step.status = 'paused'
                    return False

                # 发送播报命令
                logger.info(step.status)
                if step.status!="paused":
                    text_id = self.send_speech_command(step.params['text'])
                    if not text_id:
                        step.status = 'failed'
                        step.error = "播报请求发送失败"
                        self.pub_status("FAILED")
                        return False
                    self.current_speech_text_id = text_id
                step.status='running'

                # 等待播报完成（最多等待60秒）
                with self.speech_completion_condition:
                    self.speech_waiting_for_completion = True
                    self.speech_completion_received = False
                    # 从发送的命令中提取text_id（这里需要根据send_speech_command的实现调整）
                    # 假设send_speech_command返回了text_id，或者我们需要修改它以返回text_id
                    # 这里简化处理，实际可能需要调整send_speech_command方法

                    # 设置超时等待
                    timeout = 3600  # 60秒超时
                    start_time = time.time()

                    while not self.speech_completion_received and not self.is_paused and self.is_running:
                        remaining = timeout - (time.time() - start_time)
                        if remaining <= 0:
                            break
                        #self.speech_completion_condition.wait(remaining)
                        if self.speech_completion_condition.wait(0.5):
                            break

                    self.speech_waiting_for_completion = False
                    if  not self.is_running:
                        step.status = 'failed'
                        step.error = "计划被强制停止"
                        return False
                    if self.is_paused:
                        step.status = 'paused'
                        return False

                    if not self.speech_completion_received:
                        step.status = 'failed'
                        step.error = "播报完成确认超时"
                        return False

                # 播报成功完成
                step.status = 'completed'
                return True

            elif step.step_type == 'sleep':
                self.pub_status("SLEEPING")
                step.status='running'
                duration = float(step.params['duration'])
                if duration < 0:
                    step.status = 'failed'
                    step.error = "等待时间不能为负数"
                    return False

                # 等待任务也支持立即暂停
                start_time = time.time()
                while time.time() - start_time < duration:
                    if self.is_paused:
                        step.status = 'paused'
                        return False
                    time.sleep(0.1)

            step.status = 'completed'
            self.pub_status("RUNNING")
            return True

        except Exception as e:
            logger.error("Step execution failed: {0}".format(str(e)))
            step.status = 'failed'
            step.error = str(e)
            return False
    def clear_status(self):
        for step in self.current_plan:
            step.status = 'pending'
            step.error = None
    def _prepare_plan_execution(self, plan_name, start_index=0):
        """准备计划执行的通用逻辑"""
        # 加载计划
        plan_path = os.path.join(self.plans_dir, "{0}.json".format(plan_name))
        with open(plan_path, 'r') as f:
            plan_data = json.load(f)
            self.current_plan = [PlanStep.from_dict(step) for step in plan_data]

        # 检查是否存在播报步骤
        # has_speech_steps = any(step.step_type == 'speech' for step in self.current_plan[start_index:])
        has_speech_steps = False
        # 只有在存在播报步骤时才连接WebSocket
        if has_speech_steps:
            logger.debug("Plan contains speech steps, connecting to WebSocket...")
            #self.connect_websocket()
            # 等待连接建立
            #for _ in range(10):  # 最多等待5秒
                #if self.ws_connected:
                    #break
                #time.sleep(0.5)

            #if not self.ws_connected:
            #    raise Exception("Failed to connect to WebSocket server")

            # 启动心跳
            #self.start_heartbeat()
        else:
            logger.debug("No speech steps in plan, skipping WebSocket connection")

    def force_stop_plan(self):
        """强制停止当前正在执行的计划"""
        with self.lock:
            if not self.is_running:
                return False, "没有正在运行的计划"

            logger.info("强制停止计划执行...")
            self.force_stop_requested = True

            # 设置停止标志
            self.is_running = False
            self.is_paused = False

            # 中断导航
            self.nav_manager.cancel_navigation()

            # 中断WebSocket连接
            if self.ws_connected:
                self.disconnect_websocket()

            # 唤醒可能正在等待的线程
            with self.pause_condition:
                self.pause_condition.notify_all()

            # 唤醒可能正在等待语音完成的线程
            with self.speech_completion_condition:
                self.speech_waiting_for_completion = False
                self.speech_completion_received = True
                self.speech_completion_condition.notify_all()

            # 重置状态
            self.current_step_index = -1
            for step in self.current_plan:
                if step.status == 'running' or step.status == 'paused':
                    step.status = 'failed'
                    step.error = "计划被强制停止"

            logger.info("计划已强制停止")
            self.pub_status("STOPPED")
            return True, "计划已强制停止"
    def _cleanup_plan_execution(self):
        """清理计划执行的通用逻辑"""
        self.is_running = False
        self.is_paused = False
        if self.ws_connected:
            self.disconnect_websocket()

    def save_plan(self, plan_name, steps):
        """保存计划"""
        try:
            plan_path = os.path.join(self.plans_dir, "{0}.json".format(plan_name))
            with open(plan_path, 'w') as f:
                # 保存时不包含状态信息
                json.dump([step.to_dict() for step in steps], f, indent=4)
            return True
        except Exception as e:
            logger.error("Error saving plan: {0}".format(str(e)))
            return False

    def load_plan(self, plan_name):
        """加载计划"""
        try:
            plan_path = os.path.join(self.plans_dir, "{0}.json".format(plan_name))
            self.current_plan = []  # 清空当前计划
            with open(plan_path, 'r') as f:
                plan_data = json.load(f)
                # 加载时重置状态
                return [PlanStep.from_dict(step) for step in plan_data]
        except Exception as e:
            logger.error("Error loading plan: {0}".format(str(e)))
            return []

    def get_available_plans(self):
        """获取可用的计划列表"""
        try:
            return [f[:-5] for f in os.listdir(self.plans_dir) if f.endswith('.json')]
        except Exception as e:
            logger.error("Error getting available plans: {0}".format(str(e)))
            return []

    def get_available_waypoints(self):
        """获取可用的导航点列表"""
        try:
            return [wp.name for wp in self.waypoints_manager.waypoints_cache]
        except Exception as e:
            logger.error("Error getting available waypoints: {0}".format(str(e)))
            return []

    def get_status(self):
        """获取当前状态"""
        return {
            'is_running': self.is_running,
            'is_paused': self.is_paused,  # 添加暂停状态
            'current_step_index': self.current_step_index,
            'current_plan': [step.to_dict_with_status() for step in self.current_plan]
        }

    def run_plan(self, plan_name, start_index=0):
        """启动计划执行线程，立即返回"""
        with self.lock:
            if self.is_running and not self.is_paused:
                return False, "已有计划正在运行"

            # 如果计划已经运行但处于暂停状态，则恢复执行
            if self.is_running and self.is_paused:
                return self.resume_plan()

            # 否则启动新计划
            try:
                self._prepare_plan_execution(plan_name, start_index)
            except Exception as e:
                error_msg = "计划执行失败: {}".format(str(e))
                logger.error(error_msg)
                return False, error_msg

            self.plan_thread = threading.Thread(target=self._run_plan_worker, args=(plan_name, start_index))
            self.plan_thread.daemon = True
            self.plan_thread.start()

        return True, "计划已启动"

    def _run_plan_worker(self, plan_name, start_index):
        try:
            self.is_running = True
            self.is_paused = False
            success, message = self._run_plan_internal(plan_name, start_index)
            logger.debug("Plan finished: {}".format(message))
        finally:
            with self.lock:
                self.is_running = False
                self.is_paused = False

    def _run_plan_internal(self, plan_name, start_index):
        try:
            self.force_stop_requested = False  # 重置强制停止标志
            plan_manager.pub_status("RUNNING")

            self.current_step_index = start_index - 1
            i = start_index
            while i < len(self.current_plan):
                # 检查强制停止请求
                if self.force_stop_requested:
                    break

                self.current_step_index = i
                step = self.current_plan[i]
                # 检查暂停状态
                with self.pause_condition:
                    while self.is_paused:
                        self.pub_status("PAUSED")
                        logger.info("计划已暂停，等待继续...")
                        # 设置步骤状态为暂停（如果是新步骤）
                        if step.status == 'pending' or step.status == 'running':
                            step.status = 'paused'
                        self.pause_condition.wait()
                        if not self.is_running:
                            return False, "计划被停止"
                if self.force_stop_requested:
                    break

                #if step.status == 'paused':
                    #step.status = 'pending'
                    #step.error = None

                if not self.execute_step(step):
                    if step.status == 'paused':
                        # 如果是暂停状态，重新进入暂停等待
                        # 保持当前索引，等待恢复后重新执行
                        continue
                    else:
                        error_msg = "步骤执行失败: {}".format(step.error)
                        return False, error_msg
                
                time.sleep(1)

                i += 1

            return True, "计划执行完成"

        except Exception as e:
            error_msg = "计划执行失败: {}".format(str(e))
            return False, error_msg
        finally:
            self._cleanup_plan_execution()

    """向数字人发送暂停/继续指令"""

    def send_pause_resume_message(self, msg):
        return True
        #if not self.ws_connected:
            #logger.info("connecting to WebSocket...")
            #self.connect_websocket()
            # 等待连接建立
            #for _ in range(10):  # 最多等待5秒
            #    if self.ws_connected:
            #        break
            #    time.sleep(0.5)

            #if not self.ws_connected:
            #    raise Exception("Failed to connect to WebSocket server")
            # 启动心跳
            #self.start_heartbeat()
        try:
            if msg == "pause":
                """向数字人发送暂停信号"""
                pause_msg = {
                    "type": "text_broadcast_pause",
                    "message_id": "hb-{0}".format(int(time.time() * 1000)),
                    "timestamp": int(time.time() * 1000),
                    "data": {}
                }
                self.ws.send(json.dumps(pause_msg))
            if msg == "resume":
                """向数字人发送恢复信号"""

                resume_msg = {
                    "type": "text_broadcast_resume",
                    "message_id": "hb-{0}".format(int(time.time() * 1000)),
                    "timestamp": int(time.time() * 1000),
                    "data": {}
                }
                self.ws.send(json.dumps(resume_msg))
            elif msg=="clear":
                msg = {
                    "type": "clear",
                    "message_id": "hb-{0}".format(int(time.time() * 1000)),
                    "timestamp": int(time.time() * 1000),
                    "data": {}
                }
                self.ws.send(json.dumps(msg))
            return True
        except Exception as e:
            logger.error("Error sending speech command: {0}".format(str(e)))
            return False

    """暂停当前正在执行的计划，立即中断导航"""

    def pause_plan(self):

        with self.lock:
            if not self.is_running:
                return False, "没有正在运行的计划"
            if self.is_paused:
                return False, "计划已经处于暂停状态"
            self.is_paused = True
            """向数字人发送暂停消息"""
            self.send_pause_resume_message("pause")

            # 立即中断当前导航（如果是导航步骤）
            if (self.current_step_index >= 0 and
                    self.current_step_index < len(self.current_plan)):
                current_step = self.current_plan[self.current_step_index]
                if current_step.step_type == 'navigation':
                    self.nav_manager.pause_navigation()


            logger.info("计划已暂停，当前步骤索引: %d", self.current_step_index)
            self.pub_status("PAUSED")
            return True, "计划已暂停"

    """继续执行被暂停的计划"""

    def resume_plan(self):

        with self.lock:
            if not self.is_running:
                return False, "没有正在运行的计划"
            if not self.is_paused:
                return False, "计划未处于暂停状态"
            self.is_paused = False

            self.send_pause_resume_message("resume")

            with self.pause_condition:
                self.pause_condition.notify()  # 唤醒等待的线程
            logger.info("计划已继续，从步骤 %d 开始", self.current_step_index)
            self.pub_status("RUNNING")
            return True, "计划已继续"


logger.debug("Starting ...")
# 创建全局计划管理器实例
plan_manager = PlanManager()


@app.route('/')
def index():
    """渲染主页"""
    return render_template('index.html')


@app.route('/api/plans', methods=['GET'])
def get_plans():
    """获取可用计划列表"""
    return jsonify(plan_manager.get_available_plans())


@app.route('/api/waypoints', methods=['GET'])
def get_waypoints():
    """获取可用导航点列表"""
    return jsonify(plan_manager.get_available_waypoints())


@app.route('/api/plans/<plan_name>', methods=['GET'])
def get_plan(plan_name):
    """获取特定计划的内容"""
    # 新增：检查是否有正在运行的计划，如果有则强制停止
    if plan_manager.is_running:
        logger.info("检测到有正在运行的计划，正在强制停止...")
        success, message = plan_manager.force_stop_plan()
        if success:
            logger.info("计划已强制停止: %s", message)
        else:
            logger.warning("强制停止计划失败: %s", message)

    steps = plan_manager.load_plan(plan_name)


    return jsonify([step.to_dict_with_status() for step in steps])


@app.route('/api/plans/<plan_name>', methods=['POST'])
def save_plan(plan_name):
    """保存计划"""
    try:
        steps_data = request.json
        steps = [PlanStep.from_dict(step) for step in steps_data]
        success = plan_manager.save_plan(plan_name, steps)
        return jsonify({'success': success})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/plans/<plan_name>/run', methods=['POST'])
def run_plan(plan_name):
    """运行计划"""
    try:
        data = request.get_json() or {}
        plan_manager.clear_status()
        start_index = data.get('start_index', 0)
        success, message = plan_manager.run_plan(plan_name, start_index)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/status', methods=['GET'])
def get_status():
    """获取当前状态"""
    status = plan_manager.get_status()
    # 添加暂停状态字段
    status['is_paused'] = plan_manager.is_paused
    return jsonify(status)


@app.route('/api/plans/<plan_name>', methods=['DELETE'])
def delete_plan(plan_name):
    """删除计划"""
    try:
        plan_path = os.path.join(plan_manager.plans_dir, "{0}.json".format(plan_name))
        if os.path.exists(plan_path):
            os.remove(plan_path)
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Plan not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/plans/<plan_name>/execute_step', methods=['POST'])
def execute_single_step(plan_name):
    """执行单个步骤"""
    try:
        step_index = request.json.get('step_index')
        if step_index is None:
            return jsonify({'success': False, 'error': 'Missing step_index'})

        # 加载计划
        steps = plan_manager.load_plan(plan_name)
        if not steps or step_index >= len(steps):
            return jsonify({'success': False, 'error': 'Invalid step index'})
        plan_manager.current_plan = steps
        # 执行步骤
        step = steps[step_index]
        plan_manager.send_pause_resume_message("clear")
        success,msg =plan_manager.force_stop_plan()
        plan_manager.clear_status()
        logger.info("强制停止结果: %s, %s", success, msg)
        plan_manager.is_running=True
        success = plan_manager.execute_step(step)
        plan_manager.current_plan[step_index].status = step.status
        plan_manager.current_plan[step_index].error = step.error

        return jsonify({
            'success': success,
            'status': step.status,
            'error': step.error if not success else None
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/plans/<plan_name>/run_remaining', methods=['POST'])
def run_remaining_steps(plan_name):
    """从指定步骤开始运行计划"""
    try:
        data = request.get_json()
        #plan_manager.clear_status()
        start_index = data.get('start_index', 0)
        plan_manager.send_pause_resume_message("clear")
        success,msg =plan_manager.force_stop_plan()
        logger.info("强制停止结果: %s, %s", success, msg)
        time.sleep(1)
        success, message = plan_manager.run_plan(plan_name, start_index)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/plans/<plan_name>/pause', methods=['POST'])
def pause_plan(plan_name):
    """暂停当前正在执行的计划"""
    try:
        success, message = plan_manager.pause_plan()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/plans/<plan_name>/resume', methods=['POST'])
def resume_plan(plan_name):
    """继续执行被暂停的计划"""
    try:
        success, message = plan_manager.resume_plan()
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/api/plans/<plan_name>/reset_step/<int:step_index>', methods=['POST'])
def reset_step_status(plan_name, step_index):
    """重置步骤状态"""
    try:
        if not plan_manager.current_plan or step_index >= len(plan_manager.current_plan):
            return jsonify({'success': False, 'error': '无效的步骤索引'})

        step = plan_manager.current_plan[step_index]
        step.status = 'pending'
        step.error = None

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})



def main():
    try:
        # 启动Flask应用
        logger.info("Starting Flask application on port 8082...")
        time.sleep(10)
        plan_manager.pub_status("WAITING")
        app.run(host='0.0.0.0', port=8082, threaded=True)
    except Exception as e:
        logger.error("Failed to start Flask application: {0}".format(str(e)))
    except rospy.ROSInterruptException:
        logger.info("ROS node interrupted")
    finally:
        logger.info("Shutting down...")


if __name__ == '__main__':
    main()

