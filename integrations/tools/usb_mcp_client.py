#!/usr/bin/env python3
"""通过 USB 数据线直接调派蒙的 MCP 工具，不需要 Wi-Fi。

前置：设备刷了带 UsbMcpStart() 的固件（feature/integration），
数据线接的是 USB-C 数据口，串口出现在 /dev/cu.usbmodem1101。

用法：
  python3 usb_mcp_client.py '{"tool":"self.led.set_color","arguments":{"r":255,"g":0,"b":0}}'
  python3 usb_mcp_client.py '{"method":"tools/list","params":{}}'
  python3 usb_mcp_client.py --port /dev/cu.usbmodem1101 --timeout 10 \
      '{"tool":"self.led.status","arguments":{}}'

响应是设备打印的 __MCP_RESULT__ 前缀行，本脚本会解析并只输出可读文本。
"""
from __future__ import annotations

import argparse
import json
import sys
import time

DEFAULT_PORT = "/dev/cu.usbmodem1101"
PREFIX = "__MCP_RESULT__"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request", help="一行 JSON：{\"tool\":...,\"arguments\":{...}} 或标准 JSON-RPC")
    ap.add_argument("--port", default=DEFAULT_PORT)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--timeout", type=float, default=10.0)
    a = ap.parse_args()

    try:
        req = json.loads(a.request)
    except json.JSONDecodeError as e:
        print(f"请求不是合法 JSON: {e}", file=sys.stderr)
        return 2

    try:
        import serial
    except ImportError:
        print("需要 pyserial：用系统 python3 跑，或 pip install pyserial", file=sys.stderr)
        return 2

    ser = serial.Serial(a.port, a.baud, timeout=0.2)
    # 清掉缓冲里可能残留的日志行
    time.sleep(0.2)
    ser.reset_input_buffer()
    ser.write((json.dumps(req, ensure_ascii=False) + "\n").encode())
    ser.flush()

    deadline = time.time() + a.timeout
    while time.time() < deadline:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode(errors="replace").rstrip()
        if not line.startswith(PREFIX):
            continue
        payload = line[len(PREFIX):]
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            print(payload)
            ser.close()
            return 1
        if "error" in msg:
            print("ERROR:", msg["error"])
            ser.close()
            return 1
        content = msg.get("result", {}).get("content", [])
        for item in content:
            if item.get("type") == "text":
                print(item.get("text", ""))
            elif item.get("type") == "image":
                print("(image content)")
        if not content:
            print(json.dumps(msg.get("result", {}), ensure_ascii=False))
        ser.close()
        return 0

    print(f"超时 {a.timeout}s 没收到 {PREFIX} 响应。检查：设备是否刷了带 USB 桥的固件、串口是否被别的程序占用。", file=sys.stderr)
    ser.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
