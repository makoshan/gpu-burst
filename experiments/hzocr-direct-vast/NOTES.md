# 杭州词典 OCR 直调 Vast 实验（2026-07-21 凌晨）

首次绕过 SkyPilot 直调 Vast API 的完整实现：`launch_vast_direct.py`
（比价选机 verified+datacenter+inet_down≥500 → 官方 paddle 镜像 → base64 onstart
→ R2 数据面双向同步 → 3h 自杀保险丝 → ALL_DONE/BATCH_FAILED 显式信号）。

## 三连败实录（每次不同层面，都不是同一个 bug）

1. **SkyPilot 路径**（gb-hzocr）：实例健康，但 sky 缓存了创建时的 SSH 代理端口
   15444，Vast 实际换成 16300，sky 死磕旧端口 600s 超时。手动用新端口 ssh 一次通。
   → 教训：sky 的 Vast 代理端口是创建时快照，不刷新。
2. **直调第一发**（45407131）：paddle 官方 GPU 镜像**缺 libGL.so.1**（cv2 依赖），
   paddleocr import 秒挂；脚本静默走完收尾，假 ALL_DONE。
   → 修复：`apt-get install -y libgl1 libglib2.0-0` + 失败必须显式打 BATCH_FAILED。
   → 另坑：v1 `DELETE /instances/{id}/` 对该实例不生效（一直 running），
     `echo y | vastai destroy instance` 才杀掉 → vast_api.py 的 destroy 需对齐 CLI 路径。
3. **直调第二发**（45407827）：宿主机在拉镜像阶段合同蒸发（instances: null），
   代码没跑到。纯基建抽卡失败。

## 又一坑：R2 日志陈旧陷阱

onstart.log 上传路径不带 attempt 标识 → 第二发死得早没覆盖，验尸时差点把
第一发的 libGL 错当成第二发的。**每次 attempt 的日志/标记必须带唯一前缀。**

## 结论（写进正式实现时的规格）

- 镜像必须预烤（apt+pip 全进镜像，push Docker Hub），云机零现场安装
  —— 本地测试载体是 thursday-win WSL2 + nvidia-docker（Mac 是 ARM 测不了）
- 数据面 R2 双向同步已验证可靠（唯一全程无故障的组件）
- 失败信号三件套：per-attempt 日志前缀 + BATCH_FAILED 显式标记 + 自杀保险丝
- 宿主机抽卡失败率今晚 2/3——创建后 N 分钟无心跳即弃抽重来要做成自动
- 账单：三次尝试合计 ~$0.9（含 hello-world 验证在内今晚总支出 $0.87 差值系
  teochew-sft 并行消耗，见 gpu-burst ledger billing.json）
