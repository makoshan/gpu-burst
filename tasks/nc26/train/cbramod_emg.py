"""把开源脑电基础模型 CBraMod（ICLR 2025，MIT，cbramod_vendor/）接成肌电 → 20 关节角的回归模型。
输入 (B,16,T) 伏、2 kHz；每通道切 200 点一块（0.1 秒，与 CBraMod 的 200 点块同形，所以 EEG 预训练权重能原样装入），
骨干输出 (B,16,块数,200)，按时间块把 16 路特征拼起来 → 线性层 → 关节角（10 Hz），再线性插值回 T。
单位：微伏 / 100，和 CBraMod 预处理同量级（肌电 RMS 约 12–20 µV → 0.1–0.2）。
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

from cbramod_vendor.cbramod import CBraMod

PATCH = 200


class CBraModEMG(nn.Module):
    def __init__(self, n_chans=16, n_joints=20, layers=12, d=256):
        super().__init__()
        self.backbone = CBraMod(in_dim=PATCH, out_dim=PATCH, d_model=200, dim_feedforward=800, seq_len=50,
                                n_layer=layers, nhead=8)
        self.backbone.proj_out = nn.Identity()
        self.mix = nn.Linear(n_chans * 200, d)
        self.head = nn.Sequential(nn.GELU(), nn.Linear(d, d), nn.GELU(), nn.Linear(d, n_joints))

    def load_eeg(self, path):
        """装 CBraMod 官方 EEG 预训练权重（只装骨干，proj_out 不要）。返回装上的参数个数。"""
        st = {k: v for k, v in torch.load(path, map_location="cpu", weights_only=True).items() if not k.startswith("proj_out")}
        missing, unexpected = self.backbone.load_state_dict(st, strict=False)
        assert not unexpected and all(k.startswith("proj_out") for k in missing), (missing, unexpected)
        return len(st)

    def forward(self, X):                       # (B, C, T) volts -> (B, J, T) rad
        B, C, T = X.shape
        n = T // PATCH
        x = (X * 1e4)[..., : n * PATCH].reshape(B, C, n, PATCH)     # 伏 → 微伏/100
        f = self.backbone(x)                    # (B, C, n, 200)
        h = f.permute(0, 2, 1, 3).reshape(B, n, C * 200)
        out = self.head(self.mix(h)).float()    # (B, n, J)，10 Hz
        return F.interpolate(out.transpose(1, 2), size=T, mode="linear", align_corners=False)


if __name__ == "__main__":                      # 自检：形状、可反传、可装 EEG 权重（有文件时）
    import sys
    m = CBraModEMG()
    x = torch.randn(2, 16, 10000) * 15e-6
    y = m(x); assert y.shape == (2, 20, 10000), y.shape
    y.abs().mean().backward()
    print("params %.2fM" % (sum(p.numel() for p in m.parameters()) / 1e6), "ok")
    if len(sys.argv) > 1:
        print("eeg tensors loaded:", m.load_eeg(sys.argv[1]))
