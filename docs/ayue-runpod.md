# Ayue 720P on RunPod

Status on 2026-08-01: control-plane migration implemented; zero Pods launched and zero paid renders. The exact 19-deliverable package is structurally valid but remains blocked from paid launch.

## Safety boundary

- The legacy Vast launcher and its cancelled 30-job package are disabled.
- The RunPod route accepts only `ayue-720p-19-jobpack`: 19 exact web deliverables, 29 internal executions, 720x1280 at 25 fps, and no `payment/listening` clip.
- A mutable image tag is rejected. The image must be `repository@sha256:<digest>`.
- Paid approval must bind the package fingerprint, `provider=runpod`, immutable image reference, and generated launch-contract SHA-256.
- Every model file must have a SHA-256 and wav2vec must have an immutable revision.
- `setup` performs no `pip install`, `git clone`, or `apt-get`. ComfyUI, custom nodes, torch/triton, ffmpeg, s5cmd, and `hf` must already exist in the image.
- The provider lifecycle is bootstrap first, rate check second, workload third. A missing or above-budget observed Pod rate prevents `sky exec` from starting. Teardown is followed by a direct RunPod API check and forced DELETE escalation.

## Credential setup

The API key must not be placed on argv or committed. Load it from MyKey and materialize the private config expected by SkyPilot:

```bash
eval "$(mykey secret env --project gpu-burst --export)"
uv run gpu-burst configure-runpod --from-env
unset RUNPOD_API_KEY
```

The generated `~/.runpod/config.toml` is mode `0600`. `gpu-burst doctor` calls `sky check runpod` and refuses paid execution when the matching SkyPilot RunPod extra is unavailable.

Live verification now reports `RunPod: enabled [compute]`. A separate session injected the RunPod SDK into the existing SkyPilot tool; a reproducible reinstall should still remain an explicit operator decision. The intended pinned command is:

```bash
uv tool install 'skypilot[vast,runpod]==0.12.3.post1' --reinstall
```

## Free preflight

Use the real image digest after the image has been built, GPU-smoke-tested, and pushed:

```bash
./sky/launch-ayue-720p-runpod.sh \
  --jobpack /absolute/path/to/tasks/ayue-720p-19-jobpack \
  --image docker.io/OWNER/ayue-comfy@sha256:DIGEST
```

This only writes temporary bootstrap/workload YAML and prints the unresolved gates. It never calls SkyPilot.

Current expected blockers are:

1. approval remains pending;
2. approval is not yet bound to RunPod, the image digest, or launch-contract hash;
3. five model files lack SHA-256 values;
4. wav2vec lacks an immutable revision.

The pre-baked image and its real digest do not exist yet. A placeholder digest is acceptable only for free structure testing and must never be approved.

## Paid launch

Only after all blockers are resolved and the exact contract is approved:

```bash
GPU_BURST_LIVE=1 ./sky/launch-ayue-720p-runpod.sh \
  --jobpack /absolute/path/to/tasks/ayue-720p-19-jobpack \
  --image docker.io/OWNER/ayue-comfy@sha256:DIGEST \
  --confirm-paid
```

Do not run `sky launch` directly. The CLI ledger records the package and launch fingerprints, observed Pod metadata and hourly rate, teardown verification, and estimated wall-clock cost. The estimate is not represented as a provider invoice.

## Remaining image work

Build in the thursday-win WSL2 GPU environment, not on a paid Pod:

1. pin ComfyUI and all custom-node commits;
2. install the GPU-proven torch/triton/dependency set in the image;
3. include ffmpeg/ffprobe, s5cmd, and Hugging Face CLI;
4. run a real small V2V render with `nvidia-docker` on the 4090;
5. push once and record the registry digest;
6. regenerate the package manifest and approval contract around that digest.

The current golden freeze is CUDA 13 (`torch 2.13.0+cu130`, `triton 3.7.1`), so the generated setup also fails fast below NVIDIA driver major 580. If the image is deliberately rebuilt on a GPU-proven cu128 stack, update that gate and regenerate the launch-contract hash rather than editing generated YAML.

## Failed live attempt observed during migration

At 14:56 CST on 2026-08-01, another session launched `ayue-720p-94028172-head` on a secure RTX 4090 in CZ at an observed `$0.69/h`. It used the mutable `pytorch/pytorch:2.13.0-cuda13.0-cudnn9-runtime` tag, the legacy 30-job package, and cloud-side `apt/git/pip` setup. SkyPilot reported `FAILED_SETUP`; no render started. The Pod was explicitly torn down and the RunPod REST API then returned `pod_count: 0`.

This attempt is evidence for keeping the immutable-image and exact-19-package gates. The observed rate is not a final provider invoice.
