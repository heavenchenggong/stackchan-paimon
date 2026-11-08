# 派蒙 · Stack-chan 全栈固件与 WorkBuddy 打通

> M5Stack Core S3 Stack-chan（桌面机器人「派蒙」）的**完整固件源码 + 三条控制链路**：
> 局域网 HTTP MCP、USB 数据线 MCP、语音桥（小智云 → Mac → WorkBuddy / Claude Code）。

这套东西要解决的是一个很具体的问题：**出厂固件和社区固件都只把「身体」暴露给云端语音**。
表情、12 颗灯、头部舵机这些能力只有小智云的 LLM 能调，你 Mac 上的工具链、笔记、脚本一律够不着。
本仓库把两侧都打开：

- 设备侧：把板卡工具挂到**本地可同步返回**的 MCP 通道上（不经过云端）
- Mac 侧：提供 WorkBuddy 连接器（22 工具）和语音桥（6 工具），互为补充

---

## 三条链路，按需要选

| 链路 | 依赖 | 延迟 | 适合 |
|---|---|---|---|
| **HTTP MCP** `:8788` | Mac 与设备同网段 | 毫秒级 | 日常，在同一个 Wi-Fi 下 |
| **USB MCP** 串口 JSON-RPC | 一根数据线 | 毫秒级 | Mac 不在设备网段、或想彻底不依赖 Wi-Fi |
| **语音桥** wss 出站 | 设备联网 | 秒级 | 直接对机器人说话，让它查资料 / 跑任务 |

三条链路可以同时存在，互不冲突。设备侧工具总数 **25 个**（19 个板卡 + 6 个通用），
WorkBuddy 连接器暴露 **22 个**，语音桥 **6 个**。

---

## 目录

```
.
├── main/                          # 固件源码（ESP-IDF）
│   ├── usb_mcp_bridge.{h,cc}      # USB Serial/JTAG JSON-RPC 通道
│   ├── mcp_server.{h,cc}          # 两条结果通道：HTTP(1000000) / USB(2000000)
│   ├── notify_http_server.cc      # :8788 的 /mcp /tools /config /notify /healthz
│   └── boards/m5stack-core-s3/    # 板卡：PY32 灯控、舵机、表情、摄像头
├── partitions/v1/16m_stackchan.csv  # 16MB 分区表（app 在 ota_0 = 0x410000）
├── sdkconfig.defaults.esp32s3     # 关键：USB Serial/JTAG 作为主 console
└── integrations/                  # ← WorkBuddy / Mac 侧全部内容
    ├── docs/                      # 整合说明、语音桥、gateway 兼容
    ├── tools/                     # verify.sh、usb_mcp_client.py、API 推送脚本
    ├── workbuddy-connector/       # WorkBuddy MCP 连接器（HTTP + USB 双传输）
    ├── voice-bridge/              # 小智云 → Mac 的 MCP 桥
    ├── gateway/                   # 给自托管 gateway 用的字段兼容补丁
    └── patches/                   # 相对上游的 6 个提交（可打到新版上游）
```

详细说明见 **[integrations/README.md](integrations/README.md)**。

---

## 快速开始

### 1. 编译

仓库自带 GitHub Actions 流水线，push 后自动编译，产物含 `xiaozhi.bin` 与 `merged-binary.bin`：

```bash
gh workflow run build-cores3.yaml --ref main
gh run watch
gh run download --dir ./out
```

本地编译（ESP-IDF 5.5.2）：

```bash
idf.py set-target esp32s3
idf.py build
```

### 2. 烧录

**app 偏移是 `0x410000`**（`ota_0`），不是 `0x20000`。两种走法：

```bash
# 走法 A：整片覆盖（会清空 NVS，Wi-Fi 和绑定要重新配网）
esptool.py --chip esp32s3 -p /dev/cu.usbmodem1101 write_flash 0x0 merged-binary.bin

# 走法 B：先恢复自己的整片备份（保住 NVS），再单烧 app
esptool.py --chip esp32s3 -p /dev/cu.usbmodem1101 write_flash 0x0 paimon-backup.bin
esptool.py --chip esp32s3 -p /dev/cu.usbmodem1101 write_flash 0x410000 xiaozhi.bin
```

⚠️ **不要把 CI 产出的 `ota_data_initial.bin` 烧进去**——它两个 OTA 槽都是空值，会破坏启动槽选择。
烧 app 前先确认 `0xd000` 处 otadata 指向哪个槽（`seq` 有效且较大的那个）。

### 3. 验证

```bash
# HTTP（需同网段）
bash integrations/tools/verify.sh 192.168.1.50

# USB（不需要网络）
python3 integrations/tools/usb_mcp_client.py '{"tool":"self.get_device_status","arguments":{}}'
python3 integrations/tools/usb_mcp_client.py '{"tool":"self.led.status","arguments":{}}'
```

### 4. 接进 WorkBuddy

把 `integrations/workbuddy-connector/mcp.example.json` 里的条目合并进 `~/.workbuddy/mcp.json`，
改掉 Python 路径和串口设备名，然后在连接器面板启用。默认走 HTTP，把 `STACKCHAN_TRANSPORT`
设成 `usb` 就切到数据线。

### 5. 语音桥（可选）

让机器人直接对你说「查一下 3D 打印耗材」并调用本机能力，见
[integrations/docs/voice-bridge.md](integrations/docs/voice-bridge.md)。

---

## 踩过的坑（先看这几条，能省几小时）

1. **PY32 的 GPIO13 必须显式配置**。12 颗 WS2812 的数据线接在 PY32 自己的 GPIO13 上。
   只写 LED 数量和颜色 RAM 时，I2C 读写、寄存器回读全部正确，灯却完全不动——
   必须先把该脚配成「输出 + 上拉 + push-pull」，再设数量、等 200ms、清帧、latch。
2. **PY32 刷 WS2812 时会短暂 NACK**，I2C 写要 5 次重试 + 2ms 退避；latch 寄存器 `0x24`
   必须 read-modify-write（读回再 OR `bit6`），直接写 `count|0x40` 会清掉高位。
3. **工具不要无条件 `return true`**。旧实现的 LED 工具永远返回成功，把「灯没亮」伪装成正常，
   排查方向被带偏了两轮。现在所有硬件工具返回真实 I2C 结果。
4. **ESP-IDF 默认主 console 是 UART0**，USB Serial/JTAG 只做 secondary 且只输出日志。
   要在数据线上收命令，必须 `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` +
   `CONFIG_ESP_CONSOLE_UART_DEFAULT=n`，否则「日志看得见、stdin 收不到」。
5. **`read(stdin)` 必须阻塞**。给 USB Serial/JTAG 的 VFS 加 `O_NONBLOCK` 会一直返回 `EAGAIN`。
6. **整片烧会清掉 NVS**（`0x9000–0xcfff` 全 `0xFF`），Wi-Fi 和云端绑定都会没。想保配置就走法 B。
7. **低电量会伪装成「刷砖」**：USB 设备节点还在（`303A:1001`），但 esptool 和串口都没响应。
   先充电 / 换供电口 / 长按 RST 进下载模式，不要反复重刷。

---

## 硬件与版本

- M5Stack Core S3 + Stack-chan 底座（PY32 IO 扩展、12× WS2812C、双舵机、BMI270、OV2640）
- ESP-IDF **5.5.2**，目标 `esp32s3`，Flash 16MB，分区 `partitions/v1/16m_stackchan.csv`
- app 分区 `ota_0` = 3,145,728 B；当前固件约 2.99 MB，余量约 150 KB（**改动别超**）

---

## 许可

MIT。本仓库基于 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) 与
[heavenchenggong/stackchan-xiaozhi-firmware](https://github.com/heavenchenggong/stackchan-xiaozhi-firmware)，
原始版权归 Shenzhen Xinzhi Future Technology Co., Ltd. 及各贡献者所有，详见 [LICENSE](LICENSE)。
新增的整合代码同样以 MIT 发布。

---
---

## 附：上游 fork 原有说明（Claude Code 适配版）

### 🤖 StackChan-XiaoZhi (Claude Code bridge 适配版)

> M5Stack Core S3 Stack-chan 陪伴机器人固件 — Servo MCP 工具 + 唤醒词长期在线 + Claude Code 桥接

基于 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) 官方固件，在 `main` 分支加了：

- ✨ 4 个 servo MCP 工具（`self.head.move / center / nod / shake`）暴露给 LLM 语音调用
- 🐛 修 servo "转过去又弹回" bug（FaceTracker + Application + SetEmotion 三重并发）
- 💤 禁用 light sleep，让唤醒词 7×24 在线（默认会 30 秒关麦克风）
- 🤖 [Stack-chan ↔ Claude Code 桥接](https://github.com/heavenchenggong/stackchan-claude-bridge) — 配套项目，让派蒙能查你本地知识库 / 跑 skill / 用 30+ MCP

完整说明 + 部署步骤 → **[heavenchenggong/stackchan-claude-bridge](https://github.com/heavenchenggong/stackchan-claude-bridge)**

下载预编译固件 → [Releases](https://github.com/heavenchenggong/stackchan-xiaozhi-firmware/releases/latest)（`merged-binary.bin` 一键烧录，永久有效）

---

## 原项目说明（以下保留上游 README）

<p align="center">
  <img src="https://img.shields.io/badge/platform-ESP32--S3-green?logo=espressif" alt="ESP32-S3">
  <img src="https://img.shields.io/badge/framework-ESP--IDF%20v5.5-blue?logo=espressif" alt="ESP-IDF v5.5">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

---

## ✨ 功能

| 模块 | 硬件 | 说明 |
|---|---|---|
| 🎤 唤醒词 | Multinet6 | "你好小智"，灵敏度 Low / Medium / High |
| 👆 头顶触摸 | SI12T | 3 区电容触摸，摸头对话，7 条随机回应 |
| 📱 屏幕触摸 | FT6336 | 双击 / 滑动 / 长按 6 种手势，60 条动作文本 |
| 🕺 体感检测 | BMI270 | 摇晃 + 抱起互动，说话自动屏蔽，5 分钟冷却 |
| 💡 情绪灯环 | WS2812×12 | 21 种情绪颜色，PY32 IO Expander 控制 |
| 🎯 舵机追踪 | SCS 总线 | GC0308 人脸追踪 + 空闲扫视，对话暂停 |
| 😴 智能休眠 | — | 30 秒空闲关灯 / 停舵机 / 熄屏，唤醒词恢复 |
| 🔌 重新配网 | — | Idle 长按屏幕 5 秒进入 192.168.4.1 配网（页面已美化，升级至 esp-wifi-connect v3.2.1，支持暗色模式） |
| ✂️ 文本打断 | — | 对话中插文本消息，不静默丢弃 |
| 🔧 MCP 工具 | — | LED / 音量 / 亮度 / 摄像头 / 系统信息 |

---

## 🚀 快速开始

从 [Releases](https://github.com/howecheung/StackChan-XiaoZhi/releases) 下载 `bootloader.bin`、`partition-table.bin`、`ota_data_initial.bin`、`xiaozhi.bin`，一行命令烧录：

```bash
pip install esptool
esptool.py --chip esp32s3 -p COM4 -b 460800 \
  --before default_reset --after hard_reset \
  write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m \
  0x0       bootloader.bin \
  0x8000    partition-table.bin \
  0xd000    ota_data_initial.bin \
  0x410000  xiaozhi.bin
```

> `COM4` 换成实际串口号。首次烧录建议先 `esptool.py erase_flash` 清空旧配置。

---

## 🔨 源码编译

需要 **ESP-IDF v5.5.x**，在 "ESP-IDF 5.5 CMD" 中执行：

```bat
git clone https://github.com/howecheung/StackChan-XiaoZhi.git
cd StackChan-XiaoZhi

:: 首次编译
idf.py set-target esp32s3
idf.py fullclean
idf.py build flash

:: 后续增量编译
idf.py build flash
```

低配机器防 OOM：`idf.py build flash -- -j1`

---

## ⚙️ 配置

编辑 `sdkconfig.defaults`：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `CONFIG_CUSTOM_WAKE_WORD` | `ni hao xiao zhi` | 唤醒词拼音 |
| `CONFIG_CUSTOM_WAKE_WORD_DISPLAY` | `你好小智` | 中文显示 |
| `CONFIG_WAKE_WORD_SENSITIVITY` | `MEDIUM` | `LOW` / `MEDIUM` / `HIGH` |

### 🛠 自定义行为池

编辑 `main/boards/m5stack-core-s3/m5stack_core_s3.cc`：

| 搜索关键词 | 对应功能 |
|---|---|
| `HeadTouchPool` | 摸头回应文本 |
| `DoubleClickPool` / `UpSwipePool` … | 手势动作文本 |
| `ShakePool` / `LiftPool` | 体感动作（MotionMsg 格式） |
| `UpdateLedsFromEmotion` | 情绪灯颜色映射 |

---

## 📖 功能使用方法

### 🔌 配网页面预览（无需烧录）

修改配网页面后，可本地预览效果，无需编译烧录：

```bash
node scripts/wifi-preview.js
```

浏览器打开 `http://localhost:3000`，修改 `managed_components/78__esp-wifi-connect/assets/wifi_configuration.html` 后刷新即可。模拟了 5 个 WiFi 热点 + 3 个已保存网络，OTA 和睡眠模式选项可见。

---

## 🔥 烧录成功但设备不启动？（最高频问题）

M5Burner 显示 `Hash of data verified` + `Burn successfully`，但设备烧完**黑屏、没反应、按啥都没用**。这**不是烧录失败**（数据已校验），是启动环节问题。按顺序排查（90% 是前两条）：

**① 软复位不彻底 —— 先试这个**
M5Burner 结尾的 `Hard resetting via RTS pin` 软复位经常卡在半初始化状态。
→ **拔掉 USB-C 线 → 等 30 秒（让电容放电）→ 重新插电**
→ 还不行：长按 CoreS3 左下角电源键 6 秒强制重启

**② 旧固件 NVS 残留 —— 之前烧过别的固件必做**
这台之前烧过原厂 UIFlow 或其他固件时，旧 NVS 分区跟新固件冲突 → 开机 crash loop。
→ M5Burner 烧录前勾选 **Erase**（或命令行 `esptool.py erase_flash`），再重烧 merged-binary

**③ 供电不足**
只靠内置电池、又要同时驱动屏幕 + 舵机 + LED 全亮，电流不够开不了机。
→ **开机必须插着 USB-C 供电**，别只用电池

**④ 屏幕黑但其实在跑（容易误判）**
可能已经启动了，只是背光没亮 / 亮度 0 / 卡在等 WiFi 配网。
→ 双击屏幕试唤醒，或说"你好小智"看灯环亮不亮，靠近听有没有开机音

---

## ⚠️ 已知问题

<details>
<summary>展开查看</summary>

1. **电池供电 + 灯全亮可能无法开机** —— 插 USB 再开机
2. **LLM 控灯偶尔卡住 / 口头说调灯实际不动** —— prompt 优化中
3. **烧录后需物理重启** —— 拔 USB 关机，等 30 秒再插电
4. **唤醒词灵敏度需自行调整** —— 生僻词选 High，常见词选 Medium
5. **自部署服务端注意安全**：`auth.enabled=true`、MAC 白名单、API Key 不暴露、端口不裸奔

</details>

---

## 📋 更新日志

<details>
<summary>展开查看</summary>

- **2026-06-16** · **v0.0.2** 发布
- **2026-06-16** · 配网页面持续美化：🤖 机器人图标 + "StackChan 网络配置"品牌标识 + 日夜主题切换（自动/浅色/深色）+ 信号柱状条分色重绘 + 语言精简为中英文；新增 `self.face.expression` MCP 工具（19 种表情）+ `self.get_system_info` 改为通用工具；配网连接超时 60s → 10s + 连续 3 次失败自动清除失效凭据 + Idle 长按进配网时清空旧 WiFi；本地预览服务器 `node scripts/wifi-preview.js`
- **2026-06-16** · esp-wifi-connect v3.1.5 → v3.2.1：CSS 变量设计令牌 + 暗色模式 + 渐变背景 + 扫描动画 + 45 种语言；开启 OTA 配置和休眠模式可见性
- **2026-06-15** · 配网页面（192.168.4.1）美化：iOS 风格分段按钮 + 大圆角卡片 + 信号强度可视化 + StackChan 品牌标识
- **2026-06-11** · 修复休眠机制（恢复空闲检查，对话中不再误休眠，超时 60s → 30s）；Idle 长按屏幕 5 秒进入配网模式；说话时屏蔽 BMI270 体感避免舵机晃动误触 IMU
- **2026-06-10** · 编译修复 + 版本检查重试优化（`MAX_RETRY=1`）+ 默认 WebSocket 协议；触摸/SendUserText 长文本拦截修复（≤24 字节）；屏蔽 OTA 远程升级；体感池拆 `display+tag`、删早安问候、删 `upgrade_firmware` MCP 工具
- **2026-06-06** · 唤醒词灵敏度 Low/Medium/High 三档；文本打断优化；休眠背光彻底熄灭；SPIRAM 改回 QUAD

</details>

---

## 🙏 致谢

- [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) — 基础固件
- [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) — 服务端
- [M5Stack StackChan-BSP](https://github.com/m5stack/StackChan-BSP) — SI12T 参考
- [esp-wifi-connect](https://github.com/78/esp-wifi-connect) — WiFi 配网组件

## 📄 License

同上游 [xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)。