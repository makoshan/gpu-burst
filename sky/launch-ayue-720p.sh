#!/usr/bin/env bash
# 默认干跑（免费）：打印 sky 命令与配额检查。真发射：
#   GPU_BURST_LIVE=1 ./sky/launch-ayue-720p.sh --confirm-paid
set -euo pipefail
cd "$(dirname "$0")/.."
CMD=(sky launch -c ayue-720p sky/ayue-video-720p.yaml --idle-minutes-to-autostop 10 --down -y)
if [[ "${1:-}" == "--confirm-paid" && "${GPU_BURST_LIVE:-}" == "1" ]]; then
  uv run gpu-burst doctor >/dev/null || { echo "doctor not ready"; exit 1; }
  # R2 凭证注入：从本地 aws profile 读出，经 ssh 写到云机 ~/.aws/credentials
  # （Vast 无对象存储挂载，s5cmd 需显式凭证；绝不写进 YAML/git）
  AK=$(aws configure get aws_access_key_id --profile gpu-burst-r2)
  SK=$(aws configure get aws_secret_access_key --profile gpu-burst-r2)
  uv run "${CMD[@]}" &
  LAUNCH_PID=$!
  for i in $(seq 1 60); do
    if /usr/bin/ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no ayue-720p true 2>/dev/null; then
      /usr/bin/ssh -o StrictHostKeyChecking=no ayue-720p "mkdir -p ~/.aws && printf '[default]\naws_access_key_id = %s\naws_secret_access_key = %s\n' '$AK' '$SK' > ~/.aws/credentials" && echo "[creds] injected" && break
    fi
    sleep 20
  done
  wait $LAUNCH_PID
  exit $?
fi
echo "[dry-run] ${CMD[*]}"
uv run --with pyyaml python -c "import yaml,sys; yaml.safe_load(open('sky/ayue-video-720p.yaml')); print('YAML parse OK')"
