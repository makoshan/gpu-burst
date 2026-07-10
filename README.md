# gpu-burst

个人 AI 算力基础设施：批处理、训练、大规模音频处理，按需租云 GPU，跑完销毁，本地 5070 Ti 兜底。

## 定位

方言保育项目的算力底座——当前阶段只定位为**待验证的 song-cards 批处理器**；故障销毁、账单、数据隔离实测通过后，再晋升为统一底座（OCR、配音、采访入库、训练）。

服务的上游项目：

- `学粤语`（song-cards 歌词卡生图）
- `podcast-dub`（播客配音）
- 潮州词典 OCR / 潮汕话 TTS·ASR 模型

## 文档

当前仓库处于**设计完成、尚未实现**阶段。README 用于快速理解方向，详细契约以以下文档为准：

- [产品文档](docs/product.md)：用户、范围、MVP 验收门槛、指标和路线图
- [技术文档](docs/technical.md)：架构、任务协议、状态机、数据隔离、成本和测试策略
- [文档实施计划](docs/superpowers/plans/2026-07-10-product-technical-docs.md)：本轮文档工作的范围和验证清单

## 解决什么问题

| 现状 | 痛点 |
|---|---|
| OCR、生图、配音都跑本地 thursday-win | 显存不够 / 排队 / 占机器 |
| 手动租 Vast.ai | 开机、装环境、拷文件、忘关机都是手工活 |
| 未来要微调 TTS/ASR | 本地 5070 Ti 训不动 A100 级任务 |

## 产品形态

CLI 为底，Skill 为壳。底层是不依赖 Claude 的普通命令（可进 cron / CI / 手动调试）：

```
gpu-burst run song-cards tasks/song-cards.json
```

第一阶段目标子命令：`doctor` / `quote`（实时报价 + 预算上限）/ `run` / `status` / `logs` / `cancel`。这些接口均为 `planned`，尚无可运行实现。

背后自动：**比价租机 → 从 R2 拉权重/输入 → 跑任务 → 回传结果 → 销毁机器 → 记账**

Claude Skill 只做一层薄壳：自然语言 → CLI 参数。

## 候选管线

| 管线 | 引擎 | GPU 需求 | 当前成熟度 | 成本假设 |
|---|---|---|---|---|
| 歌词卡生图 | ComfyUI (FLUX/Qwen) | 4090 | `planned`，唯一 MVP | $1–3 / 批 |
| 词典 OCR | PaddleOCR-VL / MinerU | 4090 | `reference` | $2–8 一次性 |
| 播客配音 | podcast-dub | 4090 | `reference` | ~$0.5 / 集 |
| 采访音频入库 | whisper + 说话人分离 → 转写/切片/标注 | 4090 | `planned`，非 MVP | ~$0.3–0.5 / 小时音频 |
| 方言模型训练 | Qwen3-TTS 潮汕微调 / FireRedASR LoRA | A100/H100 ×几十小时 | `planned`，非 MVP | $50–300 / 轮 |

## 技术选型（2026-07 调研定案）

- **调度**：[SkyPilot](https://github.com/skypilot-org/skypilot) + Vast.ai 后端
  - 最便宜（Vast 市场比价），跑完即毁，不锁平台
  - Vast API key 放 `~/.config/vastai/vast_api_key`
  - 版本固定：`uv` 建 Python 3.13 环境，装 `skypilot[vast]==0.12.3.post1`（本机默认 3.14 不支持；不用 0.13.0rc）
  - 已知后端限制（Vast [官方文档](https://vast.ai/article/vast-ai-gpus-can-now-be-rentend-through-skypilot)）：不支持对象存储挂载（容器实例无 FUSE 特权）、不支持多机集群、端口须启动时配好
  - spot 抢占 + 断点续训砍训练成本：仅当训练脚本支持 resume-from-checkpoint 且走 `sky jobs launch` 时成立，实测前按 on-demand 价估算
  - 选机第一版只承诺 `datacenter_only` + 时价上限：launch 时源码不过滤 inet_down/可靠性（[创建逻辑](https://github.com/skypilot-org/skypilot/blob/v0.12.3.post1/sky/provision/vast/utils.py#L111-L132)），创建后校验实际 offer，不满足即销毁；要精确控网速/可靠性须绕过 SkyPilot 直调 Vast API 选机
- **生图（MVP）**：复用学粤语仓库现有 `scripts/comfy_batch_generator.py` 直连 ComfyUI 原生 API（`/prompt` `/history` `/view`），FLUX/Qwen 工作流已存在，不引入新组件
  - 版本全固定：ComfyUI commit + 节点 snapshot（[comfy-cli](https://github.com/Comfy-Org/comfy-cli)）+ 模型 manifest 烤进镜像；禁止云机现场装节点/解析依赖
  - 权重不烤镜像（Docker Hub 拉大镜像比 R2 慢），统一小镜像 + 启动时拉 R2
  - 后备：[comfyui-api](https://github.com/SaladTechnologies/comfyui-api)（无状态 API / S3 / webhook），做常驻服务或并发队列时再引入，避免两套上传下载与任务状态逻辑
- **数据湖**：Cloudflare R2（egress 免费），拆三桶隔离事故半径
  - `gpu-burst-cache`：模型权重 / 节点包，可再生
  - `gpu-burst-jobs`：输入 / 输出 / 日志，按 task_id 隔离，自动过期
  - `dialect-archive`：采访原音，[Bucket Lock](https://developers.cloudflare.com/r2/buckets/bucket-locks/) 防覆盖删除 + 独立备份；R2 无 S3 对象版本功能，"版本化" = 内容哈希不可变 key
  - 第一版显式同步，不用挂载（Vast 后端不支持）：任务前 `s5cmd` 拉输入/权重，任务后推回输出/日志/账单
  - 避开新实例 10+ 分钟冷启动（大镜像 + 权重 5–30GB 是实测痛点）
  - R2 非零成本：存储 + Class A/B 操作费，免费额度 10GB/月，记进账单
- **OCR 分级路线**：复用 [hybrid_ocr](https://github.com/makoshan/hybrid_ocr) 的 `快速打底 → 异常检测 → 局部升级`：先检查 PDF 文字层和版式；流式拼音页用 PP-OCR 全页 + 可疑行 VL 修复，表格页直接走 VL。昂贵模型按需加载，只有本地耗时超过云端冷启动/传输成本才上云；失败页写 manifest 状态，禁止用空输出冒充完成
- **Skill 形态参考**：wanshuiyin 的 `vast-gpu/SKILL.md`（描述任务→租→跑→毁，只学接口设计不用其代码）
- **备选**：RunPod（SkyPilot 原生支持 Pods，切换成本低；Serverless 留给哪天某条管线要对外提供 API）

### 选型时否决的方案

- RunPod Serverless 当主线：适合对外 API 产品（突发请求/常驻端点），但本项目全是低频离线批处理，维护 3 个 worker + handler + S3 管道的代价用不上其收益，且每秒单价比 Vast on-demand 贵
- Video2X/Real-ESRGAN 视频超分线：暂无真实视频需求，不为假想需求选型

## 成本假设（未实测，逐条换成账单）

价格基准（2026 年 on-demand 行情）：4090/5090 ~$0.40/hr，A100 80G ~$1.2/hr，H100 ~$2.5/hr。spot 折扣不设固定比例，以 `gpu-burst quote` 实时报价为准（GPU + 磁盘时价、Vast 上下行网络单价、预计冷启动数据量、最大总预算）。

- 起步（OCR + 首批生图）：$15–40 一次性
- 日常：<$15/月
- 采访季：+$5–20/月
- 训练期：每轮微调 $50–300，一年 2–3 轮 ≈ $150–900（对比自购 A100 $15k+）
- 隐藏项计入账单：冷启动时长、失败重跑、Vast 磁盘费（[停机仍计](https://docs.vast.ai/guides/reference/billing)）与上下行网络费、R2 存储/操作费

每次任务记账字段：task_id、实例 ID、GPU 型号、启动/运行/销毁时间、Vast 实际费用、R2 增量、产物数量。

## 仓库结构（规划）

```
gpu-burst/
├── src/gpu_burst/   # CLI、状态机、provider、storage、safety、workload adapter
├── tasks/           # 用户任务 JSON 与示例
├── sky/             # SkyPilot 资源与运行模板
├── images/          # 固定版本的小镜像，权重启动时拉 R2
├── tests/           # unit、contract、integration、显式付费 live 测试
└── docs/            # 产品与技术契约
```

模块与数据布局详见[技术文档](docs/technical.md)。

## 路线图

1. ✅ 调研选型（2026-07-10）
2. ⬜ `gpu-burst doctor`：uv 建 Python 3.13 环境 + skypilot\[vast\]==0.12.3.post1 + vastai + s5cmd + 凭证检查
3. ⬜ hello-world：`sky launch` 跑 `nvidia-smi`，单独验证创建→执行→远端 autodown→Vast 账单（与 ComfyUI 问题解耦）
4. ⬜ 最小闭环（7 天时间盒，只做 song-cards 一条管线），验收标准：
   - 1 张图：R2 拉模型/输入 → 回传结果 → 自动销毁 → 成本入账
   - 故障演练：本地 CLI 中断 / 任务失败 / 凭证过期，实例仍被销毁
   - 幂等重跑：已完成图片不重复生成；task manifest 最小字段：task_id、输入 URI + SHA-256、镜像 digest、阶段状态、预算/实际费用
   - 全部通过后才扩到 20 张批量
5. ⬜ 采访音频管线（数据积累不等人；数据目录先设计，不与 MVP 绑定）
6. ⬜ OCR：先本地跑 10 页基准（流式拼音 / 纯表格 / 复杂表格），记录每页耗时、异常规则召回、声调/字符错误与人工复核量；验证 hybrid_ocr 后再按冷启动盈亏决定是否上云
7. ⬜ 配音迁移：podcast-dub 本地 16GB 够用（其 README 自述），仅当排队 / 采访季吞吐压力出现才迁，价值是并发和释放本机
8. ⬜ 封装成 Claude Skill（CLI 稳定后再包壳）
9. ⬜ 训练管线（等潮汕 v1 音节录音 / 语料到位后启动；Vast 无多机，按单机微调设计，需多机另评 RunPod Clusters / Lambda 等）

## 安全与保险丝

- **防僵尸实例**：远端 [autodown](https://docs.skypilot.co/en/latest/reference/auto-stop.html)（`sky launch -i <min> --down`，在云机侧执行，本机关机仍生效）；外层 Vast API watchdog 放常在线设备（thursday-win），不依赖 Mac cron。这是最大的烧钱漏洞，最小闭环阶段就装上
- **R2 凭证隔离**：song-cards 按权限拆分[短期凭证](https://developers.cloudflare.com/r2/api/s3/temporary-credentials/)：模型缓存只读、任务输入只读、任务输出只写；`dialect-archive` 桶凭证永不上云机——Vast 是社区主机，房东有 root
- **采访音频信任边界**：`datacenter_only` 只提高基础设施可靠性，不等于机密计算保证；不可再生音频迁云前必须单独完成安全评审，且原始音频不落云机持久盘

## 原则

- 采访音频是**不可再生资产**：`dialect-archive` 桶从第一天当正式档案库建（目录规范 + 内容哈希不可变 key + Bucket Lock），不当临时中转站
- **任务幂等**：task_id 固定、输出路径固定，重跑不覆盖原始数据；失败后凭 task_id 查到输入/日志/中间状态/成本
- **产物校验绑定输入版本**：产物有效 = 可读 + 与输入/模型/参数哈希匹配（podcast-dub 教训：只查文件可读会错误复用旧产物）；缺件即失败或显式 degraded，禁止静默降级（如缺件填静音继续"成功"）
- **计算与发布分离**：任务成功止于产物入 R2；对外发布需显式授权，不混在同一条操作链
- 第一阶段只实现 song-cards 所需的最小任务/逐项状态机；跨 workload 的 `REVIEW`、`PUBLISH` 等通用抽象推迟到第二条管线迁入时
- 本地 5070 Ti（16GB）只做小样本验证 / dry-run / 短片段测试，不做云任务失败后的完整重跑
- 每个任务跑完记录真实单价到本 README，估算逐步换成实测
- 单价实测记录：（暂无）
