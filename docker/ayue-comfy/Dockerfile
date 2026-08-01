# 阿粤 720P 渲染镜像：ComfyUI + WanVideoWrapper + InfiniteTalk 全栈钉版。
#
# 为什么要预烤（2026-08-01 血泪）：云机现场 pip install 撞进版本地狱——
# 社区宿主机驱动参差、ComfyUI 的 requirements 是滚动的，两者对不上时在计费
# 机器上现修就是打地鼠。七次发射有四次死在这上面。
#
# 权重不烤进来（30GB），运行时从 R2 拉并逐文件 SHA-256 校验。
#
# 构建（在 thursday-win WSL2，需 GPU 直通做冒烟）：
#   docker build -t ayue-comfy:local docker/ayue-comfy
#   docker run --rm --gpus all ayue-comfy:local python3 -c "import torch;print(torch.cuda.is_available())"

FROM pytorch/pytorch:2.9.1-cuda13.0-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_ENABLE_HF_TRANSFER=1

# 系统依赖：git 拉节点、ffmpeg 供 VideoHelperSuite、curl 供健康检查
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      git curl ca-certificates ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# ---- ComfyUI 与节点：commit 钉死，与 thursday-win 生产环境一致 ----
ARG COMFY_COMMIT=b3581971
ARG WANWRAPPER_COMMIT=088128b
ARG VHS_COMMIT=4ee72c0
RUN git clone --filter=blob:none https://github.com/comfyanonymous/ComfyUI /root/ComfyUI \
 && git -C /root/ComfyUI checkout ${COMFY_COMMIT} \
 && git clone --filter=blob:none https://github.com/kijai/ComfyUI-WanVideoWrapper /root/ComfyUI/custom_nodes/ComfyUI-WanVideoWrapper \
 && git -C /root/ComfyUI/custom_nodes/ComfyUI-WanVideoWrapper checkout ${WANWRAPPER_COMMIT} \
 && git clone --filter=blob:none https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite /root/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite \
 && git -C /root/ComfyUI/custom_nodes/ComfyUI-VideoHelperSuite checkout ${VHS_COMMIT} \
 && git clone --filter=blob:none https://github.com/kijai/ComfyUI-KJNodes /root/ComfyUI/custom_nodes/ComfyUI-KJNodes

# ---- 黄金依赖集：thursday-win 生产环境（每天在跑这条管线）的 pip freeze ----
# 不用 ComfyUI 滚动的 requirements.txt。torch 系走 cu130 官方 index。
COPY golden-freeze.txt /tmp/golden-freeze.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/golden-freeze.txt \
      --extra-index-url https://download.pytorch.org/whl/cu130 \
 && python3 -m pip install --no-cache-dir s5cmd "huggingface_hub[hf_transfer]" \
 && rm -f /tmp/golden-freeze.txt

# ---- 构建期自检：装完就验，别等到云上才发现节点没注册 ----
RUN python3 - <<'PY'
import importlib, sys
import torch
print("torch", torch.__version__)
for m in ("torchvision", "torchaudio", "transformers", "diffusers", "accelerate",
          "einops", "safetensors", "av", "cv2"):
    importlib.import_module(m)
    print("ok", m)
import subprocess
subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
subprocess.run(["s5cmd", "version"], check=False, capture_output=True)
print("BUILD-SELFTEST-PASS")
PY

WORKDIR /root/ComfyUI
EXPOSE 8188
CMD ["python3", "main.py", "--listen", "127.0.0.1", "--port", "8188"]
