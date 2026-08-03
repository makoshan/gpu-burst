# 境内 → Vast SSH 跳板方案（2026-08-03 定案）

一句话：**境内到 Vast GPU 机的 SSH 只有一条活路——经美国 Vultr 跳板 + SSH 连接复用。**
直连被墙，机场代理不转发 SSH，缺一个补丁都跑不通。本文是完整诊断链与配置，
供下次撞墙时直接照抄。

## 症状（当天烧掉 5 台机器才定位）

- SkyPilot 发射 Vast 集群，`Waiting for SSH ...` 600 秒超时，`Failed to set up
  SkyPilot runtime`，集群永远 INIT，机器空烧
- 手动 `ssh -p <port> root@sshN.vast.ai` 表现为 `Connection closed by <ip>`
  （TCP 通、立刻断）
- 极易误诊为「宿主机 sshd 没起来 / 迟交付机」——我们连拆了 5 台“坏机器”，
  其实**机器全是好的**

## 诊断链（对照实验是关键）

| 实验 | 结果 | 排除/证明 |
|---|---|---|
| Mac 直连 vast SSH 端点 | Connection closed | — |
| **Vultr（美国）连同一端点** | `Permission denied (publickey)`（完整握手到认证层） | **端点健康，问题在路径** |
| Surge 走代理节点转发 | 仍 closed | — |
| **`nc github.com 22` 经代理** | 拿不到 banner | **机场节点根本不转发 SSH 协议** |
| Mac 经 Vultr 跳板 `-W` | `JUMP-SSH-OK` + 容器 hostname | **跳板是唯一活路** |

另两个此过程中撞到的 Surge 机制坑：
- `always-real-ip` 与域名规则互斥：SSH 拿到真实 IP 后直连 IP，TUN 看不到域名，
  `DOMAIN-SUFFIX` 规则匹配不上，流量漏到直连。**要按域名走策略就必须留在 fake-ip。**
- 改 Surge 配置文件后必须 reload 才生效：`/Applications/Surge.app/Contents/Applications/surge-cli reload`

## 配置（三件套，缺一不可）

### 1. SkyPilot 本地补丁（uv tool 重装后必重跑）

```bash
./patches/apply_skypilot_vast_ssh_patches.sh
```

补两处：schemas.py 放行 `vast.ssh_proxy_command`（原 additionalProperties:False
拒收）；`vast-ray.yml.j2` 模板 auth 段渲染该变量（schema 过了模板也会扔掉，
两处都补才会进集群 auth——用 `~/.sky/generated/<cluster>.yml.debug` 可验证）。

### 2. `~/.sky/config.yaml`

```yaml
vast:
  ssh_proxy_command: /usr/bin/ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 -o ControlMaster=auto -o ControlPath=/tmp/skyjump-%r@%h-%p -o ControlPersist=15m -p 2299 -W %h:%p mako@100.122.117.40
```

**ControlMaster 复用不是锦上添花，是必需**：SkyPilot 投递作业时并发开大量 SSH，
Vultr sshd 的 MaxStartups（默认 10:30:100）会把预认证连接随机丢弃，表现为
`Connection timed out during banner exchange` → `FAILED_DRIVER`（实测连炸两次）。
复用后所有隧道共享一条已认证主连接，走 MaxSessions（本机已设 50）的通道配额。

改完必须 `sky api stop`（下次命令自动带新配置重启）。

### 3. 生效条件：**只对新建集群生效**

`ssh_proxy_command` 在集群创建时烙进 auth 配置；对已有集群 relaunch/接管会沿用
旧值（backend_utils 明确注释了这个行为）。跳板配置变更后，**必须换新集群名重发**。

## 关联坑（同一天的 Vast 发射链路）

- Vast 默认镜像 conda 是 **python 3.10**，黄金 freeze 需要 ≥3.12（av==18 直接拒装）
  → setup 先 `conda create -y -n ayue python=3.12` 再重放 freeze
- 新建 env 的 bin 必须 `export PATH`：fetch_weights.sh 里 `s5cmd`/`hf` 是裸命令，
  s5cmd 找不到时 R2 分支被 `2>/dev/null` 吞掉**静默漏到 HF 下载**，hf 再 127
- 宿主机驱动参差：黄金栈 cu130 需驱动 ≥580，setup 第一行做门禁（exit 47），
  市场 2/3 机器达标，撞到旧机换一台即可
