#!/usr/bin/env bash
# Default: free plan only. Paid mode delegates all lifecycle and cleanup checks
# to gpu-burst; this wrapper never invokes SkyPilot directly.
set -euo pipefail
cd "$(dirname "$0")/.."

JOBPACK="${AYUE_720P_JOBPACK:-}"
IMAGE="${AYUE_RUNPOD_IMAGE:-}"
PAID=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --jobpack)
      JOBPACK="${2:-}"
      shift 2
      ;;
    --image)
      IMAGE="${2:-}"
      shift 2
      ;;
    --confirm-paid)
      PAID=1
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$JOBPACK" || -z "$IMAGE" ]]; then
  echo "usage: $0 --jobpack PATH --image REPOSITORY@sha256:DIGEST [--confirm-paid]" >&2
  exit 2
fi

if [[ "$PAID" -eq 1 ]]; then
  exec env GPU_BURST_PROVIDER=runpod uv run gpu-burst ayue-720p-launch \
    --jobpack "$JOBPACK" --image "$IMAGE" --confirm-paid
fi

PLAN_FILE="$(mktemp "${TMPDIR:-/tmp}/ayue-runpod-plan.XXXXXX.yaml")"
trap 'rm -f "$PLAN_FILE"' EXIT
env GPU_BURST_PROVIDER=runpod uv run gpu-burst ayue-720p-plan \
  --jobpack "$JOBPACK" --image "$IMAGE" --output "$PLAN_FILE" --allow-pending
