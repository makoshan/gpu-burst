"""EMGFormer-S for Track 4, ported to one file from EgoEMG (MIT, arXiv 2605.05712).

Model code adapted from github.com/zhenqis123/EgoEMG @ f7cbd04,
Copyright (c) 2026 EgoEMG Authors, MIT License (see LICENSE-EgoEMG).

TDS featurizer with global squeeze-excite (tds_slim_16ch) -> 3-layer non-causal
RoPE transformer (256-d, 4 heads, FFN 512) -> MLP head, linearly upsampled to
the input rate. Recipe from EgoEMG ``emg2pose_emgformer_small``: AdamW 1e-3
(wd 0.01) with cosine to 1e-5, bf16, grad clip 1, L1 loss, input / 18.49 in
microvolts, and the augmentations below.

Track-specific: inputs arrive in volts and the featurizer's valid convs eat
``left_context`` (510) samples, so windows are scaled to microvolts and
left zero-padded by that much at train and test time.

ponytail: no fingertip (FK) loss term (EgoEMG adds 0.01x) and no validation
checkpoint selection; the last epoch is kept.
"""

import collections
import math
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import nn

from benchmark_utils.base_solver import CompetSolver

EMG2POSE_STD_UV = 18.49


# --- TDS featurizer --------------------------------------------------------

class SqueezeExcite(nn.Module):
    def __init__(self, channels, reduction=4):
        super().__init__()
        hidden = max(channels // reduction, 1)
        self.net = nn.Sequential(
            nn.Conv1d(channels, hidden, 1), nn.ReLU(inplace=True),
            nn.Conv1d(hidden, channels, 1), nn.Sigmoid())

    def forward(self, x):                       # global mode, residual
        return x * self.net(x.mean(dim=-1, keepdim=True)) + x


class Conv1dBlock(nn.Module):
    def __init__(self, cin, cout, kernel_size, stride):
        super().__init__()
        self.kernel_size, self.stride = kernel_size, stride
        self.conv = nn.Sequential(nn.Conv1d(cin, cout, kernel_size, stride),
                                  nn.ReLU(inplace=True))
        self.norm = nn.LayerNorm(cout)
        self.se = SqueezeExcite(cout)

    def forward(self, x):
        x = self.norm(self.conv(x).swapaxes(-1, -2)).swapaxes(-1, -2)
        return self.se(x)


class TDSConv2dBlock(nn.Module):
    def __init__(self, channels, width, kernel_width):
        super().__init__()
        self.channels, self.width = channels, width
        self.conv2d = nn.Conv2d(channels, channels, (1, kernel_width))
        self.layer_norm = nn.LayerNorm(channels * width)
        self.se = SqueezeExcite(channels * width)

    def forward(self, inputs):
        B, C, T = inputs.shape
        x = F.relu(self.conv2d(inputs.reshape(B, self.channels, self.width, T)))
        x = x.reshape(B, C, -1)
        x = x + inputs[..., -x.shape[-1]:]
        return self.se(self.layer_norm(x.swapaxes(-1, -2)).swapaxes(-1, -2))


class TDSFullyConnectedBlock(nn.Module):
    def __init__(self, n):
        super().__init__()
        self.fc_block = nn.Sequential(nn.Linear(n, n), nn.ReLU(inplace=True),
                                      nn.Linear(n, n))
        self.layer_norm = nn.LayerNorm(n)
        self.se = SqueezeExcite(n)

    def forward(self, inputs):
        x = self.fc_block(inputs.swapaxes(-1, -2)).swapaxes(-1, -2) + inputs
        return self.se(self.layer_norm(x.swapaxes(-1, -2)).swapaxes(-1, -2))


class TdsStage(nn.Module):
    def __init__(self, cin, in_kernel, in_stride, channels, feature_width,
                 kernel_width):
        super().__init__()
        C = channels * feature_width
        self.in_kernel, self.in_stride, self.kernel_width = (
            in_kernel, in_stride, kernel_width)
        self.layers = nn.Sequential(collections.OrderedDict(
            conv1dblock=Conv1dBlock(cin, C, in_kernel, in_stride),
            tds=nn.Sequential(TDSConv2dBlock(channels, feature_width, kernel_width),
                              TDSFullyConnectedBlock(C))))

    def forward(self, x):
        return self.layers(x)


class TdsSlim16(nn.Module):
    """``tds_slim_16ch``: 2 stem convs + 2 one-block TDS stages, 256 channels."""

    def __init__(self, n_chans=16):
        super().__init__()
        stem = [Conv1dBlock(n_chans, 256, 11, 5), Conv1dBlock(256, 256, 5, 2)]
        stages = [TdsStage(256, 9, 5, 8, 32, 5), TdsStage(256, 3, 1, 8, 32, 3)]
        self.layers = nn.Sequential(*stem, *stages)
        left, stride = 0, 1
        for b in stem:
            left += (b.kernel_size - 1) * stride
            stride *= b.stride
        for s in stages:
            left += (s.in_kernel - 1) * stride
            stride *= s.in_stride
            left += (s.kernel_width - 1) * stride
        self.left_context = left                # 510 samples

    def forward(self, x):
        return self.layers(x)


# --- RoPE transformer ------------------------------------------------------

def _rope(x, cos, sin):
    x1, x2 = x[..., ::2], x[..., 1::2]
    return torch.stack((x1 * cos - x2 * sin, x1 * sin + x2 * cos), -1).flatten(-2)


class RopeLayer(nn.Module):
    def __init__(self, d, heads, ffn, dropout):
        super().__init__()
        self.heads, self.hd, self.dropout = heads, d // heads, dropout
        self.in_proj = nn.Linear(d, 3 * d)
        self.out_proj = nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, ffn), nn.ReLU(), nn.Dropout(dropout),
                                nn.Linear(ffn, d), nn.Dropout(dropout))
        self.norm1, self.norm2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.drop1 = nn.Dropout(dropout)
        self.register_buffer("inv_freq", 1.0 / (10000 ** (
            torch.arange(0, self.hd, 2).float() / self.hd)), persistent=False)

    def forward(self, x):                       # (B, T, d), norm first
        b, t, d = x.shape
        q, k, v = self.in_proj(self.norm1(x)).chunk(3, -1)
        q, k, v = (z.view(b, t, self.heads, self.hd).transpose(1, 2) for z in (q, k, v))
        freqs = torch.outer(torch.arange(t, device=x.device, dtype=self.inv_freq.dtype),
                            self.inv_freq)
        cos, sin = freqs.cos().to(q.dtype), freqs.sin().to(q.dtype)
        q, k = _rope(q, cos, sin), _rope(k, cos, sin)
        a = F.scaled_dot_product_attention(
            q, k, v, dropout_p=self.dropout if self.training else 0.0)
        x = x + self.drop1(self.out_proj(a.transpose(1, 2).reshape(b, t, d)))
        return x + self.ff(self.norm2(x))


ENV_WINDOWS = (100, 400)        # 50 ms and 200 ms RMS windows at 2 kHz


def envelope(x, n_frames, hop=50):
    """Log-RMS envelopes per channel at the featurizer frame rate: (B, n_frames, C * len(ENV_WINDOWS))."""
    feats = []
    for w in ENV_WINDOWS:
        e = F.avg_pool1d(x.float().pow(2), w, stride=hop, padding=w // 2)[..., :n_frames]
        if e.shape[-1] != n_frames:
            e = F.interpolate(e, size=n_frames, mode="linear", align_corners=False)
        feats.append(torch.log(e.sqrt() + 1e-3))
    return torch.cat(feats, 1).transpose(1, 2)


class EMGFormerS(nn.Module):
    def __init__(self, n_chans=16, n_joints=20, d=256, heads=4, layers=3, ffn=512,
                 dropout=0.1, chan_stride=1, env=False, n_protos=0):
        super().__init__()
        # chan_stride=2 keeps every other electrode: emulates an 8-channel band.
        self.chan_stride, self.n_in = chan_stride, n_chans // chan_stride
        self.featurizer = TdsSlim16(self.n_in)
        # Optional second stream: amplitude envelopes added to the conv features.
        # Zero-initialised, so the model starts out identical to the single-stream one.
        self.env = env
        if env:
            self.env_proj = nn.Linear(self.n_in * len(ENV_WINDOWS), d)
            nn.init.zeros_(self.env_proj.weight)
            nn.init.zeros_(self.env_proj.bias)
        self.layers = nn.ModuleList(RopeLayer(d, heads, ffn, dropout)
                                    for _ in range(layers))
        self.output_proj = nn.Linear(d, d)
        self.head = nn.Sequential(nn.Linear(d, 512), nn.ReLU(), nn.Dropout(dropout),
                                  nn.Linear(512, n_joints))
        self.register_buffer("x_scale", torch.tensor(1e6 / EMG2POSE_STD_UV))
        # Optional hand-shape prototypes: classify each 40 Hz frame into one of K pose prototypes
        # (k-means centres of training poses) and add the expected prototype to the regressed
        # output, which then only has to learn the residual. Zero-initialised logits and a
        # mean-removed prototype table: the model starts out identical to the plain one.
        self.n_protos = n_protos
        if n_protos:
            self.register_buffer("protos", torch.zeros(n_protos, n_joints))
            self.proto_head = nn.Linear(d, n_protos)
            nn.init.zeros_(self.proto_head.weight)
            nn.init.zeros_(self.proto_head.bias)
        self.proto_temp = 1.0                   # < 1 sharpens the prototype choice at inference
        self.logits = None                      # (B, T_feat, K) of the last forward, for the CE loss

    def set_protos(self, protos):               # (K, J) rad
        self.protos.copy_(torch.as_tensor(protos, dtype=self.protos.dtype))

    def forward(self, X):                       # (B, C, T) volts -> (B, J, T) rad
        T = X.shape[-1]
        if X.shape[1] != self.n_in:             # full 16-ch input: keep evens
            X = X[:, ::self.chan_stride]
        Xs = X * self.x_scale
        h = self.featurizer(F.pad(Xs, (self.featurizer.left_context, 0))).transpose(1, 2)  # (B, T_feat, 256) at 40 Hz
        if self.env:
            h = h + self.env_proj(envelope(Xs, h.shape[1])).to(h.dtype)
        for layer in self.layers:
            h = layer(h)
        h = self.output_proj(h)
        out = self.head(h).float()
        if self.n_protos:
            self.logits = self.proto_head(h).float()
            w = torch.softmax(self.logits / self.proto_temp, -1)
            out = out + w @ (self.protos - self.protos.mean(0))
        return F.interpolate(out.transpose(1, 2), size=T, mode="linear", align_corners=False)


# --- augmentation (EgoEMG emgformer_regression_aug_best) ----------------------

def augment(X):
    """Per-sample: band rotation +-1, 25% channel mask, 3 frequency masks of
    <=128 rfft bins, and 50% Gaussian noise at 25-35 dB SNR."""
    B, C, T = X.shape
    shifts = torch.randint(-1, 2, (B,), device=X.device)
    idx = (torch.arange(C, device=X.device)[None] - shifts[:, None]) % C
    X = torch.gather(X, 1, idx[:, :, None].expand(B, C, T))
    X = X * (torch.rand(B, C, 1, device=X.device) >= 0.25)
    spec = torch.fft.rfft(X, dim=-1)
    n_freq = spec.shape[-1]
    keep = torch.ones(B, 1, n_freq, device=X.device)
    for _ in range(3):
        size = torch.randint(0, 129, (B,), device=X.device)
        start = (torch.rand(B, device=X.device) * (n_freq - size + 1)).long()
        f = torch.arange(n_freq, device=X.device)[None]
        keep[:, 0] *= ~((f >= start[:, None]) & (f < (start + size)[:, None]))
    X = torch.fft.irfft(spec * keep, n=T, dim=-1)
    power = X.pow(2).mean(dim=(1, 2), keepdim=True)
    snr = torch.empty(B, 1, 1, device=X.device).uniform_(25, 35)
    noise = torch.randn_like(X) * (power / 10 ** (snr / 10)).sqrt()
    return X + noise * (torch.rand(B, 1, 1, device=X.device) < 0.5)


class Model:
    def __init__(self, meta, device, n_epochs, lr, chan_stride=1, env=False, layers=3, ffn=512, n_protos=0):
        self.device, self.n_epochs, self.lr = device, n_epochs, lr
        self.net = EMGFormerS(meta["n_chans"], meta["n_joints"], layers=layers, ffn=ffn,
                              chan_stride=chan_stride, env=env, n_protos=n_protos).to(device)

    def fit(self, train_loader):
        opt = torch.optim.AdamW(self.net.parameters(), lr=self.lr, weight_decay=0.01)
        sched = torch.optim.lr_scheduler.CosineAnnealingLR(
            opt, T_max=max(self.n_epochs, 1), eta_min=1e-5)
        use_bf16 = str(self.device).startswith("cuda")
        for epoch in range(self.n_epochs):
            self.net.train()
            total = n = 0.0
            for X, y, _ in train_loader:
                X, y = X.to(self.device).float(), y.to(self.device).float()
                with torch.autocast("cuda", dtype=torch.bfloat16, enabled=use_bf16):
                    # Random electrode subset per batch when chan_stride > 1,
                    # selected before augment so rotation acts on the 8-band.
                    offset = int(torch.randint(self.net.chan_stride, ()))
                    pred = self.net(augment(X[:, offset::self.net.chan_stride]))
                mask = ~torch.isnan(y)
                loss = (pred - y.nan_to_num()).abs()[mask].mean()
                opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), 1.0)
                opt.step()
                total += loss.item() * len(X)
                n += len(X)
            sched.step()
            print(f"[emgformer] epoch {epoch + 1}/{self.n_epochs} "
                  f"train L1 {math.degrees(total / n):.2f} deg", flush=True)
        return self

    @torch.no_grad()
    def predict(self, X):
        self.net.eval()
        return self.net(torch.as_tensor(X, dtype=torch.float32).to(self.device))


class Ensemble:
    """Averages the radian predictions of several trained Models."""

    def __init__(self, models):
        self.models = models

    @torch.no_grad()
    def predict(self, X):
        return sum(m.predict(X) for m in self.models) / len(self.models)


def load_trained(meta, device, submission_dir, n_epochs=30, lr=1e-3, chan_stride=1):
    """Model per shipped weights*.pt (sorted); an Ensemble when there are several.

    Each file knows its own electrode width (first conv), so 8- and 16-channel
    members can be mixed. With no weights, returns an untrained Model to fit.
    """
    files = sorted(Path(submission_dir).glob("weights*.pt"))
    if not files:
        return Model(meta, device, n_epochs, lr, chan_stride)
    models = []
    for f in files:
        state = torch.load(f, map_location=device, weights_only=True)
        cs = meta["n_chans"] // state["featurizer.layers.0.conv.0.weight"].shape[1]
        # depth / FFN width are read off the weights too, so sizes can be mixed
        depth = len({k.split(".")[1] for k in state if k.startswith("layers.")})
        m = Model(meta, device, n_epochs, lr, cs, env="env_proj.weight" in state,
                  layers=depth, ffn=state["layers.0.ff.0.weight"].shape[0],
                  n_protos=state["protos"].shape[0] if "protos" in state else 0)
        m.net.load_state_dict(state)
        print(f"[loading] {f} (chan_stride={cs})")
        models.append(m)
    return models[0] if len(models) == 1 else Ensemble(models)


class Solver(CompetSolver):
    name = "EMGFormer-S"
    parameters = {"n_epochs": [30], "lr": [1e-3], "chan_stride": [1]}

    def load_model(self, meta):
        return load_trained(meta, self.device, meta["submission_dir"],
                            self.n_epochs, self.lr, self.chan_stride)

    def fit(self, model, train_loader):
        model.fit(train_loader)

    def save_model(self, model, path):
        torch.save(model.net.state_dict(), path / "weights.pt")


if __name__ == "__main__":
    # Shape / context self-check: python emgformer.py (needs benchmark_utils on path)
    net = EMGFormerS()
    assert net.featurizer.left_context == 510, net.featurizer.left_context
    X = torch.randn(2, 16, 10000) * 4e-5
    assert net(X).shape == (2, 20, 10000)
    assert augment(X).shape == X.shape
    nete = EMGFormerS(env=True)
    assert nete(X).shape == (2, 20, 10000)
    assert envelope(X * nete.x_scale, 200).shape == (2, 200, 32)
    net8 = EMGFormerS(chan_stride=2)
    assert net8(X).shape == net8(augment(X[:, 1::2])).shape == (2, 20, 10000)
    print("ok", sum(p.numel() for p in net.parameters()) / 1e6, "M params")
