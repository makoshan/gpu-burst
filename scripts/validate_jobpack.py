#!/usr/bin/env python3
"""作业包发射前全量校验——把「发射后才炸」的问题全部在本地查出来。

2026-08-01 的教训：七次发射里有四次死在本地就能查出的错误上
（模型名与权重清单不符、阶段依赖的文件名对不上、音频缺失…），
每次都要烧掉 15 分钟 setup + 计费机时才看得见。

用法：
    python3 scripts/validate_jobpack.py tasks/ayue-720p-jobpack [--strict-720p]

退出码非 0 即禁止发射。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# fetch_weights.sh 里声明的目标路径 → ComfyUI 里的文件名
WEIGHT_RE = re.compile(r'\["([^"]+)"\]="([^"]+)"')
LOADER_FIELDS = ("model", "model_name", "clip_name", "lora", "vae_name")
MEDIA_FIELDS = ("audio", "video", "image")


def load_declared_weights(pack: Path) -> dict[str, str]:
    """会被放进 models/ 的文件名。优先读 weights-manifest.json（带 sha256 的权威源），
    回退到解析 fetch_weights.sh 的内联声明。"""
    mf = pack / "weights-manifest.json"
    if mf.exists():
        data = json.loads(mf.read_text(encoding="utf-8"))
        out = {Path(k).name: k for k in data}
        return out
    sh = (pack / "fetch_weights.sh").read_text(encoding="utf-8")
    out = {}
    for dst, _src in WEIGHT_RE.findall(sh):
        out[Path(dst).name] = dst
    if "chinese-wav2vec2-base" in sh:
        out["chinese-wav2vec2-base"] = "wav2vec/chinese-wav2vec2-base"
    return out


def validate_weights_manifest(pack: Path) -> list[str]:
    """权重清单自身的完整性：每个文件要有 sha256（wav2vec 要有不可变 revision）。"""
    mf = pack / "weights-manifest.json"
    if not mf.exists():
        return ["缺少 weights-manifest.json（权重无 SHA-256 锁定，禁止发射）"]
    errs = []
    data = json.loads(mf.read_text(encoding="utf-8"))
    for key, meta in data.items():
        if key.startswith("wav2vec"):
            rev = meta.get("revision", "")
            if not re.fullmatch(r"[0-9a-f]{40}", rev):
                errs.append(f"weights-manifest: {key} 的 revision 不是 40 位不可变 commit（当前 '{rev}'）")
            continue
        sha = meta.get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            errs.append(f"weights-manifest: {key} 缺少合法 sha256（当前 '{sha[:20]}'）")
        if not meta.get("repo") or not meta.get("path"):
            errs.append(f"weights-manifest: {key} 缺 repo/path，无法兜底下载")
    # fetch_weights.sh 必须真的做校验，不能只声明
    sh = (pack / "fetch_weights.sh").read_text(encoding="utf-8")
    if "sha256sum" not in sh:
        errs.append("fetch_weights.sh 没有 sha256sum 校验——清单等于没锁")
    return errs


def iter_nodes(job: dict):
    prompt = job.get("prompt", job)
    for nid, node in prompt.items():
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
            yield nid, node


def validate(pack: Path, strict_720p: bool) -> list[str]:
    errors: list[str] = []
    jobs_dir = pack / "jobs"
    inputs_dir = pack / "inputs"
    if not jobs_dir.is_dir():
        return [f"缺少 {jobs_dir}"]

    errors.extend(validate_weights_manifest(pack))
    weights = load_declared_weights(pack)
    job_files = sorted(jobs_dir.glob("*.json"))
    if not job_files:
        return [f"{jobs_dir} 里没有作业"]

    produced: set[str] = set()          # 各阶段会产出的文件名（filename_prefix 推导）
    stage_of: dict[str, str] = {}
    consumed_media: list[tuple[str, str]] = []

    # 第一遍：收集产出
    for f in job_files:
        stage = f.name.split("_", 1)[0]
        stage_of[f.name] = stage
        job = json.loads(f.read_text(encoding="utf-8"))
        for _nid, node in iter_nodes(job):
            pref = node["inputs"].get("filename_prefix")
            if pref:
                produced.add(f"{pref}_00001.mp4")

    # 第二遍：逐项校验
    for f in job_files:
        job = json.loads(f.read_text(encoding="utf-8"))
        tag = f.name
        stage = stage_of[tag]
        seen_loader = False

        for nid, node in iter_nodes(job):
            ins = node["inputs"]
            ctype = node.get("class_type", "?")

            # 1) 模型名必须在权重清单里
            for field in LOADER_FIELDS:
                val = ins.get(field)
                if isinstance(val, str) and val.endswith(".safetensors"):
                    seen_loader = True
                    if Path(val).name not in weights:
                        errors.append(
                            f"[{tag}] 节点{nid} {ctype}.{field}='{val}' 不在 fetch_weights.sh 清单里"
                        )

            # 2) 分辨率
            if strict_720p and "width" in ins and "height" in ins:
                if (ins["width"], ins["height"]) != (720, 1280):
                    errors.append(
                        f"[{tag}] 节点{nid} {ctype} 分辨率 {ins['width']}x{ins['height']} != 720x1280"
                    )

            # 3) 媒体输入：音频/图片必须在 inputs/；视频要么在 inputs/ 要么由前序阶段产出
            for field in MEDIA_FIELDS:
                val = ins.get(field)
                if not isinstance(val, str) or "/" in val or not val:
                    continue
                if not re.search(r"\.(wav|mp3|png|jpg|jpeg|mp4|webm)$", val, re.I):
                    continue
                consumed_media.append((tag, val))
                on_disk = (inputs_dir / val).exists()
                if val.lower().endswith((".mp4", ".webm")):
                    if not on_disk and val not in produced:
                        errors.append(
                            f"[{tag}] 节点{nid} {ctype}.{field}='{val}' 既不在 inputs/ 也没有任何阶段产出它"
                        )
                elif not on_disk:
                    errors.append(f"[{tag}] 节点{nid} {ctype}.{field}='{val}' 在 inputs/ 里不存在")

            # 4) 帧数下限（InfiniteTalk 分段最小 33）
            nf = ins.get("num_frames")
            if isinstance(nf, int) and not (33 <= nf <= 201):
                errors.append(f"[{tag}] 节点{nid} num_frames={nf} 超出 [33,201]")

        if not seen_loader:
            errors.append(f"[{tag}] 没有任何 .safetensors 加载节点，工作流可能损坏")

        if not any(
            node["inputs"].get("filename_prefix") for _n, node in iter_nodes(job)
        ):
            errors.append(f"[{tag}] 没有 filename_prefix，成片会覆盖默认名")

    # 5) 输出前缀唯一性
    seen_pref = defaultdict(list)
    for f in job_files:
        job = json.loads(f.read_text(encoding="utf-8"))
        for _nid, node in iter_nodes(job):
            p = node["inputs"].get("filename_prefix")
            if p:
                seen_pref[p].append(f.name)
    for pref, owners in seen_pref.items():
        if len(owners) > 1:
            errors.append(f"filename_prefix '{pref}' 被多个作业共用：{owners}（成片互相覆盖）")

    # 6) 未被任何作业使用的输入（提示浪费，不算错误）
    if inputs_dir.is_dir():
        used = {v for _t, v in consumed_media}
        for p in sorted(inputs_dir.iterdir()):
            if p.is_file() and p.name not in used and p.suffix.lower() in {".wav", ".mp3"}:
                print(f"提示：inputs/{p.name} 没有被任何作业引用", file=sys.stderr)

    return errors


def validate_launch_yaml(pack: Path, yaml_path: Path | None) -> list[str]:
    """交叉校验发射 YAML 与作业包：审计确认第 1/5/6/10/11/14/15 项全是这一族——
    YAML 引用包里没有的脚本、或投递包里不存在的 stage（空 glob 静默假成功）。"""
    if yaml_path is None or not yaml_path.exists():
        return [f"发射 YAML 不存在，无法交叉校验: {yaml_path}"]
    text = yaml_path.read_text(encoding="utf-8")
    errs: list[str] = []

    for script in sorted(set(re.findall(r"/job/([\w./-]+\.(?:py|sh))", text))):
        if not (pack / script).exists():
            errs.append(f"YAML 引用 /job/{script}，但作业包里没有这个文件")

    yaml_stages = set(re.findall(r"--stage\s+(\w+)", text))
    pack_stages = {f.name.split("_", 1)[0] for f in (pack / "jobs").glob("*.json")}
    for st in sorted(yaml_stages - pack_stages):
        errs.append(f"YAML 投递 --stage {st}，但 jobs/ 里没有 {st}_*.json（空 glob 会静默假成功）")
    for st in sorted(pack_stages - yaml_stages):
        n = len(list((pack / "jobs").glob(f"{st}_*.json")))
        errs.append(f"jobs/ 有 {n} 个 {st}_*.json，但 YAML 从不投递 --stage {st}（这些作业永远不会渲）")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", type=Path)
    ap.add_argument("--strict-720p", action="store_true")
    ap.add_argument("--launch-yaml", type=Path, default=None,
                    help="交叉校验发射 YAML 的 stage 与脚本引用")
    a = ap.parse_args()

    errors = validate(a.pack, a.strict_720p)
    if a.launch_yaml is not None:
        errors.extend(validate_launch_yaml(a.pack, a.launch_yaml))
    jobs = len(list((a.pack / "jobs").glob("*.json")))
    if errors:
        print(f"✗ {a.pack.name}: {jobs} 个作业，发现 {len(errors)} 处问题：")
        for e in errors:
            print("  -", e)
        return 1
    print(f"✓ {a.pack.name}: {jobs} 个作业全部通过校验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
