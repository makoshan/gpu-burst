"""MAE on official windows of the 6 held-out stages only: val (15 users) and test user_stage (warm-up board)."""
import sys, math, numpy as np, torch
sys.path[:0] = ['bench', 'bench/solvers', '.']
from emgformer import EMGFormerS
from windows import Memmap, official_windows, WIN
S6 = ["CountingUpDownFaceSideAway", "CountingUpDownFingerWigglingSpreading", "FingerFreeform",
      "HandOverHandCountingUpDownFingerWigglingSpreading", "HookEmHornsOKScissors", "ShakaVulcanPeace"]
mm = Memmap('memmap'); dev = 'cuda'
nets = []
for w in sys.argv[1:]:
    n = EMGFormerS().to(dev).eval(); n.load_state_dict(torch.load(w, map_location=dev, weights_only=True)); nets.append(n)
sets = {}
v = mm.select('val')
sets['val6'] = official_windows(mm, v[v.stage.isin(S6)])
sets['val_rest'] = official_windows(mm, v[~v.stage.isin(S6)])
sets['test'] = official_windows(mm, mm.select('test'))
@torch.no_grad()
def score(st, members):
    err = n = 0.0
    for i in range(0, len(st), 64):
        x = torch.from_numpy(np.stack([np.asarray(mm.emg[a:a + WIN], np.float32).T for a in st[i:i + 64]]) * 1e-6).to(dev)
        y = torch.from_numpy(np.stack([np.asarray(mm.joints[a:a + WIN], np.float32).T for a in st[i:i + 64]])).to(dev)
        p = 0
        for net in members:
            with torch.autocast('cuda', dtype=torch.bfloat16): p = p + net(x).float()
        err += (p / len(members) - y).abs().sum().item(); n += y.numel()
    return math.degrees(err / n)
print({k: len(v) for k, v in sets.items()})
rows = [(w.split('/')[-2] if '/' in w else w, [n]) for w, n in zip(sys.argv[1:], nets)]
if len(nets) > 1: rows.append(('ensemble', nets))
for name, m in rows: print(name, ' '.join(f'{k} {score(st, m):.2f}' for k, st in sets.items()), flush=True)
