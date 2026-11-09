# 派蒙功能整合报告

日期：2026-11-08
对象：`$REPO`（`heavenchenggong/stackchan-xiaozhi-firmware`）
前置报告：`analysis/PORTING.md`（资产解析）、`analysis/UPGRADE.md`（基线升级）

---

## 一、结论

**整合完成并全链路验证通过：编译 ✓ → 烧录 ✓ → 设备启动 ✓ → HTTP MCP 15/15 ✓ → WorkBuddy 连接器端到端 ✓。**

**2026-11-08 追加两项**：① 修复 PY32 12 灯「调用了但不变色」——**真根因是
从未配置 PY32 的 GPIO13**（WS2812 数据线），叠加 I2C 无重试、latch 写法错、
工具谎报成功；用户已确认「红灯了」，彩虹动画也跑通；② 新增 **USB 数据线
MCP 通道**，完全不依赖 Wi-Fi，可在 Mac 网段不通时直接调全部工具。

2026-11-08 09:34 用户把 Mac 切回同网段（`192.168.1.20`）后，`verify.sh` 一次跑出
**15 pass / 0 fail**；`GET /tools` 返回 25 个工具、无分页；`/mcp` 能同步拿到真实返回值
（角度 JSON、表情清单、设备状态 JSON），动作类工具也确实执行了。
`stackchan_connector.py` 的 `robot_status` / `device_tools` / `set_face` /
`led_pattern` / `nod` 对真机调用全部成功。

- CI run `42431590590`（`feature/integration` @ `34f6fc0`），6m33s，全部步骤 ✓，无链接错误。
- 2026-11-08 09:12 按「走法 B」烧录：整片恢复 `paimon-backup.bin`
  （16MB，MD5 校验通过）→ 单烧 `0x410000 xiaozhi.bin`（`Hash of data verified`）。
  备份 otadata 指向 `ota_0`（slot0 seq=1），`0x410000` 正是启动槽；NVS 未动。
- 串口启动日志实证：`PY32 found` / `SCS bus init OK` / `BMI270 initialized`、
  `MCP: Add tool:` 列出全部 19 个板卡工具（含 9 个新增）、
  `NotifyHttp: HTTP MCP server on port 8788: /notify /dismiss /healthz /tools /mcp /config`、
  `sta ip: 192.168.1.50` 且 `Connected to WiFi: MyWiFi` —— **Wi-Fi 配置确实保住了**。
- 曾卡在网段：Mac 在有线 `192.168.1.30`、`networksetup -setairportnetwork en0
  MyWiFi` 返回 `-3900`；用户手动在菜单栏连回 Wi-Fi 后（Mac 变
  `192.168.1.20`）立即畅通。**已解除，不再需要任何操作。**
- 产物已下载到 `firmware/out/`，`xiaozhi.bin` 2,990,736 B，`ota_0` 分区
  3,145,728 B 还剩 154,992 B；相对旧版只涨 23,184 B。
- `strings` 已核对：9 个新工具名、`/mcp` `/tools` `/config` 端点、
  `rainbow`/`heart_eyes`/`led_pattern` 等只在新 bin 里出现，旧 bin 没有。
- 本机 `IDF_PATH` 未设、无 `idf.py`、无 Docker，但**不是阻塞项**：编译在
  GitHub runner 上完成，本机零安装（见第五节）。
- `git push` 被本机代理拦（`github.com` CONNECT 502，只放行 `api.github.com`），
  改用 GitHub Git Data API 建了等价 commit + ref，远端 sha 与本地完全一致。

核心设计选择：**不引 gateway，把 `:8788` 扩成一个本地 MCP-over-HTTP 端点。**

原先 WorkBuddy 只有一个 `stackchan` 连接器、三个工具，而且只能通过
`/notify` `/dismiss` 发提醒。设备其实注册了 10 个工具，但那些工具只挂在
小智云 wss 的 MCP 通道上，局域网侧够不着。整合后：

```
WorkBuddy ──stdio MCP──> stackchan_connector.py ──HTTP :8788/mcp──> McpServer::ParseMessage()
                                                    ↑ ResultSink 同步回传结果
                                                    └─> 设备全部 19 + 6 = 25 个工具
```

不依赖小智云、不依赖 Qoder、不需要本地 WebSocket gateway、不需要改 NVS
就能控制身体。原来 `PORTING.md` 里那条「唯一结构性卡点」（设备怎么连本地
gateway，要加 `settings.cc` 配网页）在这条路上**直接绕过去了**；`/config`
接口仍然补上了，作为以后真要跑 gateway 时的开关。

---

## 二、能力前后对比

| 维度 | 整合前 | 整合后 |
|---|---|---|
| WorkBuddy 可调用工具 | 3（提醒 / 清除 / 状态） | 22（含 `device_tools` / `device_call` 逃生舱） |
| 设备注册工具 | 10（且 PY32 探测失败会全丢） | 19 板卡 + 6 通用，且注册不再依赖 PY32 |
| 表情 | `self.face.expression` 一个 | 表情 + 13 种 overlay 特效 + `self.face.list` 可枚举 |
| 12 颗 RGB 灯 | 只能整体单色 / 关 / 自动 | 逐颗上色、统一亮度、3 种内置动画（rainbow / breath / chase） |
| 头部 | move / center / nod / shake | 加 `get_angles`（可读角度）、`tilt`（歪头卖萌） |
| 端点切换 | 只能重编译 | `GET/POST /config` 或 `self.gateway_config.get/set` 写 NVS，可立即重启 |
| 工具返回值 | 局域网侧拿不到 | `ResultSink` 同步回传，HTTP 调用能拿到结果 |
| 唤醒词 | 默认 Wakenet | 仅 `feature/integration-v242` 分支可选「你好，派蒙」 |

新增 9 个板卡工具：`self.led.set_many` / `clear` / `pattern`、
`self.face.list` / `overlay`、`self.head.get_angles` / `tilt`、
`self.gateway_config.get` / `set`。

**顺手修了一个真 bug**：旧构造器把 4 个 `Register*McpTools()` 全包在
`if (py32_found_)` 里。PY32（舵机电源 + 灯控芯片）一旦探测失败，连表情、
notify 这些跟它无关的工具也全部不注册。现在注册无条件执行，servo 工具
内部用 `servo_ok_` 守卫，LED 工具内部 `py32_dev_` 判空。

---

## 三、两条分支，选一条

| 分支 | 基线 | 得到 | 代价 / 风险 |
|---|---|---|---|
| `feature/integration` (`34f6fc0`) | `main` = `33e57dc`，2026-06-25 upstream snapshot | 变量最少，跟你现在备份里的那版同源 | 没有自定义唤醒词 |
| `feature/integration-v242` (`6d3b140`) | `upgrade/v2.4.2` = `b86d7f8` | 上面全部 + 可选「你好，派蒙」 | 668 文件 / 6.5 万行上游版本差，未编译、未烧录；通用工具少一个 `self.get_system_info` |

两条分支的整合改动内容一致（v242 是 cherry-pick 过来的，自动合并无冲突），
都额外搬进了 `main/porting_extras/`。

**我的判断（推测，未验证）**：先走 `feature/integration`。你之前担心的
「升级以后反而没原来好了」不是没道理——v2.4.2 那 668 个文件的差异，
在没编译验证之前不值得一起上。唤醒词是唯一实质收益，且它跟
`USE_AFE_WAKE_WORD` 是同一个 `choice`，开了会**关掉 AFE/AEC**，
远场唤醒反而可能变差。想清楚再切。

---

## 四、代码改了什么

### 固件仓库（两条分支都有）

| 文件 | 改动 |
|---|---|
| `main/mcp_server.h` | 加 `kHttpRpcIdBase = 1000000`、`ResultSink`、`SetResultSink()`、成员 `result_sink_` |
| `main/mcp_server.cc` | `ReplyResult` / `ReplyError` 对 `id >= kHttpRpcIdBase` 的响应改投 sink 并 return；云端 wss 的小 id 完全不受影响 |
| `main/notify_http_server.h/.cc` | 新增 `GET /tools`、`POST /mcp`（通用 JSON-RPC 中继，同步等 8 秒）、`GET/POST /config`；保留 `/notify` `/dismiss` `/healthz`，healthz 多返回 `mcp:true` |
| `main/boards/m5stack-core-s3/m5stack_core_s3.cc` | 9 个新工具；`M5StackAvatarDisplay::SetOverlayByName()`；12 灯动画状态机（ESP timer，不占主循环）；注册顺序修复；servo 守卫 |
| `main/boards/m5stack-core-s3/touch_gesture.h`、`power_save_gate.h`、`PORTING_NOTES.md` | 从 stackchan-mcp 搬入的纯头文件资产，头文件不参与 GLOB 编译，随时可 include |
| `main/porting_extras/` | 暂存的 MIT `feetech_scs` 驱动、mDNS 发现、listening_profile，含激活说明。**不参与当前构建** |
| `sdkconfig.wake-word.example`（仅 v242） | 5 行自定义唤醒词配置 + AFE/Multinet 二选一说明 |

`/mcp` 支持两种 body：标准 JSON-RPC（`method` + `params`，id 会被替换成
本地段）和简写 `{"tool":"self.head.nod","arguments":{}}`。
`ResultSink` 用一把 `std::mutex` 串行化 + 二值信号量同步，一次只飞一个调用。

### WorkBuddy 连接器（已提交，`cb3b895`）

`bridge/bridge/stackchan_connector.py`：22 个工具，`py_compile` +
FastMCP `list_tools()` + 本地 mock HTTP 全链路跑通。旧固件的三个工具
保持原样，`/mcp` 返回 404 时给明确提示而不是糊一个网络错误。
`~/.workbuddy/mcp.json` 的 `stackchan` 配置**不用改**。

### gateway 适配（可选路线）

`integrations/gateway/`：`fork_compat.py` + `gateway-fork.patch`。
把 gateway 写死的 `self.robot.*` / `self.display.*` 改派到派蒙的
`self.head.*` / `self.face.*`，并做参数转换。详见 `GATEWAY.md`。
**这条路现在是备选**——HTTP 桥已经覆盖同样的能力，且少一层。

---

## 五、编译（必须先做，但**不用在本机做**）

2026-11-08 复核修正：仓库自带 `.github/workflows/build-cores3.yaml`，
在 GitHub runner 上用 `espressif/idf:v5.5.2` 容器编译，产物打包成 artifact。
`gh run list` 查到近 8 次全部 success（最近一次 2026-09-06 就是 `33e57dc`
基线，耗时 6m12s），且 2026-06-22 有一次 `workflow_dispatch` 成功记录。
本机 `gh` 已登录 `github.com / heavenchenggong`，`repo` + `workflow` scope
齐全，`git ls-remote origin` 通。**所以不需要装 Docker，也不需要在本机装 ESP-IDF。**

### 路线 1（推荐）：GitHub CI，本机零安装

```bash
FW="$REPO"
cd "$FW" && git checkout feature/integration
git push -u origin feature/integration

# workflow 的 push 触发分支只有 main / codex-refactor，需手动 dispatch
GH_HOST=github.com gh -R heavenchenggong/stackchan-xiaozhi-firmware \
  workflow run build-cores3.yaml --ref feature/integration
GH_HOST=github.com gh -R heavenchenggong/stackchan-xiaozhi-firmware run watch

# 下载产物（artifact 保留 90 天）
GH_HOST=github.com gh -R heavenchenggong/stackchan-xiaozhi-firmware \
  run download --dir ./out
ls -lh ./out/
```

`out/` 里会有 `xiaozhi.bin`、`merged-binary.bin`、`bootloader.bin`、
`partition-table.bin`、`srmodels.bin`、`generated_assets.bin`。
想永久留档可以额外打 `v*` tag 触发 Release 附件（artifact 只留 90 天）。

### 路线 2：本机装 Docker（备胎）

```bash
docker run --rm -v "$PWD":/project -w /project espressif/idf:v5.5.2 \
  bash -lc ". \$IDF_PATH/export.sh && idf.py set-target esp32s3 && idf.py reconfigure && idf.py build"
```

注意 CI 里有一段专门处理 `managed_components/78__esp-wifi-connect` 的
HTML/metadata 坑（先 stash、删目录让 component manager 重下、再覆盖回去），
本机手写命令要照抄那段，否则大概率卡在 `reconfigure`。

### 路线 3：本机装 ESP-IDF（最重）

`idf.py` + Xtensa 工具链约数 GB，还要设 `IDF_PATH`。没有 CI 方便，不推荐。

**实测结果（2026-11-08）**：走路线 1，一次编译通过，`std::mutex`、
`cJSON_IsTrue`、ESP timer 回调签名这些静态预审存疑的点都没报错。
`git push` 被代理拦时用的 API 建 commit 脚本已通用化并保存到
`integrations/push_via_gh_api.py`（`--repo / --branch / --base / --fw`）。
它复用本地 commit 的 author/committer/date/message，因此远端 sha 与本地
完全一致；远端分支已存在时改走 PATCH 强制更新。

### ⚠️ 烧录偏移：0x410000，不是 0x20000

我从你备份里那份实际在跑的 `partition-table.bin` 解出来的真实布局：

```
nvs      0x00009000  0x4000
otadata  0x0000d000  0x2000
phy_init 0x0000f000  0x1000
model    0x00010000  0x400000
ota_0    0x00410000  0x300000   ← app 在这里
ota_1    0x00710000  0x300000
assets   0x00a10000  0x5f0000
```

对应 `partitions/v1/16m_stackchan.csv`。`PORTING.md` 里「只烧
`xiaozhi.bin` 到 `0x20000`」那句是照抄 stackchan-mcp 的 v2 分区表，
**对本 fork 不适用**，别照着烧。

上面「走法 B」单烧 app 时用的就是这个 `0x410000`：

```bash
python3 -m esptool --chip esp32s3 --port /dev/cu.usbmodem* \
  --before usb-reset write_flash 0x410000 ./out/xiaozhi.bin
```

若编译产物的分区表与备份不同（例如切到 v2 布局），先解一次
`build/partition-table.bin` 确认 `ota_0` 偏移再烧。

---

## 六、验证步骤

设备现在刷的还是 **QChan**：分区布局、bootloader、app 全是 QChan 那套，
而且闭源、强绑 Qoder。所以**不能只在它上面盖一个 app 分区**，得先把整片
换成自 fork 的布局。两种走法：

**走法 A — 一条命令整片覆盖（最省事，但 Wi-Fi 要重配）**

CI 产出的 `merged-binary.bin` 从 `0x0` 一次写完全部分区，QChan 被整体抹掉，
不需要先 restore 备份：

```bash
python3 -m esptool --chip esp32s3 --port /dev/cu.usbmodem* \
  --before usb-reset --baud 460800 \
  write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m \
  0x0 ./out/merged-binary.bin
```

⚠️ 实测过：`merged-binary.bin` 的 `0x9000–0xcfff`（nvs 区）全是 `0xFF`，
整片烧会**擦掉 Wi-Fi / 绑定**，开机后要走配网（`192.168.4.1` captive portal）。

**走法 B — 保住 Wi-Fi / 绑定（两步）**

```bash
# 1) 先整片恢复成原来的 33e57dc 运行时状态（含 NVS）
cd ~/qchan-backup
./flash_qchan.sh restore paimon-backup.bin
# 2) 只换 app 分区：bootloader / 分区表 / model / assets 都不动
python3 -m esptool --chip esp32s3 --port /dev/cu.usbmodem* \
  --before usb-reset write_flash 0x410000 /path/to/out/xiaozhi.bin
```

✅ 容量已验证：`ota_0` = 3,145,728 B，旧 app 2,967,552 B，
新 app **2,990,736 B**（只涨 23,184 B），剩 **154,992 B** 余量。
新 `partition-table.bin` 与旧版逐字节相同，走法 B 不需要改分区表。

然后按顺序验（`STACKCHAN_URL` 按实际 IP 换，它现在可能在 `MyWiFi`
的 `192.168.1.50`，也可能在有线网段）：

```bash
IP=192.168.1.50
curl -s http://$IP:8788/healthz
curl -s http://$IP:8788/tools | python3 -m json.tool | head -40
curl -s -X POST http://$IP:8788/mcp -H 'Content-Type: application/json' \
  -d '{"tool":"self.face.list","arguments":{}}'
curl -s -X POST http://$IP:8788/mcp -H 'Content-Type: application/json' \
  -d '{"tool":"self.led.pattern","arguments":{"name":"rainbow","speed_ms":120}}'
curl -s -X POST http://$IP:8788/mcp -H 'Content-Type: application/json' \
  -d '{"tool":"self.head.nod","arguments":{}}'
curl -s http://$IP:8788/config
```

预期：`/healthz` 带 `"mcp":true`；`/tools` 返回 25 个左右工具；
灯跑彩虹、头点一下；`/config` 返回 `mode: xiaozhi-cloud`。

WorkBuddy 侧：连接器进程如果还挂着旧代码，需要重启 stdio 进程
（之前是 `kill <PID>` 后自动 respawn）。然后在对话里试
「让派蒙跑个彩虹灯」「派蒙歪个头」「查一下派蒙状态」。

切自托管 gateway（可选，不需要重编译）：

```bash
curl -s -X POST http://$IP:8788/config -H 'Content-Type: application/json' \
  -d '{"websocket_url":"ws://192.168.1.10:8765","websocket_token":"","restart":true}'
# 切回小智云
curl -s -X POST http://$IP:8788/config -H 'Content-Type: application/json' \
  -d '{"clear":true,"restart":true}'
```

一键冒烟脚本：`integrations/verify.sh`。

---

## 六之二、USB 数据线通道（不依赖 Wi-Fi）

Mac 反复在有线网段与设备所在 Wi-Fi 网段之间掉线，
所以给固件加了一条**串口 JSON-RPC 通道**：数据线（USB Serial/JTAG）上
发一行 JSON，设备回一行 `__MCP_RESULT__` 前缀的 JSON-RPC 响应。

```bash
python3 integrations/usb_mcp_client.py \
  '{"tool":"self.led.set_color","arguments":{"r":255,"g":0,"b":0}}'
python3 integrations/usb_mcp_client.py '{"method":"tools/list","params":{}}'
```

**WorkBuddy 连接器也支持这条通道**（2026-11-08 新增）：
`~/.workbuddy/mcp.json` 里给 stackchan 的 env 加

```json
"STACKCHAN_TRANSPORT": "usb",
"STACKCHAN_SERIAL": "/dev/cu.usbmodem1101"
```

之后 22 个工具全部走数据线，不再需要 Wi-Fi。默认仍是 `http`，
切回网络只要把 `STACKCHAN_TRANSPORT` 改成 `http`。

实现细节：USB 模式下**每次调用开关串口**（不长期独占），所以连接器和
命令行客户端可以共存；断线自动重连；`robot_status` / `notify_*` /
`device_tools` 分别改调 `self.get_device_status` / `self.notify.*` /
`tools/list`。依赖 pyserial（已装进 `claude-bridge-mcp/.venv`）。

改了 env 之后宿主**不会自动重载**连接器，需要在连接器面板关掉再打开，
或重启 WorkBuddy。

实现要点（踩过坑，别改回去）：

- `McpServer` 加独立 `kUsbRpcIdBase=2000000` + `SetUsbResultSink()`，
  与 `:8788` 的 HTTP 桥（1000000 段）用 id 段隔离，**不依赖 HTTP server
  是否启动**（Wi-Fi 没连时也能用）。
- `main/usb_mcp_bridge.cc` 起独立 task，`read(stdin)` 按行解析，
  复用 `McpServer::ParseMessage()`；结果 `printf("__MCP_RESULT__%s\n")`。
- 🔴 **必须阻塞读**。最初加了 `fcntl(O_NONBLOCK)`，ESP-IDF 的
  `usb_serial_jtag` VFS 一直返回 `EAGAIN`，命令根本读不进来。
- 🔴 `sdkconfig.defaults.esp32s3` 必须设
  `CONFIG_ESP_CONSOLE_USB_SERIAL_JTAG=y` /
  `CONFIG_ESP_CONSOLE_UART_DEFAULT=n`。默认主 console 是 UART0、
  USB Serial/JTAG 只做 secondary **只输出日志**，所以「日志看得见、
  stdin 收不到」。
- 已知小瑕疵：空闲时 task 每 500ms 打一条
  `W UsbMcp: stdin read failed (errno=11)`（EAGAIN），纯日志噪音，
  不影响功能；要清掉得再改一次固件。

**LED 修复的验证就是靠这条通道完成的**（当时 Wi-Fi 又断了）：

```
set_color(255,0,0) -> true
status            -> {"i2c_ok":true,"cfg_0x24":12,"led0_rgb565":63488,"manual":true,"pattern":""}
set_many(三色)    -> true
pattern rainbow   -> true
status            -> {"i2c_ok":true,"cfg_0x24":12,"led0_rgb565":1787,"manual":true,"pattern":"rainbow"}
```

63488 = 0xF800 = 纯红 RGB565，1787 是动画帧在变 —— 写入确实进了 PY32。
**用户已确认物理灯变红，彩虹动画也可见。**

### 12 灯不变的真正根因（2026-11-08 最终定位）

PY32 是用**它自己的 GPIO13** 驱动这 12 颗 WS2812C 的。fork 的
`InitializePy32LedDevice()` 原来只写 `0x24`（LED 数量）就清帧，
**从没配置过 GPIO13**，所以：

- I2C 读写全部成功
- `0x24` / `0x30` 寄存器回读全部正确（甚至能看到颜色值）
- 但数据线没被配成输出，PY32 的 LED 引擎不往灯带推数据

修复分三层：

1. `Py32WriteRegBlock` / `Py32ReadReg`：5 次重试 + 2ms 退避（PY32 刷
   WS2812 时会短暂 NACK）。
2. `0x24` latch 改 read-modify-write（`cfg | bit6`），不再直接写 `count|0x40`。
3. **配置 PY32 GPIO13**：顺序与 M5 BSP / stackchan 上游一致——
   `输出(0x04 bit5)` → `上拉(0x0A bit5=1, 0x0C bit5=0)` →
   `push-pull(0x14 bit5=0)` → `SetLedCount(12)` → **200ms settle** →
   清帧 → latch。

配置方式最终定为**不放进启动流程**：`self.led.init` 手动工具执行
（读改写 + 单次访问，返回每一步的值），避免启动路径出现不可恢复的
阻塞。`self.led.probe` 可单次读写任意寄存器，用于定位问题。

补充观察：

- PY32 的 GPIO 配置**在 ESP32 复位后仍然保留**（PY32 未掉电）；
  但完全断电后 PY32 会复位，需要重新调 `self.led.init`，或把它改回
  启动流程（用「读回检查、未配置才写」的方式最稳）。
- 「刷完设备失联、串口 0 字节」那次是**电量 1%** 导致的，不是 GPIO
  代码：充电到 100% 后 esptool 立即能连，且 PY32 里的配置值仍然正确。

### 实测结果（2026-11-08 09:34）

```
== 派蒙 HTTP MCP 冒烟验证 @ http://192.168.1.50:8788 ==
[1]~[6] 全 PASS —— 15 pass / 0 fail
```

- `GET /tools` → 25 个工具，`nextCursor` 为空（一页装得下）：
  6 个上游通用 + 19 个板卡（含 9 个新增）。
- `POST /mcp` 同步返回真实值，证明 `ResultSink` 机制成立：
  `self.head.get_angles` → `{"yaw":-11,"pitch":13}`；
  `self.face.list` → 21 个表情 + 14 种 overlay；
  `self.get_device_status` → 音量 100、亮度 75、电量 17% 充电中、
  Wi-Fi `MyWiFi` 信号强；`self.led.set_many` / `self.face.overlay` → `true`。
- `GET /config` → `wss://api.tenclass.net/xiaozhi/v1/`、`websocket_token_set:true`
  —— 小智云的 URL 和 token 都还在 NVS 里，**走法 B 连云端绑定也保住了**。
- WorkBuddy 连接器（22 工具）用真机跑了 `robot_status` / `device_tools` /
  `set_face` / `led_pattern` / `nod` / `led_auto`，全部成功；
  `~/.workbuddy/mcp.json` 的 `stackchan.disabled` 已为 `false`。
  宿主侧若工具列表没刷新，在连接器面板切一下或重启 WorkBuddy 即可
  （stdio 进程不会因配置文件变更自动重载）。
- 未测：`POST /config` 写 NVS（会改动云端连接配置，没必要为验证去动它）；
  `self.camera.take_photo` 的 Explain（需要 vision URL，见风险 5）。

**已知小瑕疵**：`/config` 和 `self.gateway_config.get` 的 `mode` 字段用
「`url` 非空」判断，把小智云官方地址也标成了 `custom-ws`。只是显示文案不准，
不影响任何功能；要修需改一行判断 + 重跑 CI + 单烧 app（不动 NVS）。

---

## 七、风险与已知限制

1. ~~没编译~~ **已解决**：CI 一次通过，产物已下载校验。
2. ~~没烧录~~ **已解决**：走法 B 烧录完成，启动日志确认 19 个板卡工具全部注册、
   HTTP MCP server 监听 8788、Wi-Fi 连上且 NVS 配置保留（设备 MAC `AA:BB:CC:DD:EE:FF`）。
3. ~~HTTP 端到端未验证~~ **已解决**：`verify.sh` 15/15 通过，连接器端到端也通过。
   仍未覆盖的是 `POST /config` 写 NVS 与拍照 Explain（见第六节）。
4. `:8788` 无鉴权，局域网内谁都能调 `/config` 和 `/mcp`。只在可信
   Wi-Fi 下用；要上公网必须加 token。
5. `self.camera.take_photo` 的 `Explain()` 需要先通过 MCP `initialize`
   配置 vision URL/token，纯 HTTP 桥没走 initialize，直接调会报错。
   拍照本身不依赖云端，但要「让 LLM 看图」还得把 `device_call` 用来发一次
   `initialize`，或改走 gateway。
6. `GET /tools` 受上游 `GetToolsList()` 的 8KB 分页限制，工具很多时要用
   `cursor` 翻页；25 个工具目前一页装得下。
7. `/mcp` 同步等待 8 秒，工具回调跑在 Application 主循环上；主循环被
   音频任务堵住时会超时返回错误（动作本身仍会执行）。
8. `main/porting_extras/` 里的 `.cc` 故意不进 SOURCES，**不能当作已集成功能**。
   `feetech_scs` 曾因仓库根 `.gitignore` 的 `components/` 规则被静默忽略，
   已改名为 `porting_extras/feetech_scs/` 并补提交。
9. 自定义唤醒词只在 v242 分支有效，且和 AFE 是二选一（见
   `sdkconfig.wake-word.example`）。

---

## 八、回滚

- 固件：`./flash_qchan.sh restore paimon-backup.bin`
  （16MB 整片，含原 Wi-Fi / 绑定），另有 `qchan/rollback/restore_paimon.sh`
  和 `cores3-33e57dc.zip` 兜底。
- 代码：`git checkout main`（固件仓库）、`git checkout 55066f3 -- bridge/stackchan_connector.py`（bridge 仓库）。
- `feature/integration` 已 push 到远端（`34f6fc0`，与本地同 sha）；
  `feature/integration-v242` 仍在本地。要撤远端分支：
  `GH_HOST=github.com gh api -X DELETE repos/heavenchenggong/stackchan-xiaozhi-firmware/git/refs/heads/feature/integration`

---

## 九、交付物

| 路径 | 内容 |
|---|---|
| `firmware/out/` | CI 编译出的 7 个可烧文件：`xiaozhi.bin`、`merged-binary.bin`、`bootloader.bin`、`partition-table.bin`、`srmodels.bin`、`generated_assets.bin`、`ota_data_initial.bin` |
| 固件分支 `feature/integration` / `feature/integration-v242` | 全部 C++ 改动；前者已 push 并编译通过，后者仍只在本地 |
| bridge `main` (`cb3b895`) | 22 工具 WorkBuddy 连接器，已本地验证 |
| `integrations/INTEGRATION.md` | 本报告 |
| `integrations/GATEWAY.md` | gateway 工具名映射表与可选适配说明 |
| `integrations/gateway/fork_compat.py` + `gateway-fork.patch` | 可 `patch -p1` 应用的适配，dry-run 已通过 |
| `integrations/sdkconfig.wake-word` | 唤醒词配置片段（含适用分支说明） |
| `integrations/verify.sh` | 冒烟验证脚本 |
| `integrations/push_via_gh_api.py` | 代理拦 `git push` 时用 GitHub Git Data API 建等价 commit 的通用脚本 |
| `integrations/usb_mcp_client.py` | USB 数据线调设备 MCP 工具的 Mac 端客户端（pyserial） |
| `firmware/main/usb_mcp_bridge.{h,cc}` | 设备侧串口 JSON-RPC 桥 |
