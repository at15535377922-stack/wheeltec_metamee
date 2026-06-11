#!/usr/bin/env python
# -*- coding: utf-8 -*-

import rospy
import actionlib
import json
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from geometry_msgs.msg import Quaternion
from tf.transformations import quaternion_from_euler
import time
import logging

logger = logging.getLogger(__name__)

class NavigationManager(object):
    def __init__(self):
        # 移除 rospy.init_node() 调用，因为已经在 plan_manager.py 中初始化
        
        # 初始化move_base客户端
        self.move_base_client = actionlib.SimpleActionClient('move_base', MoveBaseAction)
        self.move_base_client.wait_for_server()
        self.current_goal = None
        self.is_navigating = False
        self.should_pause = False
        logger.info("Navigation manager initialized")
    
    def navigate_to_goal(self, x, y, theta):
        """导航到指定位置"""
        """导航到指定位置，支持中断"""
        try:
            # 重置状态
            self.is_navigating = True
            self.should_pause = False

            # 设置目标位置
            goal = MoveBaseGoal()
            goal.target_pose.header.frame_id = "map"
            goal.target_pose.header.stamp = rospy.Time.now()
            goal.target_pose.pose.position.x = x
            goal.target_pose.pose.position.y = y

            q = quaternion_from_euler(0, 0, theta)
            goal.target_pose.pose.orientation = Quaternion(*q)

            # 发送导航命令
            self.move_base_client.send_goal(goal)
            self.current_goal = goal

            # 等待导航完成（但可以响应暂停）
            while self.is_navigating:
                # 检查暂停请求
                if self.should_pause:
                    self.move_base_client.cancel_goal()
                    self.is_navigating = False
                    return False  # 返回False表示被暂停

                # 检查导航状态
                if self.move_base_client.wait_for_result(rospy.Duration(0.1)):
                    state = self.move_base_client.get_state()
                    if state == actionlib.GoalStatus.SUCCEEDED:
                        logger.info("Navigation completed successfully")
                        self.is_navigating = False
                        return True
                    else:
                        logger.error("Navigation failed with state: %d", state)
                        self.is_navigating = False
                        return False

            return False

        except Exception as e:
            logger.error("Navigation error: %s", str(e))
            self.is_navigating = False
            return False

    """暂停导航（立即停止移动）"""
    def pause_navigation(self):

        if self.is_navigating:
            self.should_pause = True
            logger.info("Navigation pause requested")
            # 等待导航真正停止
            for _ in range(10):  # 最多等待1秒
                if not self.is_navigating:
                    break
                time.sleep(0.1)
            return True
        return False

    def resume_navigation(self):
        """继续被暂停的导航"""
        if self.current_goal and not self.is_navigating:
            # 需要重新创建导航步骤，由PlanManager处理
            return True
        return False

    def cancel_navigation(self):
        """取消当前导航（强制停止）"""
        try:
            if self.is_navigating:
                logger.info("Cancelling current navigation")
                self.move_base_client.cancel_all_goals()
                self.is_navigating = False
                self.should_pause = False
                return True
            return False
        except Exception as e:
            logger.error("Error cancelling navigation: %s", str(e))
            return False

    def navigate_to_goals(self, goals):
        """导航到多个目标点
        
        参数:
            goals: 目标点列表，每个目标点为 (x, y, theta) 元组
        """
        for goal in goals:
            x, y, theta = goal
            success = self.navigate_to_goal(x, y, theta)
            if success:
                logger.info("在目标点停留5秒...")
                time.sleep(5)  # 在目标点停留5秒
            else:
                logger.warning("跳过剩余目标点")
                break

def main():
    try:
        # 如果直接运行此文件，则初始化节点
        rospy.init_node('navigation_manager')
        nav_manager = NavigationManager()
        rospy.spin()
    except rospy.ROSInterruptException:
        pass

if __name__ == '__main__':
    main()

"""
使用示例：

1. 直接运行导航：
```bash
rosrun your_package_name nav_service.py
```

2. 在其他Python代码中使用：
```python
from nav_service import NavigationManager

# 创建导航管理器实例
nav_manager = NavigationManager()

# 导航到单个目标点
success = nav_manager.navigate_to_goal(0.766, -0.543, 1.423)

# 或者导航到多个目标点
goals = [
    (0.766, -0.543, 1.423),
    (0.897, 0.553, 2.909)
]
nav_manager.navigate_to_goals(goals)
```

注意事项：
1. 确保move_base节点已经启动
2. 确保RGB LED管理器节点已经启动
3. 导航过程中LED颜色变化：
   - 橙色：正在移动
   - 绿色：成功到达
   - 红色：导航失败
"""


