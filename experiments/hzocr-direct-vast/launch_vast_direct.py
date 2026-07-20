"""Launch a Vast instance directly (no SkyPilot): docker image + R2 data plane.

Picks a verified datacenter RTX4090 offer with fast downlink, injects R2 creds
as env vars, and boots a base64-packed onstart script that pulls pages from R2,
runs the OCR batch, and pushes results back. No SSH involved at any point.
"""
import base64
import configparser
import json
import subprocess
import sys
from pathlib import Path

EP = "https://1df50a43697ddc762baf3b76d1dc9ef1.r2.cloudflarestorage.com"
BUCKET = "s3://gpu-burst-jobs/hzocr-20260721"
IMAGE = "paddlepaddle/paddle:3.2.2-gpu-cuda12.6-cudnn9.5"

creds = configparser.ConfigParser()
creds.read(Path.home() / ".aws" / "credentials")
ak = creds["gpu-burst-r2"]["aws_access_key_id"]
sk = creds["gpu-burst-r2"]["aws_secret_access_key"]

script = f"""#!/bin/bash
exec > /root/onstart.log 2>&1
set -x
(sleep 10800 && shutdown -h now) &
cd /root
apt-get update -qq && apt-get install -y -qq libgl1 libglib2.0-0
pip install -q "paddleocr==3.7.0" "paddlex[ocr]==3.7.2" awscli
EP={EP}
B={BUCKET}
aws --endpoint-url $EP s3 sync $B/in/ /root/hzocr/ --quiet
cd /root/hzocr
mkdir -p out_dict out_yd
(while true; do
  aws --endpoint-url $EP s3 sync out_dict $B/out_dict --quiet
  aws --endpoint-url $EP s3 sync out_yd $B/out_yd --quiet
  aws --endpoint-url $EP s3 cp /root/onstart.log $B/onstart.log --quiet
  sleep 90
done) &
FAIL=0
python batch_cloud.py pages_dict out_dict --reverse || FAIL=1
python batch_cloud.py pages_yd out_yd || FAIL=1
aws --endpoint-url $EP s3 sync out_dict $B/out_dict --quiet
aws --endpoint-url $EP s3 sync out_yd $B/out_yd --quiet
aws --endpoint-url $EP s3 cp /root/onstart.log $B/onstart.log --quiet
if [ "$FAIL" = "0" ]; then echo done > /root/ALL_DONE; aws --endpoint-url $EP s3 cp /root/ALL_DONE $B/ALL_DONE; else echo failed > /root/BATCH_FAILED; aws --endpoint-url $EP s3 cp /root/BATCH_FAILED $B/BATCH_FAILED; fi
shutdown -h now
"""
b64 = base64.b64encode(script.encode()).decode()
onstart = f"echo {b64} | base64 -d > /root/go.sh && bash /root/go.sh"

# pick offer: verified datacenter, fast downlink, cheap
q = "gpu_name=RTX_4090 num_gpus=1 verified=true datacenter=true inet_down>=500 dph<=0.48 rentable=true"
out = subprocess.run(["vastai", "search", "offers", q, "-o", "dph", "--raw"],
                     capture_output=True, text=True, check=True)
offers = json.loads(out.stdout)
if not offers:
    sys.exit("no offers matched")
best = offers[0]
print("chosen offer:", best["id"], best.get("geolocation"), round(best["dph_total"], 3),
      "inet_down:", best.get("inet_down"))

create = subprocess.run(
    ["vastai", "create", "instance", str(best["id"]),
     "--image", IMAGE, "--disk", "40",
     "--env", f"-e AWS_ACCESS_KEY_ID={ak} -e AWS_SECRET_ACCESS_KEY={sk} -e AWS_DEFAULT_REGION=auto",
     "--onstart-cmd", onstart, "--raw"],
    capture_output=True, text=True)
print("create stdout:", create.stdout[:400])
if create.returncode != 0:
    print("create stderr:", create.stderr[:400])
    sys.exit(1)
