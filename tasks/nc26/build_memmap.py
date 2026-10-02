"""Convert the emg2pose BIDS release (NEMAR nm000281) into two flat fp16 memmaps.

    emg.f16     (N, 16)  sEMG in microvolts
    joints.f16  (N, 20)  joint angles in radians, NaN where IK failed
    valid.u8    (N,)     1 where all 20 angles are finite (window filtering
                         without rescanning joints)
    index.csv   one row per recording: offset, length and the split fields

Loading goes through the same ``Salter2024Emg2pose._load_raw`` the competition
uses (crop after the last valid IK annotation, NaN over BAD_IK spans), so the
arrays match what neuralset feeds the official benchmark, up to fp16.

Two passes: lengths first (to size the memmaps), then workers write their
slices in place. Re-running skips recordings already marked done.

    python build_memmap.py --out ~/neural-compet26/memmap --workers 12
"""

import argparse
import json
import os
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

STUDY_PATH = Path(os.path.expanduser("~/neural-compet26/data/neural_compet/Salter2024Emg2pose"))
FIELDS = ["subject", "session", "run", "recording", "user", "split",
          "generalization", "stage", "side", "path"]

_study = None


def study():
    global _study
    if _study is None:
        import mne
        mne.set_log_level("ERROR")
        from neuralfetch.studies.salter2024emg2pose import Salter2024Emg2pose
        _study = Salter2024Emg2pose(path=STUDY_PATH)
    return _study


def load(tl):
    raw = study()._load_raw(tl)
    emg = raw.get_data(picks="emg").T * 1e6            # (T, 16) microvolts
    joints = raw.get_data(picks="misc").T               # (T, 20) radians
    assert emg.shape[1] == 16 and joints.shape[1] == 20, (emg.shape, joints.shape)
    return emg, joints


def length_of(tl):
    emg, _ = load(tl)
    return len(emg)


def write_one(args):
    i, tl, offset, length, out = args
    emg, joints = load(tl)
    assert len(emg) == length, (tl["path"], len(emg), length)
    e = np.memmap(out / "emg.f16", np.float16, "r+", shape=(total_len(out), 16))
    j = np.memmap(out / "joints.f16", np.float16, "r+", shape=(total_len(out), 20))
    e[offset:offset + length] = emg
    j[offset:offset + length] = joints
    v = np.memmap(out / "valid.u8", np.uint8, "r+", shape=(total_len(out),))
    v[offset:offset + length] = np.isfinite(joints).all(axis=1)
    e.flush(); j.flush(); v.flush()
    (out / "done" / f"{i}").touch()
    return i


def total_len(out):
    return json.loads((out / "meta.json").read_text())["n_samples"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("~/neural-compet26/memmap").expanduser())
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0, help="first N recordings only (smoke test)")
    a = ap.parse_args()
    out = a.out
    (out / "done").mkdir(parents=True, exist_ok=True)

    tls = sorted(study().iter_timelines(), key=lambda t: t["path"])
    if a.limit:
        tls = tls[:a.limit]

    idx_path = out / "index.csv"
    if idx_path.exists():
        index = pd.read_csv(idx_path)
        assert len(index) == len(tls), "index.csv is from a different recording set"
    else:
        t = time.time()
        with Pool(a.workers) as pool:
            lengths = pool.map(length_of, tls, chunksize=8)
        index = pd.DataFrame([{k: tl.get(k) for k in FIELDS} for tl in tls])
        index["length"] = lengths
        index["offset"] = np.concatenate([[0], np.cumsum(lengths)[:-1]])
        n = int(index.length.sum())
        (out / "meta.json").write_text(json.dumps(
            {"n_samples": n, "sfreq": 2000.0, "emg_unit": "uV", "joints_unit": "rad",
             "n_recordings": len(index), "dtype": "float16"}, indent=1))
        np.memmap(out / "emg.f16", np.float16, "w+", shape=(n, 16)).flush()
        np.memmap(out / "joints.f16", np.float16, "w+", shape=(n, 20)).flush()
        np.memmap(out / "valid.u8", np.uint8, "w+", shape=(n,)).flush()
        index.to_csv(idx_path, index=False)   # written last: marks pass 1 complete
        print(f"pass 1: {len(index)} recordings, {n} samples "
              f"({n / 2000 / 3600:.1f} h) in {time.time() - t:.0f}s", flush=True)

    todo = [(i, tls[i], int(r.offset), int(r.length), out)
            for i, r in index.iterrows() if not (out / "done" / f"{i}").exists()]
    t = time.time()
    with Pool(a.workers) as pool:
        for k, _ in enumerate(pool.imap_unordered(write_one, todo, chunksize=4), 1):
            if k % 1000 == 0 or k == len(todo):
                print(f"pass 2: {k}/{len(todo)} in {time.time() - t:.0f}s", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
