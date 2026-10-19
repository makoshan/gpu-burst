#!/usr/bin/env bash
# 发射 nc26 RunPod 机(数据准备 + 测速)。默认 dry-run;真发射需 --confirm-paid 且 GPU_BURST_LIVE=1。
set -euo pipefail
cd "$(dirname "$0")/.."

AK=$(aws configure get aws_access_key_id --profile gpu-burst-r2)
SK=$(aws configure get aws_secret_access_key --profile gpu-burst-r2)
[ -n "$AK" ] && [ -n "$SK" ] || { echo "missing gpu-burst-r2 creds"; exit 1; }

if [ "${1:-}" = "--confirm-paid" ] && [ "${GPU_BURST_LIVE:-}" = "1" ]; then
  # 2026-10-02: 密钥失效到推 R2 那步才发现,白跑了下载。发射前先试写。
  EP=$(awk '/R2_ENDPOINT:/{print $2}' sky/nc26-runpod.yaml)
  echo probe | AWS_ACCESS_KEY_ID="$AK" AWS_SECRET_ACCESS_KEY="$SK" aws s3 cp - s3://gpu-burst-jobs/nc26-emgpose/_probe.txt --endpoint-url "$EP" --region auto >/dev/null \
    || { echo "R2 写不进去,先修凭据再发射"; exit 1; }
  # 自毁计时只看 SkyPilot 任务队列:绕过队列直接 ssh 起的进程不算数,到点照停
  # (2026-10-02 停在推送中途)。所有步骤都走 sky launch / sky exec。
  echo ">>> PAID LAUNCH (RunPod; 云机侧空闲 45 分钟后自毁)"
  exec uv run sky launch -c nc26-rp -y --detach-run \
    --idle-minutes-to-autostop 45 --down \
    --env AWS_ACCESS_KEY_ID="$AK" --env AWS_SECRET_ACCESS_KEY="$SK" \
    sky/nc26-runpod.yaml
else
  echo ">>> DRY RUN (加 --confirm-paid 且 GPU_BURST_LIVE=1 才真发射)"
  exec uv run sky launch --dryrun -y \
    --env AWS_ACCESS_KEY_ID=placeholder --env AWS_SECRET_ACCESS_KEY=placeholder \
    sky/nc26-runpod.yaml
fi
