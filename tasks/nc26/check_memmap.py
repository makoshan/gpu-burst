"""Checks for build_memmap.py output. Exits non-zero on any failure.

A  random recordings match Salter2024Emg2pose._load_raw within fp16 precision;
   a one-sample misalignment must be caught (must-fail sample).
B  on the 20-subject subset, official window counts equal what the competition
   loader produced there: train 7714 / val 1567 / test 463.
C  (--official) the 463 subset test windows match the competition loader's
   windows value by value.
D  (--speed) DataLoader throughput on the full train split.
"""
import argparse, json, os, sys, time
from pathlib import Path
import numpy as np, torch
sys.path.insert(0, str(Path(__file__).parent))
from windows import Memmap, official_windows, train_windows, loader
from build_memmap import load, study

ap = argparse.ArgumentParser()
ap.add_argument("--root", default="~/neural-compet26/memmap")
ap.add_argument("--n", type=int, default=20)
ap.add_argument("--official", action="store_true")
ap.add_argument("--speed", action="store_true")
a = ap.parse_args()
mm = Memmap(a.root)
fail = []

def close(ours, ref):
    ref16 = ref.astype(np.float16).astype(np.float64)
    same_nan = np.array_equal(np.isnan(ours), np.isnan(ref16))
    ok = np.isclose(ours, ref16, rtol=0, atol=1e-6, equal_nan=True).all()
    return same_nan and ok

# A
tls = sorted(study().iter_timelines(), key=lambda t: t["path"])
assert len(tls) == len(mm.index)
rng = np.random.default_rng(0)
for i in rng.choice(len(tls), size=min(a.n, len(tls)), replace=False):
    r = mm.index.iloc[i]
    assert r.path == tls[i]["path"]
    emg, joints = load(tls[i])
    o, L = int(r.offset), int(r.length)
    e = np.asarray(mm.emg[o:o + L], np.float64); j = np.asarray(mm.joints[o:o + L], np.float64)
    if not (close(e, emg) and close(j, joints)):
        fail.append(f"A mismatch recording {i}")
    if L > 1 and close(np.asarray(mm.emg[o + 1:o + L + 1], np.float64), emg):
        fail.append(f"A must-fail: 1-sample shift NOT detected on {i}")
print(f"A: {a.n} recordings checked, 1-sample shift detected on all" if not fail else fail)

# B
subs = json.load(open(os.path.expanduser("~/neural-compet26/subset20.json")))
got = {s: len(official_windows(mm, mm.select(s, subs))) for s in ("train", "val", "test")}
want = {"train": 7714, "val": 1567, "test": 463}
print("B:", got, "want", want)
if got != want:
    fail.append(f"B window counts {got} != {want}")

# C
if a.official:
    sys.path.insert(0, os.path.expanduser("~/neural-compet26/2026-competition/tracks/emg_pose"))
    from benchmark_utils.nb_task import load_task
    d = Path(os.path.expanduser("~/neural-compet26/data/neural_compet"))
    q = [f"Salter2024Emg2pose/{s}" for s in subs]
    loaders, _ = load_task("emg", "pose", data_dir=d, device="cpu", batch_size=64, seed=0,
                           num_workers=0, subset="full",
                           overrides={"study.source.query": f"subject in {q!r}",
                                      "target.infra.cluster": None,
                                      "target.infra.folder": str(d / "cache"),
                                      "target.infra.permissions": None,
                                      "study.source.timelines.infra.backend": "Cached",
                                      "study.source.timelines.infra.folder": str(d / "cache")})
    X0, Y0 = zip(*[(X, y) for X, y, _ in loaders["test"]])
    X0, Y0 = torch.cat(X0).numpy(), torch.cat(Y0).numpy()
    starts = official_windows(mm, mm.select("test", subs))
    X1 = np.stack([np.asarray(mm.emg[s:s + 10000], np.float32).T * 1e-6 for s in starts])
    Y1 = np.stack([np.asarray(mm.joints[s:s + 10000], np.float32).T for s in starts])
    f0, f1 = Y0[:, :, ::500].reshape(len(Y0), -1), Y1[:, :, ::500].reshape(len(Y1), -1)
    match = np.argmin(((f0[:, None] - f1[None]) ** 2).sum(-1), axis=1)
    dx = np.abs(X0 - X1[match]).max() * 1e6; dy = np.abs(Y0 - Y1[match]).max()
    print(f"C: {len(X0)} official vs {len(X1)} ours, one-to-one={len(set(match)) == len(match)}, "
          f"max |dX| {dx:.3f} uV, max |dy| {dy:.5f} rad")
    if len(set(match)) != len(match) or dx > 1.0 or dy > 2e-3:
        fail.append("C official windows differ")

# D
if a.speed:
    starts, shifts = train_windows(mm, mm.select("train"))
    dl = loader(mm, starts, shifts, shuffle=True, workers=8)
    it = iter(dl); next(it); t = time.time()
    for _ in range(100):
        next(it)
    dt = time.time() - t
    print(f"D: {len(starts)} train windows; {100 * 64 / dt:.0f} windows/s "
          f"-> one epoch {len(starts) / (100 * 64 / dt) / 60:.1f} min (data only)")

print("FAIL" if fail else "PASS", *fail, sep="\n")
sys.exit(1 if fail else 0)
