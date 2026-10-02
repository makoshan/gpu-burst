#!/usr/bin/env bash
# emg2pose (NEMAR nm000281) -> fp16 memmaps (+ compact copy) -> object store. Runs on the cloud machine.
#   DEST=r2  (default, Vast/SkyPilot): s5cmd -> s3://gpu-burst-jobs/$TASK_ID, needs /tmp/r2-common.sh + AWS_* env
#   DEST=gcs (GCP VM with storage-rw scope): gcloud storage -> $GCS_OUT, e.g. gs://makoshan-nc26-emgpose
#   COMPACT=1 also builds the 82 GB training copy (train split at 200 Hz targets + official val/test windows)
set -euo pipefail
DEST=${DEST:-r2}; COMPACT=${COMPACT:-0}
[ "$DEST" = r2 ] && source /tmp/r2-common.sh
ROOT=$HOME/neural-compet26
D=$ROOT/data/neural_compet/Salter2024Emg2pose
[ "$DEST" = r2 ] && OUT="s3://gpu-burst-jobs/$TASK_ID" || OUT="${GCS_OUT:?GCS_OUT required for DEST=gcs}"
mkdir -p "$D/download" "$ROOT/memmap"
cd "$ROOT"
source ~/nc26env/bin/activate
cp code/subset20.json "$ROOT/subset20.json"
avail=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc 0-9)
need=$((560 + 90 * COMPACT)); [ -f "$ROOT/.verified" ] && need=$((230 + 90 * COMPACT))   # raw already on disk: only the memmaps are left
[ "$avail" -ge "$need" ] || { echo "disk too small: ${avail}G free, need ${need}G"; exit 47; }
# nproc obeys OMP_NUM_THREADS (set to 1 inside sky jobs) and ignores the cgroup CPU quota
WORKERS=$(python3 -c "
import os
try: q,p=open('/sys/fs/cgroup/cpu.max').read().split(); n=int(q)//int(p)
except Exception: n=10**6
print(max(1,min(n,len(os.sched_getaffinity(0)))))")
echo "workers=$WORKERS"
# 2026-10-02 Vast 宿主机内存吃紧时,新分配的匿名页每次缺页都卡在内核里(单文件 8~170 s)。
# 让 glibc 留住堆、不把大块还给系统,数组复用旧页:实测 0.1 s/文件。
export MALLOC_MMAP_THRESHOLD_=33554432 MALLOC_TRIM_THRESHOLD_=4294967296 MALLOC_TOP_PAD_=268435456 MALLOC_ARENA_MAX=1
stage() { echo "=== $(date -u +%T) $*"; }

stage "sidecars (git) + split metadata"
[ -d nm000281-git ] || git clone -q --depth 1 https://github.com/nemarDatasets/nm000281.git nm000281-git
curl -fsSL -o "$D/emg2pose_metadata.csv" https://fb-ctrl-oss.s3.amazonaws.com/emg2pose/emg2pose_metadata.csv

if [ ! -f "$ROOT/.verified" ]; then
stage "download bdf (retry loop)"
ok=0
for i in $(seq 1 40); do
  pids=()
  for lo in $(seq 1 16 193); do
    hi=$((lo + 15)); [ "$hi" -gt 193 ] && hi=193
    ( python code/download_all.py "$lo" "$hi" > "download-$lo.log" 2>&1 && grep -q "^DONE" "download-$lo.log" ) & pids+=($!)
  done
  fail=0; for p in "${pids[@]}"; do wait "$p" || fail=1; done
  [ "$fail" = 0 ] && { ok=1; break; }
  echo "attempt $i failed: $(grep -a -h -E 'Error|rror:' download-*.log | tail -1 | cut -c1-200); bdf=$(find "$D/download" -name '*.bdf' | wc -l)"
  sleep 20
done
[ "$ok" = 1 ] || { echo "download never completed"; exit 41; }
rsync -a --no-links --ignore-existing --exclude .git nm000281-git/ "$D/download/nm000281/"

stage "verify sizes against annex keys"
python code/verify_sizes.py
touch "$ROOT/.verified"
fi

stage "build memmap"
python code/build_memmap.py --out "$ROOT/memmap" --workers "$WORKERS" 2>&1 | grep -v -i -E "warn|montage|original_user|read_raw_bids"

stage "check memmap (random recordings vs loader; 20-subject window counts)"
python code/check_memmap.py --root "$ROOT/memmap" --n 30 2>&1 | grep -v -i -E "warn|montage|original_user|read_raw_bids|Reading 0"

stage "chunk checksums (reference: the copy built at home)"
cd "$ROOT/memmap"
for spec in "emg.f16 0" "emg.f16 700" "emg.f16 1400" "joints.f16 100" "joints.f16 1800" "valid.u8 40"; do
  set -- $spec; echo "$1@$2 $(dd if=$1 bs=64M skip=$2 count=1 2>/dev/null | md5sum | cut -c1-12)"
done | tee ../chunks.txt
diff ../chunks.txt "$ROOT/code/chunks.ref.txt" && echo "CHUNKS IDENTICAL to home build" || { echo "CHUNKS DIFFER from home build - not pushing"; exit 45; }
ls -l "$ROOT/memmap" | awk '{print $5, $9}' > ../sizes.txt

if [ "$COMPACT" = 1 ]; then
  stage "compact copy"
  cd "$ROOT"; [ -f compact/.done ] || { python code/make_compact.py "$ROOT/compact" 2>&1 | tail -3; touch compact/.done; }
  (cd compact && find . -type f ! -name .done -printf '%s %P\n' | sort -k2) > compact-sizes.txt
fi
cd "$ROOT"; cat sizes.txt chunks.txt > _DONE.txt

stage "push to $DEST ($OUT)"
if [ "$DEST" = r2 ]; then
  # -n -s: 桶里已有且大小相同的跳过(2026-10-02 首次只差 joints.f16)
  for f in joints.f16 meta.json index.csv valid.u8 emg.f16; do
    $S5 cp -n -s --concurrency 32 "$ROOT/memmap/$f" "$OUT/memmap-v1/$f"
  done
  [ "$COMPACT" = 1 ] && $S5 cp -n -s --concurrency 32 --exclude .done "$ROOT/compact/*" "$OUT/compact-v1/"
  $S5 ls "$OUT/memmap-v1/" | tee r2-listing.txt
  $S5 cp _DONE.txt "$OUT/memmap-v1/_DONE.txt"
  [ "$COMPACT" = 1 ] && $S5 cp compact-sizes.txt "$OUT/compact-v1/_DONE.txt"
else
  # 同区 GCS 不收流量费;-n 已存在的不覆盖
  for f in joints.f16 meta.json index.csv valid.u8 emg.f16; do
    gcloud storage cp -n "$ROOT/memmap/$f" "$OUT/memmap-v1/$f"
  done
  [ "$COMPACT" = 1 ] && gcloud storage rsync -r -x '^\.done$' "$ROOT/compact" "$OUT/compact-v1"
  gcloud storage ls -l "$OUT/memmap-v1/" | tee gcs-listing.txt
  gcloud storage cp _DONE.txt "$OUT/memmap-v1/_DONE.txt"
  [ "$COMPACT" = 1 ] && gcloud storage cp compact-sizes.txt "$OUT/compact-v1/_DONE.txt"
fi
stage "ALL DONE"
