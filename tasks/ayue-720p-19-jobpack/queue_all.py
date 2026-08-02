#!/usr/bin/env python3
"""按 stage 投递 /job/jobs/<stage>_*.json 到本机 ComfyUI 并等全部完成。"""
import json, sys, time, glob, urllib.request

BASE = "http://127.0.0.1:8188"
def post(path, data=None):
    req = urllib.request.Request(BASE+path, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

stage = sys.argv[sys.argv.index("--stage")+1]
WALL_CLOCK_LIMIT_S = 3 * 3600   # 单阶段墙钟上限：ComfyUI 卡死时 autostop 永不触发，
                                # 没有这个上限就是无上限烧钱（审计确认项）
# 上一阶段的成片落在 output/，但下一阶段的 VHS_LoadVideo 只从 input/ 读——
# 阶段之间必须显式搬运，否则 V2V 报 "Invalid video file"（2026-08-01 首跑坑）。
import shutil, os
if stage != "sources":
    for f in glob.glob("/root/ComfyUI/output/*.mp4"):
        dst = "/root/ComfyUI/input/" + os.path.basename(f)
        if not os.path.exists(dst):
            shutil.copy(f, dst); print("staged->input", os.path.basename(f), flush=True)
ids = []
for f in sorted(glob.glob(f"/job/jobs/{stage}_*.json")):
    r = post("/prompt", json.load(open(f)))
    assert "prompt_id" in r, f"{f}: {r}"
    ids.append(r["prompt_id"]); print("queued", f, r["prompt_id"], flush=True)
# 空 glob 会让下面的 while 首轮就 len(done)==len(ids)==0 成立，静默报「阶段完成」
# 并退出 0——审计确认这正是 --stage finals 导致 15/19 支不渲却全绿的机制。
assert ids, f"stage {stage}: /job/jobs/{stage}_*.json 匹配到 0 个作业文件"
started = time.time()
while True:
    if time.time() - started > WALL_CLOCK_LIMIT_S:
        raise SystemExit(f"stage {stage}: 超过墙钟上限 {WALL_CLOCK_LIMIT_S}s，中止以免无上限计费")
    hist = {i: json.load(urllib.request.urlopen(f"{BASE}/history/{i}", timeout=30)) for i in ids}
    done = [i for i in ids if hist[i]]
    print(f"{time.strftime('%H:%M:%S')} {len(done)}/{len(ids)} done", flush=True)
    if len(done) == len(ids):
        for i in ids:
            st = hist[i][i]["status"]
            assert st.get("status_str") != "error", f"{i} failed: {st}"
        print("stage", stage, "complete"); break
    time.sleep(60)
