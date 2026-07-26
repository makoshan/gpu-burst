#!/usr/bin/env python3
"""云端 Matcha 训练前置:filelist PUA symbols → symbols.py + 生成 hydra config。

读环境变量(发射脚本/yaml envs 注入),避免在 SkyPilot yaml 的 block-scalar 里
内联生成 yaml(缩进会被二次剥离,极易炸)。独立文件也可本地单测。

env:
  MATCHA_SRC   Matcha 源码根(默认 ~/matcha-src)
  FILELISTS    filelist 目录(含 train.txt/val.txt/symbols.json,默认 ~/data/filelists)
  EXPERIMENT   config 名(teochew_bigvgan / teochew_sandhi)
  N_VOCAB      = len(symbols),校验用
  MEL_MEAN MEL_STD  f_max=null 域实算统计
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PUNCT = ';:,.!?¡¿—…"«»“” '  # Matcha 标准 _punctuation(含空格,SPACE_ID 依赖)


def render_symbols(symbols_json: list[str]) -> str:
    """list-based 渲染(逐元素 repr,不 "".join 拼接——后者往返丢字符,实测教训)。"""
    if not symbols_json or symbols_json[0] != "_":
        raise SystemExit("symbols.json[0] 应为 _pad")
    pua = symbols_json[1:]
    return "\n".join([
        '"""Teochew PUA phoneme symbols (cloud, list-based)."""',
        '_pad = "_"',
        f"_punctuation = {PUNCT!r}",
        f"_pua = {pua!r}",
        "symbols = [_pad] + list(_punctuation) + _pua",
        'SPACE_ID = symbols.index(" ")',
        "",
    ])


def render_data_cfg(name: str, filelists: Path, mel_mean: str, mel_std: str) -> str:
    return (
        "_target_: matcha.data.text_mel_datamodule.TextMelDataModule\n"
        f"name: {name}\n"
        f"train_filelist_path: {filelists}/train.txt\n"
        f"valid_filelist_path: {filelists}/val.txt\n"
        "batch_size: 16\n"
        "num_workers: 8\n"
        "pin_memory: True\n"
        "cleaners: [basic_cleaners]\n"
        "add_blank: True\n"
        "n_spks: 1\n"
        "n_fft: 1024\n"
        "n_feats: 80\n"
        "sample_rate: 22050\n"
        "hop_length: 256\n"
        "win_length: 1024\n"
        "f_min: 0\n"
        "f_max: null\n"
        "data_statistics:\n"
        f"  mel_mean: {mel_mean}\n"
        f"  mel_std: {mel_std}\n"
        "seed: ${seed}\n"
        "load_durations: false\n"
    )


def render_exp_cfg(name: str) -> str:
    return (
        "# @package _global_\n"
        "defaults:\n"
        f"  - override /data: {name}.yaml\n"
        'tags: ["teochew", "cloud"]\n'
        f"run_name: {name}_cloud\n"
        "model:\n"
        "  n_vocab: ${N_VOCAB_PLACEHOLDER}\n"
    )


def main() -> int:
    matcha = Path(os.environ.get("MATCHA_SRC", str(Path.home() / "matcha-src")))
    fl = Path(os.environ.get("FILELISTS", str(Path.home() / "data/filelists")))
    exp = os.environ.get("EXPERIMENT", "teochew_bigvgan")
    n_vocab = int(os.environ["N_VOCAB"])
    mean, std = os.environ["MEL_MEAN"], os.environ["MEL_STD"]

    sj = json.loads((fl / "symbols.json").read_text(encoding="utf-8"))
    sym_py = render_symbols(sj)
    (matcha / "matcha/text/symbols.py").write_text(sym_py, encoding="utf-8")
    n_sym = 1 + len(PUNCT) + len(sj[1:])
    if n_sym != n_vocab:
        raise SystemExit(f"symbols {n_sym} != N_VOCAB {n_vocab}(filelist 与 env 不匹配)")

    cfg = matcha / "configs"
    (cfg / "data" / f"{exp}.yaml").write_text(render_data_cfg(exp, fl, mean, std))
    (cfg / "experiment" / f"{exp}.yaml").write_text(
        render_exp_cfg(exp).replace("${N_VOCAB_PLACEHOLDER}", str(n_vocab)))

    # best-val checkpoint(monitor loss/val, min)。P1 教训:小数据 best-val 会欠拟合,
    # 训练脚本仍应取晚期 ckpt;这里只是让 checkpoint 按 val 存 top-k 便于对比。
    mc = cfg / "callbacks/model_checkpoint.yaml"
    if mc.exists():
        s = mc.read_text().replace("monitor: epoch", "monitor: loss/val").replace('mode: "max"', 'mode: "min"')
        mc.write_text(s)

    print(f"cloud setup ok: symbols={n_sym} n_vocab={n_vocab} exp={exp} mel=({mean},{std})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
