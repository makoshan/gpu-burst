#!/usr/bin/env bash
# 带驱动门禁重试的发射循环：Vast 市场 2/3 是 CUDA13 机器，但 SkyPilot 选机
# 不看驱动（连续两次抽中旧驱动少数派）。撞到就拆机换一台，最多 5 台。
# 每次坏循环成本约 $0.08（12min × $0.4/h），期望 1-2 次内命中。
set -uo pipefail
cd "$(dirname "$0")/.."
C=ayue-720p-final
Y="$(pwd)/sky/ayue-video-720p-live.yaml"
for attempt in 1 2 3 4 5; do
  echo "[$(date +%H:%M)] attempt $attempt: launching"
  uv run sky launch -c $C "$Y" --idle-minutes-to-autostop 60 --down --detach-run -y >> /tmp/gate-retry-launch.log 2>&1
  # 等作业离开 SETTING_UP（门禁在 setup 最前面，几分钟内见分晓）
  verdict=""
  for i in $(seq 1 30); do
    sleep 60
    # SSH 运行时装不上（Vast 迟交付宿主机 sshd 不起）也是可重试失败——
    # 提前从 provision 日志识别，别等 30 分钟无结论（2026-08-03 两台白等）
    PL=$(ls -dt ~/sky_logs/sky-* 2>/dev/null | head -1)
    if [ -n "$PL" ] && grep -q "Failed to SSH to .* after timeout" "$PL/provision.log" 2>/dev/null; then
      verdict=sshfail; break
    fi
    J=$(uv run sky queue $C 2>/dev/null | grep -oE "SETTING_UP|RUNNING|SUCCEEDED|FAILED_SETUP|FAILED" | head -1)
    echo "[$(date +%H:%M)] attempt $attempt poll: job=${J:-unknown}"
    case "$J" in
      RUNNING|SUCCEEDED) verdict=good; break;;
      FAILED_SETUP|FAILED)
        if uv run sky logs $C 1 --no-follow 2>/dev/null | grep -q "DRIVER-TOO-OLD"; then
          verdict=gate
        else
          verdict=other
        fi; break;;
    esac
  done
  case "$verdict" in
    good)  echo "[$(date +%H:%M)] 门禁通过，渲染进行中"; exit 0;;
    gate)  echo "[$(date +%H:%M)] 驱动太老，换机"; uv run sky down $C -y >/dev/null 2>&1;;
    sshfail) echo "[$(date +%H:%M)] 宿主机 sshd 不起（迟交付机），换机"; uv run sky down $C -y >/dev/null 2>&1;;
    other) echo "[$(date +%H:%M)] 非门禁失败，停下人工看"; exit 3;;
    *)     echo "[$(date +%H:%M)] 30分钟无结论，停下人工看"; exit 4;;
  esac
done
echo "5 台全是旧驱动，停"; exit 5
