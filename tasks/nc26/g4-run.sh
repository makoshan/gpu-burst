#!/usr/bin/env bash
# 在 GCP G4 上:装环境 → 数据准备(不外推)→ 建手型原型 → 两组训练并行(对照 / 原型头 0.5) → 结果同步到 GCS → 机器自删。
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
if [ "${MODE:-}" = glasses ]; then   # 10-06:从 s51 出发,只在眼镜相关 6 个阶段微调 4 轮 vs 全部阶段续训 4 轮,再按场景分组评分
  stage glasses_ft; mkdir -p "$W/runs"; gcloud storage cp "$OUT/init/s51.pt" "$W/s51.pt" || exit 48
  G=IndexPinchesMiddlePinchesThumbswipes,FingerPinchesSingleFingerPinchesMultiple,ThumbsSwipesWholeHand,AllFingerPinchesThumbSwipeThumbRotate,PokeDrawPinchRotateclosefar,PokePinchCloseFar
  F="--root $R/memmap --bench . --epochs 4 --lr 1e-4 --seed 51 --vel-weight 0.5 --tip-weight 0.01 --egoemg $R/egoemg_fk --train-splits train,test:stage --workers 14 --init $W/s51.pt"
  $PY -u train.py $F --out "$W/runs/ft_all4" > "$W/runs/ft_all4.log" 2>&1 & a=$!
  $PY -u train.py $F --stages "$G" --out "$W/runs/ft_glasses4" > "$W/runs/ft_glasses4.log" 2>&1 & b=$!
  wait $a && wait $b || exit 49
  $PY scene_eval.py "$W/runs/scene.json" "$W/s51.pt" "$W/runs/ft_all4/last.pt" "$W/runs/ft_glasses4/last.pt" > "$W/runs/scene.log" 2>&1 || exit 50
  cat "$W/runs/scene.log"; stage finished; exit 0
fi
$PY make_protos.py "$W/protos64.npy" 64
mkdir -p "$W/runs"
( while sleep 600; do sync_out; done ) &
stage train
C="--root $R/memmap --bench . --epochs 30 --seed 51 --vel-weight 0.5 --tip-weight 0.01 --egoemg $R/egoemg_fk --train-splits train,test:stage --save-at 10,20 --workers 14"
# RESUME=gs://.../ckpt20:从上一台机器存下的第 20 轮断点接着跑(GCP 不许改运行中机器的时限,只能换机续跑)
rs() { [ -n "${RESUME:-}" ] || return 0; mkdir -p "$W/ckpt/$1"; gcloud storage cp "$RESUME/$1/ckpt_e20.pt" "$W/ckpt/$1/" >&2 || exit 47; echo "--resume $W/ckpt/$1/ckpt_e20.pt"; }
RC=$(rs g4_ctrl_s51); RP=$(rs g4_proto64_w05_s51)
$PY -u train.py $C $RC --out "$W/runs/g4_ctrl_s51" > "$W/runs/g4_ctrl_s51.log" 2>&1 &
$PY -u train.py $C $RP --protos "$W/protos64.npy" --proto-weight 0.5 --out "$W/runs/g4_proto64_w05_s51" > "$W/runs/g4_proto64_w05_s51.log" 2>&1 &
fail=0; for j in $(jobs -p | tail -2); do wait "$j" || fail=1; done
grep -h "DONE best val" "$W"/runs/*.log || true
stage finished
exit $fail
