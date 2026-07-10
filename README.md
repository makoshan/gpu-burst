# gpu-burst

个人 AI 算力基础设施：批处理、训练、大规模音频处理，按需租云 GPU，跑完销毁，本地 5070 Ti 兜底。

## 定位

方言保育项目的算力底座——现在服务日常批处理任务，未来扛方言模型训练和采访音频入库。

服务的上游项目：

- `学粤语`（song-cards 歌词卡生图）
- `podcast-dub`（播客配音）
- 潮州词典 OCR / 潮汕话 TTS·ASR 模型

## 解决什么问题

| 现状 | 痛点 |
|---|---|
| OCR、生图、配音都跑本地 thursday-win | 显存不够 / 排队 / 占机器 |
| 手动租 Vast.ai | 开机、装环境、拷文件、忘关机都是手工活 |
| 未来要微调 TTS/ASR | 本地 5070 Ti 训不动 A100 级任务 |

## 产品形态

一个 Claude Skill + 本仓库。对用户只有一个动作：

```
/gpu-burst 生图 tasks/song-cards.json
```

背后自动：**比价租机 → 挂权重缓存 → 跑任务 → 回传结果 → 销毁机器 → 记账**

## 五条管线

| 管线 | 引擎 | GPU 需求 | 成本量级 |
|---|---|---|---|
| **现在** | | | |
| 词典 OCR | PaddleOCR-VL / MinerU | 4090 | $2–8 一次性 |
| 歌词卡生图 | ComfyUI (FLUX/Qwen) | 4090 | $1–3 / 批 |
| 播客配音 | podcast-dub | 4090 | ~$0.5 / 集 |
| **未来** | | | |
| 采访音频入库 | whisper + 说话人分离 → 转写/切片/标注 | 4090 | ~$0.3–0.5 / 小时音频 |
| 方言模型训练 | Qwen3-TTS 潮汕微调 / FireRedASR LoRA | A100/H100 ×几十小时 | $50–300 / 轮 |

## 技术选型（2026-07 调研定案）

- **调度**：[SkyPilot](https://github.com/skypilot-org/skypilot) + Vast.ai 后端
  - 最便宜（Vast 市场比价），跑完即毁，不锁平台
  - spot 抢占 + 断点续训，训练成本砍 30–40%
  - Vast API key 放 `~/.config/vastai/vast_api_key`
- **生图 API 化**：[comfyui-api](https://github.com/SaladTechnologies/comfyui-api)（Salad，平台无关单二进制）
  - Docker 结构参考 [worker-comfyui](https://github.com/runpod-workers/worker-comfyui)
  - 云机装节点/拉模型用 [comfy-cli](https://github.com/Comfy-Org/comfy-cli)
- **权重缓存 + 数据湖**：Cloudflare R2（egress 免费），SkyPilot `MOUNT_CACHED` 挂载
  - 避开新实例 10+ 分钟冷启动（大镜像 + 权重 5–30GB 是实测痛点）
  - 同一个桶：模型权重缓存 / 采访原始音频 / 切片数据集 / 训练 checkpoint
- **Skill 形态参考**：wanshuiyin 的 `vast-gpu/SKILL.md`（描述任务→租→跑→毁，只学接口设计不用其代码）
- **备选**：RunPod Serverless + worker-template（哪天某条管线要对外提供 API 再切，训练场景它干不了）

### 选型时否决的方案

- RunPod Serverless 当主线：适合对外 API 产品（突发请求/常驻端点），但本项目全是低频离线批处理，维护 3 个 worker + handler + S3 管道的代价用不上其收益，且每秒单价比 Vast on-demand 贵
- Video2X/Real-ESRGAN 视频超分线：暂无真实视频需求，不为假想需求选型

## 成本预期

价格基准（2026 年 on-demand 行情）：4090/5090 ~$0.40/hr，A100 80G ~$1.2/hr，H100 ~$2.5/hr；spot 约 7 折。

- 起步（OCR + 首批生图）：$15–40 一次性
- 日常：<$15/月
- 采访季：+$5–20/月
- 训练期：每轮微调 $50–300，一年 2–3 轮 ≈ $150–900（对比自购 A100 $15k+）

## 仓库结构（规划）

```
gpu-burst/
├── tasks/           # 每条管线一个 .sky.yaml
│   ├── comfyui-song-cards.yaml
│   ├── paddleocr-teochew.yaml
│   ├── podcast-dub.yaml
│   └── interview-ingest.yaml
├── images/          # Dockerfile（权重烤进镜像 or 启动脚本拉 R2 缓存）
├── scripts/         # 上传输入/回收输出/记账的胶水脚本
└── README.md        # 本文件 + 单价实测记录
```

## 路线图

1. ✅ 调研选型（2026-07-10）
2. ⬜ 最小闭环：装 SkyPilot + 配 Vast key → song-cards 生图云上出 1 张图 → 记录真实耗时/单价
3. ⬜ 采访音频管线（提前：数据积累不等人，可复用 podcast-dub 大部分代码）
4. ⬜ OCR / 配音管线迁移
5. ⬜ 封装成 Claude Skill
6. ⬜ 训练管线（等潮汕 v1 音节录音 / 语料到位后启动）
7. ⬜ 番外（零成本）：thursday-win 本地用 10 页词典实测 MinerU vs PaddleOCR-VL，看版面解析能否省掉后处理

## 原则

- 采访音频是**不可再生资产**：R2 桶从第一天当正式数据湖建（目录规范 + 版本化），不当临时中转站
- 每个任务跑完记录真实单价到本 README，估算逐步换成实测
- 单价实测记录：（暂无）
