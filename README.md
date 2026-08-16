# SeeMeTVC

美妆 / 硬件短片工作台：左侧 **TVC Agent** 驱动中间节点画布出片。Agent = LLM + 进程内 MCP + Skill + 对话记忆。画布仍可手搭；模板与 Lookbook 分 **美学** 和 **硬件 / 科创** 两套。人物一级库本轮是空页，素材请在项目里上传。

默认超管写在仓库根目录 `.env.example`（`BOOTSTRAP_ADMIN_*`）。复制为 `.env` 后改口令，不要提交。上游视频 / LLM Key **只写在超管渠道表**，不放 `.env`，源码里也没有。

## 怎么跑

本机开发（SQLite，不强制 Docker）。需本机 **ffmpeg**。口播另起 TTS（下面 aisrv）。

```bash
cp .env.example .env   # Windows: copy .env.example .env

# 后端
cd backend
.venv\Scripts\activate    # Windows；macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

浏览器打开 Vite 端口（默认 `5173`），`/api` 与 `/uploads` 会代理到后端。

TTS（二选一）：

```bash
# 本机 Python（aisrv/server.py，需 pip install edge-tts fastapi uvicorn）
cd aisrv
uvicorn server:app --host 127.0.0.1 --port 5050

# 或官方 edge-tts 镜像，API_KEY 与 .env 里 AISRV_API_KEY 一致
docker run -d -p 5050:5050 -e API_KEY=<与 AISRV_API_KEY 相同> -e DEFAULT_VOICE=zh-CN-XiaoxiaoNeural travisvn/openai-edge-tts:latest
```

一整套（Postgres + API + Web + TTS）：

```bash
docker compose up --build
```

compose 要求 `.env` 里 `JWT_SECRET`、`BOOTSTRAP_ADMIN_PASSWORD`、`AISRV_API_KEY`、`POSTGRES_PASSWORD` 非空。

## 超管与渠道

演示态默认**不显示**超管入口。超管账号在顶栏头像上 **2 秒内连点 5 次** 可开关（只对自己的 session 有效）。打开后侧栏出现「超管」，可配渠道、探活、改 Key。

启动时会写入渠道骨架（无 Key 则不启用）。常见预设：

| 用途 | 渠道 | 说明 |
| --- | --- | --- |
| 图生 / 文生视频 | 火山方舟 Seedance Lite / 2.5 | `ARK_API_KEY` 填渠道表。Lite 约 2–12s、无原生音频；2.5 默认同步音频、可参考图 / 首尾帧 |
| Agent 对话（默认） | DeepSeek-V4-Pro | 官方 `https://api.deepseek.com`，上游 `deepseek-v4-pro` |
| Agent 对话 | DeepSeek-V4-Pro（tqx） / Claude Sonnet 4.6 / GPT-5.4 | 网关 `https://llm.tqx.ai`。tqx 与官方 DeepSeek **Key 不能混用** |
| 文生图 | Gemini（向量引擎）或 OpenAI 兼容 Images | |
| TTS | Edge TTS（aisrv） | 钥匙来自 `AISRV_API_KEY` |
| ASR | OpenAI 兼容 Whisper | 可选 |

一条渠道 = 一个主机 + 一把 Key。改 Base URL 会丢掉旧 Key，避免把 A 站的 token 发到 B 站。改 Agent 相关表结构后需重启一次后端。

## 全链路架构

```
浏览器
  工作区 / 模板 / 画布（节点 · 素材 · TVC Agent）
       │  REST + SSE（长出片每 12s keepalive）
       ▼
FastAPI  backend/
  鉴权 · 项目 graph_json · 余额流水 · 生成历史
  Agent 循环（skill + 近 16 轮记忆 + 摘要）
       ├─ LLM 渠道（OpenAI 兼容 / Anthropic Messages）
       ├─ 进程内 MCP（改图 / run_*）──► 同一套 workflow 执行器
       │                              target_ids 跑单节点
       └─ 写库：对话、graph、撤销快照（最多 50 份）
              │
              ├─ 视频：火山方舟 Seedance（Ark）/ Agnes
              ├─ 文生图：Gemini 原生 / OpenAI 兼容 Images
              ├─ TTS → aisrv（Edge TTS）
              ├─ ASR → Whisper 兼容
              └─ ffmpeg 裁切 / 拼接 / 混音 / 字幕
```

要点：

- Agent 不另写出片引擎。`run_*` 就是现有节点执行，扣费仍走工作流 run。
- MCP **不开放端口**，只给本进程 Agent 调。
- Agent 回合内画布只读；每步改图立刻写入 `graph_json`，SSE 推全图。回合外仍手动保存。点发送时若有未保存手改，会先保存再开跑。
- 会扣费的文生图 / 图生视频先出**对话内确认卡**（不弹系统对话框），暂停态落库，刷新后仍可确认 / 取消。
- 发给上游的对话会整理工具回执：历史只保留文字，当前这一轮才带成对的 `tool_calls`。画布状态在 system 里。

## 已经具备

**账号与后台**

- 注册登录；超管渠道（视频 / LLM / TTS / 图 / ASR）、探活、余额与流水、失败退款（出片路径）。
- 开发登录页可按 `.env` 预填超管（`DEV_PREFILL_LOGIN`，生产构建不预填）。

**项目与画布**

- 工作区项目网格；进入画布手搭 DAG。
- 节点：文本 / 图 / 视频 / 音频、LLM（对话 / Brief / 单镜）、文生图、图对比、图生视频、参考视频反推、TTS、ASR、裁切、拼接、拆音轨、混音、烧字幕。
- 官方模板可预填一条龙（美学成片 / 硬件成片 / 硬件工坊 / 快测）；可单节点跑或一键跑；输入变化可自动排队（Agent 改图时会抑制，避免抢跑）。
- 顶栏 **一键排版**：按依赖分层。Agent 搭完图也会调同一套 `layout_graph`。
- 素材库、上传（参考图自动压缩）、检查器改参；生成历史可丢回画布。
- Seedance 2.5 支持风格 / 角色 / 产品参考图（按模型能力开关）。

**TVC Agent**

- 每项目一条对话线程，刷新还在；可清空对话（画布不动）。
- 工作模式 **Auto / Plan**（默认 Plan）：Plan 先出方案卡，按 Brief → 分镜 → 搭图逐环点开始；Auto 四件套齐了就干。扣费确认卡两种模式都不跳。
- 默认对话模型：**DeepSeek-V4-Pro**（可在面板换已启用的 LLM 渠道）。
- Skill 下拉：`seedance-tvc`（默认，美妆 / 硬件短片导演）、`wes-anderson-tvc` 等，规程在 `backend/app/skills/*/SKILL.md`。
- 图工具：`get_graph` / `add_node` / `patch_node` / `connect` / `delete_node` / `layout_graph`。
- 计划：`propose_plan` / `complete_stage`（Plan 闸门按环白名单禁工具）。
- 素材：`get_node_output` / `list_asset_versions` / `send_asset_to_canvas` / `expand_scenes_to_nodes`（反推分镜展开）。
- 执行：每种可跑节点一个 `run_*`（含 `run_text_to_image` / `run_image_to_video` / `run_video_mux` / `run_video_reverse_prompt` 等）。
- 流式：字、工具过程、画布更新、方案卡 / 环节卡、确认卡。
- 顶栏撤销（服务端快照）。

## 暂不具备，或明显偏弱

- MCP 不是对外 JSON-RPC 服务，Cursor 等连不上。
- 没有跨项目记忆、没有 Skill 商店。
- 人物一级库是空页；请在项目里上传图片。
- 两个浏览器标签同时改同一项目会后写覆盖，没有合并。
- 出片 SSE 可能被网关超时掐断；确认卡刷新可续。Agent 侧已做 12s keepalive，反向代理仍建议加大超时。
- `connect` 的端口合法性比画布手连要松。
- 无自动化测试覆盖 Agent。
- 上线前密钥、限流、权限还要加固。
