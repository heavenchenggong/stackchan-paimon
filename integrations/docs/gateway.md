# gateway 工具名适配（可选路线）

## 先说结论

**这次整合没走 gateway。** 设备 `:8788` 加了 `POST /mcp` 之后，WorkBuddy
的 `stackchan_connector.py` 已经能直接驱动全部 25 个设备工具，少一层
WebSocket、少一个常驻 Python 服务、不用改 NVS 里的 `websocket.url`。

下面这份适配是给「以后确实想跑 stackchan-mcp gateway」准备的：它的
`say` / `listen` / `beat_mode` / `take_photo(question)` / Wi-Fi OTA 这些
能力是 Python 侧的，HTTP 桥没有。要走那条路，设备侧工具名必须先对上。

---

## 问题

gateway 的 `stdio_server.py:1094` 有一张写死的 `tool_map`，把 MCP 工具名
映射到 `boards/stackchan/stackchan.cc`（v2.2.6 基线）注册的
`self.robot.*` / `self.display.*` / `self.led.*`。你的 fork 用的是
`self.head.*` / `self.face.*`，参数 schema 也不同（它有 `speed`，你没有；
它的 `set_leds` 收 `[[r,g,b],...]`，你的是逗号分隔十六进制字符串）。

`esp32_client.py` 还有一张 `_TOOL_LANES` 前缀表，用来给不同硬件通道排队；
`self.head.` / `self.face.` / `self.notify.` / `self.gateway_config.`
这些前缀不在表里，会全落到 `default` 通道。

---

## 映射表

| gateway 工具 | 原设备工具 | 派蒙设备工具 | 参数转换 |
|---|---|---|---|
| `get_device_info` | `self.get_device_status` | 同 | 无需改 |
| `take_photo` | `self.camera.take_photo` | 同 | 无需改 |
| `set_volume` | `self.audio_speaker.set_volume` | 同 | 无需改 |
| `set_brightness` | `self.screen.set_brightness` | 同 | 无需改 |
| `set_led` | `self.led.set_color` | 同 | 无需改 |
| `clear_leds` | `self.led.clear` | 同（整合分支新增别名） | 无需改 |
| `gateway_config_get/set` | `self.gateway_config.get/set` | 同（整合分支新增） | 无需改 |
| `move_head` | `self.robot.set_head_angles` | `self.head.move` | 丢掉 `speed`；yaw 夹到 -45..45，pitch 夹到 5..60 |
| `get_head_angles` | `self.robot.get_head_angles` | `self.head.get_angles` | 无需改 |
| `set_avatar` | `self.display.set_avatar` | `self.face.expression` | `face` 枚举 → emotion：idle→neutral、off→sleepy，其余同名 |
| `set_leds` | `self.led.set_many` | 同 | `[[r,g,b],...]` → `#RRGGBB,#RRGGBB,...`；补 `brightness` |
| `set_all_leds` | `self.led.set_all` | `self.led.set_color` | 取第一个颜色拆成 r/g/b |

**没有对应实现、会从 tool_map 里删掉的**：`self.power.*` 7 个、
`self.port_b/c.*` 10 个、`self.i2c.*` 4 个、`self.robot.*` 底层诊断
（gpio_test / uart_diag / check_vm_en / 扭矩 / 触摸开关）、
`self.display.set_mouth*` / `set_blink`、`self.screen.set_off_timeout`、
`self.wifi.set_power_save`。删掉后调用会走原有的 `Unknown tool` 分支，
而不是把不存在的名字发给设备。

注意：`stdio_server.py` 的 MCP 工具清单（`list_tools()`）是另一份独立定义，
这份 patch 只改 `tool_map`。想让 LLM 看不到那些不支持的工具，还要在
`list_tools()` 里按 `fork_compat.UNSUPPORTED` 过滤一遍。

---

## 应用方式

```bash
cd /path/to/stackchan-mcp/gateway
cp $REPO/integrations/gateway/fork_compat.py \
   stackchan_mcp/fork_compat.py
patch -p1 < $REPO/integrations/gateway/gateway-fork.patch
```

patch 只做两件事：

1. 在 `stdio_server.py` 的 `tool_map` 字面量结束后插两行，调用
   `apply_fork_compat(tool_map, arguments)`；
2. 在 `esp32_client.py` 的 `_TOOL_LANES` / `_TOOL_LANE_NAMES` 补 4 个前缀
   和 `notify` / `gateway` 两个 lane 名。

已验证：`fork_compat.py` 通过 `py_compile`；patch 对
`analysis/porting/gateway/stackchan_mcp/` 的原始副本 `patch --dry-run`
成功；映射函数对 `move_head` / `set_avatar` / `set_leds` 的样例转换正确。

---

## 设备怎么连上 gateway

`PORTING.md` 里说的「唯一结构性卡点」现在有两个解法，任选：

```
# A. HTTP /config（不用重编译、不清 Wi-Fi）
curl -s -X POST http://192.168.1.50:8788/config \
  -H 'Content-Type: application/json' \
  -d '{"websocket_url":"ws://<Mac的IP>:8765","websocket_token":"","restart":true}'

# B. MCP 工具
device_call("self.gateway_config.set",
            {"url":"ws://<Mac的IP>:8765","restart":true})
```

切回小智云：`{"clear":true,"restart":true}`。

`WebsocketProtocol::OpenAudioChannel()` 从 NVS namespace `websocket` 读
`url` / `token` / `version`，`Ota` 从 namespace `wifi` 读 `ota_url`，
写进去重启即生效。前提是设备上跑的是整合分支固件；当前刷着的 QChan
用的是 Qoder 私有 WSS 协议，这套配置对它无效。

---

## 别忘了协议前提

gateway 走的是标准 xiaozhi MCP-over-WebSocket（`{"type":"mcp","payload":...}`）。
你的 fork `main/protocols/protocol.cc` 和 `websocket_protocol.cc`
（`features.mcp = true`）支持这套，协议层是通的。但设备开机默认连的是
小智云，必须先按上面切 URL；且切到自托管后就失去了小智云的 ASR/LLM/TTS，
这些得由 gateway 自己供给（`say` / `listen` / `faster-whisper`）。
