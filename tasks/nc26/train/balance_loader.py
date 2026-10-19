"""阶段均衡采样（V1）的外挂：不改 train.py / windows.py，只在外层替换 windows.loader。

用法（在 run.py 里 `import windows` 之后、运行 train.py 之前）：
    import balance_loader; balance_loader.install(windows, alpha)
alpha = 0 时什么都不做，训练与原来逐行相同；alpha > 0 时只改训练集的抽样：
每个窗口的权重 = 它所在阶段的窗口数 ^ (-alpha)，有放回抽 len(starts) 个，所以每轮步数不变。
为什么：自由活动三个阶段约占训练窗口 44%，结构化手势被稀释；没见过的阶段都是结构化手势。
评估用的 loader（shuffle=False）原样返回。"""
import numpy as np
import torch

FREE = ("unconstrained", "TwoHandedFreeStyle", "OneHandedFreeStyle")


def stage_weights(index, starts, alpha):
    """返回 (每个窗口的权重, 说明字典)。index 需要 offset（递增）和 stage 两列。"""
    off = index.offset.to_numpy()
    assert (np.diff(off) > 0).all(), "index.offset 必须严格递增"
    stage = index.stage.to_numpy()[np.searchsorted(off, np.asarray(starts), side="right") - 1]
    names, inv, cnt = np.unique(stage, return_inverse=True, return_counts=True)
    w = cnt[inv].astype(np.float64) ** -alpha
    share = np.bincount(inv, weights=w) / w.sum()
    free = np.isin(names, FREE)
    info = {"alpha": alpha, "stages": int(len(names)), "windows": int(len(w)),
            "free_share_before": float(cnt[free].sum() / cnt.sum()), "free_share_after": float(share[free].sum()),
            "max_stage_share_after": float(share.max()), "min_stage_share_after": float(share.min())}
    return w, info


def install(windows, alpha):
    if not alpha:
        return None
    original = windows.loader

    def balanced(mm, starts, *args, **kwargs):
        dl = original(mm, starts, *args, **kwargs)
        if not kwargs.get("shuffle", False):
            return dl                                   # val / test：不动
        w, info = stage_weights(mm.index, starts, alpha)
        print({"stage_balance": info}, flush=True)
        return torch.utils.data.DataLoader(
            dl.dataset, batch_size=dl.batch_size, num_workers=dl.num_workers, pin_memory=dl.pin_memory,
            drop_last=True, persistent_workers=dl.persistent_workers, worker_init_fn=dl.worker_init_fn,
            sampler=torch.utils.data.WeightedRandomSampler(torch.from_numpy(w), len(w), replacement=True))

    windows.loader = balanced
    return balanced
