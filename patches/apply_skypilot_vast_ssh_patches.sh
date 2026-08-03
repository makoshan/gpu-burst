#!/usr/bin/env bash
# SkyPilot 本地补丁重放脚本（uv tool 重装 skypilot 后必须重跑）
#
# 背景（2026-08-03 血泪，详见 docs/vast-ssh-jump.md）：
# 境内到 Vast 的 SSH 直连被墙 RST，机场节点不转发 SSH（github:22 实测同死），
# 唯一通路是 Vultr 跳板。但 SkyPilot 对 vast 云不支持 ssh_proxy_command：
#   1) schemas.py 的 vast 段 additionalProperties:False 不放行该字段
#   2) vast-ray.yml.j2 模板的 auth 段不渲染该变量（schema 过了也白过）
# 两处都要补。幂等：重复执行安全。
set -euo pipefail
SP=$(ls -d ~/.local/share/uv/tools/skypilot/lib/python3.*/site-packages/sky | head -1)
[ -n "$SP" ] || { echo "找不到 skypilot tool 安装"; exit 1; }

python3 - "$SP" <<'PY'
import sys
from pathlib import Path
sp = Path(sys.argv[1])

# 补丁1: schema 放行 vast.ssh_proxy_command
f = sp/"utils/schemas.py"; s = f.read_text()
if "'ssh_proxy_command'" not in s.split("'vast': {")[1][:800]:
    s = s.replace("""        'vast': {
            'type': 'object',
            'required': [],
            'additionalProperties': False,
            'properties': {""",
"""        'vast': {
            'type': 'object',
            'required': [],
            'additionalProperties': False,
            'properties': {
                'ssh_proxy_command': {
                    'oneOf': [{'type': 'string'}, {'type': 'null'}],
                },""", 1)
    f.write_text(s); print("补丁1 schemas.py: 已应用")
else:
    print("补丁1 schemas.py: 已存在，跳过")

# 补丁2: vast 模板渲染 ssh_proxy_command（照抄 aws 模板写法）
f = sp/"templates/vast-ray.yml.j2"; s = f.read_text()
if "ssh_proxy_command" not in s:
    s = s.replace("""auth:
  ssh_user: root
  ssh_private_key: {{ssh_private_key}}""",
"""auth:
  ssh_user: root
  ssh_private_key: {{ssh_private_key}}
{% if ssh_proxy_command is not none %}
  ssh_proxy_command: {{ssh_proxy_command}}
{% endif %}""", 1)
    f.write_text(s); print("补丁2 vast-ray.yml.j2: 已应用")
else:
    print("补丁2 vast-ray.yml.j2: 已存在，跳过")
PY
echo "完成。另需 ~/.sky/config.yaml 配置跳板（见 docs/vast-ssh-jump.md），改完 sky api stop 重载。"
