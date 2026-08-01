#!/usr/bin/env bash
# R2-first、HF 兜底并 tee 回 R2。逐文件幂等。
set -euo pipefail
M=/root/ComfyUI/models
declare -A W=(
  ["diffusion_models/Wan2_1-I2V-14B-720P_fp8_e4m3fn.safetensors"]="Kijai/WanVideo_comfy Wan2_1-I2V-14B-720P_fp8_e4m3fn.safetensors"
  ["diffusion_models/Wan2_1-InfiniTetalk-Single_fp16.safetensors"]="Kijai/WanVideo_comfy InfiniteTalk/Wan2_1-InfiniTetalk-Single_fp16.safetensors"
  ["text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"]="Kijai/WanVideo_comfy umt5-xxl-enc-fp8_e4m3fn.safetensors"
  ["vae/Wan2_1_VAE_bf16.safetensors"]="Kijai/WanVideo_comfy Wan2_1_VAE_bf16.safetensors"
  ["loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"]="Kijai/WanVideo_comfy Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"
)
export HF_HUB_ENABLE_HF_TRANSFER=1
for dst in "${!W[@]}"; do
  read -r repo file <<< "${W[$dst]}"
  mkdir -p "$M/$(dirname "$dst")"
  if s5cmd --endpoint-url "$R2_ENDPOINT" cp "s3://$R2_CACHE/ayue-video/$dst" "$M/$dst" 2>/dev/null; then
    echo "R2-hit $dst"
  else
    hf download "$repo" "$file" --local-dir /tmp/hf
    mv "/tmp/hf/$file" "$M/$dst"
    s5cmd --endpoint-url "$R2_ENDPOINT" cp "$M/$dst" "s3://$R2_CACHE/ayue-video/$dst" && echo "teed $dst" || echo "tee-failed $dst (non-fatal)"
  fi
done
hf download TencentGameMate/chinese-wav2vec2-base --local-dir "$M/wav2vec/chinese-wav2vec2-base"
