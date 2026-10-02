"""Compact copy of the memmaps for a smaller disk (thursday-win, ~86 GB).

    train/emg.f16       train-split sEMG, 2 kHz, uV            (N, 16)
    train/joints200.f16 train-split angles at 200 Hz (every 10th sample)
    train/valid.u8      2 kHz finite-target mask (window filtering)
    train/index.csv     train rows with offsets into the arrays above
    val_emg.f16 / val_joints.f16    official val windows, full rate  (W, 10000, C)
    test_emg.f16 / test_joints.f16  official user_stage test windows, full rate

Storing angles at 200 Hz costs 0.12 deg mean error on val (linear upsampling);
training compares pred[..., ::10] with them, so nothing is interpolated there.
Val/test stay at 2 kHz so scores keep the official definition.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from windows import Memmap, official_windows   # noqa: E402

DS = 10
src = Memmap("~/neural-compet26/memmap")
out = Path(sys.argv[1] if len(sys.argv) > 1 else "~/neural-compet26/compact").expanduser()
(out / "train").mkdir(parents=True, exist_ok=True)

rows = src.index[src.index.split == "train"].copy()
n = int(rows.length.sum())
n200 = int(((rows.length + DS - 1) // DS).sum())
emg = np.memmap(out / "train/emg.f16", np.float16, "w+", shape=(n, 16))
j200 = np.memmap(out / "train/joints200.f16", np.float16, "w+", shape=(n200, 20))
valid = np.memmap(out / "train/valid.u8", np.uint8, "w+", shape=(n,))
o = o2 = 0
new_off, new_off200 = [], []
for k, r in enumerate(rows.itertuples(), 1):
    s, L = int(r.offset), int(r.length)
    emg[o:o + L] = src.emg[s:s + L]
    valid[o:o + L] = src.valid[s:s + L]
    L2 = (L + DS - 1) // DS
    j200[o2:o2 + L2] = src.joints[s:s + L:DS]
    new_off.append(o); new_off200.append(o2)
    o += L; o2 += L2
    if k % 2000 == 0:
        print(f"train {k}/{len(rows)}", flush=True)
rows["offset"], rows["offset200"] = new_off, new_off200
rows.to_csv(out / "train/index.csv", index=False)
emg.flush(); j200.flush(); valid.flush()

meta = {"n_train": n, "n_train200": n200, "downsample": DS}
for split in ("val", "test"):
    starts = official_windows(src, src.select(split))
    e = np.memmap(out / f"{split}_emg.f16", np.float16, "w+", shape=(len(starts), 10000, 16))
    j = np.memmap(out / f"{split}_joints.f16", np.float16, "w+", shape=(len(starts), 10000, 20))
    for i, s in enumerate(starts):
        e[i] = src.emg[s:s + 10000]
        j[i] = src.joints[s:s + 10000]
    e.flush(); j.flush()
    meta[f"n_{split}"] = len(starts)
    print(split, len(starts), "windows", flush=True)
(out / "meta.json").write_text(json.dumps(meta, indent=1))
print("DONE", meta, flush=True)
