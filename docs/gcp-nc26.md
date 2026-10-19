# nc26 数据准备:GCP 和 Vast 的实测经验(2026-10-02)

任务:emg2pose(NEMAR nm000281,25253 个 bdf,310 GB)→ fp16 memmap(224 GB)→ 精简训练数据(82 GB)→ 对象存储。
同一天两条路都跑过:Vast + SkyPilot + R2(`sky/launch-nc26-dataprep.sh`),GCP + GCS(另一会话手工跑通,这里固化成 `gcp/launch-nc26-dataprep.sh`)。
两条路共用 `tasks/nc26/dataprep.sh`,用 `DEST=r2|gcs` 切目的地。

状态:Vast 路径**已实测通过**到校验(抽查 PASS、分块校验和与家里一致),R2 上 `memmap-v1` **缺 `joints.f16`**。
GCP 路径:手工版**已实测通过**到建库;`gcp/launch-nc26-dataprep.sh` 本身**已实现未验收**(只跑过 dry-run)。

## 实测数字

| | GCP us-central1 | Vast 马里兰 4090 | Vast 保加利亚 V100 |
|---|---|---|---|
| 下载 310 GB | 29 分钟(约 178 MB/s,单进程一次成功) | 30 分钟(约 236 MB/s) | 单进程 27 MB/s;拆 13 进程 90 MB/s |
| 建 memmap | 12 核:第一遍约 8 分钟,第二遍约 33 条/秒 | 宿主机内存吃紧:修复前 80 分钟没出第一遍;修复后 30 + 47 分钟 | 没跑到 |
| 传出 | 同区 GCS 免流量费;往 R2 传约 $0.08–0.12/GB(没核价) | R2 约 400 MB/s | 没跑到 |
| 每小时 | 竞价 A100 $2.2(准备数据用不着,CPU 机即可) | 标价 $0.40,实际 $0.97(含 650 GB 盘 $0.30 和流量) | $0.94 |

us-east5 的 e2-standard-4 测过 3 个被试:52 MB/s。家里到 R2 上传只有 1 MB/s,别指望从家里补传大文件。

## 踩过的坑

**GCP**
- VM 默认服务账号对存储只读。建机时就给 `--scopes storage-rw`,否则传 GCS 要停机改权限,竞价机停了不一定开得回来。
- Debian 12 自带 Python 3.11,`neuralfetch==0.3.1` 要 3.12,用 uv 建环境。
- `s3://nemar/...` 不开放 List 和 Get,只能走 eegdash 的解析下载。
- 深度学习镜像里 torch 和 torchaudio 的 CUDA 版本要配对装(`torch==2.11.0` + `torchaudio==2.11.0+cu128`)。
- GPU 配额:`makoshan-be381` 在 us-east5 / us-central1 有 A100 竞价配额;AWS 的 G/P 配额是 0;Vultr 美国开不了 GPU。
- 准备数据不需要 GPU。launcher 默认 `n2-standard-16` 竞价机,A100 留给训练,训练机从同区 GCS 拉数据。

**Vast + SkyPilot**
- SkyPilot 任务环境里 `OMP_NUM_THREADS=1`,`nproc` 跟着报 1。并行数改按 cgroup 配额和 CPU 亲和算。
- 空闲自毁只看 SkyPilot 任务队列。绕过队列用 ssh 直接起的进程不算数,到点照停(停在推送中途)。
- 停机 ≠ 销毁:停机后盘继续计费,显卡可能被别人租走,开不回来。
- 宿主机内存吃紧时,新分配的内存每次缺页都卡在内核里。`MALLOC_*` 让 glibc 留住堆后快 3 倍(单进程 100 倍)。
- 标价只是显卡价。盘和流量另算,下 324 GB 的流量费就超过 $1。发射前用 `vastai show instance` 的 `dph_total` 和 `inet_*_cost` 估。
- SkyPilot 按自己的目录挑机器,挑不到指定报价;余额不足时报的是 `string indices must be integers`。
- R2 令牌会过期。launcher 发射前先试写。
- 同一个集群名被两个会话同时管会互相删机器。一个资源只归一个会话。

## 数据放哪

- **精简数据(82 GB)只含 train 划分**(外加官方 val / test 窗口)。新配方成员用 train+test 训练,要读**全量 memmap**。所以 GCS 上两份都传:`compact-v1/` 和 `memmap-v1/`,合计约 306 GB,每月约 $6(没核价)。
- GCS 给 GCP 同区的训练机用(免流量费);R2 给其它家用(流出免费)。从 GCP 往 R2 补齐要付流出费。

## 用法

```bash
gcp/launch-nc26-dataprep.sh                                   # dry-run
GPU_BURST_LIVE=1 gcp/launch-nc26-dataprep.sh --confirm-paid   # 开机(付费)
gcp/launch-nc26-dataprep.sh status
gcp/launch-nc26-dataprep.sh down                              # 删机并核对没有残留
```

跑完(校验通过并传完)机器自删;失败留着查,`--max-run-duration`(默认 6 小时)到点由 GCP 删除。
