#!/usr/bin/env python3
"""按 stage 投递 /job/jobs/<stage>_*.json 到本机 ComfyUI 并等全部完成。"""
import json, sys, time, glob, urllib.request

BASE = "http://127.0.0.1:8188"
def post(path, data=None):
    req = urllib.request.Request(BASE+path, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

stage = sys.argv[sys.argv.index("--stage")+1]
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
