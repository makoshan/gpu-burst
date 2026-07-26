#!/bin/bash
# 发射 Matcha 潮汕训练到 Vast(付费!)。凭据从本地 aws profile 注入,不写进 YAML。
# 用法:
#   ./sky/launch-matcha-teochew.sh                                   # 干跑(默认,不花钱)
#   GPU_BURST_LIVE=1 ./sky/launch-matcha-teochew.sh --confirm-paid   # 真发射
#   EXPERIMENT=teochew_sandhi N_VOCAB=296 ./sky/launch-matcha-teochew.sh  # sandhi 版
set -euo pipefail
cd "$(dirname "$0")/.."

AK=$(aws configure get aws_access_key_id --profile gpu-burst-r2)
SK=$(aws configure get aws_secret_access_key --profile gpu-burst-r2)
[ -n "$AK" ] && [ -n "$SK" ] || { echo "missing gpu-burst-r2 creds"; exit 1; }

# 允许发射时覆盖 experiment/n_vocab(citation vs sandhi 单变量对照)
ENV_ARGS=()
[ -n "${EXPERIMENT:-}" ] && ENV_ARGS+=(--env EXPERIMENT="$EXPERIMENT")
[ -n "${N_VOCAB:-}" ] && ENV_ARGS+=(--env N_VOCAB="$N_VOCAB")

ARGS=(launch -c matcha-teochew -y -d
  --env AWS_ACCESS_KEY_ID="$AK"
  --env AWS_SECRET_ACCESS_KEY="$SK"
  "${ENV_ARGS[@]}"
  sky/matcha-teochew.yaml)

if [ "${1:-}" = "--confirm-paid" ] && [ "${GPU_BURST_LIVE:-}" = "1" ]; then
  echo ">>> PAID LAUNCH (Vast on-demand, --down after finish)"
  exec uv run sky "${ARGS[@]}"
else
  echo ">>> DRY RUN (加 --confirm-paid 且 GPU_BURST_LIVE=1 才真发射)"
  exec uv run sky launch --dryrun -y \
    --env AWS_ACCESS_KEY_ID=placeholder --env AWS_SECRET_ACCESS_KEY=placeholder \
    "${ENV_ARGS[@]}" sky/matcha-teochew.yaml
fi
