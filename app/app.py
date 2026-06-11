#!/usr/bin/env python2.7
# -*- coding: utf-8 -*-

from flask import Flask, render_template, request, jsonify, redirect, url_for
from gevent.pywsgi import WSGIServer
import yaml
import os
import subprocess
import signal
import psutil
import socket
import sys
import logging
import datetime
import traceback
from logging.handlers import RotatingFileHandler

class UnicodeFormatter(logging.Formatter):
    def format(self, record):
        try:
            return super(UnicodeFormatter, self).format(record)
        except Exception:
            try: 
                record.msg = record.msg.decode('utf-8')
            except UnicodeDecodeError:
                # 如果解码失败，可以用其他编码或忽略
                record.msg = record.msg.decode('gbk', errors='ignore')
            except Exception as e:
                print("解码失败，强制转ASCII")
                print(record.msg)
                record.msg = record.msg.encode('ascii', 'ignore')
                return super(UnicodeFormatter, self).format(record)

# 配置日志
def setup_logger():
    # 创建logs目录
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    # 配置根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_format = UnicodeFormatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_format)
    
    # 创建文件处理器 - 按日期和大小滚动
    log_file = os.path.join('logs', 'app_{}.log'.format(datetime.datetime.now().strftime('%Y%m%d')))
    file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5)
    file_handler.setLevel(logging.DEBUG)
    file_format = UnicodeFormatter('%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(funcName)s - %(message)s')
    file_handler.setFormatter(file_format)
    
    # 添加处理器到日志记录器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger

# 初始化日志
logger = setup_logger()

app = Flask(__name__)
home_path = "../envs"
config_path = "../config.yaml"
map_link = os.path.abspath('../map')

GMAPPING_CMD = "roslaunch wpr_simulation wpb_gmapping.launch"
MAP_SAVE_CMD = "rosrun map_server map_saver -f "
#ROSBRIDGE_CMD = 'roslaunch rosbridge_server rosbridge_websocket.launch'
NAVIGATION_CMD = 'roslaunch wpr_simulation wpb_demo_nav.launch'
PLAN_MANAGER_CMD = 'bash ../plan/plan_manager.sh'

# for wheeltec
GMAPPING_CMD = 'roslaunch turn_on_wheeltec_robot mapping.launch'
NAVIGATION_CMD = 'roslaunch turn_on_wheeltec_robot navigation.launch'

# 确保配置文件存在
def ensure_config_exists():
    logger.info("检查配置文件是否存在")
    if not os.path.exists(config_path):
        logger.info("配置文件不存在，创建默认配置")
        config = {
            'metamee_ws': 'ws://192.168.0.156:8080/metamee/ws'
            #'metamee_ws': 'ws://192.168.0.223:8080/metamee/ws'
        }
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        logger.debug("创建默认配置: %s", config)
    return load_config()

# 加载配置文件
def load_config():
    try:
        logger.info("加载配置文件")
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            logger.debug("加载的配置: %s", config)
            return config
    except Exception as e:
        logger.error("加载配置文件失败: %s", str(e))
        logger.error(traceback.format_exc())
        return {}

# 保存配置文件
def save_config(config):
    try:
        logger.info("保存配置文件")
        logger.debug("保存的配置: %s", config)
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode = True)
        logger.info("配置文件保存成功")
    except Exception as e:
        logger.error("保存配置文件失败: %s", str(e))
        logger.error(traceback.format_exc())

# 确保环境目录存在
def ensure_env_dir(home_path):
    logger.info("检查环境目录是否存在: %s", home_path)
    if not os.path.exists(home_path):
        logger.info("环境目录不存在，创建目录: %s", home_path)
        try:
            os.makedirs(home_path)
            logger.info("环境目录创建成功")
        except Exception as e:
            logger.error("创建环境目录失败: %s", str(e))
            logger.error(traceback.format_exc())

# 获取地图列表
def get_maps(home_path):
    logger.info("获取地图列表，路径: %s", home_path)
    maps = []
    try:
        if os.path.exists(home_path):
            for item in os.listdir(home_path):
                item_path = os.path.join(home_path, item)
                if os.path.isdir(item_path):
                    map_yaml_exists = os.path.exists(os.path.join(item_path, 'map.yaml'))
                    map_pgm_exists = os.path.exists(os.path.join(item_path, 'map.pgm'))
                    waypoints_exists = os.path.exists(os.path.join(item_path, 'waypoints.json'))
                    
                    map_info = {
                        'name': item,
                        'has_map_yaml': map_yaml_exists,
                        'has_map_pgm': map_pgm_exists,
                        'has_waypoints': waypoints_exists
                    }
                    maps.append(map_info)
                    logger.debug("找到地图: %s, yaml: %s, pgm: %s, waypoints: %s", 
                                item, map_yaml_exists, map_pgm_exists, waypoints_exists)
        logger.info("共找到 %d 个地图", len(maps))
        return maps
    except Exception as e:
        logger.error("获取地图列表失败: %s", str(e))
        logger.error(traceback.format_exc())
        return []

# 获取当前地图
def get_current_map(home_path):
    logger.info("获取当前地图")
    current_map = None
    try:
        if os.path.exists(map_link) and os.path.islink(map_link):
            target = os.readlink(map_link)
            current_map = os.path.basename(target)
            logger.info("当前地图: %s, 链接目标: %s", current_map, target)
        else:
            logger.info("未找到地图软链接或不是有效的软链接")
    except Exception as e:
        logger.error("获取当前地图失败: %s", str(e))
        logger.error(traceback.format_exc())
    
    return current_map

# 切换地图
def switch_map(home_path, map_name):
    logger.info("切换地图: %s", map_name)
    map_path = os.path.abspath(os.path.join(home_path, map_name))
    
    # 检查目标地图是否存在
    if not os.path.exists(map_path):
        logger.error("地图文件夹不存在: %s", map_path)
        return False, "地图文件夹不存在"
    
    # 如果软链接已存在，先删除
    try:
        if os.path.islink(map_link):
            logger.info("删除现有软链接: %s", map_link)
            os.unlink(map_link)
        # 创建新的软链接
        logger.info("创建新的软链接: %s -> %s", map_link, map_path)
        os.symlink(map_path, map_link)
        logger.info("地图切换成功")
        return True, "地图切换成功"
    except Exception as e:
        logger.error("切换地图失败: %s", str(e))
        logger.error(traceback.format_exc())
        return False, str(e)

# 检查进程是否运行
def is_process_running(process_name):
    logger.debug("检查进程是否运行: %s", process_name)
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'])
            if process_name in cmdline:
                logger.debug("进程正在运行: %s, PID: %s", process_name, proc.info['pid'])
                return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            logger.debug("检查进程时出现异常: %s", str(e))
            pass
    logger.debug("进程未运行: %s", process_name)
    return False, None

# 启动进程
def start_process(cmd):
    logger.info("启动进程: %s", cmd)
    try:
        process = subprocess.Popen(cmd, shell=True)
        logger.info("进程启动成功, PID: %s", process.pid)
        return True, process.pid
    except Exception as e:
        logger.error("启动进程失败: %s", str(e))
        logger.error(traceback.format_exc())
        return False, str(e)

# 停止进程
def stop_process(process_name):
    logger.info("停止进程: %s", process_name)
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'])
            if process_name in cmdline:
                logger.info("找到进程，准备终止: %s, PID: %s", process_name, proc.info['pid'])
                os.kill(proc.info['pid'], signal.SIGTERM)  # 可按需要进行修改
                logger.info("进程已终止")
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            logger.debug("检查进程时出现异常: %s", str(e))
            pass
    logger.warning("未找到要停止的进程: %s", process_name)
    return False

# 获取本机IP地址
def get_local_ip():
    logger.info("获取本机IP地址")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        logger.info("获取到本机IP: %s", ip)
        return ip
    except Exception as e:
        logger.error("获取本机IP失败: %s", str(e))
        logger.error(traceback.format_exc())
        logger.info("使用默认IP: 127.0.0.1")
        return '127.0.0.1'

# 路由：主页
@app.route('/')
def index():
    logger.info("访问主页")
    try:
        config = ensure_config_exists()
        metamee_ws = config.get('metamee_ws', 'ws://192.168.0.156:8080/metamee/ws')
        
        ensure_env_dir(home_path)
        maps = get_maps(home_path)
        current_map = get_current_map(home_path)
        
        # 检查建图进程状态
        logger.info("检查建图进程状态")
        gmapping_running, gmapping_pid = is_process_running(GMAPPING_CMD)
        #rosbridge_gmapping_running, rosbridge_gmapping_pid = is_process_running(ROSBRIDGE_CMD)
        mapping_status = gmapping_running #and rosbridge_gmapping_running
        #logger.info("建图状态: %s (gmapping: %s, rosbridge: %s)", 
        #           mapping_status, gmapping_running, rosbridge_gmapping_running)
        logger.info("建图状态: gmapping: %s, pid: %s)" , gmapping_running, gmapping_pid) 
        
        # 检查导航进程状态
        logger.info("检查导航进程状态")
        nav_running, nav_pid = is_process_running(NAVIGATION_CMD)
        plan_manager_running, plan_manager_pid = is_process_running(PLAN_MANAGER_CMD)
        #rosbridge_nav_running, rosbridge_nav_pid = is_process_running(ROSBRIDGE_CMD)
        nav_status = nav_running and plan_manager_running #and rosbridge_nav_running
        #logger.info("导航状态: %s (nav: %s, plan_manager: %s, rosbridge: %s)", 
        #           nav_status, nav_running, plan_manager_running, rosbridge_nav_running)
        logger.info("导航状态: %s (nav: %s, plan_manager: %s) pid: (%s, %s)", 
                   nav_status, nav_running, plan_manager_running, nav_pid, plan_manager_pid)
        
        logger.info("渲染主页模板")
        return render_template('index.html', 
                            metamee_ws=metamee_ws, 
                            maps=maps, 
                            current_map=current_map,
                            mapping_status=mapping_status,
                            nav_status=nav_status)
    except Exception as e:
        logger.error("主页渲染失败: %s", str(e))
        logger.error(traceback.format_exc())
        return "服务器内部错误，请查看日志", 500

# 路由：保存配置
@app.route('/save_config', methods=['POST'])
def save_config_route():
    logger.info("保存配置请求")
    try:
        metamee_ws = request.form.get('metamee_ws')
        config = {
            'metamee_ws': metamee_ws.encode('ascii', 'ignore')
        }
        
        save_config(config)
        ensure_env_dir(home_path)
        
        logger.info("配置保存成功，重定向到主页")
        return redirect(url_for('index'))
    except Exception as e:
        logger.error("保存配置失败: %s", str(e))
        logger.error(traceback.format_exc())
        return "服务器内部错误，请查看日志", 500

# 路由：切换地图
@app.route('/switch_map', methods=['POST'])
def switch_map_route():
    logger.info("切换地图请求")
    try:
        map_name = request.form.get('map_name')
        
        logger.info("切换地图参数: home_path=%s, map_name=%s", home_path, map_name)
        
        success, message = switch_map(home_path, map_name)
        
        logger.info("切换地图结果: success=%s, message=%s", success, message)
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error("切换地图失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

# 路由：启动建图
@app.route('/start_mapping', methods=['POST'])
def start_mapping():
    logger.info("启动建图请求")
    try:
        # 启动建图进程
        logger.info("启动 wpb_gmapping.launch")
        success1, result1 = start_process(GMAPPING_CMD)
        logger.info("启动 rosbridge_websocket.launch")
        #success2, result2 = start_process(ROSBRIDGE_CMD)
        
        success = success1 #and success2
        message = "建图启动成功" if success else "建图启动失败"
        
        logger.info("启动建图结果: success=%s, message=%s", success, message)
        #if not success:
        #    logger.error("启动失败详情: wpb_gmapping=%s, rosbridge=%s", result1, result2)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error("启动建图失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

# 路由：停止建图
@app.route('/stop_mapping', methods=['POST'])
def stop_mapping():
    logger.info("停止建图请求")
    try:
        # 停止建图进程
        logger.info("停止 wpb_gmapping.launch")
        success1 = stop_process(GMAPPING_CMD)
        #logger.info("停止 rosbridge_websocket.launch")
        #success2 = stop_process(ROSBRIDGE_CMD)
        
        success = success1 #and success2
        message = "建图停止成功" if success else "建图停止失败"
        
        logger.info("停止建图结果: success=%s, message=%s", success, message)
        #if not success:
        #    logger.warning("停止失败详情: wpb_gmapping=%s, rosbridge=%s", success1, success2)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error("停止建图失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

# 路由：保存地图文件
@app.route('/save_map_file', methods=['POST'])
def save_map_file():
    logger.info("保存地图请求")
    try:
        # 生成地图名称（使用当前日期）
        import datetime
        file_name = "map"
        map_path = os.path.abspath(os.path.join("..", 'map'))
        
        logger.info("保存地图: home_path=%s, file_name=%s, map_path=%s", home_path, file_name, map_path)
        
        # 保存地图
        cmd = MAP_SAVE_CMD + os.path.join(map_path, file_name)
        logger.info("执行保存地图命令: %s", cmd)
        success, result = start_process(cmd)
        
        message = "地图保存成功" if success else "地图保存失败"
        
        logger.info("保存地图结果: success=%s, message=%s", success, message)
        if not success:
            logger.error("保存地图失败详情: %s", result)
        
        return jsonify({'success': success, 'message': message, 'file_name': file_name})
    except Exception as e:
        logger.error("保存地图失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

# 路由：启动导航
@app.route('/start_navigation', methods=['POST'])
def start_navigation():
    logger.info("启动导航请求")
    try:
        # 启动导航进程
        logger.info("启动 wpb_demo_nav.launch")
        success1, result1 = start_process(NAVIGATION_CMD)
        logger.info("启动 plan_manager.py")
        success2, result2 = start_process(PLAN_MANAGER_CMD)
        logger.info("启动 rosbridge_websocket.launch")
        #success3, result3 = start_process(ROSBRIDGE_CMD)
        
        success = success1 and success2 #and success3
        message = "导航启动成功" if success else "导航启动失败"
        
        logger.info("启动导航结果: success=%s, message=%s", success, message)
        #if not success:
        #    logger.error("启动失败详情: wpb_demo_nav=%s, plan_manager=%s, rosbridge=%s", 
        #                result1, result2, result3)
        if not success:
            logger.error("启动失败详情: wpb_demo_nav=%s, plan_manager=%s", 
                        result1, result2)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error("启动导航失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

# 路由：停止导航
@app.route('/stop_navigation', methods=['POST'])
def stop_navigation():
    logger.info("停止导航请求")
    try:
        # 停止导航进程
        logger.info("停止 wpb_demo_nav.launch")
        success1 = stop_process(NAVIGATION_CMD)
        logger.info("停止 plan_manager.py")
        success2 = stop_process(PLAN_MANAGER_CMD)
        logger.info("停止 rosbridge_websocket.launch")
        #success3 = stop_process(ROSBRIDGE_CMD)
        
        success = success1 and success2 #and success3
        message = "导航停止成功" if success else "导航停止失败"
        
        logger.info("停止导航结果: success=%s, message=%s", success, message)
        #if not success:
        #    logger.warning("停止失败详情: wpb_demo_nav=%s, plan_manager=%s, rosbridge=%s", 
        #                  success1, success2, success3)
        if not success:
            logger.warning("停止失败详情: wpb_demo_nav=%s, plan_manager=%s", 
                          success1, success2)
        
        return jsonify({'success': success, 'message': message})
    except Exception as e:
        logger.error("停止导航失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

# 在app.py中添加以下路由函数（放在其他路由函数附近）

# 路由：创建新地图
@app.route('/create_map', methods=['POST'])
def create_map_route():
    logger.info("创建新地图请求")
    try:
        map_name = request.form.get('map_name')
        
        if not map_name:
            logger.error("地图名称为空")
            return jsonify({'success': False, 'message': "地图名称不能为空"})
        
        logger.info("创建新地图: home_path=%s, map_name=%s", home_path, map_name)
        
        # 确保环境目录存在
        ensure_env_dir(home_path)
        
        # 创建新地图目录
        map_path = os.path.join(home_path, map_name)
        if os.path.exists(map_path):
            logger.warning("地图目录已存在: %s", map_path)
            return jsonify({'success': False, 'message': "地图名称已存在"})
        
        try:
            os.makedirs(map_path)
            logger.info("地图目录创建成功: %s", map_path)
            
            # 切换到新地图
            success, message = switch_map(home_path, map_name)
            if success:
                logger.info("自动切换到新地图成功")
                return jsonify({'success': True, 'message': "新地图创建成功并已切换"})
            else:
                logger.warning("自动切换到新地图失败: %s", message)
                return jsonify({'success': True, 'message': "新地图创建成功，但切换失败: " + message})
        except Exception as e:
            logger.error("创建地图目录失败: %s", str(e))
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'message': "创建地图目录失败: " + str(e)})
    except Exception as e:
        logger.error("创建新地图失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

# 路由：删除地图
@app.route('/delete_map', methods=['POST'])
def delete_map_route():
    logger.info("删除地图请求")
    try:
        map_name = request.form.get('map_name')
        
        if not map_name:
            logger.error("地图名称为空")
            return jsonify({'success': False, 'message': "地图名称不能为空"})
        
        logger.info("删除地图: home_path=%s, map_name=%s", home_path, map_name)
        
        # 检查地图目录是否存在
        map_path = os.path.join(home_path, map_name)
        if not os.path.exists(map_path):
            logger.warning("地图目录不存在: %s", map_path)
            return jsonify({'success': False, 'message': "地图不存在"})
        
        # 检查是否为当前地图
        current_map = get_current_map(home_path)
        if current_map == map_name:
            logger.warning("无法删除当前正在使用的地图")
            return jsonify({'success': False, 'message': "无法删除当前正在使用的地图，请先切换到其他地图"})
        
        try:
            # 删除地图目录及其内容
            import shutil
            shutil.rmtree(map_path)
            logger.info("地图目录删除成功: %s", map_path)
            return jsonify({'success': True, 'message': "地图删除成功"})
        except Exception as e:
            logger.error("删除地图目录失败: %s", str(e))
            logger.error(traceback.format_exc())
            return jsonify({'success': False, 'message': "删除地图目录失败: " + str(e)})
    except Exception as e:
        logger.error("删除地图失败: %s", str(e))
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': "服务器内部错误: " + str(e)})

if __name__ == '__main__':
    # 确保配置文件存在
    ensure_config_exists()
    
    port = 8080
    host = "0.0.0.0"
    logger.info("=== 环境管理应用启动 ===")
    logger.info("服务地址: http://{}:{}".format(host, port))
    print("环境管理应用启动在 http://{}:{}".format(host, port))
    
    try:
        # 使用pywsgi启动服务
        logger.info("使用pywsgi启动服务")
        http_server = WSGIServer((host, port), app, log=logger)
        http_server.serve_forever()
    except Exception as e:
        logger.critical("服务启动失败: %s", str(e))
        logger.critical(traceback.format_exc())
        print("服务启动失败: {}".format(str(e)))

