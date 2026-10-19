"""把 braindecode 里带预训练权重的成熟脑电基础模型（BIOT、LaBraM）接成肌电 → 20 关节角的逐帧回归。
它们默认把整段压成一个向量再分类；这里改取逐 token 的特征：按时间把 16 路特征拼起来 → 线性层 → 关节角，再插值回 T。
- BIOT（3.2M，Hugging Face braindecode/biot-pretrained-prest-16chs）：每路做 STFT（200 点窗、100 点步长），2 kHz 下每 50 ms 一帧，约 20 Hz。
- LaBraM（5.8M，braindecode/labram-pretrained）：每路 200 点一块，10 Hz；电极按名字查位置嵌入，腕上 16 路映射到头皮一圈 16 个电极（RING）。
输入单位：伏 ×1e4 = 微伏/100，与 LaBraM 的 0.1 mV 约定同量级。sfreq 传 200：把 2 kHz 当 200 Hz 读，肌电 20–450 Hz 落到 2–45 Hz（脑电频段）。
"""
import torch
import torch.nn as nn
import torch.nn.functional as F

REPOS = {"biot": "braindecode/biot-pretrained-prest-16chs", "labram": "braindecode/labram-pretrained"}
# 头皮上沿外圈的 16 个 10-20 电极，按顺时针，对应腕带一圈 16 路（只为借位置嵌入，没有生理对应关系）
RING = ["FP2", "AF8", "F8", "FT8", "T8", "TP8", "P8", "PO8", "O2", "O1", "PO7", "P7", "TP7", "T7", "FT7", "F7"]


def _load_labram(model, repo):
    from huggingface_hub import hf_hub_download, list_repo_files
    f = [x for x in list_repo_files(repo) if x.endswith((".safetensors", ".bin", ".pth", ".pt"))][0]
    path = hf_hub_download(repo, f)
    if f.endswith(".safetensors"):
        from safetensors.torch import load_file
        st = load_file(path)
    else:
        st = torch.load(path, map_location="cpu", weights_only=True)
    te = st["temporal_embedding"]                # (1, 1+15, D)
    n = model.temporal_embedding.shape[1] - 1
    st["temporal_embedding"] = torch.cat([te[:, :1], F.interpolate(te[:, 1:].transpose(1, 2), size=n, mode="linear",
                                          align_corners=True).transpose(1, 2)], 1)
    st = {k: v for k, v in st.items() if not k.startswith("final_layer")}
    missing, unexpected = model.load_state_dict(st, strict=False)
    assert all(k.startswith("final_layer") for k in missing) and not unexpected, (missing, unexpected)
    return len(st)


class BDEMG(nn.Module):
    def __init__(self, kind, pretrained=True, n_chans=16, n_times=10000, n_joints=20, d=256):
        super().__init__()
        from braindecode.models import BIOT, Labram
        self.kind = kind
        kw = dict(n_outputs=2, n_chans=n_chans, n_times=n_times, sfreq=200)
        if kind == "labram":
            kw["chs_info"] = [{"ch_name": n} for n in RING]
        cls = {"biot": BIOT, "labram": Labram}[kind]
        if kind == "labram" and pretrained:     # 预训练时序位置嵌入只有 15 块（15 秒脑电），这里要 50 块：线性插值后再装
            self.backbone = cls(**kw)
            self.n_loaded = _load_labram(self.backbone, REPOS[kind])
        else:
            self.backbone = cls.from_pretrained(REPOS[kind], **kw) if pretrained else cls(**kw)
        self._tok = None
        if kind == "labram":                     # 位置嵌入按电极名查：第 0 个给 CLS，其余是 RING 在 LaBraM 电极表里的序号 +1
            from braindecode.models.labram import _LABRAM_CANONICAL_INDEX
            self.register_buffer("input_chans", torch.tensor([0] + [_LABRAM_CANONICAL_INDEX[n] + 1 for n in RING]), persistent=False)
        if kind == "biot":                       # 截住线性注意力层的输出：(B, C*帧数, D)，通道为主序
            self.backbone.encoder.transformer.register_forward_hook(lambda m, i, o: setattr(self, "_tok", o))
        with torch.no_grad():
            D = self._tokens(torch.zeros(1, n_chans, n_times)).shape[-1]
        self.mix = nn.Linear(n_chans * D, d)
        self.head = nn.Sequential(nn.GELU(), nn.Linear(d, d), nn.GELU(), nn.Linear(d, n_joints))

    def _tokens(self, x):                        # -> (B, C, 帧数, D)
        B, C = x.shape[:2]
        if self.kind == "biot":
            self.backbone(x)
            t = self._tok
        else:
            t = self.backbone.forward_features(x, input_chans=self.input_chans.to(x.device), return_patch_tokens=True)
        return t.reshape(B, C, -1, t.shape[-1])

    def forward(self, X):                        # (B, C, T) volts -> (B, J, T) rad
        T = X.shape[-1]
        t = self._tokens(X * 1e4)
        B, C, n, D = t.shape
        out = self.head(self.mix(t.permute(0, 2, 1, 3).reshape(B, n, C * D))).float()
        return F.interpolate(out.transpose(1, 2), size=T, mode="linear", align_corners=False)


if __name__ == "__main__":
    for k in ("biot", "labram"):
        m = BDEMG(k)
        x = torch.randn(2, 16, 10000) * 15e-6
        y = m(x); assert y.shape == (2, 20, 10000), y.shape
        y.abs().mean().backward()
        print(k, "ok params %.2fM" % (sum(p.numel() for p in m.parameters()) / 1e6), "loaded", getattr(m, "n_loaded", "from_pretrained"))
