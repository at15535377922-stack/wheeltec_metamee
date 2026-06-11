import requests
from config.config import load_config
import logging

logger = logging.getLogger(__file__)


class NavigationExecutor:
    def __init__(self):
        pass

    @staticmethod
    def goto(goal_id: str):
        """
        调度导航移动到某个地点
        Args:
            goal_id: 目标地点，比如食堂
        """
        response = requests.post(f"{load_config().navi.base_url}/api/goal/{goal_id}")
        if response.status_code != 200:
            logger.error(
                f"NavigationExecutor.goto {goal_id} error: {response.status_code} {response.text}"
            )
            return "导航失败"
        return response.text

    @staticmethod
    def list_goals():
        """
        获取所有可以导航的地点位置
        """
        response = requests.get(f"{load_config().navi.base_url}/api/goal/list")
        if response.status_code != 200:
            logger.error(
                f"NavigationExecutor.list_goals error: {response.status_code} {response.text}"
            )
            return "获取导航点失败"
        data = response.json()
        goal_label_list = [item.get('label','') for item in data]
        return ",".join(goal_label_list)

    @staticmethod
    def stop_navigate():
        """停止当前执行中的导航"""
        response = requests.post(f"{load_config().navi.base_url}/api/goal/stop")
        if response.status_code != 200:
            logger.error(
                f"NavigationExecutor.stop_navigation error: {response.status_code} {response.text}"
            )
            return "停止导航失败"
        return "停止导航成功"
