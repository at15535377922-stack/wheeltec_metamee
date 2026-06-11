#!/usr/bin/env python
# -*- coding: utf-8 -*-
import websocket
import json
import time
import threading

WS_URL = "ws://localhost:8083"


def on_message(ws, message):
    print("<<< " + message)


def on_error(ws, error):
    print("错误: " + str(error))


def on_close(ws, *args):
    print("连接关闭")


def on_open(ws):
    print("连接建立，发送 goto 请求...")

    def send_loop():
        msg = json.dumps({"method": "goto", "args": "{\"name\": \"海外市场展区\"}"})
        print(">>> " + msg)
        ws.send(msg)

        # 长连接：等待 5 秒后再发一次，演示连接保持
        time.sleep(5)
        print("再次发送...")
        ws.send(msg)

    t = threading.Thread(target=send_loop)
    t.daemon = True
    t.start()


if __name__ == "__main__":
    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    print("连接到 " + WS_URL)
    ws.run_forever()
