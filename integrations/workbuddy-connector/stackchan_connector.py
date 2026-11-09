"""Stack-chan MCP connector for WorkBuddy 自定义连接器.

把桌面机器人派蒙（Stack-chan）的本地控制接口包装成 MCP 连接器，让 WorkBuddy
通过「连接器 → 自定义连接器」挂载后，直接在聊天里指挥派蒙。

两条能力线：
  A. 旧接口（任何固件都能用，向后兼容）
     notify_attention / notify_dismiss / robot_status —— 走 /notify /dismiss /healthz
  B. 功能整合接口（需要刷 feature/integration 分支固件）
     device_tools / device_call + 一组易用的封装（表情、12 灯、头部、音量、亮度、
     拍照、gateway 配置）—— 走设备的 POST /mcp 通用 MCP 中继，同步拿返回值。

B 线不需要小智云、不需要 Qoder、不需要本地 WebSocket gateway：设备 :8788 直接把
JSON-RPC 交给 McpServer，工具执行结果经 ResultSink 同步回 HTTP 调用方。

在 WorkBuddy「连接器 → 自定义连接器」里用如下配置安装：
{
  "mcpServers": {
    "stackchan": {
      "type": "stdio",
      "command": "python3",
      "args": ["$REPO/integrations/workbuddy-connector/bridge/stackchan_connector.py"],
      "env": {"STACKCHAN_URL": "http://192.168.1.50:8788"},
      "description": "桌面机器人派蒙：提醒/表情/灯效/头部动作/状态/配置"
    }
  }
}

前置条件：HTTP 模式下 Mac 与机器人需在同一网段；USB 模式（数据线）不需要。

环境变量:
  STACKCHAN_TRANSPORT       — http（默认，走 :8788）| usb（USB 数据线，走串口 JSON-RPC）
  STACKCHAN_URL             — HTTP 模式下的服务地址（默认 http://192.168.1.50:8788）
  STACKCHAN_SERIAL          — USB 模式下的串口（默认 /dev/cu.usbmodem1101）
  STACKCHAN_SERIAL_BAUD     — USB 模式下的波特率（默认 115200）
  STACKCHAN_CONNECTOR_HTTP  — 置 1 时改以 streamable-http 模式跑在 127.0.0.1:8790
                              （给只支持 HTTP 接入的宿主用；默认 stdio）

USB 模式（STACKCHAN_TRANSPORT=usb）完全不依赖 Wi-Fi：Mac 不在设备网段时
也能用全部 22 个工具。需要 pyserial。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from mcp.server.fastmcp import FastMCP

STACKCHAN_URL = os.environ.get("STACKCHAN_URL", "http://192.168.1.50:8788")  # 改成你的设备 IP
TIMEOUT_SECS = 12

# 传输层：http（默认，走 :8788）或 usb（USB 数据线，走串口 JSON-RPC）。
# USB 模式完全不需要 Wi-Fi，适合 Mac 不在设备网段时。
TRANSPORT = os.environ.get("STACKCHAN_TRANSPORT", "http").strip().lower()
SERIAL_PORT = os.environ.get("STACKCHAN_SERIAL", "/dev/cu.usbmodem1101")
SERIAL_BAUD = int(os.environ.get("STACKCHAN_SERIAL_BAUD", "115200"))
RESULT_PREFIX = "__MCP_RESULT__"

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("stackchan-connector")

mcp = FastMCP("stackchan")

_serial_lock = threading.Lock()


def _usb_request(payload: dict[str, Any]) -> tuple[bool, str, int]:
    """通过 USB 串口发一行 JSON，读回一行 __MCP_RESULT__ 响应。

    每次调用开关串口（约 0.2s 开销），不长期独占，这样 WorkBuddy 连接器和
    命令行调试工具可以共存。返回 (ok, body, status)，status=0 表示传输失败。
    """
    with _serial_lock:
        ser = None
        try:
            import serial  # pyserial

            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=0.2)
            time.sleep(0.15)
            try:
                ser.reset_input_buffer()
            except Exception:
                pass
            ser.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
            ser.flush()
            deadline = time.time() + TIMEOUT_SECS
            while time.time() < deadline:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode(errors="replace").rstrip()
                if line.startswith(RESULT_PREFIX):
                    return True, line[len(RESULT_PREFIX):], 200
            return False, f"串口 {TIMEOUT_SECS}s 内没有收到 {RESULT_PREFIX} 响应", 0
        except Exception as e:
            return False, f"{type(e).__name__}: {e}", 0
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass


def _usb_call(tool: str, arguments: dict[str, Any] | None = None) -> tuple[bool, str, int]:
    return _usb_request({"tool": tool, "arguments": arguments or {}})

_OLD_FIRMWARE_HINT = (
    "设备返回 404：当前固件只有 /notify、/dismiss、/healthz，没有 /mcp。"
    "需要刷 fork 的 feature/integration 分支固件（回滚包仍在 qchan/）。"
)


def _post(path: str, payload: dict | None = None) -> tuple[bool, str, int]:
    url = f"{STACKCHAN_URL}{path}"
    data = json.dumps(payload).encode() if payload is not None else b"{}"
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
            return True, resp.read().decode(errors="replace"), resp.status
    except urllib.error.HTTPError as e:
        return False, e.read().decode(errors="replace"), e.code
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", 0


def _get(path: str) -> tuple[bool, str, int]:
    url = f"{STACKCHAN_URL}{path}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
            return True, resp.read().decode(errors="replace"), resp.status
    except urllib.error.HTTPError as e:
        return False, e.read().decode(errors="replace"), e.code
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", 0


def _offline(body: str) -> str:
    if TRANSPORT == "usb":
        return (f"❌ 派蒙叫不应（{body}）。检查：USB-C **数据线**插好没、"
                f"串口 {SERIAL_PORT} 是否被别的程序占用（如串口监视器）。")
    return f"❌ 派蒙叫不应（{body}）。检查：机器人开着没、Mac 和它是不是同一个 Wi-Fi（MyWiFi）。"


def _call(tool: str, arguments: dict[str, Any] | None = None) -> str:
    """调用设备上的任意 MCP 工具，返回可读文本。"""
    if TRANSPORT == "usb":
        ok, body, status = _usb_call(tool, arguments or {})
    else:
        ok, body, status = _post("/mcp", {"tool": tool, "arguments": arguments or {}})
    if status == 404:
        return _OLD_FIRMWARE_HINT
    if not ok:
        return _offline(body) if status == 0 else f"❌ 设备返回 HTTP {status}: {body}"
    try:
        msg = json.loads(body)
    except json.JSONDecodeError:
        return f"派蒙已执行，但返回不是合法 JSON: {body[:300]}"
    if "error" in msg:
        err = msg["error"]
        text = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        if text.startswith("Unknown tool"):
            return (f"❌ 派蒙的设备上没有「{tool}」这个工具。"
                    f"先调 device_tools 查可用工具名，不要自己编名字；"
                    f"派蒙只有身体能力（表情/灯/头部/拍照/音量/亮度），没有业务数据。")
        if text.startswith("Missing valid argument"):
            return (f"❌ 工具「{tool}」参数不全或类型不对（{text}）。"
                    f"调 device_tools 看该工具的 inputSchema 再传参。")
        return f"❌ 工具「{tool}」报错: {text}"
    try:
        content = msg["result"]["content"]
        parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        image_count = sum(1 for c in content if c.get("type") == "image")
        text = "\n".join(p for p in parts if p)
        if image_count:
            text += f"\n（另返回 {image_count} 张图片）"
        return text or "派蒙已执行（工具无返回内容）。"
    except (KeyError, TypeError):
        return f"派蒙已执行，原始响应: {body[:400]}"


# ── A 线：旧接口 ────────────────────────────────────────────────────────

@mcp.tool()
def notify_attention(project: str) -> str:
    """让桌面机器人派蒙吸引用户注意：摇头 3 次，屏幕钉住"等你确认：<project>"，直到 notify_dismiss。

    使用场景：需要用户回到电脑前做确认/审批/授权时（比如任务等用户拍板、权限等待批准），
    用户不盯屏幕也能看到是哪件事在等。闲聊、通知类消息不要用。

    Args:
        project: 等待确认的事项名，会显示在机器人屏幕上，例 "Q3 报告审批"
    """
    if TRANSPORT == "usb":
        r = _call("self.notify.attention", {"project": project})
        if r.startswith("❌"):
            return r
        return f"派蒙正在摇头提醒你确认「{project}」，屏幕上已钉住，处理完叫我清除。"
    ok, body, _ = _post("/notify", {"project": project})
    if ok:
        return f"派蒙正在摇头提醒你确认「{project}」，屏幕上已钉住，处理完叫我清除。"
    return _offline(body)


@mcp.tool()
def notify_dismiss() -> str:
    """让派蒙点头并清除屏幕上的"等你确认"提醒。在用户已回应/事项已处理完后调用。"""
    if TRANSPORT == "usb":
        r = _call("self.notify.dismiss")
        if r.startswith("❌"):
            return r
        return "派蒙点头，屏幕提醒已清掉。"
    ok, body, _ = _post("/dismiss")
    if ok:
        return "派蒙点头，屏幕提醒已清掉。"
    return _offline(body)


@mcp.tool()
def robot_status() -> str:
    """检查桌面机器人派蒙在不在线（连通性/健康检查），并报告是否已刷功能整合固件。"""
    if TRANSPORT == "usb":
        r = _call("self.get_device_status")
        if r.startswith("❌"):
            return f"派蒙不在线（USB 串口 {SERIAL_PORT}）❌ {r}"
        return f"派蒙在线（USB 数据线）✅ {r}"
    ok, body, _ = _get("/healthz")
    if not ok:
        return f"派蒙不在线 ❌（{body}）。它在 MyWiFi 网段的 192.168.1.50，确认 Mac 连的同一个 Wi-Fi。"
    try:
        mcp_ready = bool(json.loads(body).get("mcp"))
    except json.JSONDecodeError:
        mcp_ready = False
    suffix = "MCP 桥可用，表情/灯效/头部动作都能调。" if mcp_ready else "旧固件：只有提醒/清除能力，/mcp 不可用。"
    return f"派蒙在线 ✅ {body} —— {suffix}"


# ── B 线：通用 MCP 中继 ─────────────────────────────────────────────────

@mcp.tool()
def device_tools() -> str:
    """列出派蒙当前固件注册的全部 MCP 工具名与参数 schema。想用没封装过的能力时先查这个。"""
    if TRANSPORT == "usb":
        ok, body, status = _usb_request({"method": "tools/list", "params": {}})
    else:
        ok, body, status = _get("/tools")
    if status == 404:
        return _OLD_FIRMWARE_HINT
    if not ok:
        return _offline(body) if status == 0 else f"❌ 设备返回 HTTP {status}: {body}"
    try:
        tools = json.loads(body).get("result", {}).get("tools", [])
    except (json.JSONDecodeError, AttributeError):
        return f"无法解析工具列表: {body[:500]}"
    lines = [f"派蒙共有 {len(tools)} 个工具："]
    for t in tools:
        props = t.get("inputSchema", {}).get("properties", {})
        args = ", ".join(f"{k}:{v.get('type','?')}" for k, v in props.items()) or "无参数"
        lines.append(f"- {t.get('name')} ({args}) — {t.get('description','')[:110]}")
    nc = json.loads(body).get("result", {}).get("nextCursor")
    if nc:
        lines.append(f"（列表被 8KB 分页截断，后续游标：{nc}）")
    return "\n".join(lines)


@mcp.tool()
def device_call(tool: str, arguments: dict[str, Any] | None = None) -> str:
    """直接调用派蒙上的任意 MCP 工具（逃生舱）。

    ⚠️ 先用 device_tools 查名字和参数，**不要自己编工具名**。
    派蒙只有身体能力（表情 / 12 灯 / 头部舵机 / 摄像头 / 音量 / 亮度 /
    设备状态 / 网关配置），**没有存储、数据库或业务数据**。用户说
    「查 XX 资料/库存/记录」时不要调设备工具，直接说明做不到，或改用
    WorkBuddy 侧的数据工具。

    常见名字：self.face.expression、self.led.set_many、self.led.pattern、
    self.head.move、self.get_device_status、self.camera.take_photo、
    self.gateway_config.get、self.led.status。

    Args:
        tool: 设备侧工具全名，例 "self.head.move"
        arguments: 参数字典，例 {"yaw": 20, "pitch": 35}；无参数时不填
    """
    return _call(tool, arguments)


# ── B 线：表情 ──────────────────────────────────────────────────────────

@mcp.tool()
def set_face(emotion: str) -> str:
    """让派蒙显示一个表情。可用名字：neutral, happy, laughing, funny, sad, crying,
    angry, loving, embarrassed, surprised, shocked, thinking, winking, cool,
    relaxed, delicious, kissy, confident, sleepy, silly, confused。
    部分表情会连带点头/摇头和情绪灯。不确定的名字会被安全忽略。"""
    return _call("self.face.expression", {"emotion": emotion})


@mcp.tool()
def face_overlay(name: str) -> str:
    """在当前表情上叠一层小特效，不换表情。可用：none, heart_eyes, tear,
    kiss_heart, cheek_blush, cool_glasses, excl_mark, think_bubble, star_burst,
    wave_squiggle, drool, laugh_lines, question_mark, zzz。none 表示清除。"""
    return _call("self.face.overlay", {"name": name})


# ── B 线：12 颗 RGB 灯 ──────────────────────────────────────────────────

@mcp.tool()
def set_led_color(r: int, g: int, b: int) -> str:
    """把 12 颗灯统一设成一个 RGB 颜色（各 0-255）。"""
    return _call("self.led.set_color", {"r": r, "g": g, "b": b})


@mcp.tool()
def set_leds(colors: str, brightness: int = 100) -> str:
    """逐颗设置 12 颗灯，可做渐变/分区配色。

    Args:
        colors: 逗号分隔的十六进制颜色，例 "#ff0000,#ff8800,#ffff00"；
                最多 12 个，不足时剩下的灯沿用最后一个颜色。
        brightness: 整体亮度 0-100，默认 100
    """
    return _call("self.led.set_many", {"colors": colors, "brightness": brightness})


@mcp.tool()
def led_pattern(name: str, speed_ms: int = 120) -> str:
    """跑一个内置灯效动画：rainbow（旋转彩虹）、breath（白色呼吸）、
    chase（橙色跑马灯）、off（停动画）。speed_ms 为每帧间隔 40-2000。"""
    return _call("self.led.pattern", {"name": name, "speed_ms": speed_ms})


@mcp.tool()
def led_auto() -> str:
    """停掉手动灯效，回到「跟表情联动」的自动灯光模式。"""
    return _call("self.led.auto")


# ── B 线：头部动作 ──────────────────────────────────────────────────────

@mcp.tool()
def move_head(yaw: int, pitch: int) -> str:
    """把派蒙的头转到指定角度并保持（会暂停人脸追踪，直到 head_center）。

    Args:
        yaw: -45 到 45，负数向左、正数向右、0 正中
        pitch: 5 到 60，小=低头、大=抬头，30 是平视
    """
    return _call("self.head.move", {"yaw": yaw, "pitch": pitch})


@mcp.tool()
def head_center() -> str:
    """让派蒙的头回正，并恢复人脸追踪。用完 move_head 之后要调这个解锁。"""
    return _call("self.head.center")


@mcp.tool()
def nod() -> str:
    """派蒙点头（同意/打招呼/确认）。"""
    return _call("self.head.nod")


@mcp.tool()
def shake() -> str:
    """派蒙摇头（否定/不同意/拒绝）。"""
    return _call("self.head.shake")


@mcp.tool()
def tilt() -> str:
    """派蒙歪头卖萌（被摸头时的那个动作）。"""
    return _call("self.head.tilt")


@mcp.tool()
def head_angles() -> str:
    """读派蒙头部最后一次指令角度（yaw / pitch，单位度）。"""
    return _call("self.head.get_angles")


# ── B 线：通用设备能力 ──────────────────────────────────────────────────

@mcp.tool()
def device_status() -> str:
    """读派蒙实时状态：电量、充电、音量、屏幕亮度、网络等 JSON。"""
    return _call("self.get_device_status")


@mcp.tool()
def set_volume(volume: int) -> str:
    """设置派蒙扬声器音量（0-100）。"""
    return _call("self.audio_speaker.set_volume", {"volume": volume})


@mcp.tool()
def set_brightness(brightness: int) -> str:
    """设置派蒙屏幕背光亮度（0-100）。"""
    return _call("self.screen.set_brightness", {"brightness": brightness})


@mcp.tool()
def take_photo(question: str = "描述一下你看到了什么") -> str:
    """让派蒙用摄像头拍一张照片并解释。

    注意：设备侧的 Explain() 需要先通过 MCP initialize 配置 vision URL/token，
    否则会返回错误；纯拍照能力本身不依赖云端。"""
    return _call("self.camera.take_photo", {"question": question})


@mcp.tool()
def gateway_config() -> str:
    """读派蒙当前的语音/WebSocket 端点配置（NVS），判断它连的是小智云还是自托管 gateway。"""
    return _call("self.gateway_config.get")


if __name__ == "__main__":
    if os.environ.get("STACKCHAN_CONNECTOR_HTTP") == "1":
        logger.info("stackchan connector starting in streamable-http mode on 127.0.0.1:8790")
        mcp.run(transport="streamable-http")
    else:
        logger.info("stackchan connector starting in stdio mode")
        mcp.run()
