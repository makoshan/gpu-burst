#!/usr/bin/env bash
# R2-first、HF 兜底、逐文件 SHA-256 校验。
#
# 2026-08-01 教训：只声明清单不校验等于没锁——R2 缓存可能是上一轮的错误版本，
# HF 下载可能截断。这里每个文件落盘后都比对 weights-manifest.json 的 sha256，
# 不符就删掉重下；两次都不符则整个 setup 失败（宁可不发射，也不要渲一批废片）。
set -euo pipefail
M=/root/ComfyUI/models
MANIFEST=/job/weights-manifest.json
PY=${PY:-/usr/bin/python3}
export HF_HUB_ENABLE_HF_TRANSFER=1

field() { $PY -c "import json,sys; print(json.load(open('$MANIFEST'))[sys.argv[1]].get(sys.argv[2],''))" "$1" "$2"; }

for dst in $($PY -c "import json; print(' '.join(k for k in json.load(open('$MANIFEST')) if not k.startswith('wav2vec')))"); do
  want=$(field "$dst" sha256); repo=$(field "$dst" repo); path=$(field "$dst" path)
  mkdir -p "$M/$(dirname "$dst")"
  target="$M/$dst"

  for attempt in 1 2; do
    if [ ! -f "$target" ]; then
      if s5cmd --endpoint-url "$R2_ENDPOINT" cp "s3://$R2_CACHE/ayue-video/$dst" "$target" 2>/dev/null; then
        echo "R2-hit $dst"
      else
        echo "HF-download $dst"
        hf download "$repo" "$path" --local-dir /tmp/hf
        mv "/tmp/hf/$path" "$target"
        s5cmd --endpoint-url "$R2_ENDPOINT" cp "$target" "s3://$R2_CACHE/ayue-video/$dst" \
          && echo "teed $dst" || echo "tee-failed $dst (non-fatal)"
      fi
    fi
    got=$(sha256sum "$target" | cut -d' ' -f1)
    if [ "$got" = "$want" ]; then echo "sha-ok $dst"; break; fi
    echo "SHA-MISMATCH $dst want=${want:0:16} got=${got:0:16} (attempt $attempt)"
    rm -f "$target"
    [ "$attempt" = "2" ] && { echo "FATAL: $dst 两次校验都不符"; exit 48; }
  done
done

# wav2vec 是整目录，用不可变 commit 固定
REV=$(field "wav2vec/chinese-wav2vec2-base" revision)
hf download TencentGameMate/chinese-wav2vec2-base --revision "$REV" \
  --local-dir "$M/wav2vec/chinese-wav2vec2-base"
echo "wav2vec pinned @ $REV"
echo "ALL-WEIGHTS-VERIFIED"
