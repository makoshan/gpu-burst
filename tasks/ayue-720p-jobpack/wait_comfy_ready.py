import time, urllib.request, sys
for i in range(60):
    try:
        urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=5); print("comfy ready"); sys.exit(0)
    except Exception: time.sleep(5)
sys.exit("comfy not ready after 300s")
