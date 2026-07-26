"""Behavior tests for sky/lib/setup_matcha_cloud.py (Matcha 云训练前置)。

纯渲染/校验逻辑,不触云、不装 Matcha。覆盖 P1 实测教训:
list-based symbols 渲染不丢字符(字符串拼接会丢)。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "sky/lib/setup_matcha_cloud.py"

spec = importlib.util.spec_from_file_location("smc", MODULE)
smc = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(smc)


def test_render_symbols_list_based_no_char_loss():
    """284 个 PUA 全部保留(build_matcha_filelist 曾用 ''.join 丢 6 个)。"""
    pua = [chr(0xE000 + i) for i in range(284)]
    out = smc.render_symbols(["_"] + pua)
    ns: dict = {}
    exec(out, ns)
    syms = ns["symbols"]
    assert len(syms) == 1 + len(smc.PUNCT) + 284
    assert all(c in syms for c in pua), "所有 PUA 字符必须无丢失"
    assert ns["SPACE_ID"] == syms.index(" ")
    assert len(set(syms)) == len(syms), "符号不重复"


def test_render_symbols_rejects_bad_pad():
    for bad in ([], ["x"], ["a", chr(0xE000)]):
        try:
            smc.render_symbols(bad)
        except SystemExit:
            continue
        raise AssertionError(f"应拒绝 {bad!r}")


def test_render_data_cfg_fmax_null_and_stats():
    dc = smc.render_data_cfg("teochew_bigvgan", Path("/d/fl"), "-4.578679", "2.125941")
    assert "f_max: null" in dc                      # 对齐 BigVGAN(非 8000)
    assert "mel_mean: -4.578679" in dc
    assert "mel_std: 2.125941" in dc
    assert "train_filelist_path: /d/fl/train.txt" in dc
    assert "${seed}" in dc                          # hydra 插值保留
    assert "sample_rate: 22050" in dc


def test_render_exp_cfg_experiment_name():
    ec = smc.render_exp_cfg("teochew_sandhi")
    assert "override /data: teochew_sandhi.yaml" in ec
    assert "run_name: teochew_sandhi_cloud" in ec
    assert "${N_VOCAB_PLACEHOLDER}" in ec           # main() 再替换成实际数


def test_punct_contains_space_for_space_id():
    assert " " in smc.PUNCT
