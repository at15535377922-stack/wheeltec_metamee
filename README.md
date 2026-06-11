# 🤖 Metamee — 机器人导航与智能服务系统

基于 ROS 的移动机器人导航管理平台，集成地图管理、任务计划执行、语音交互与 AI 对话能力。

---

## 📋 目录

- [项目简介](#项目简介)
- [系统架构](#系统架构)
- [功能模块](#功能模块)
- [目录结构](#目录结构)
- [快速开始](#快速开始)
- [API 文档](#api-文档)
- [配置说明](#配置说明)
- [地图管理](#地图管理)

---

## 项目简介

Metamee 是一个运行在 Wheeltec 机器人平台上的综合服务系统，主要提供：

- 🗺️ **地图与环境管理** — 多套地图的创建、切换、保存
- 🤖 **ROS 导航控制** — 建图与自主导航的启停管理
- 📋 **任务计划执行** — 按步骤执行导航 + 语音 + 等待的组合任务
- 🎙️ **AI 语音交互** — 语音唤醒 → 识别 → LLM 对话 → 语音播报
- 🌐 **Web 管理界面** — 浏览器可视化控制面板

---

## 系统架构

```
用户浏览器 / 语音输入
        │
        ├── [app] :8080  ─── 地图管理 & ROS 进程控制
        │       │
        │       ├── 启动/停止 roslaunch mapping.launch
        │       ├── 启动/停止 roslaunch navigation.launch
        │       └── 管理 map → envs/xxx 软链接
        │
        ├── [plan] :8082  ── 任务计划执行引擎
        │       │
        │       ├── 加载/执行 JSON 任务计划
        │       ├── NavigationManager → ROS move_base → 机器人
        │       └── WaypointsManager ↔ /metamee/waypoints
        │
        └── [mcp_server]  ── AI 语音服务层
                │
                ├── SherpaListener (唤醒词检测)
                ├── TencentAsrClient (语音识别)
                ├── MCPClient + LLMClient (AI 对话)
                ├── ByteDanceTtsClient (语音合成)
                └── FastMCP ToolServer (MCP 工具服务)
```

---

## 功能模块

### 🌐 `app/` — Web 环境管理服务 (端口 8080)

基于 Flask + gevent 的 Web 后端，负责整个系统的环境编排。

**主要功能：**
- 展示、创建、切换、删除地图环境
- 通过 shell 命令控制 ROS 建图与导航进程
- 保存地图文件（调用 `map_server map_saver`）
- 管理当前活动地图（通过软链接 `map → envs/<name>`）
- 启停任务计划管理器

**核心 ROS 命令：**
```bash
roslaunch turn_on_wheeltec_robot mapping.launch
roslaunch turn_on_wheeltec_robot navigation.launch
rosrun map_server map_saver -f <map_dir>/map
```

---

### 📋 `plan/` — 任务计划执行引擎 (端口 8082)

基于 Flask + rospy + actionlib，负责机器人任务的编排与执行。

**任务计划由 JSON 定义，支持三种步骤类型：**

| 步骤类型 | 说明 |
|----------|------|
| `navigation` | 导航到指定航点 |
| `speech` | 播报指定语音内容 |
| `sleep` | 等待指定秒数 |

**示例计划 JSON：**
```json
{
  "steps": [
    {"type": "navigation", "waypoint": "reception"},
    {"type": "speech", "text": "您好，欢迎光临"},
    {"type": "sleep", "duration": 3},
    {"type": "navigation", "waypoint": "home"}
  ]
}
```

**核心组件：**
- `PlanManager` — 计划加载、执行、暂停、恢复、停止
- `NavigationManager` — ROS `move_base` 动作客户端封装
- `WaypointsManager` — 航点的加载、发布与保存

**ROS 通信：**
- 动作：`move_base` (`MoveBaseAction`)
- 话题发布：`/metamee/waypoints` (`std_msgs/String`)
- 话题发布：`/metamee/status_command` (`std_msgs/String`)

---

### 🎙️ `mcp_server/` — AI 语音与工具服务层

基于 Python 3 + asyncio，提供语音交互与 AI 工具能力。

**语音交互流程：**
```
麦克风音频流
    → SherpaListener (本地唤醒词检测: "百应百应")
    → TencentAsrClient (腾讯云实时语音识别)
    → MCPClient → LLM 对话 (通过 SSE 协议)
    → ByteDanceTtsClient (字节跳动语音合成)
    → Speaker (音频播放)
```

**MCP 工具服务：**
- `mcp_server.py` — 基于 FastMCP 的工具服务端
- `server.py` — 基于 Starlette 的 SSE/MCP 服务端
- 工具模块动态加载自 `pkg/tools/`

**配置文件：** `mcp_server/config/config.yaml`（见下方配置说明）

---

### 🌍 `slam/` — SLAM 可视化前端

Flutter Web 编译产物，用于地图可视化与 SLAM 过程展示，通过 Python 简单 HTTP 服务器托管（端口 8081）。

---

### 🗂️ `envs/` — 地图环境数据库

每套环境独立存储，包含：

```
envs/<环境名>/
├── map.pgm          # 栅格地图图像（二进制）
├── map.yaml         # 地图元数据（分辨率、原点等）
└── waypoints.json   # 航点坐标列表
```

---

## 目录结构

```
metamee/
├── README.md
├── .gitignore
├── config.yaml              # 根配置 (metamee_ws WebSocket 地址)
├── start.sh                 # 一键启动脚本
├── metamee.service          # systemd 服务文件
│
├── app/                     # Web 环境管理服务
│   ├── app.py
│   ├── templates/index.html
│   └── static/
│
├── plan/                    # 任务计划执行引擎
│   ├── plan_manager.py      # 主服务
│   ├── nav_manager.py       # ROS 导航封装
│   ├── waypoints_manager.py # 航点管理
│   └── plans/               # JSON 计划文件存储
│
├── mcp_server/              # AI 语音与工具服务
│   ├── main.py              # 语音交互主程序
│   ├── mcp_server.py        # FastMCP 工具服务端
│   ├── server.py            # Starlette SSE 服务端
│   ├── config/
│   │   ├── config.yaml      # 密钥与配置（不含于版本控制）
│   │   └── config.yaml.example  # 配置模板
│   └── pkg/                 # 功能包
│       ├── asr/             # 语音识别
│       ├── tts/             # 语音合成
│       ├── mic/             # 麦克风 & 唤醒词
│       ├── player/          # 音频播放
│       ├── mcp/             # MCP 客户端 & LLM
│       ├── service/         # 工具服务发现
│       └── tools/           # MCP 工具模块
│
├── slam/                    # Flutter Web SLAM 可视化
└── envs/                    # 地图环境数据库
    ├── office/
    ├── hall/
    ├── map905/
    └── ...
```

---

## 快速开始

### 环境要求

- Ubuntu 18.04 (ARM64)
- ROS Melodic
- Python 2.7（`app/`、`plan/` 模块）
- Python 3.6+（`mcp_server/` 模块）
- Wheeltec 机器人 ROS 功能包

### 启动服务

```bash
cd ~/metamee
bash start.sh
```

`start.sh` 会依次启动：
1. SLAM 可视化服务（端口 8081）
2. Web 环境管理服务（端口 8080）

任务计划服务（端口 8082）由 `app` 服务在导航启动时自动拉起。

### 配置 mcp_server

```bash
cd ~/metamee/mcp_server/config
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入真实的 API 密钥
```

启动 AI 语音服务：

```bash
cd ~/metamee/mcp_server
python main.py
```

---

## API 文档

### app 服务 (`:8080`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web 管理界面 |
| POST | `/switch_map` | 切换当前地图 |
| POST | `/start_mapping` | 开始建图 |
| POST | `/stop_mapping` | 停止建图 |
| POST | `/save_map_file` | 保存地图文件 |
| POST | `/start_navigation` | 开始导航 |
| POST | `/stop_navigation` | 停止导航 |
| POST | `/create_map` | 创建新地图环境 |
| POST | `/delete_map` | 删除地图环境 |
| POST | `/save_config` | 保存配置 |

### plan 服务 (`:8082`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/plans` | 获取所有计划列表 |
| GET | `/api/plans/<name>` | 获取指定计划详情 |
| POST | `/api/plans/<name>` | 创建/更新计划 |
| DELETE | `/api/plans/<name>` | 删除计划 |
| POST | `/api/plans/<name>/run` | 执行计划 |
| POST | `/api/plans/<name>/pause` | 暂停执行 |
| POST | `/api/plans/<name>/resume` | 恢复执行 |
| GET | `/api/status` | 获取执行状态 |
| GET | `/api/waypoints` | 获取所有航点 |
| POST | `/api/plans/<name>/execute_step` | 执行单步 |

---

## 配置说明

### 根配置 `config.yaml`

```yaml
metamee_ws: ws://192.168.0.61:5050/metamee/ws
```

### mcp_server 配置 `mcp_server/config/config.yaml`

参考 `config.yaml.example`：

```yaml
model:
  model_name: qwen3-max
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
  api_key: YOUR_DASHSCOPE_API_KEY

navi:
  base_url: http://127.0.0.1:8082

sherpa:
  base_dir: /home/wheeltec/metamee/mcp_server/sherpa-onnx
  keywords: ["百应百应", "百应"]
  keyword_score: 3
  keyword_threshold: 0.05

tencent:
  appid: "YOUR_TENCENT_APPID"
  secret_id: "YOUR_TENCENT_SECRET_ID"
  secret_key: "YOUR_TENCENT_SECRET_KEY"

google:
  api_key: YOUR_GOOGLE_API_KEY
```

---

## 地图管理

航点文件格式 (`waypoints.json`)：

```json
[
  {
    "name": "reception",
    "x": 1.23,
    "y": 4.56,
    "theta": 0.0
  },
  {
    "name": "home",
    "x": 0.0,
    "y": 0.0,
    "theta": 0.0
  }
]
```

---

## 注意事项

- ⚠️ `mcp_server/config/config.yaml` 包含 API 密钥，**不纳入版本控制**，请勿提交
- ⚠️ `envs/**/*.pgm` 地图图像文件较大，**不纳入版本控制**
- ⚠️ `.venv/` 虚拟环境目录**不纳入版本控制**
