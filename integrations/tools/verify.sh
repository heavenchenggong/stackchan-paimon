#!/bin/bash
# 派蒙功能整合固件冒烟验证
# 用法: ./verify.sh [设备IP]      默认 192.168.1.50
# 前置: 设备已回滚到 xiaozhi 备份并刷上 feature/integration 分支编译出的 app
set -u
IP="${1:-192.168.1.50}"
BASE="http://${IP}:8788"

# 本机 HTTP_PROXY 会拦局域网/回环请求，制造假故障（之前踩过）
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY="${IP},127.0.0.1,localhost" no_proxy="${IP},127.0.0.1,localhost"

pass=0; fail=0
check() {
  local label="$1" expect="$2" out="$3"
  if echo "$out" | grep -q "$expect"; then
    printf '  PASS  %-28s\n' "$label"; pass=$((pass+1))
  else
    printf '  FAIL  %-28s (期望包含 %s)\n' "$label" "$expect"
    printf '        实际: %s\n' "$(echo "$out" | head -c 200)"; fail=$((fail+1))
  fi
}

echo "== 派蒙 HTTP MCP 冒烟验证 @ ${BASE} =="
echo

echo "[1] healthz"
OUT=$(curl -sS --max-time 5 "${BASE}/healthz" 2>&1)
check "健康检查" '"ok"' "$OUT"
check "MCP 桥已启用" '"mcp":true' "$OUT"

echo "[2] GET /tools"
OUT=$(curl -sS --max-time 8 "${BASE}/tools" 2>&1)
check "工具列表返回" '"tools"' "$OUT"
check "self.face.expression" 'self.face.expression' "$OUT"
check "self.led.pattern" 'self.led.pattern' "$OUT"
check "self.head.get_angles" 'self.head.get_angles' "$OUT"

echo "[3] GET /config"
OUT=$(curl -sS --max-time 5 "${BASE}/config" 2>&1)
check "配置可读" '"mode"' "$OUT"

echo "[4] POST /mcp —— 只读工具"
OUT=$(curl -sS --max-time 10 -X POST "${BASE}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"tool":"self.face.list","arguments":{}}' 2>&1)
check "face.list 返回表情名" 'expressions' "$OUT"

OUT=$(curl -sS --max-time 10 -X POST "${BASE}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"tool":"self.head.get_angles","arguments":{}}' 2>&1)
check "head.get_angles 返回角度" 'yaw' "$OUT"

echo "[5] POST /mcp —— 标准 JSON-RPC 格式"
OUT=$(curl -sS --max-time 10 -X POST "${BASE}/mcp" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"self.get_device_status","arguments":{}}}' 2>&1)
check "标准 JSON-RPC 中继" '"jsonrpc"' "$OUT"

echo "[6] POST /mcp —— 动作（看设备有没有反应）"
for spec in \
  '{"tool":"self.head.nod","arguments":{}}|head.nod' \
  '{"tool":"self.led.pattern","arguments":{"name":"rainbow","speed_ms":120}}|led.pattern' \
  '{"tool":"self.face.expression","arguments":{"emotion":"happy"}}|face.expression' \
  '{"tool":"self.led.auto","arguments":{}}|led.auto' \
  '{"tool":"self.head.center","arguments":{}}|head.center'; do
  BODY="${spec%%|*}"; LABEL="${spec##*|}"
  OUT=$(curl -sS --max-time 10 -X POST "${BASE}/mcp" \
    -H 'Content-Type: application/json' -d "$BODY" 2>&1)
  check "$LABEL" '"jsonrpc"' "$OUT"
done

echo
echo "== 结果: ${pass} pass / ${fail} fail =="
if [ "$fail" -gt 0 ]; then
  echo "提示：若全挂，先确认 (1) 设备刷的是整合分支固件而非 QChan，"
  echo "     (2) Mac 与设备同网段，(3) udev/端口已释放。"
  exit 1
fi
echo "固件侧 OK。WorkBuddy 侧还需重启 stackchan stdio 进程加载新连接器。"
