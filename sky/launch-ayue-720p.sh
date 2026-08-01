#!/usr/bin/env bash
# 默认干跑（免费）：打印 sky 命令与配额检查。真发射：
#   GPU_BURST_LIVE=1 ./sky/launch-ayue-720p.sh --confirm-paid
set -euo pipefail
cd "$(dirname "$0")/.."
CMD=(sky launch -c ayue-720p sky/ayue-video-720p.yaml --idle-minutes-to-autostop 10 --down -y)
if [[ "${1:-}" == "--confirm-paid" && "${GPU_BURST_LIVE:-}" == "1" ]]; then
  uv run gpu-burst doctor >/dev/null || { echo "doctor not ready"; exit 1; }
  exec uv run "${CMD[@]}"
fi
echo "[dry-run] ${CMD[*]}"
uv run --with pyyaml python -c "import yaml,sys; yaml.safe_load(open('sky/ayue-video-720p.yaml')); print('YAML parse OK')"
