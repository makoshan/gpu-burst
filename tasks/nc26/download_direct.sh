#!/usr/bin/env bash
# 不经 eegdash 的元数据服务,直接按 git-annex 内容键从 S3 取原始 bdf。
# NEMAR 的桶允许匿名 GET s3://nemar/<id>/objects/<KEY>;KEY 就是 git 仓库里每个 bdf 软链指向的文件名
# (SHA256E-s<字节数>--<sha256>.bdf)。2026-10-04 data.eegdash.org 整站超时,这条路仍然可用。
# 用法: download_direct.sh <nm000281-git 目录> <目标目录>   可重跑:已存在且大小相同的跳过
set -euo pipefail
GIT=$1; DST=$2
command -v s5cmd >/dev/null || { curl -fsSL https://github.com/peak/s5cmd/releases/download/v2.2.2/s5cmd_2.2.2_Linux-64bit.tar.gz | tar xz -C /usr/local/bin s5cmd; }
( cd "$GIT" && find . -name '*.bdf' -type l | while read -r l; do
    echo "cp -n -s s3://nemar/nm000281/objects/$(basename "$(readlink "$l")") $DST/${l#./}"; done ) > "$DST.cmds.txt"
n=$(wc -l < "$DST.cmds.txt"); [ "$n" = 25253 ] || { echo "expected 25253 bdf links, found $n"; exit 3; }
s5cmd --no-sign-request --numworkers 96 --log error run "$DST.cmds.txt"
echo "DONE direct $(find "$DST" -name '*.bdf' | wc -l) files"
