#!/usr/bin/env python
# -*- coding: utf-8 -*-
import threading
import rospy
import math
import time
from std_msgs.msg import Int32, Bool
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry


class SteeringOdomNode:
    def __init__(self):
        rospy.init_node("steering_odom_node", anonymous=True)

        self.cmd_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=10)
        self.odom_sub = rospy.Subscriber("/odom", Odometry, self.odom_callback)

        # --- 状态变量 ---
        self.current_yaw = 0.0
        self.is_moving = False

        # --- 控制参数配置 ---
        self.front_offset = 90  # 麦克风定义的正前方角度 (度)

        # P控制器参数
        self.kp = 1.5  # 比例系数: 决定响应速度 (1.5为柔和模式)

        # 速度限制 (rad/s)
        self.max_speed = 0.5  # 最大旋转角速度
        self.min_speed = 0.15  # 最小启动角速度 (克服静摩擦力)

        # 终止条件
        self.angle_tolerance = 8.0  # 角度容差 (度): 低于此误差认为到达目标
        self.timeout = 10.0  # 动作超时时间 (秒)

        rospy.loginfo("=" * 60)
        rospy.loginfo("里程计转向控制器已启动")
        rospy.loginfo(
            "参数设定: 正前方[%d]度 | 容差[%.1f]度 | Kp[%.1f]",
            self.front_offset,
            self.angle_tolerance,
            self.kp,
        )
        rospy.loginfo("坐标逻辑: 180度(右) -> 负速度(右转)")
        rospy.loginfo("=" * 60)

    def odom_callback(self, msg):
        """
        里程计回调函数
        功能: 将四元数转换为欧拉角(Yaw)
        """
        q = msg.pose.pose.orientation
        siny_cosp = 2 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1 - 2 * (q.y * q.y + q.z * q.z)
        self.current_yaw = math.atan2(siny_cosp, cosy_cosp)

    def normalize_angle(self, angle):
        """
        工具函数: 将角度归一化到 [-pi, pi] 区间
        用于处理跨越 +/- 180 度的角度计算
        """
        while angle > math.pi:
            angle -= 2.0 * math.pi
        while angle < -math.pi:
            angle += 2.0 * math.pi
        return angle

    def angle_callback(self, raw_angle):
        """
        唤醒角度回调函数
        功能: 接收声源角度，计算目标Yaw值并触发转向
        """
        if self.is_moving:
            return

        raw_angle
        rospy.loginfo("\n" + "-" * 40)
        rospy.loginfo("收到唤醒信号: 原始角度 %d度", raw_angle)

        # --- 步骤1: 计算相对于车头的偏差角度 ---
        # 麦克风定义: 0左, 90前, 180右
        # 偏差 = 原始角度 - 正前方角度
        mic_diff = raw_angle - self.front_offset

        # --- 步骤2: 转换为ROS坐标系转向指令 ---
        # ROS定义: 逆时针(左)为正，顺时针(右)为负
        # 麦克风在右边(diff > 0) -> 需要右转(vel < 0) -> 取反
        turn_needed_deg = -mic_diff

        # 归一化处理 (处理 -180 到 180 之外的数值)
        if turn_needed_deg > 180:
            turn_needed_deg -= 360
        if turn_needed_deg < -180:
            turn_needed_deg += 360

        rospy.loginfo(
            "分析: 声源位于[%d度], 需要机器人转动[%d度]", raw_angle, turn_needed_deg
        )

        # 死区检查
        if abs(turn_needed_deg) < self.angle_tolerance:
            rospy.loginfo("目标在容差范围内，无需转动")
            self.finish_pub.publish(True)
            return

        # --- 步骤3: 计算世界坐标系下的绝对目标Yaw ---
        turn_needed_rad = math.radians(turn_needed_deg)
        target_yaw = self.normalize_angle(self.current_yaw + turn_needed_rad)

        rospy.loginfo(
            "锁定目标: 当前Yaw[%.1f] -> 目标Yaw[%.1f]",
            math.degrees(self.current_yaw),
            math.degrees(target_yaw),
        )

        # 进入控制循环
        self.execute_turn(target_yaw)

    def execute_turn(self, target_yaw):
        """
        执行转向逻辑
        使用P控制算法逼近目标角度，每0.5秒打印一次状态
        """
        self.is_moving = True
        start_time = time.time()
        last_log_time = 0  # 用于控制打印频率

        rate = rospy.Rate(20)  # 控制频率 20Hz

        rospy.loginfo("开始执行P控制转向...")
        rospy.loginfo(
            "%-8s | %-12s | %-12s | %-10s",
            "Time(s)",
            "CurYaw(deg)",
            "Error(deg)",
            "CmdVel",
        )
        rospy.loginfo("-" * 50)

        while not rospy.is_shutdown():
            current_time = time.time()
            elapsed = current_time - start_time

            # 1. 超时保护
            if elapsed > self.timeout:
                rospy.logwarn("转向超时，强制停止")
                break

            # 2. 计算误差 (目标 - 当前)
            # 使用 normalize_angle 确保误差走最短路径
            error_rad = self.normalize_angle(target_yaw - self.current_yaw)
            error_deg = math.degrees(error_rad)

            # 3. 检查是否到达目标 (使用 8度 容差)
            if abs(error_deg) < self.angle_tolerance:
                rospy.loginfo(
                    "到达目标范围 (剩余误差 %.2f度 < %.1f度)",
                    error_deg,
                    self.angle_tolerance,
                )
                break

            # 4. P控制计算速度
            cmd_vel = self.kp * error_rad

            # 5. 速度限幅 (确保有最小启动力矩，且不超过最大速度)
            if cmd_vel > 0:
                cmd_vel = min(cmd_vel, self.max_speed)
                cmd_vel = max(cmd_vel, self.min_speed)
            else:
                cmd_vel = max(cmd_vel, -self.max_speed)
                cmd_vel = min(cmd_vel, -self.min_speed)

            # 6. 发布速度命令
            move_cmd = Twist()
            move_cmd.angular.z = cmd_vel
            self.cmd_pub.publish(move_cmd)

            # 7. 定时日志打印 (每0.5秒一次)
            if current_time - last_log_time >= 0.5:
                curr_deg = math.degrees(self.current_yaw)
                rospy.loginfo(
                    "%6.2f   | %8.1f     | %8.1f     | %8.3f",
                    elapsed,
                    curr_deg,
                    error_deg,
                    cmd_vel,
                )
                last_log_time = current_time

            rate.sleep()

        # --- 动作结束 ---
        # 发送停止指令
        stop_cmd = Twist()
        stop_cmd.angular.z = 0.0
        self.cmd_pub.publish(stop_cmd)
        rospy.sleep(0.5)  # 等待惯性消除

        # 计算最终静止后的误差
        final_error = math.degrees(self.normalize_angle(target_yaw - self.current_yaw))

        rospy.loginfo("-" * 50)
        rospy.loginfo("转向结束: 最终偏差 %.1f度", final_error)

        self.is_moving = False


_steering_odom = None
_lock = threading.Lock()


def get_steering_odom_node():
    global _steering_odom
    if _steering_odom is not None:
        return _steering_odom
    with _lock:
        if _steering_odom is not None:
            return _steering_odom

        _steering_odom = SteeringOdomNode()
    return _steering_odom


if __name__ == "__main__":
    try:
        node = SteeringOdomNode()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass
