#!/usr/bin/env bash
# 默认干跑（免费）：打印 sky 命令并校验 YAML。真发射：
#   GPU_BURST_LIVE=1 ./sky/launch-ayue-720p.sh --confirm-paid
# 凭证由 YAML 的 file_mounts 送上去，这里不做任何后台/ssh 包装——
# 包装层会让 sky launch 提前退出并触发 --down 拆机。
# --detach-run 必须带：不带的话客户端一断（后台任务被杀/网络抖动）
# 整个 launch 就死，--down 随即拆机，三小时的批次绝对撑不到头。
set -euo pipefail
cd "$(dirname "$0")/.."
CMD=(sky launch -c ayue-720p sky/ayue-video-720p.yaml --idle-minutes-to-autostop 15 --down --detach-run -y)
if [[ "${1:-}" == "--confirm-paid" && "${GPU_BURST_LIVE:-}" == "1" ]]; then
  uv run gpu-burst doctor >/dev/null || { echo "doctor not ready"; exit 1; }
  [[ -f ~/.config/gpu-burst/r2-credentials ]] || { echo "missing ~/.config/gpu-burst/r2-credentials"; exit 1; }
  exec uv run "${CMD[@]}"
fi
echo "[dry-run] ${CMD[*]}"
uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('sky/ayue-video-720p.yaml')); print('YAML parse OK')"
