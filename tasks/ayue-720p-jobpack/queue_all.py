#!/usr/bin/env python3
"""按 stage 投递 /job/jobs/<stage>_*.json 到本机 ComfyUI 并等全部完成。"""
import json, sys, time, glob, urllib.request

BASE = "http://127.0.0.1:8188"
def post(path, data=None):
    req = urllib.request.Request(BASE+path, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

stage = sys.argv[sys.argv.index("--stage")+1]
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
while True:
    hist = {i: json.load(urllib.request.urlopen(f"{BASE}/history/{i}", timeout=30)) for i in ids}
    done = [i for i in ids if hist[i]]
    print(f"{time.strftime('%H:%M:%S')} {len(done)}/{len(ids)} done", flush=True)
    if len(done) == len(ids):
        for i in ids:
            st = hist[i][i]["status"]
            assert st.get("status_str") != "error", f"{i} failed: {st}"
        print("stage", stage, "complete"); break
    time.sleep(60)
