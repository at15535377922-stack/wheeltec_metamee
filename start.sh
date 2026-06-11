#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
. /home/wheeltec/.bashrc
#roslaunch rosbridge_server rosbridge_websocket.launch >> /dev/null 2>&1 &
cd slam
python -m SimpleHTTPServer 8081 >>/dev/null 2>&1 &
cd ..
cd app
python app.py >> app.log 2>&1
