#!/usr/bin/env bash
# 默认干跑（免费）。真发射：GPU_BURST_LIVE=1 ./sky/launch-ayue-720p.sh --confirm-paid
# 驱动门禁：setup 里检测宿主机驱动 >= 580（黄金栈 torch 2.13+cu130 需 CUDA 13），
# 不达标 exit 47 → 这里 down 掉换机重试，最多 4 台。
set -euo pipefail
cd "$(dirname "$0")/.."
CMD=(sky launch -c ayue-720p ${AYUE_YAML:-sky/ayue-video-720p.yaml} --idle-minutes-to-autostop 15 --down --detach-run -y)
if [[ "${1:-}" == "--confirm-paid" && "${GPU_BURST_LIVE:-}" == "1" ]]; then
  uv run gpu-burst doctor >/dev/null || { echo "doctor not ready"; exit 1; }
  [[ -f ~/.config/gpu-burst/r2-credentials ]] || { echo "missing r2-credentials"; exit 1; }
  for attempt in 1 2 3 4; do
    echo "[launch] attempt $attempt"
    uv run "${CMD[@]}"
    # detach 模式立即返回；等 setup 结论（门禁在 setup 最前面，几分钟内见分晓）
    for i in $(seq 1 40); do
      sleep 30
      ST=$(uv run sky queue ayue-720p 2>/dev/null | awk "/^1 |^[0-9]+ /{print \$NF}" | head -1)
      OUT=$(uv run sky logs ayue-720p --no-follow 2>/dev/null | tail -40 || true)
      if echo "$OUT" | grep -q "DRIVER-TOO-OLD"; then
        echo "[gate] 驱动太老，换机"; uv run sky down ayue-720p -y; continue 2
      fi
      if echo "$OUT" | grep -qE "driver ok"; then
        echo "[gate] 驱动达标，交给云机自跑（--detach-run）"; exit 0
      fi
    done
    echo "[launch] 20 分钟没见到门禁结论，人工检查"; exit 3
  done
  echo "[launch] 连续 4 台驱动都不达标，停"; exit 4
fi
echo "[dry-run] ${CMD[*]}"
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('${AYUE_YAML:-sky/ayue-video-720p.yaml}')); print('YAML parse OK')"
