#!/usr/bin/env bash
# nc26 数据准备放到 GCP:us-central1 的 CPU 竞价机直拉 NEMAR(美国 S3)→ memmap → 精简数据 → 同区 GCS。
# 默认只打印将要执行的命令;真开机要 --confirm-paid 且 GPU_BURST_LIVE=1(和 sky/launch-*.sh 同一约定)。
#   gcp/launch-nc26-dataprep.sh [--confirm-paid]   开机并起流水线
#   gcp/launch-nc26-dataprep.sh status             看阶段日志
#   gcp/launch-nc26-dataprep.sh down               删机器,并核对实例和磁盘都没了
# 经验和实测数字见 docs/gcp-nc26.md。
set -euo pipefail
cd "$(dirname "$0")/.."

P=${GCP_PROJECT:-makoshan-be381}
NAME=${NAME:-nc26-prep}
BUCKET=${BUCKET:-gs://makoshan-nc26-emgpose}        # us-central1,已建,禁止公开访问
MACHINE=${MACHINE:-n2-standard-16}                   # 这一步不用 GPU:要的是核数、盘和到 S3 的网速
DISK_GB=${DISK_GB:-750}                              # 原始 310 + memmap 224 + 精简 82 + 余量
MAX_RUN=${MAX_RUN:-6h}                               # 硬上限:到点 GCP 自己删机器,不依赖本机会话
ZONES=${ZONES:-"us-central1-a us-central1-b us-central1-c us-central1-f"}
G="gcloud compute"

zone() { $G instances list --project "$P" --filter="name=$NAME" --format="value(zone.basename())"; }

case "${1:-}" in
status)
  Z=$(zone); [ -n "$Z" ] || { echo "没有 $NAME"; exit 0; }
  $G ssh "$NAME" --project "$P" --zone "$Z" --quiet --command \
    'grep -E "^===|workers|checked|pass [12]|PASS|FAIL|CHUNKS|attempt|RC=" ~/dataprep.log | tail -20; df -h ~ | tail -1' 2>/dev/null
  ;;
down)
  Z=$(zone); [ -n "$Z" ] && $G instances delete "$NAME" --project "$P" --zone "$Z" --quiet
  echo "剩余实例: $($G instances list --project "$P" --format='value(name)' | tr '\n' ' ')"
  echo "剩余磁盘: $($G disks list --project "$P" --format='value(name)' | tr '\n' ' ')"
  ;;
--confirm-paid)
  [ "${GPU_BURST_LIVE:-}" = 1 ] || { echo "要 GPU_BURST_LIVE=1"; exit 1; }
  echo ">>> PAID LAUNCH ($MACHINE 竞价 + ${DISK_GB}GB pd-balanced;$MAX_RUN 后 GCP 自动删除)"
  for Z in $ZONES; do
    # storage-rw:默认服务账号对存储只读,传 GCS 要停机改权限(2026-10-02 踩过)。compute-rw:跑完自删。
    # 到期动作 DELETE:竞价被收回也会删,进度丢失;整条流水线约 1.2 小时,重跑比留着孤儿盘便宜。
    $G instances create "$NAME" --project "$P" --zone "$Z" --machine-type "$MACHINE" \
      --provisioning-model SPOT --instance-termination-action DELETE --max-run-duration "$MAX_RUN" \
      --image-family debian-12 --image-project debian-cloud \
      --boot-disk-size "${DISK_GB}GB" --boot-disk-type pd-balanced \
      --scopes storage-rw,compute-rw --labels purpose=nc26-prep,owner=mako \
      --format="value(name,zone.basename(),status)" && break
  done
  Z=$(zone); [ -n "$Z" ] || { echo "所有可用区都没开出来"; exit 1; }
  sleep 30   # sshd
  $G scp --project "$P" --zone "$Z" --quiet --recurse tasks/nc26 "$NAME":~/nc26-code
  $G ssh "$NAME" --project "$P" --zone "$Z" --quiet --command "bash ~/nc26-code/gcp-bootstrap.sh '$BUCKET' '$Z'"
  echo "已起。看进度: $0 status    跑完机器自删;提前收: $0 down"
  ;;
*)
  echo ">>> DRY RUN(加 --confirm-paid 且 GPU_BURST_LIVE=1 才真开机)"
  echo "项目 $P  机器 $MACHINE 竞价  盘 ${DISK_GB}GB  上限 $MAX_RUN  目的地 $BUCKET"
  echo "可用区顺序: $ZONES"
  gcloud storage buckets describe "$BUCKET" --format="value(location,public_access_prevention)" 2>&1 | head -1
  ;;
esac
