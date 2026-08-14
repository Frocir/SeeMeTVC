# SeeMeTVC

美妆短片工作台：左侧对话里的 **TVC Agent** 驱动中间节点画布出片。Agent = LLM + 进程内 MCP + Skill + 对话记忆。画布仍可手搭；人物一级库本轮空着。

默认账号写在仓库根目录 `.env.example`（`BOOTSTRAP_ADMIN_*`）。复制为 `.env` 后按需改口令与钥匙，不要提交。源码与镜像默认值里不再带这些密钥。

## 怎么跑

本机开发（SQLite，不强制 Docker）：

```bash
# 后端（需本机 ffmpeg；TTS 另起 aisrv 或 docker 里的 edge-tts）
cd backend
.venv\Scripts\activate    # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

浏览器打开 Vite 端口（默认 5173），`/api` 会代理到后端。

一整套（Postgres + API + Web + TTS）：

```bash
docker compose up --build
```

超管在 **超管** 页启用渠道并填 Key：视频 / LLM / TTS / 文生图。无 Key 时可用「本地 LLM 模拟」「本地文生图模拟」、mock 视频。改 Agent 相关表后需重启一次后端。

## 全链路架构

```
浏览器
  工作区 / 模板 / 画布（节点 · 素材 · TVC Agent）
       │  REST + SSE
       ▼
FastAPI  backend/
  鉴权 · 项目 graph_json · 余额流水
  Agent 循环（skill + 近 16 轮记忆 + 摘要）
       ├─ LLM 渠道（OpenAI 兼容 / Anthropic / 本地模拟）
       ├─ 进程内 MCP（改图 / run_*）──► 同一套 workflow 执行器
       │                              target_ids 跑单节点
       └─ 写库：对话、graph、撤销快照（最多 50 份）
              │
              ├─ 图生视频渠道（Seedance / Agnes / mock）
              ├─ 文生图（目前仅本地占位图）
              ├─ TTS → aisrv（Edge TTS，OpenAI speech 兼容）
              └─ ffmpeg 裁切 / 拼接 / 混音 / 字幕
```

要点：

- Agent 不另写一套出片引擎。`run_*` 就是现有节点执行，扣费仍走工作流 run。
- MCP **不开放端口**，只给本进程 Agent 调。
- Agent 回合内画布只读；每步改图立刻写入 `graph_json`，SSE 推全图。回合外仍手动保存。点发送时若有未保存手改，会先保存再开跑。
- 会扣费的图生视频先出确认卡，暂停态落库，刷新后仍可确认 / 取消。

## 已经具备

**账号与后台**

- 注册登录、超管渠道（视频 / LLM / TTS / 图）、余额与流水、失败退款（出片路径）。

**项目与画布**

- 工作区项目网格；进入画布手搭 DAG。
- 节点：文本 / 图 / 视频 / 音频、LLM（对话 / Brief / 单镜）、文生图、图生视频、TTS、裁切、拼接、拆音轨、混音、烧字幕。
- 官方模板可预填一条龙；可单节点跑或一键跑；输入变化可自动排队（Agent 改图时会抑制，避免抢跑）。
- 素材库、上传、检查器改参。

**TVC Agent**

- 每项目一条对话线程，刷新还在。
- Skill 下拉：`grill-me`（先问清 Brief）、`wes-anderson-tvc`（自研安德森风导演流程，不是 LibTV 副本）。规程在 `backend/app/skills/*/SKILL.md`。
- 图工具：`get_graph` / `add_node` / `patch_node` / `connect` / `delete_node`。
- 执行工具：每种可跑节点一个 `run_*`。
- 流式：字、工具过程、画布更新、确认卡。
- 顶栏撤销（服务端快照）。

## 暂不具备，或明显偏弱

- **本地 LLM 模拟几乎不会「当导演」**：只会按关键词加节点，不会认真 grill、也不会自己连线出片。真提问 / 真搭图需要已启用的真 LLM。
- 文生图没有真模型，只有本地占位图。
- MCP 不是对外 JSON-RPC 服务，Cursor 等连不上。
- 没有「新对话」、没有跨项目记忆、没有 Skill 商店。
- 人物一级库是空页；请在项目里上传图片。
- 两个浏览器标签同时改同一项目会后写覆盖，没有合并。
- 出片 SSE 可能被网关超时掐断；确认卡刷新可续，但长连接本身没做代理超时配置。
- `connect` 的端口合法性比画布手连要松。
- 无自动化测试覆盖 Agent。
- 上线前密钥、限流、权限还要加固。

## 改进计划（先做上面的）

1. **无 Key 也能看懂 Agent**：模拟渠道按 Skill 走完整提问 + 加节点 + 连线（现在演示偏口号）。
2. **有 Key 走通确认卡出片**：真 LLM 选导演 Skill → 搭图 → 图生视频确认 → 成片上节点。顺带核对长 SSE / 刷新后续确认。
3. **文生图接真渠道**，与现有视频 / LLM / TTS 一样可配置、可扣费、可进确认卡。
4. **连线规则与画布一致**，避免 Agent 接出检查器认为非法的边。
5. **人物库做成能选进节点的资产**，不要长期停在空态。
6. **需要时再外开 MCP 端口**（鉴权、只读/写图分权），给 Cursor 或其他 client。
7. **多会话 / 新对话**（现在每项目永远一条线，旧 Brief 会一直占窗口，只能靠摘要）。
8. **测试与上线加固**：Agent 循环、确认暂停、撤销、扣费退款的回归；密钥与限流。

1–2 是「现在像不像真 Agent」；3–5 是创作闭环；6–8 是平台化。
