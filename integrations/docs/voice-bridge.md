# 语音链路：派蒙 → 小智云 → WorkBuddy（原 Claude 桥的修复版）

日期：2026-11-08
位置：`~/workbuddy-bridge-mcp/`
历史源码：`$REPO/integrations/workbuddy-connector/`

---

## 一、这条链路和「WorkBuddy 控制派蒙」是反的

前面做的 `stackchan_connector.py` 是 **WorkBuddy 主动调设备**（表情/灯/头）。
本文这条是 **你对派蒙说话时，它反过来调 Mac 上的能力**：

```
你说「派蒙，3D 打印材料还有多少」
  → 派蒙麦克风 → 小智云 ASR
  → 小智云 LLM（DeepSeek）决定调用工具
  → wss://api.xiaozhi.me/mcp/?token=...（小智云的 MCP 接入点）
  → Mac 上的 mcp_pipe.py（wss ↔ stdio）
  → server_workbuddy.py（FastMCP，6 个工具）
  → query_filament() 读本地 JSON / search_wiki() 搜 wiki
     或 workbuddy_* 启动 claude -p 跑完整 agent
  → 结果回传 → 小智云 TTS → 派蒙念出来
```

**关键：不需要 Mac 与设备同网段**。是 Mac 主动 outbound 连小智云，
设备侧完全不知道 Mac 的地址。这一点和 HTTP 桥相反。

---

## 二、文件职责

| 文件 | 作用 |
|---|---|
| `mcp_pipe.py` | 读 `MCP_ENDPOINT`（`.env`）连小智云 wss，把请求转给本地 stdio server |
| `mcp_config.json` | 指定要启动的 server 脚本（`server_workbuddy.py`）|
| `server_workbuddy.py` | FastMCP 服务，注册 6 个工具 |
| `.env` | `MCP_ENDPOINT=wss://api.xiaozhi.me/mcp/?token=...`（agent_****，2027 到期）|
| `run_bridge.sh` | 启动包装：source `.env` 后 exec python（供 launchd 用）|
| `/tmp/wb-bridge.log` `.err` | 运行日志 |

工具清单：

- `workbuddy(task)` — 异步，立刻回执，结果写 outbox
- `workbuddy_quick(task)` — 同步，≤20 秒
- `workbuddy_background(task, summary_for_user)` — 长任务异步
- `workbuddy_check_results()` — 取 outbox 最新结果
- `query_filament()` — **新增**，读最新耗材快照，毫秒级
- `search_wiki(keyword)` — **新增**，grep 1800 篇 wiki，1–2 秒

---

## 三、为什么 2026-11-08 之前一直是「没查到数据」

引擎 `codebuddy -p` 起不来，三层问题叠加，全都记在 outbox 里
（`/tmp/workbuddy-bridge-outbox/done/377956798.txt` 就是「3D 打印材料」那次）：

1. **`MODULE_NOT_FOUND`** — `cli/bin/codebuddy:286` 里
   `require('../dist/codebuddy')`，但 WorkBuddy App 2026-10-27 升级后
   `dist/` 里只剩 `codebuddy-lite-wb.mjs`，入口没了。
2. **`EADDRINUSE 127.0.0.1:58592`** — headless 默认端口被 App 自身占用。
3. **`Authentication required`** — 子进程没有登录态，需要交互式 `/login`，
   无人值守场景无法完成。

---

## 四、修复内容

### 1. 引擎换成 Claude Code CLI

`claude` 2.1.97 已安装且 `claude -p` 免交互可用（实测返回结果）。
`server_workbuddy.py` 默认值改为：

```python
WORKBUDDY_BIN = "claude"
WORKBUDDY_MODEL = ""          # 空则不传 --model
```

参数兼容性：`-p`、`--permission-mode`、`--add-dir`、
`--append-system-prompt`、`--mcp-config` 都支持。

### 2. 两个参数陷阱（踩过，别改回去）

- **`--add-dir` 和 `--mcp-config` 是可变参数**（`<directories...>` /
  `<configs...>`）。用空格分隔时，它们会把后面的 task 也吃掉，报
  `MCP config file not found: <cwd>/<task>`。
  **必须用 `--opt=value` 形式**：`--add-dir=/path`、`--mcp-config=/path.json`。
- **`--mcp-config` 只接受文件路径**（不像 codebuddy 允许内联 JSON）。
  已改为写 `/tmp/workbuddy-bridge-mcp-config.json` 再传路径。

### 3. 新增两个不走 agent 的查询工具

`query_filament()` 读 `~/Claude Code/3d-printing/耗材/耗材状态-*.json`
最新快照（9 个版本，取 mtime 最新）；`search_wiki(keyword)` 用
`/usr/bin/grep -ril --include=*.md` 搜 `~/wiki/pages`（约 1800 篇 / 688MB），
命中后取前 3 篇的上下文片段。

系统的 `rg` 不在 PATH 里，所以用 grep。

### 4. 环境坑

- `OUTBOX.mkdir(exist_ok=True)` 在 WorkBuddy App 的 `sitecustomize`
  broker shim 下会对已存在目录误报 `FileExistsError`，已加 try/except。
- 测试脚本要 `env -u PYTHONPATH`，否则会加载 App 的 shim。

---

## 五、验证结果（2026-11-08 18:08）

MCP stdio 客户端直连 `server_workbuddy.py`：

```
tools = 6
query_filament  -> 3D 打印耗材共 64 种（快照 耗材状态-2026-11-07-07-03.json）…
search_wiki     -> wiki 里找到 106 篇相关笔记，最相关的前 3 篇…
workbuddy_quick -> 4          （claude 引擎真实跑通）
```

桥重启后日志：

```
18:09:19 Starting servers: workbuddy
18:09:21 Successfully connected to WebSocket server
18:09:22 MCP server starting
18:09:22 Processing request of type ListToolsRequest
```

---

## 六、运维

- **日志**：`tail -f /tmp/wb-bridge.err`
- **重启**：`pkill -f mcp_pipe.py`（有 supervisor 会在数秒内自动拉起）；
  或手动 `bash ~/Claude Code/workbuddy-bridge-mcp/run_bridge.sh`
- **后台任务结果**：`ls -lt /tmp/workbuddy-bridge-outbox/`
- **改模型**：`WORKBUDDY_MODEL=sonnet` 之类的环境变量
- **换成别的引擎**：`WORKBUDDY_BIN=/path/to/cli`，注意参数兼容性

### 已知未完成

- `launchctl load` 在本机沙箱下报 `Load failed: 5: Input/output error`，
  所以 `~/Library/LaunchAgents/com.heaven.workbuddy-bridge.plist` 没生效。
  当前靠一个已有的 supervisor 自动重启（kill 后 2 秒即起）。
  **重启 Mac 后需要确认桥是否还在**；不在的话手动跑 `run_bridge.sh`
  或改用 `launchctl bootstrap gui/$(id -u)` 重试。
- `search_wiki` 是字面 grep，不做语义排序，"最相关"实际是文件遍历顺序。
  需要语义检索时应走 `workbuddy(task)`。
