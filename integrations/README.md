# integrations — Mac 侧的全部内容

固件跑在机器人上，这里跑在你电脑上。三块彼此独立，可以只装一块。

```
integrations/
├── docs/
│   ├── firmware-integration.md   # 9 个新板卡工具 + HTTP MCP 桥的设计与验证记录
│   ├── voice-bridge.md           # 小智云 → Mac 语音桥的架构、修复过程、运维
│   └── gateway.md                # 用自托管 gateway 替代小智云时的字段兼容
├── tools/
│   ├── verify.sh                 # HTTP 端到端冒烟（15 项）
│   ├── usb_mcp_client.py         # 数据线上发一行 JSON、收一行结果
│   └── push_via_gh_api.py        # git push 被代理拦住时，用 Git Data API 建等价 commit
├── workbuddy-connector/
│   └── stackchan_connector.py    # WorkBuddy MCP 连接器，22 个工具，HTTP/USB 双传输
├── voice-bridge/
│   ├── mcp_pipe.py               # 小智云 wss ↔ 本地 stdio 管道
│   ├── server_workbuddy.py       # FastMCP 服务，6 个工具
│   ├── run_bridge.sh             # 启动脚本（供 LaunchAgent 调用）
│   ├── .env.example              # 配置模板（token 自己填）
│   └── launchd/*.plist           # 开机自启
├── gateway/
│   ├── fork_compat.py            # 工具名映射：self.robot.* → self.head.* 等
│   └── gateway-fork.patch        # 打到 gateway 仓库的补丁
└── patches/                      # 相对上游 main 的 6 个提交
```

---

## 1. WorkBuddy 连接器

把机器人接进 WorkBuddy，然后就能在对话里说「让派蒙点个头」「灯调成暖白」「查一下电量」。

**安装**

```bash
python3 -m pip install mcp pyserial
```

**配置**：把 `workbuddy-connector/mcp.example.json` 合并进 `~/.workbuddy/mcp.json`，
改掉 Python 路径、脚本路径和串口设备名（macOS 一般是 `/dev/cu.usbmodem1101`，用
`ls /dev/cu.usbmodem*` 确认）。

**两种传输**

| 值 | 走哪 | 前提 |
|---|---|---|
| `http`（默认） | `http://<设备IP>:8788/mcp` | Mac 与设备同网段 |
| `usb` | 串口一行 JSON-RPC | 插着数据线即可，不需要网络 |

USB 模式每次调用开关串口（约 0.2 秒开销），所以不会长期独占，可以和命令行调试共存。
只有一种情况会冲突：你自己开着串口监视器（Arduino IDE、`screen`）会锁住设备节点。

**工具清单**：22 个。表情 2、头部 4、灯 5、提醒 2、设备 3、配置 1，外加 `device_tools`
（列设备侧 25 个工具）和 `device_call`（逃生舱，直接调任意设备工具）。

---

## 2. USB 串口客户端

不需要 WorkBuddy，也不需要网络：

```bash
# 读状态
python3 tools/usb_mcp_client.py '{"tool":"self.get_device_status","arguments":{}}'

# 点个灯
python3 tools/usb_mcp_client.py '{"tool":"self.led.set_color","arguments":{"r":255,"g":0,"b":0}}'

# 列所有设备侧工具
python3 tools/usb_mcp_client.py '{"method":"tools/list","params":{}}'
```

协议很简单：**发一行 JSON，收一行 `__MCP_RESULT__{...}`**。支持简写
`{"tool":..., "arguments":...}` 和标准 JSON-RPC 两种。

---

## 3. HTTP 冒烟验证

```bash
bash tools/verify.sh 192.168.1.50
```

跑 15 项检查：`/healthz`、`/tools` 工具数、`/mcp` 同步返回、表情、灯效、头部角度、
设备状态。改固件后先跑这个，比手工 curl 快。

---

## 4. 语音桥

让机器人**自己**去查资料——把「查 3D 打印耗材」「搜一下我的笔记」这类请求转给 Mac 上的引擎执行。

方向和上面两节相反：不是 Mac 调设备，而是设备（经小智云）调 Mac。**不需要同网段**，
因为 Mac 主动向外建立 wss 长连接。

```bash
cp voice-bridge/.env.example voice-bridge/.env
# 填入小智云控制台给的 MCP 接入点（带 token）
python3 -m pip install -r voice-bridge/requirements.txt
bash voice-bridge/run_bridge.sh
```

6 个工具：

- `query_filament()` — 读最新耗材快照，毫秒级，不走引擎
- `search_wiki(keyword)` — 全文检索本地笔记，1–2 秒
- `workbuddy_quick(task)` — 同步等 20 秒以内
- `workbuddy(task)` — 异步，先回「正在查」，结果落盘
- `workbuddy_background(task, summary)` — 长任务
- `workbuddy_check_results()` — 取回异步结果

两个快速工具是关键：语音场景下等 30 秒的 agent 启动是不可接受的。

---

## 5. 固件补丁

`patches/` 是相对上游 `main` 的 6 个提交，按顺序：

1. `feat(integration)` — 本地 HTTP MCP 桥 + 9 个新板卡工具 + porting 资产
2. `fix(led)` — I2C 重试、latch 改 read-modify-write、返回真实结果
3. `feat(usb-mcp)` — USB Serial/JTAG JSON-RPC 通道
4. `fix(usb-mcp)` — 阻塞 stdin 读 + console 切到 USB
5. `fix(led)` — 配置 PY32 GPIO13（真根因）
6. `fix(led)` — GPIO 配置移出启动路径 + 加 probe/init 诊断工具

换到更新版本的上游时，可以直接打：

```bash
git am integrations/patches/*.patch
```

---

## 已知限制

- `:8788` **没有鉴权**，局域网内谁都能调。只在可信网络下用，要暴露到公网必须自己加 token。
- `/mcp` 同步等待上限 8 秒，工具回调跑在主循环上；音频任务占满时会超时（动作仍会执行）。
- `self.camera.take_photo` 的「让 LLM 描述画面」需要先通过 MCP `initialize` 配好 vision
  的 URL / token，纯 HTTP 桥不走 initialize，直接调会报错。
- 自定义唤醒词只在 `feature/integration-v242` 分支可选，且与 AFE 二选一（开了会丢 AEC）。
- `main/porting_extras/` 里的代码**故意不进构建**（mDNS 发现、Feetech 驱动、listening profile），
  当参考资料看，别当成已启用功能。
