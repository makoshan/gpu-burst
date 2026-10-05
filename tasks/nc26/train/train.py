"""Train EMGFormer-S on the memmaps, outside benchopt.

Each epoch is scored on the official val windows (15 held-out users) and the
official user_stage test windows (20 users); the checkpoint with the best val
MAE is kept. ``weights.pt`` is the model state dict, so the competition
submission is simply ``solvers/emgformer.py`` (as submission.py) + that file.

    python train.py --out runs/s16_e30 --epochs 30
    python train.py --out runs/final_s1 --epochs 250 --train-splits train,val,test --seed 1

WSD with branches: one long run holds the LR flat and saves checkpoints; short
cooldown runs resume from those checkpoints, so one run measures several
training lengths. Because the LR is a pure function of (epoch, epochs,
decay-epochs), a branch resumed at epoch 40 with --epochs 50 --decay-epochs 10
is exactly "40 flat + 10 decay".

    python train.py --out runs/wsd100 --epochs 100 --sched wsd --decay-epochs 20 --save-at 40,60
    python train.py --out runs/wsd50 --epochs 50 --sched wsd --decay-epochs 10 --resume runs/wsd100/ckpt_e40.pt
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).parent
ap = argparse.ArgumentParser()
ap.add_argument("--root", default="~/neural-compet26/memmap")
ap.add_argument("--compact", action="store_true", help="root is a make_compact.py copy")
ap.add_argument("--bench", default="~/neural-compet26/2026-competition/tracks/emg_pose",
                help="competition track dir (emgformer.py imports benchmark_utils)")
ap.add_argument("--out", required=True)
ap.add_argument("--epochs", type=int, default=30)
ap.add_argument("--lr", type=float, default=1e-3)
ap.add_argument("--bs", type=int, default=64)
ap.add_argument("--chan-stride", type=int, default=1)
ap.add_argument("--stride", type=int, default=5000, help="train window stride (samples)")
ap.add_argument("--train-splits", default="train")
ap.add_argument("--workers", type=int, default=8)
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--max-steps", type=int, default=0, help="stop each epoch early (smoke test)")
ap.add_argument("--sched", choices=["cosine", "wsd"], default="cosine")
ap.add_argument("--decay-epochs", type=int, default=0, help="wsd: linear decay over the last K epochs")
ap.add_argument("--save-at", default="", help="comma list of epochs to checkpoint net+optimizer")
ap.add_argument("--resume", default="", help="checkpoint from --save-at; continues after its epoch")
ap.add_argument("--init", default="", help="start from these weights (fine-tune); schedule starts at epoch 1")
ap.add_argument("--eval-every", type=int, default=1, help="decay epochs are always scored")
ap.add_argument("--vel-weight", type=float, default=0.0,
                help="extra L1 on 50 Hz first differences of the angles (velocity), weight w")
ap.add_argument("--env", action="store_true", help="add the log-RMS envelope stream (dual-stream fusion)")
ap.add_argument("--frac-rot", action="store_true",
                help="aug: blend each electrode with a neighbour by up to half a step (band worn between zones)")
ap.add_argument("--chan-gain-db", type=float, default=0.0, help="aug: random per-channel gain within +-dB")
ap.add_argument("--layers", type=int, default=3, help="transformer depth (S = 3)")
ap.add_argument("--ffn", type=int, default=512, help="transformer FFN width (S = 512)")
ap.add_argument("--protos", default="", help="K x 20 pose prototypes (.npy, rad) from make_protos.py: adds the hand-shape head")
ap.add_argument("--proto-weight", type=float, default=0.1, help="cross-entropy weight on the nearest-prototype label")
ap.add_argument("--tip-weight", type=float, default=0.0,
                help="EgoEMG fingertip loss: mean fingertip distance (mm, UmeTrack FK) x w; 0.01 upstream")
ap.add_argument("--egoemg", default="~/neural-compet26/egoemg_fk",
                help="dir holding the vendored egoemg package (kinematics + UmeTrack, CC BY-NC)")
a = ap.parse_args()

sys.path.insert(0, str(Path(a.bench).expanduser()))
sys.path.insert(0, str(Path(a.bench).expanduser() / "solvers"))
sys.path.insert(0, str(HERE))
from emgformer import EMGFormerS, augment          # noqa: E402
from windows import (Memmap, official_windows, train_windows, loader,   # noqa: E402
                     Compact, CompactTrain, CompactEval, make_loader)

torch.manual_seed(a.seed); np.random.seed(a.seed)
dev = "cuda" if torch.cuda.is_available() else "cpu"
out = Path(a.out).expanduser(); out.mkdir(parents=True, exist_ok=True)
(out / "args.json").write_text(json.dumps(vars(a), indent=1))

if a.compact:
    assert a.train_splits == "train", "the compact copy holds the train split only"
    c = Compact(a.root)
    tr = make_loader(CompactTrain(c, *c.train_windows(stride=a.stride)), a.bs, True, a.workers)
    val = make_loader(CompactEval(*c.eval_arrays("val")), a.bs, workers=a.workers)
    test = make_loader(CompactEval(*c.eval_arrays("test")), a.bs, workers=a.workers)
else:
    mm = Memmap(a.root)
    # "split" or "split:generalization", e.g. train,test:stage = train users incl. the 6 held-out
    # gestures, without the 20 warm-up test users (test:user / test:user_stage are those users)
    def pick(spec):
        sp, _, gen = spec.partition(":")
        m = mm.index.split == sp
        return m & (mm.index.generalization == gen) if gen else m
    rows = mm.index[np.logical_or.reduce([pick(s) for s in a.train_splits.split(",")])]
    tr_starts, tr_shift = train_windows(mm, rows, stride=a.stride)
    tr = loader(mm, tr_starts, tr_shift, a.bs, shuffle=True, workers=a.workers)
    val = loader(mm, official_windows(mm, mm.select("val")), batch_size=a.bs, workers=a.workers)
    test = loader(mm, official_windows(mm, mm.select("test")), batch_size=a.bs, workers=a.workers)
print(f"windows: train {len(tr.dataset)} (splits={a.train_splits}), val {len(val.dataset)}, "
      f"test {len(test.dataset)}", flush=True)

protos = torch.from_numpy(np.load(Path(a.protos).expanduser())).float() if a.protos else None
net = EMGFormerS(chan_stride=a.chan_stride, env=a.env, layers=a.layers, ffn=a.ffn,
                 n_protos=0 if protos is None else len(protos)).to(dev)
if protos is not None:
    net.set_protos(protos.to(dev))
print(f"params: {sum(p.numel() for p in net.parameters()) / 1e6:.2f}M" + (f", protos {len(protos)}" if protos is not None else ""), flush=True)


def extra_aug(X):
    B, C, _ = X.shape
    if a.frac_rot:
        alpha = torch.rand(B, 1, 1, device=X.device) * 0.5
        left = torch.rand(B, 1, 1, device=X.device) < 0.5
        X = (1 - alpha) * X + alpha * torch.where(left, torch.roll(X, 1, dims=1), torch.roll(X, -1, dims=1))
    if a.chan_gain_db:
        X = X * 10 ** ((torch.rand(B, C, 1, device=X.device) * 2 - 1) * a.chan_gain_db / 20)
    return X
opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=0.01)
LR_MIN = 1e-5
save_at = {int(e) for e in a.save_at.split(",") if e}
start = 1
if a.init:                                  # strict=False: a plain checkpoint has no prototype head yet
    missing, _ = net.load_state_dict(torch.load(Path(a.init).expanduser(), map_location=dev, weights_only=True), strict=False)
    assert all(k.startswith("proto") for k in missing), missing
    print(f"init from {a.init}", flush=True)
if a.resume:
    ck = torch.load(Path(a.resume).expanduser(), map_location=dev, weights_only=False)
    net.load_state_dict(ck["net"]); opt.load_state_dict(ck["opt"]); start = ck["epoch"] + 1
    print(f"resumed {a.resume} at epoch {ck['epoch']}", flush=True)
bf16 = dev == "cuda"

if a.tip_weight:
    sys.path.insert(0, str(Path(a.egoemg).expanduser()))
    from egoemg.constants import LANDMARKS                      # noqa: E402
    from egoemg.kinematics import (forward_kinematics,          # noqa: E402
                                   load_default_hand_model, TorchHandModel)
    HAND = TorchHandModel(load_default_hand_model())
    HAND.to(dev)
    TIPS = [lm.index for lm in LANDMARKS if "fingertip" in lm.groups]


def proto_ce(logits, y):
    """Cross-entropy against the nearest prototype (L1) of the true pose at each feature frame."""
    yf = F.interpolate(y.nan_to_num(), size=logits.shape[1], mode="linear", align_corners=False).transpose(1, 2)   # (B, Tf, J)
    ok = ~torch.isnan(F.interpolate(y, size=logits.shape[1], mode="nearest")).any(1)                               # (B, Tf)
    target = torch.cdist(yf, net.protos, p=1).argmin(-1)
    return F.cross_entropy(logits[ok], target[ok]) if ok.any() else logits.sum() * 0


def tip_loss(p, y):
    """Mean fingertip distance in mm over ~100 frames, on frames with finite targets."""
    idx = torch.arange(0, y.shape[-1], max(1, y.shape[-1] // 100), device=y.device)
    pf, yf = p.float()[..., idx], y[..., idx]
    valid = ~torch.isnan(yf).any(dim=1)                          # (B, t)
    pp = forward_kinematics(pf, HAND)                            # (B, t, landmarks, 3)
    yp = forward_kinematics(yf.nan_to_num(), HAND)
    d = torch.linalg.norm(pp[:, :, TIPS] - yp[:, :, TIPS], dim=-1)   # (B, t, 5)
    return d[valid].mean() if valid.any() else d.sum() * 0.0


def lr_at(e):
    """LR used during epoch e (1-based); a function of the epoch only, so resumes are exact."""
    if a.sched == "cosine":
        return LR_MIN + (a.lr - LR_MIN) * (1 + math.cos(math.pi * (e - 1) / a.epochs)) / 2
    flat = a.epochs - a.decay_epochs
    if e <= flat:
        return a.lr
    frac = (e - flat) / a.decay_epochs
    return a.lr + (LR_MIN - a.lr) * frac


@torch.no_grad()
def mae_deg(dl):
    net.eval()
    err = n = 0.0
    for X, y, _ in dl:
        X, y = X.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=bf16):
            p = net(X)
        err += (p.float() - y).abs().sum().item()
        n += y.numel()
    return math.degrees(err / n)


best = float("inf")
log = open(out / "log.jsonl", "a")
for epoch in range(start, a.epochs + 1):
    lr = lr_at(epoch)
    for g in opt.param_groups:
        g["lr"] = lr
    net.train()
    t, total, count = time.time(), 0.0, 0
    for step, (X, y, _) in enumerate(tr, 1):
        X, y = X.to(dev, non_blocking=True), y.to(dev, non_blocking=True)
        # Random electrode subset per batch when emulating a sparser band.
        off = int(torch.randint(a.chan_stride, ()))
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=bf16):
            p = net(extra_aug(augment(X[:, off::a.chan_stride])))
        if y.shape[-1] != p.shape[-1]:          # compact: 200 Hz targets
            p = p[..., ::p.shape[-1] // y.shape[-1]]
        mask = ~torch.isnan(y)
        loss = (p.float() - y.nan_to_num()).abs()[mask].mean()
        if a.vel_weight:
            # 50 Hz first differences: 2 kHz -> every 40th sample (200 Hz compact -> every 4th)
            k = max(1, y.shape[-1] // 250)
            dp, dy = p.float()[..., ::k].diff(dim=-1), y[..., ::k].diff(dim=-1)
            vm = ~torch.isnan(dy)
            loss = loss + a.vel_weight * (dp - dy.nan_to_num()).abs()[vm].mean()
        if a.tip_weight:
            loss = loss + a.tip_weight * tip_loss(p, y)
        if protos is not None:
            loss = loss + a.proto_weight * proto_ce(net.logits, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
        total += loss.item() * len(X); count += len(X)
        if a.max_steps and step >= a.max_steps:
            break
    train_s = time.time() - t
    if epoch in save_at:
        torch.save({"net": net.state_dict(), "opt": opt.state_dict(), "epoch": epoch},
                   out / f"ckpt_e{epoch}.pt")
    rec = {"epoch": epoch, "train_l1_deg": math.degrees(total / count),
           "train_s": round(train_s), "lr": lr}
    scored = (epoch % a.eval_every == 0 or lr < a.lr or epoch == a.epochs or epoch in save_at)
    if scored:
        rec["val_deg"], rec["test_deg"] = mae_deg(val), mae_deg(test)
    log.write(json.dumps(rec) + "\n"); log.flush()
    print(json.dumps(rec), flush=True)
    if scored and rec["val_deg"] < best:
        v = rec["val_deg"]
        best = v
        torch.save(net.state_dict(), out / "weights.pt")
        (out / "best.json").write_text(json.dumps(rec, indent=1))
torch.save(net.state_dict(), out / "last.pt")   # fine-tunes are judged on a subset, not on best overall val
print("DONE best val", best, flush=True)
