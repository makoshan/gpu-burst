#!/bin/bash
# 发射 teochew-sft 到 Vast(付费!)。凭据从本地 aws profile 注入,不写进 YAML。
# 用法:
#   ./sky/launch-teochew-sft.sh            # 干跑(默认,不花钱)
#   GPU_BURST_LIVE=1 ./sky/launch-teochew-sft.sh --confirm-paid   # 真发射
set -euo pipefail
cd "$(dirname "$0")/.."

AK=$(aws configure get aws_access_key_id --profile gpu-burst-r2)
SK=$(aws configure get aws_secret_access_key --profile gpu-burst-r2)
[ -n "$AK" ] && [ -n "$SK" ] || { echo "missing gpu-burst-r2 creds"; exit 1; }

ARGS=(launch -c teochew-sft -y -d --down
  --env AWS_ACCESS_KEY_ID="$AK"
  --env AWS_SECRET_ACCESS_KEY="$SK"
  sky/teochew-sft.yaml)

if [ "${1:-}" = "--confirm-paid" ] && [ "${GPU_BURST_LIVE:-}" = "1" ]; then
  echo ">>> PAID LAUNCH (Vast on-demand, --down after finish)"
  exec uv run sky "${ARGS[@]}"
else
  echo ">>> DRY RUN (加 --confirm-paid 且 GPU_BURST_LIVE=1 才真发射)"
  exec uv run sky launch --dryrun -y \
    --env AWS_ACCESS_KEY_ID=placeholder --env AWS_SECRET_ACCESS_KEY=placeholder \
    sky/teochew-sft.yaml
fi
