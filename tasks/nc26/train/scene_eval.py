"""场景尺子（docs/PLAN_SCENE_TRAINING.md S0）：官方 val 窗口、全部帧，按场景组报 MAE。可传多个权重，最后报集成。
  python train/scene_eval.py out.json runs/a/weights.pt [runs/b/weights.pt ...]
路径约定同 stage6_eval.py（当前目录下 bench、memmap）。眼镜操控组 = Meta 眼镜产品手势最接近的 6 个阶段（网页图 8b）。"""
import sys, json, math, numpy as np, torch
sys.path[:0] = ['bench', 'bench/solvers', '.', 'train']
from emgformer import EMGFormerS
from windows import Memmap, official_windows, WIN
GLASSES = ['IndexPinchesMiddlePinchesThumbswipes', 'FingerPinchesSingleFingerPinchesMultiple', 'ThumbsSwipesWholeHand',
           'AllFingerPinchesThumbSwipeThumbRotate', 'PokeDrawPinchRotateclosefar', 'PokePinchCloseFar']
S6 = ['CountingUpDownFaceSideAway', 'CountingUpDownFingerWigglingSpreading', 'FingerFreeform',
      'HandOverHandCountingUpDownFingerWigglingSpreading', 'HookEmHornsOKScissors', 'ShakaVulcanPeace']
FINGERS = {'thumb': range(0, 4), 'index': range(4, 8), 'middle': range(8, 12), 'ring': range(12, 16), 'pinky': range(16, 20)}
dev = 'cuda' if torch.cuda.is_available() else 'cpu'; out_path, weights = sys.argv[1], sys.argv[2:]
mm = Memmap('memmap'); val = mm.select('val'); starts, stages = [], []
for r in val.itertuples():
    st = official_windows(mm, val.loc[[r.Index]]); starts += list(st); stages += [r.stage] * len(st)
starts, stages = np.asarray(starts), np.asarray(stages)
groups = {'total': np.ones(len(starts), bool), 'glasses': np.isin(stages, GLASSES), 'val6': np.isin(stages, S6),
          'rest': ~np.isin(stages, GLASSES + S6)}
assert groups['glasses'].sum() > 0 and not (groups['glasses'] & groups['val6']).any()
nets = []
for w in weights:
    n = EMGFormerS().to(dev).eval(); n.load_state_dict(torch.load(w, map_location=dev, weights_only=True)); nets.append(n)
@torch.no_grad()
def joint_err(members):                       # (窗口数, 20) 每窗每关节的平均绝对误差（度）
    E = []
    for i in range(0, len(starts), 64):
        s = starts[i:i + 64]
        x = torch.from_numpy(np.stack([np.asarray(mm.emg[a:a + WIN], np.float32).T for a in s]) * 1e-6).to(dev)
        y = torch.from_numpy(np.stack([np.asarray(mm.joints[a:a + WIN], np.float32).T for a in s])).to(dev)
        p = 0
        for n in members:
            with torch.autocast('cuda', dtype=torch.bfloat16, enabled=dev == 'cuda'): p = p + n(x).float()
        E.append(((p / len(members) - y).abs().mean(2) * 180 / math.pi).cpu().numpy())
    return np.concatenate(E)
res = {'windows': {k: int(v.sum()) for k, v in groups.items()}, 'glasses_stages': GLASSES, 'models': {}}
rows = [(w, [n]) for w, n in zip(weights, nets)] + ([('ensemble', nets)] if len(nets) > 1 else [])
for name, m in rows:
    E = joint_err(m)
    r = {k: round(float(E[g].mean()), 3) for k, g in groups.items()}
    r['glasses_by_finger'] = {f: round(float(E[groups['glasses']][:, list(j)].mean()), 2) for f, j in FINGERS.items()}
    r['glasses_by_stage'] = {s: round(float(E[stages == s].mean()), 2) for s in GLASSES}
    res['models'][name] = r; print(name, {k: r[k] for k in groups}, r['glasses_by_finger'], flush=True)
json.dump(res, open(out_path, 'w'), ensure_ascii=False, indent=1)
