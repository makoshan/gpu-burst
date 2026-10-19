"""场景训练的一臂：只在外层换训练集抽样，再原样运行 train.py（train.py / windows.py 不改）。
  python run_arm.py [--balance 0.5 | --scene-share 0.25] -- <train.py 的参数>
--balance：阶段均衡（balance_loader.py）。--scene-share：把眼镜操控组 6 个阶段的抽样份额提到该值，组内、组外各自保持原比例。
两个都不给就是对照臂，什么都不替换。"""
import runpy, sys
from pathlib import Path
import numpy as np, torch
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import windows, balance_loader

GLASSES = ['IndexPinchesMiddlePinchesThumbswipes', 'FingerPinchesSingleFingerPinchesMultiple', 'ThumbsSwipesWholeHand',
           'AllFingerPinchesThumbSwipeThumbRotate', 'PokeDrawPinchRotateclosefar', 'PokePinchCloseFar']   # 同 train/scene_eval.py


def scene_weights(stage, share):
    g = np.isin(stage, GLASSES)
    assert 0 < g.mean() < share < 1, f'眼镜操控组原份额 {g.mean():.3f}，目标 {share}'
    return np.where(g, share / g.sum(), (1 - share) / (~g).sum()), float(g.mean())


def install_scene(share):
    original = windows.loader

    def weighted(mm, starts, *args, **kwargs):
        dl = original(mm, starts, *args, **kwargs)
        if not kwargs.get('shuffle', False):
            return dl                                       # val / test：不动
        off = mm.index.offset.to_numpy()
        stage = mm.index.stage.to_numpy()[np.searchsorted(off, np.asarray(starts), side='right') - 1]
        w, before = scene_weights(stage, share)
        print({'scene_share': {'before': before, 'after': share, 'windows': int(len(w))}}, flush=True)
        return torch.utils.data.DataLoader(
            dl.dataset, batch_size=dl.batch_size, num_workers=dl.num_workers, pin_memory=dl.pin_memory,
            drop_last=True, persistent_workers=dl.persistent_workers, worker_init_fn=dl.worker_init_fn,
            sampler=torch.utils.data.WeightedRandomSampler(torch.from_numpy(w), len(w), replacement=True))
    windows.loader = weighted


if __name__ == '__main__':
    i = sys.argv.index('--'); mine, rest = sys.argv[1:i], sys.argv[i + 1:]
    opt = dict(zip(mine[::2], map(float, mine[1::2])))
    assert set(opt) <= {'--balance', '--scene-share'} and len(opt) <= 1, '一臂只改一个变量'
    if '--self-check' in rest:                              # 不需要数据：份额算得对不对
        st = np.array(['unconstrained'] * 90 + [GLASSES[0]] * 6 + [GLASSES[1]] * 4)
        w, b = scene_weights(st, 0.25)
        assert abs(b - 0.10) < 1e-9 and abs(w[90:].sum() - 0.25) < 1e-9 and abs(w.sum() - 1) < 1e-9
        print('self-check ok'); sys.exit(0)
    balance_loader.install(windows, opt.get('--balance', 0.0))
    if '--scene-share' in opt:
        install_scene(opt['--scene-share'])
    sys.argv = [str(HERE / 'train.py')] + rest
    runpy.run_path(sys.argv[0], run_name='__main__')
