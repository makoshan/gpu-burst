#!/usr/bin/env bash
# 在 GCP G4 上:装环境 → 数据准备(不外推)→ 建手型原型 → 三组训练并行 → 结果同步到 GCS → 机器自删。
# 由 systemd 以 root 起(ssh 会话退出会清共享内存,DataLoader 崩;2026-10-03 Codex 实测)。
# 用法: g4-run.sh <gs://bucket/prefix> <zone>
set -uo pipefail
OUT=$1; ZONE=$2; export HOME=${HOME:-/root}
W=$HOME/nc26-g4; mkdir -p "$W"; exec > >(tee -a "$W/run.log") 2>&1
stage() { echo "STAGE $(date -u +%FT%TZ) $*"; }
# 上一轮桶里一个文件都没有、错误又被吞掉;现在错误写进 sync.err,一开机先试写一次,写不进就直接退出删机
sync_out() { [ -d "$W/runs" ] && gcloud storage rsync -r -x '.*ckpt_e.*\.pt$' "$W/runs" "$OUT/runs" >/dev/null 2>>"$W/sync.err"; gcloud storage cp "$W/run.log" "$OUT/run.log" >/dev/null 2>>"$W/sync.err"; }
finish() { r=$?; echo "G4_EXIT=$r"; sync_out; gcloud compute instances delete "$(hostname)" --zone "$ZONE" --quiet; }
trap finish EXIT
set -e
stage gcs_write_probe
echo "started $(date -u +%FT%TZ)" > "$W/started.txt"
gcloud storage cp "$W/started.txt" "$OUT/started.txt" || { echo "GCS 写不进 $OUT"; exit 46; }
stage setup
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
apt-get update -qq && apt-get install -y -qq git rsync curl python3-dev python3-pip > "$W/apt.log"
python3 -m pip install --break-system-packages -q uv 2>/dev/null || python3 -m pip install -q uv
export PATH="$HOME/.local/bin:/usr/local/bin:/snap/bin:$PATH"
uv venv -q -p 3.12 "$HOME/nc26env"
printf 'torch==2.11.0\ntorchaudio==2.11.0\n' > "$W/constraints.txt"
VIRTUAL_ENV="$HOME/nc26env" uv pip install -q torch==2.11.0 torchaudio==2.11.0 --index-url https://download.pytorch.org/whl/cu128   # 两个要同一 CUDA 版本,否则 torchaudio 加载失败
VIRTUAL_ENV="$HOME/nc26env" uv pip install -q -c "$W/constraints.txt" neuralset==0.3.1 neuralfetch==0.3.1 exca==0.5.29 eegdash==0.9.1 benchopt==1.10.0 mne mne-bids pandas numpy scipy scikit-learn
PY=$HOME/nc26env/bin/python
$PY -c 'import torch, torchaudio, neuralfetch.download; assert torch.__version__.startswith("2.11.0") and torch.cuda.is_available(); print("TORCH", torch.__version__, torch.cuda.get_device_name(0))'
R=$HOME/neural-compet26; mkdir -p "$R"; rm -rf "$R/code"; cp -r "$W/code" "$R/code"; tar xzf "$R/code/egoemg_fk.tgz" -C "$R"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
stage prepare_data
ln -sfn "$HOME/nc26env" ~/nc26env 2>/dev/null || true
DEST=none COMPACT=0 bash "$R/code/dataprep.sh"
stage protos
cd "$R/code/train"; ln -sfn "$R/memmap" memmap
$PY make_protos.py "$W/protos64.npy" 64
mkdir -p "$W/runs"
( while sleep 600; do sync_out; done ) &
stage train
C="--root $R/memmap --bench . --epochs 30 --seed 51 --vel-weight 0.5 --tip-weight 0.01 --egoemg $R/egoemg_fk --train-splits train,test:stage --save-at 10,20 --workers 14"
$PY -u train.py $C --out "$W/runs/g4_ctrl_s51" > "$W/runs/g4_ctrl_s51.log" 2>&1 &
$PY -u train.py $C --protos "$W/protos64.npy" --proto-weight 0.1 --out "$W/runs/g4_proto64_w01_s51" > "$W/runs/g4_proto64_w01_s51.log" 2>&1 &
$PY -u train.py $C --protos "$W/protos64.npy" --proto-weight 0.5 --out "$W/runs/g4_proto64_w05_s51" > "$W/runs/g4_proto64_w05_s51.log" 2>&1 &
fail=0; for j in $(jobs -p | tail -3); do wait "$j" || fail=1; done
grep -h "DONE best val" "$W"/runs/*.log || true
stage finished
exit $fail
