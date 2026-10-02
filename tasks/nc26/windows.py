"""Windows over the flat memmaps written by build_memmap.py.

``official_windows`` reproduces the neuralbench emg/pose segmentation so local
scores match the platform:
  - recordings shorter than 5.895 s are dropped;
  - 5-s windows start at 0 with a 5-s stride, the incomplete tail is dropped;
  - a window with any non-finite angle is dropped (min_finite_target_fraction 1);
  - test keeps only generalization == 'user_stage'.

``train_windows`` is the training sampler: overlapping windows, a random shift
per draw, and windows kept while at least ``min_valid`` of their frames have
finite targets (NaN frames are masked in the loss instead).

Items are (X volts float32 (16, L), y radians float32 (20, L)), the same
contract as the competition loader, so solvers train on either unchanged.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

SFREQ = 2000
WIN = 10_000                      # 5 s
MIN_REC = int(5.895 * SFREQ)      # neuralbench drops recordings shorter than this


class Memmap:
    def __init__(self, root):
        root = Path(root).expanduser()
        meta = json.loads((root / "meta.json").read_text())
        n = meta["n_samples"]
        self.index = pd.read_csv(root / "index.csv", dtype={"subject": str, "session": str, "run": str})
        self.emg = np.memmap(root / "emg.f16", np.float16, "r", shape=(n, 16))
        self.joints = np.memmap(root / "joints.f16", np.float16, "r", shape=(n, 20))
        self.valid = np.memmap(root / "valid.u8", np.uint8, "r", shape=(n,))

    def select(self, split, subjects=None, test_user_stage_only=True):
        r = self.index[self.index.split == split]
        if split == "test" and test_user_stage_only:
            r = r[r.generalization == "user_stage"]
        if subjects is not None:
            r = r[r.subject.isin(set(subjects))]
        return r


def _valid_counts(mm, starts, length):
    """Finite-target frames in each window (a sum over the valid mask)."""
    out = np.empty(len(starts), np.int64)
    for k, s in enumerate(starts):
        out[k] = int(mm.valid[s:s + length].sum())
    return out


def official_windows(mm, rows, length=WIN):
    starts = []
    for r in rows.itertuples():
        if r.length < MIN_REC:
            continue
        for s in range(0, r.length - length + 1, length):
            starts.append(r.offset + s)
    starts = np.asarray(starts, np.int64)
    return starts[_valid_counts(mm, starts, length) == length]


def train_windows(mm, rows, length=WIN, stride=WIN // 2, min_valid=0.5):
    """Returns (starts, max_shift): each draw may move right by up to max_shift."""
    starts, shifts = [], []
    for r in rows.itertuples():
        if r.length < length:
            continue
        last = r.length - length
        for s in range(0, last + 1, stride):
            starts.append(r.offset + s)
            shifts.append(min(stride - 1, last - s))
    starts, shifts = np.asarray(starts, np.int64), np.asarray(shifts, np.int64)
    keep = _valid_counts(mm, starts, length) >= min_valid * length
    return starts[keep], shifts[keep]


class WindowDataset(torch.utils.data.Dataset):
    def __init__(self, mm, starts, length=WIN, max_shift=None):
        self.mm, self.starts, self.length = mm, starts, length
        self.max_shift = max_shift

    def __len__(self):
        return len(self.starts)

    def __getitem__(self, i):
        s = int(self.starts[i])
        if self.max_shift is not None and self.max_shift[i] > 0:
            s += int(np.random.randint(0, self.max_shift[i] + 1))
        x = torch.from_numpy(np.asarray(self.mm.emg[s:s + self.length], np.float32).T * 1e-6)
        y = torch.from_numpy(np.asarray(self.mm.joints[s:s + self.length], np.float32).T)
        return x, y, {}


def loader(mm, starts, max_shift=None, batch_size=64, shuffle=False, workers=8):
    return torch.utils.data.DataLoader(
        WindowDataset(mm, starts, max_shift=max_shift), batch_size=batch_size,
        shuffle=shuffle, num_workers=workers, pin_memory=True, drop_last=shuffle,
        persistent_workers=workers > 0,
        worker_init_fn=lambda w: np.random.seed((torch.initial_seed() + w) % 2**32))


class Compact:
    """The make_compact.py layout: train split with 200 Hz angles + stored val/test windows."""

    DS = 10

    def __init__(self, root):
        root = Path(root).expanduser()
        self.root, self.meta = root, json.loads((root / "meta.json").read_text())
        m = self.meta
        self.index = pd.read_csv(root / "train/index.csv", dtype={"subject": str})
        self.emg = np.memmap(root / "train/emg.f16", np.float16, "r", shape=(m["n_train"], 16))
        self.j200 = np.memmap(root / "train/joints200.f16", np.float16, "r", shape=(m["n_train200"], 20))
        self.valid = np.memmap(root / "train/valid.u8", np.uint8, "r", shape=(m["n_train"],))

    def train_windows(self, length=WIN, stride=WIN // 2, min_valid=0.5):
        assert stride % self.DS == 0
        starts, off200, shifts = [], [], []
        for r in self.index.itertuples():
            if r.length < length:
                continue
            last = r.length - length
            for s in range(0, last + 1, stride):
                starts.append(r.offset + s); off200.append(r.offset200 + s // self.DS)
                shifts.append(min(stride - self.DS, last - s) // self.DS)   # in 200 Hz steps
        starts, off200, shifts = map(lambda v: np.asarray(v, np.int64), (starts, off200, shifts))
        keep = _valid_counts(self, starts, length) >= min_valid * length
        return starts[keep], off200[keep], shifts[keep]

    def eval_arrays(self, split):
        n = self.meta[f"n_{split}"]
        e = np.memmap(self.root / f"{split}_emg.f16", np.float16, "r", shape=(n, WIN, 16))
        j = np.memmap(self.root / f"{split}_joints.f16", np.float16, "r", shape=(n, WIN, 20))
        return e, j


class CompactTrain(torch.utils.data.Dataset):
    """y comes back at 200 Hz (20, L/10); compare with pred[..., ::10]."""

    def __init__(self, c, starts, off200, shifts, length=WIN):
        self.c, self.starts, self.off200, self.shifts, self.length = c, starts, off200, shifts, length

    def __len__(self):
        return len(self.starts)

    def __getitem__(self, i):
        k = int(np.random.randint(0, self.shifts[i] + 1)) if self.shifts[i] > 0 else 0
        s, s2 = int(self.starts[i]) + k * Compact.DS, int(self.off200[i]) + k
        x = torch.from_numpy(np.asarray(self.c.emg[s:s + self.length], np.float32).T * 1e-6)
        y = torch.from_numpy(np.asarray(self.c.j200[s2:s2 + self.length // Compact.DS], np.float32).T)
        return x, y, {}


class CompactEval(torch.utils.data.Dataset):
    def __init__(self, e, j):
        self.e, self.j = e, j

    def __len__(self):
        return len(self.e)

    def __getitem__(self, i):
        return (torch.from_numpy(np.asarray(self.e[i], np.float32).T * 1e-6),
                torch.from_numpy(np.asarray(self.j[i], np.float32).T), {})


def make_loader(ds, batch_size=64, shuffle=False, workers=8):
    return torch.utils.data.DataLoader(
        ds, batch_size=batch_size, shuffle=shuffle, num_workers=workers, pin_memory=True,
        drop_last=shuffle, persistent_workers=workers > 0,
        worker_init_fn=lambda w: np.random.seed((torch.initial_seed() + w) % 2**32))
