"""K-means hand-shape prototypes from the training poses.   python make_protos.py out.npy [K] [splits]

Frames are taken every 0.1 s from the chosen rows (default train,test:stage), capped at 400k, and
clustered with plain k-means (L2, 40 iterations, k-means++-style seeding by farthest sampling).
"""
import sys, numpy as np
sys.path[:0] = ['.']
from windows import Memmap
out = sys.argv[1]; K = int(sys.argv[2]) if len(sys.argv) > 2 else 64; splits = sys.argv[3] if len(sys.argv) > 3 else "train,test:stage"
mm = Memmap('memmap'); idx = mm.index
def pick(spec):
    sp, _, gen = spec.partition(":"); m = idx.split == sp
    return m & (idx.generalization == gen) if gen else m
rows = idx[np.logical_or.reduce([pick(s) for s in splits.split(",")])]
rng = np.random.default_rng(0); per = max(1, 400_000 // len(rows))
X = []
for r in rows.itertuples():
    t = rng.integers(0, max(1, r.length - 1), per) + r.offset
    X.append(np.asarray(mm.joints[np.sort(t)], np.float32))
X = np.concatenate(X); X = X[np.isfinite(X).all(1)]
C = [X[rng.integers(len(X))]]
for _ in range(K - 1):                                   # farthest-point seeding on a subsample
    S = X[rng.integers(0, len(X), 20000)]
    C.append(S[np.min(np.abs(S[:, None] - np.stack(C)[None]).sum(-1), 1).argmax()])
C = np.stack(C)
for it in range(40):
    a = np.concatenate([((X[i:i + 50000, None] - C[None]) ** 2).sum(-1).argmin(1) for i in range(0, len(X), 50000)])
    C = np.stack([X[a == k].mean(0) if (a == k).any() else C[k] for k in range(K)])
d = np.concatenate([np.abs(X[i:i + 50000] - C[a[i:i + 50000]]).mean(1) for i in range(0, len(X), 50000)])
np.save(out, C.astype(np.float32))
print(f"frames {len(X)}  K {K}  mean |pose - prototype| {np.degrees(d.mean()):.2f} deg  (mean pose baseline {np.degrees(np.abs(X - X.mean(0)).mean()):.2f} deg)")
print("cluster sizes min/median/max", np.bincount(a, minlength=K).min(), int(np.median(np.bincount(a, minlength=K))), np.bincount(a, minlength=K).max())
