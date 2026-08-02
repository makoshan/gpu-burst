#!/usr/bin/env bash
# 云平台（RunPod/Vast）都靠 SSH 进容器装编排运行时。光装 sshd 不够——
# 必须真启动它，并把平台注入的公钥写进 authorized_keys。
# 2026-08-02 第九次发射就死在这：sshd 在镜像里但 CMD 是 ComfyUI，
# sshd 从未运行 → SkyPilot SSH 600s 超时 → 集群永远 INIT。
set -euo pipefail
mkdir -p /root/.ssh && chmod 700 /root/.ssh
# RunPod 用 PUBLIC_KEY，Vast 用 SSH_PUBLIC_KEY，两个都收
for var in PUBLIC_KEY SSH_PUBLIC_KEY; do
  val="${!var:-}"
  [ -n "$val" ] && { echo "$val" >> /root/.ssh/authorized_keys; echo "injected $var"; }
done
[ -f /root/.ssh/authorized_keys ] && chmod 600 /root/.ssh/authorized_keys
ssh-keygen -A                                    # 生成主机密钥
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
echo "starting sshd"
exec /usr/sbin/sshd -D -e
