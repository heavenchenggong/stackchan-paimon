"""把 stackchan-mcp gateway 的 tool_map 改派到派蒙自己的固件工具名。

背景：gateway 的 `stdio_server.py` 里写死了 `self.robot.*` / `self.display.*`
等名字，那是 `boards/stackchan/stackchan.cc`（v2.2.6 基线）注册的工具。
`heavenchenggong/stackchan-xiaozhi-firmware` 用的是 `self.head.*` /
`self.face.*`，参数 schema 也不同。

用法（见同目录 gateway-fork.patch）：
    # 在 stdio_server.py 的 tool_map 字面量结束 `}` 之后插入两行
    from .fork_compat import apply_fork_compat
    tool_map = apply_fork_compat(tool_map, arguments)

设计取舍：只做「能一一对应」的映射，对应不上的工具从 tool_map 里删掉，
调用时会走原有的 `Unknown tool` 分支，而不是把未知名字发给设备。
"""
from __future__ import annotations

import json
from typing import Any

# gateway 的 face 枚举 → 派蒙 self.face.expression 的 emotion 名字
_FACE_TO_EMOTION = {
    "idle": "neutral",
    "happy": "happy",
    "thinking": "thinking",
    "sad": "sad",
    "surprised": "surprised",
    "embarrassed": "embarrassed",
    # 派蒙没有 "off"（关掉 avatar 露出底层 UI），sleepy 最接近
    "off": "sleepy",
}

# 派蒙没有对应实现的 gateway 工具（power / port B,C / i2c / robot 底层 /
# touch / 息屏超时 / 舵机扭矩 / 唇形序列等）。留着会发一个设备上不存在的
# 工具名，不如直接删掉让调用方拿到明确的 Unknown tool。
UNSUPPORTED = frozenset({
    "set_off_timeout", "get_off_timeout",
    "set_external_power_auto_off", "get_external_power_auto_off",
    "set_charge_protection", "get_charge_protection", "set_charge_thresholds",
    "gpio_test", "uart_diag", "check_vm_en",
    "get_touch_sensor_enabled", "set_touch_sensor_enabled", "get_touch_state",
    "set_mouth", "set_mouth_sequence", "set_blink",
    "set_servo_torque", "set_auto_torque_release",
    "set_all_leds",
    "port_b_ws2812_init", "port_b_ws2812_set_pixel", "port_b_ws2812_set_strip",
    "port_b_ws2812_refresh", "port_b_ws2812_clear",
    "port_c_ws2812_init", "port_c_ws2812_set_pixel", "port_c_ws2812_set_strip",
    "port_c_ws2812_refresh", "port_c_ws2812_clear",
    "i2c_scan", "i2c_read", "i2c_write", "i2c_write_read",
    "wifi_set_power_save",
})


def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _rgb_triples_to_hex(colors: Any) -> str:
    """gateway: [[r,g,b], ...] → 派蒙: '#RRGGBB,#RRGGBB,...'。"""
    if isinstance(colors, str):
        try:
            colors = json.loads(colors)
        except json.JSONDecodeError:
            return colors  # 已经是逗号分隔字符串，原样透传
    out = []
    for c in (colors or [])[:12]:
        if isinstance(c, str):
            out.append(c if c.startswith("#") or c.startswith("0x") else "#" + c)
            continue
        if not isinstance(c, (list, tuple)) or len(c) < 3:
            continue
        r, g, b = (_clamp(x, 0, 255, 0) for x in c[:3])
        out.append(f"#{r:02x}{g:02x}{b:02x}")
    return ",".join(out)


def _first_rgb(arguments: dict[str, Any]) -> dict[str, int]:
    """set_all_leds 的 color 可能是 [r,g,b] 或 {'r':..}；转成 set_color 的 r/g/b。"""
    c = arguments.get("color", arguments.get("colors"))
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        return {"r": _clamp(c[0], 0, 255, 0),
                "g": _clamp(c[1], 0, 255, 0),
                "b": _clamp(c[2], 0, 255, 0)}
    if isinstance(c, dict):
        return {k: _clamp(c.get(k, 0), 0, 255, 0) for k in ("r", "g", "b")}
    return {"r": 0, "g": 0, "b": 0}


def apply_fork_compat(
    tool_map: dict[str, tuple[str, dict[str, Any]]],
    arguments: dict[str, Any],
) -> dict[str, tuple[str, dict[str, Any]]]:
    """返回改派后的 tool_map（原地拷贝，不修改传入对象）。"""
    result = dict(tool_map)

    for name in UNSUPPORTED:
        result.pop(name, None)

    # 这些名字在派蒙固件里已经一致，无需改动：
    #   get_device_info → self.get_device_status
    #   take_photo      → self.camera.take_photo
    #   set_volume      → self.audio_speaker.set_volume
    #   set_brightness  → self.screen.set_brightness
    #   set_led         → self.led.set_color
    #   clear_leds      → self.led.clear（整合分支新增的别名）
    #   gateway_config_get/set → self.gateway_config.get/set（整合分支新增）

    result["move_head"] = (
        "self.head.move",
        {
            # 派蒙固件 yaw 限 -45..45、pitch 限 5..60，且没有 speed 参数
            "yaw": _clamp(arguments.get("yaw", 0), -45, 45, 0),
            "pitch": _clamp(arguments.get("pitch", 30), 5, 60, 30),
        },
    )
    result["get_head_angles"] = ("self.head.get_angles", {})
    result["set_avatar"] = (
        "self.face.expression",
        {"emotion": _FACE_TO_EMOTION.get(arguments.get("face", "idle"), "neutral")},
    )
    result["set_leds"] = (
        "self.led.set_many",
        {
            "colors": _rgb_triples_to_hex(arguments.get("colors", [])),
            "brightness": _clamp(arguments.get("brightness", 100), 0, 100, 100),
        },
    )
    # gateway 的 set_all_leds 没有直接对应工具，落到 set_color
    result["set_all_leds"] = ("self.led.set_color", _first_rgb(arguments))

    return result
