#!/usr/bin/env bash
# gpu-burst 冷启动 + 传输公共库(source 进 SkyPilot setup 用)。
#
# 兑现 docs/technical.md 已定但 teochew-sft 未落实的两项优化:
#   1. 传输: s5cmd 并行(替 `aws s3 cp` 单线程)——大文件/多文件实测快数倍,
#      直接砍 R2 拉输入/推产物的墙钟(technical.md §对象同步选型)。
#   2. 冷启动: R2 依赖/模型缓存(替每次 pip install + HF snapshot_download)——
#      首次现装并推缓存,后续拉解即用(technical.md gpu-burst-cache 桶用途)。
#      渐进式: 缓存未命中时 fallback 现装,首次不慢于现状,后续快。
#
# 依赖: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY(发射脚本 --env 注入,不落盘)、
#       R2_ENDPOINT。s5cmd 读标准 AWS 环境凭据。
#
# 诚实边界: s5cmd 并行加速是选型依据(未在本项目 live 计时);缓存命中率与
# 实际冷启动收益需首次真云跑后记进 README「单价实测记录」。

: "${R2_ENDPOINT:?R2_ENDPOINT required (R2 S3 兼容端点)}"

S5="s5cmd --endpoint-url ${R2_ENDPOINT}"

# 装 s5cmd(单静态二进制,秒级;比 pip awscli 轻)。幂等。
ensure_s5cmd() {
  command -v s5cmd >/dev/null 2>&1 && { s5cmd version; return; }
  local ver=2.2.2 tag
  case "$(uname -m)" in
    aarch64|arm64) tag="Linux-arm64" ;;
    *)             tag="Linux-64bit" ;;
  esac
  curl -fsSL "https://github.com/peak/s5cmd/releases/download/v${ver}/s5cmd_${ver}_${tag}.tar.gz" \
    | tar xz -C /usr/local/bin s5cmd
  s5cmd version
}

# 并行拉。s5cmd cp 对目录/通配自动多 worker 并发。
#   r2_pull s3://gpu-burst-jobs/<id>/input/wavs22k/'*' /local/wavs22k/
r2_pull() { $S5 cp "$1" "$2"; }

# 并行推。回传产物用。
#   r2_push /local/exp/'*' s3://gpu-burst-jobs/<id>/output/exp/
r2_push() { $S5 cp "$1" "$2"; }

# 冷启动缓存: R2 有缓存 tar 则拉解跳过现装,否则跑 build 再推缓存(渐进)。
#   r2_cache_or_build s3://gpu-burst-cache/matcha-venv.tgz /opt/venv build_matcha_env
# build 函数负责把内容装进 $2 目录;成功后本函数打包推 R2 供下次命中。
r2_cache_or_build() {
  local uri="$1" dir="$2" build_fn="$3"
  mkdir -p "$dir"
  if $S5 ls "$uri" >/dev/null 2>&1; then
    echo "[cache] HIT $uri -> $dir"
    local tmp; tmp=$(mktemp)
    $S5 cp "$uri" "$tmp"
    tar xzf "$tmp" -C "$dir"
    rm -f "$tmp"
  else
    echo "[cache] MISS $uri -> building"
    "$build_fn"
    local tmp; tmp=$(mktemp)
    tar czf "$tmp" -C "$dir" .
    $S5 cp "$tmp" "$uri" || echo "[cache] push failed (non-fatal, next run rebuilds)"
    rm -f "$tmp"
  fi
}

# 模型从 R2 拉 + SHA-256 校验(technical.md §11.1: 模型不烤镜像,按 manifest 拉并校验)。
#   r2_pull_verified s3://gpu-burst-cache/bigvgan/g_05330000 /path/g_05330000 <sha256>
r2_pull_verified() {
  local uri="$1" dst="$2" expect="$3"
  $S5 cp "$uri" "$dst"
  local got; got=$(sha256sum "$dst" | cut -d' ' -f1)
  if [ "$got" != "$expect" ]; then
    echo "[verify] SHA mismatch $dst: got $got want $expect" >&2
    rm -f "$dst"
    return 1
  fi
  echo "[verify] OK $dst"
}
