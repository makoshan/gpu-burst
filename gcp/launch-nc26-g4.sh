#!/usr/bin/env bash
# nc26 训练放到 GCP G4(RTX PRO 6000,48 核):数据准备 + 手型原型头三组对照并行。
# 默认只打印计划;真开机要 --confirm-paid 且 GPU_BURST_LIVE=1。机型、镜像、磁盘、systemd 启动沿用
# 2026-10-03 Codex 实测通过的配置(vibe-hw evidence/2026-10-03-gcp-g4-test)。
#   gcp/launch-nc26-g4.sh [--confirm-paid] | status | pull | down
set -euo pipefail
cd "$(dirname "$0")/.."
P=${GCP_PROJECT:-makoshan-be381}; NAME=${NAME:-nc26-claude-g4}; BUCKET=${BUCKET:-gs://makoshan-nc26-runs}; PREFIX=${PREFIX:-proto-$(date +%m%d)}
MAX_RUN=${MAX_RUN:-5h}                # 硬上限:到点 GCP 删机(竞价被收回也删;结果每 10 分钟同步到 GCS)
ZONES=${ZONES:-"us-central1-c us-central1-b us-central1-a us-central1-f"}
IMAGE=common-cu129-ubuntu-2404-nvidia-580-v20261001
G="gcloud compute"; zone() { $G instances list --project "$P" --filter="name=$NAME" --format="value(zone.basename())"; }
case "${1:-}" in
status)
  Z=$(zone); [ -n "$Z" ] || { echo "没有 $NAME"; gcloud storage cat "$BUCKET/$PREFIX/run.log" 2>/dev/null | grep -E "STAGE|G4_EXIT|DONE" | tail -8; exit 0; }
  $G ssh "$NAME" --project "$P" --zone "$Z" --quiet --command 'sudo grep -E "STAGE|checked|pass [12]|PASS|CHUNKS|frames|G4_EXIT" /root/nc26-g4/run.log | tail -12; for f in $(sudo ls /root/nc26-g4/runs/*.log 2>/dev/null || sudo find /root/nc26-g4/runs -maxdepth 1 -name "*.log"); do echo "$(basename $f) $(sudo grep -c "\"epoch\"" $f) $(sudo grep "\"epoch\"" $f | tail -1 | cut -c1-160)"; done 2>/dev/null; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader; uptime' 2>/dev/null ;;
pull) mkdir -p "${2:-/tmp/nc26-g4-runs}"; gcloud storage rsync -r "$BUCKET/$PREFIX" "${2:-/tmp/nc26-g4-runs}" ;;
down)
  Z=$(zone); [ -n "$Z" ] && $G instances delete "$NAME" --project "$P" --zone "$Z" --quiet
  echo "剩余实例: $($G instances list --project "$P" --format='value(name)' | tr '\n' ' ')"; echo "剩余磁盘: $($G disks list --project "$P" --format='value(name)' | tr '\n' ' ')" ;;
--confirm-paid)
  [ "${GPU_BURST_LIVE:-}" = 1 ] || { echo "要 GPU_BURST_LIVE=1"; exit 1; }
  [ -z "$(zone)" ] || { echo "$NAME 已存在"; exit 1; }
  gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1 || gcloud storage buckets create "$BUCKET" --project "$P" --location us-central1 --uniform-bucket-level-access --public-access-prevention
  for Z in $ZONES; do
    $G instances create "$NAME" --project "$P" --zone "$Z" --machine-type g4-standard-48 \
      --provisioning-model SPOT --instance-termination-action DELETE --max-run-duration "$MAX_RUN" \
      --image "$IMAGE" --image-project deeplearning-platform-release \
      --boot-disk-size 750GB --boot-disk-type hyperdisk-balanced --boot-disk-provisioned-iops 7500 --boot-disk-provisioned-throughput 1265 \
      --scopes storage-rw,compute-rw --labels owner=claude,purpose=nc26-proto \
      --format="value(name,zone.basename(),status)" && break
  done
  Z=$(zone); [ -n "$Z" ] || { echo "所有可用区都没开出来"; exit 1; }
  for i in 1 2 3 4 5 6; do $G ssh "$NAME" --project "$P" --zone "$Z" --quiet --command 'mkdir -p ~/stage' 2>/dev/null && break; sleep 20; done
  $G scp --project "$P" --zone "$Z" --quiet --recurse tasks/nc26 "$NAME":~/stage/code
  $G ssh "$NAME" --project "$P" --zone "$Z" --quiet --command "sudo mkdir -p /root/nc26-g4 && sudo rm -rf /root/nc26-g4/code && sudo cp -r ~/stage/code /root/nc26-g4/code && sudo systemd-run --unit=nc26-g4 --collect --setenv=HOME=/root ${RESUME:+--setenv=RESUME=$RESUME} ${MODE:+--setenv=MODE=$MODE} /bin/bash /root/nc26-g4/code/g4-run.sh '$BUCKET/$PREFIX' '$Z' && sleep 20 && sudo tail -3 /root/nc26-g4/run.log"
  echo "已起 $NAME @ $Z。进度: $0 status   结果: $0 pull   提前收: $0 down" ;;
*)
  echo ">>> DRY RUN(加 --confirm-paid 且 GPU_BURST_LIVE=1 才真开机)"
  echo "项目 $P  机器 g4-standard-48 竞价  盘 750GB hyperdisk  上限 $MAX_RUN  结果 $BUCKET/$PREFIX"
  echo "现有实例: $($G instances list --project "$P" --format='value(name,status)' | tr '\n' ' ')"
  $G images describe "$IMAGE" --project deeplearning-platform-release --format="value(status)" ;;
esac
