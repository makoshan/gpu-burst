# gpu-burst 产品文档

> 状态：Phase 1 本地 CLI 骨架已实现；song-cards 云端批处理 MVP 尚未实现。
>
> 更新日期：2026-07-10

## 1. 产品摘要

gpu-burst 是个人 AI 算力基础设施：把已经能在本地运行的 GPU 批处理任务，封装成可报价、可追踪、可恢复、跑完自动销毁的命令行工作流。

第一阶段不建设通用 GPU 平台，只验证一个闭环：使用 Vast.ai 临时实例运行 [comfy-batch](https://github.com/makoshan/comfy-batch)，生成一批 song-cards 图片，经 R2 回传产物和账单后自动销毁实例。

产品入口是普通 CLI，Agent Skill 只负责把自然语言翻译成参数：

```bash
gpu-burst doctor
gpu-burst quote song-cards tasks/song-cards.json
gpu-burst run song-cards tasks/song-cards.json
gpu-burst status <task_id>
gpu-burst logs <task_id>
gpu-burst cancel <task_id>
```

当前已实现本地 Phase 1 和受保护的 hello-world 生命周期：`doctor`、fake-cloud `quote`、`run --dry-run`、status/logs、本地 cancel、hello-world dry-run/live 入口，以及 watchdog dry-run。live hello-world 会在 finally 路径执行 `sky down`，但仍缺 Vast API 销毁复核和账单关联；song-cards 自动云端执行仍是 `planned`。

## 2. 要解决的问题

当前 GPU 工作负载分散在本地脚本、WSL、远程 SSH 和手工租机流程里。模型本身通常已经能运行，真正反复消耗时间的是：

- 判断应该继续用本地 5070 Ti，还是临时租云 GPU；
- 查价、选机、开机、同步模型和输入；
- 处理冷启动、失败重跑、断点续跑和产物回收；
- 防止实例忘记销毁或磁盘继续计费；
- 记录真实耗时与费用，使下一次报价有依据；
- 在不可再生数据、临时任务数据和可再生模型缓存之间建立权限边界。

gpu-burst 的价值不是“让模型跑起来”，而是让现有任务以可控成本可靠运行，并留下可审计的任务记录。

## 3. 目标用户与核心任务

### 3.1 主要用户

- Mako：运行方言保育项目的生图、OCR、配音、采访处理与未来训练任务；
- Agent：代表用户调用稳定 CLI，但不能绕过预算、安全和发布授权；
- 上游项目：提供领域输入并消费产物，不把领域规则塞进 gpu-burst。

### 3.2 Jobs to be Done

| 场景 | 用户真正要完成的任务 | gpu-burst 的职责 |
|---|---|---|
| song-cards 生图 | 给一批已审核 prompt 生成风格稳定的图片 | 报价、租机、执行 comfy-batch、回传、销毁、记账 |
| 词典 OCR | 低成本处理大量页面，只升级疑难内容 | 比较本地/云端盈亏，执行已选定的 hybrid OCR workload |
| 播客配音 | 在本地 GPU 排队时获得额外吞吐 | 保存阶段产物，恢复失败单元，回传音轨与质量报告 |
| 采访入库 | 安全处理不可再生原始音频 | 执行受信任 workload，但不得扩大数据暴露范围 |
| 方言模型训练 | 租用本地无法提供的显存与算力 | 单机训练、checkpoint 回传、抢占恢复与预算保护 |

## 4. 产品定位与非目标

### 4.1 当前定位

当前是“待验证的 song-cards 批处理器”，不是已经上线的统一算力底座。只有当故障销毁、账单、数据隔离和幂等恢复通过真实运行验证后，才扩大到第二条管线。

### 4.2 第一阶段非目标

- 不提供公共生图 API 或多人 SaaS；
- 不运行常驻 ComfyUI 服务或 Web dashboard；
- 不建设跨云自动套利和复杂调度器；
- 不以 spot 作为默认成本假设；
- 不迁移本地已经足够快且没有排队压力的任务；
- 不自动发布生成内容到公开网站；
- 不在单样本阶段抽象完整的通用工作流平台；
- 不承诺多机训练，Vast 后端当前也不支持该路径。

## 5. 产品原则

1. **CLI 为底，Skill 为壳。** cron、CI、人工调试和 Agent 使用同一个接口。
2. **本地优先，云端有盈亏门槛。** 云端总耗时包含冷启动和传输，总成本包含 GPU、磁盘、网络与对象存储。
3. **便宜阶段先跑，昂贵阶段按需升级。** 复用 [hybrid_ocr](https://github.com/makoshan/hybrid_ocr) 的 `快速打底 → 异常检测 → 局部升级` 思路。
4. **产物必须绑定输入版本。** “文件存在”不等于完成；输入、模型、参数或工作流变化后必须重新计算。
5. **候选不等于 verified。** 任务执行成功不代表内容质量通过，上游领域项目负责最终质量判断。
6. **计算与发布分离。** 成功边界默认止于产物进入私有 R2；公开发布需要独立、显式授权。
7. **安全销毁优先于体验便利。** 任何不确定状态都不得取消预算上限、远端 autodown 或外层 watchdog。
8. **先用真实账单替换估算。** README 中的价格只是启动假设，不作为长期承诺。

## 6. 能力成熟度

统一使用以下标签：

- `reference`：上游项目已证明某种做法可行，但尚未接入 gpu-burst；
- `planned`：接口和验收方式已经定义，尚未实现；
- `experimental`：实现已存在，只通过受控烟测；
- `verified`：通过真实任务、故障演练和可复现验证；
- `production`：持续运行并具备稳定监控、运维和回滚路径。

| 能力 | 当前状态 | 晋级条件 |
|---|---|---|
| gpu-burst 本地 CLI 骨架 | `experimental` | 默认测试通过，可生成本地 dry-run ledger；尚未触达云端 |
| Vast hello-world 生命周期 | `experimental` | 手工云端烟测已完成；CLI 已有 guarded launch/finally down，待真实 CLI 故障演练、Vast 销毁复核和账单关联 |
| comfy-batch 本地生图 | `reference` | 已有 50 张 song-cards 上线记录；gpu-burst 不把它冒充为云端验证 |
| song-cards 云端 1 张闭环 | `planned` | 产物、manifest、账单、自动销毁全部通过 |
| song-cards 20 张批量 | `planned` | 单张闭环与故障演练通过后，逐项恢复无重复生成 |
| hybrid OCR | `reference` | 先完成本地 10 页基准和异常规则评估，再判断是否值得上云 |
| podcast-dub 云端迁移 | `reference` | 只有本地出现排队或吞吐瓶颈才启动迁移 |
| 采访音频入库 | `planned` | 信任边界、授权、备份和数据留存策略完成评审 |
| 训练 | `planned` | 数据、训练脚本、checkpoint 恢复和单轮预算基线齐备 |

## 7. song-cards MVP

### 7.1 输入

- 已审核的 JSON 任务文件；
- 每项具有稳定 `item_id`、prompt、seed 和 profile；
- profile 第一版只允许 `fast`、`quality`、`style`；
- 固定 comfy-batch commit、ComfyUI 版本、节点 snapshot、模型 manifest 和 LoRA 哈希。

### 7.2 输出

- 每个 item 的 PNG；
- task manifest 与逐项状态；
- stdout/stderr 和 ComfyUI 执行记录；
- 实例、GPU、启动、运行、回传、销毁时间；
- Vast GPU、磁盘和网络费用；
- R2 增量与最终任务汇总。

### 7.3 用户旅程

```text
doctor
  → quote（查看总预算与本地/云端建议）
  → run（确认后启动）
  → status / logs
  → 产物进入 R2
  → 自动销毁
  → 返回本地输出目录与成本摘要
```

### 7.4 MVP 范围内

- on-demand Vast 实例；
- `datacenter_only` 与最大时价；
- 单个 FLUX GGUF profile；
- 一批任务复用同一实例和已加载模型；
- R2 显式同步；
- 短期、最小权限凭证；
- 远端 autodown 与独立 watchdog；
- 逐项 manifest、幂等恢复和失败退出码；
- 本地 CLI 输出和账单记录。

### 7.5 MVP 范围外

- dashboard、公开端口与 comfyui-api；
- Qwen 与多 profile 自动选择；
- spot、跨云 fallback、并发多实例；
- 自动人工审核或自动公开发布；
- OCR、配音、采访和训练实现。

## 8. 发布门槛

### Gate A：本地开发闭环

- `gpu-burst doctor` 能区分已安装、缺失、无效和未配置状态；
- `--dry-run` 不产生云费用，能生成标准 task manifest；
- manifest 与 schema 测试通过；
- 日志中不出现密钥值。

### Gate B：Vast hello-world

- `nvidia-smi` 成功；
- 实际 offer 满足 GPU、显存、内存、时价与 datacenter 条件；
- 正常结束、本地中断和命令失败三种情况下实例都能销毁；
- Vast 账单能关联到 task_id。

### Gate C：单张图片

- 固定输入生成一张可读 PNG；
- ComfyUI history 明确显示执行成功，而不只是 HTTP 200；
- PNG、manifest、日志和费用回传 R2；
- 重跑同一 task_id 不重复生成已完成 item；
- 实例在配置的销毁 SLA 内同时从 SkyPilot 与 Vast 视图消失。

### Gate D：20 张批量

- 20 个 required item 全部完成或任务明确失败；
- 强制制造单项失败后，只重跑失败项；
- 任务不能以退出码 0 隐藏缺失产物；
- 实际总费用不超过硬预算；
- 上游完成独立图片质量审核后，才称为业务可用。

## 9. 成功指标

当前没有足够真实付费运行数据设置长期 SLA，第一阶段使用阶段门槛和临时目标。累计至少 5 次付费运行后再调整目标。

### 9.1 主要指标

| 指标 | 定义 | 临时目标 | 决策用途 |
|---|---|---|---|
| 安全完成率 | required item 全部验证通过、账单写入且实例按时销毁的任务数 / 已启动任务数 | Gate C 与 Gate D 验证批次必须 100%；任一未销毁事件阻止扩容 | 是否允许扩大批量或迁入第二条管线 |
| 预算遵守率 | 实际总费用不超过用户硬预算的已启动任务数 / 已启动任务数 | 100%，硬预算不可软化 | 是否允许 Agent 无人值守运行 |
| 报价误差 | `abs(actual - quote) / max(actual, 最小计费单位)` | 5 次付费运行后目标不高于 20% | 是否需要修正冷启动、网络或磁盘估算 |

### 9.2 驱动指标

- 冷启动占比：准备完成前耗时 / 总任务耗时；
- 模型传输量与复用率：本次下载字节、命中缓存字节；
- item 首次成功率与重试次数；
- 人工操作次数与从 `run` 到产物可用的总时长。

### 9.3 质量与安全护栏

- required item 缺件数必须为 0，或整个任务明确失败；
- 云机不得获得 `dialect-archive` 长期凭证；
- 未经授权不得把产物上传到公共站点；
- 内容质量由上游 fixture 或人工审核判定，不以“生成了 PNG”替代；
- 本地现有用户和任务不得因 gpu-burst 试验被抢占或破坏。

### 9.4 数据来源

- task manifest：阶段状态、item 状态、重试与产物；
- SkyPilot/Vast：实例与计费；
- R2：传输和存储增量；
- CLI 本地 ledger：quote、actual、销毁核验与人工操作；
- 上游审核结果：内容质量与可发布性。

## 10. 路线图

1. ✅ 文档与 schema；
2. ✅ 本地 `doctor`、fake-cloud `quote`、`run --dry-run`、ledger、status/logs；
3. ✅ Vast hello-world 非付费准备：dry-run plan、live gate、local watchdog；
4. 🟨 Vast hello-world live 生命周期已实现，待真实 CLI 验证、销毁复核与账单；
5. song-cards 单张；
6. 20 张批量与故障恢复；
7. 基于真实账单修正 quote；
8. 评估第二条管线，优先选择能验证新抽象而不是重复第一条路径的 workload；
9. CLI 稳定后再增加 Agent Skill。

## 11. 开放决策

- R2 短期凭证由本地签发还是由最小 Worker 签发；
- 外层 Vast watchdog 放在 thursday-win 还是独立定时服务；
- 本地与云端的盈亏阈值采用固定分钟数还是 workload profile 历史模型；
- 首批付费运行使用 4090、5090 还是等价的最低成本 offer；
- Gate D 后第二条管线选择 hybrid OCR 还是 podcast-dub 的一个受控子阶段。

## 12. 相关文档

- [README](../README.md)
- [技术文档](technical.md)
- [comfy-batch](https://github.com/makoshan/comfy-batch)
- [hybrid_ocr](https://github.com/makoshan/hybrid_ocr)
- [podcast-dub](https://github.com/makoshan/podcast-dub)
