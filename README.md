# SeeMeTVC

美妆 TVC 创意广告生成平台：工作室一键出片 + 轻量节点工作流（类 ComfyUI，不嵌入 ComfyUI）。前后端分离开发，`docker compose up` 一次拉起。

- **细化方案（架构与进度）：** [细化方案.md](细化方案.md)
- **产品计划书（PRD）：** [项目计划书.md](项目计划书.md)

## 产品边界（当前）

- 用户只看到**余额**与**消耗 / 余额变化**，不展示 token
- 超管维护上游渠道（Key、模型、每秒扣费、启停）
- 上游支持：`mock`（联调）、`fal`（Seedance 等）、`agnes` / Pavo（免费渠道，需自备 Key）
- 参考图支持公网 URL 与**本地上传**（本机素材会在提交上游前内联，避免 Agnes 拉不到 `localhost`）
- 工作流固定节点：`BriefInput` → `ScenePlan` → `MakeupControl` → `ShotGenerate` → `TimelineMux` → `PreviewOut`
- 不做独立 new-api、不嵌入完整 ComfyUI、不做用户侧 token 审计大盘

## 快速启动

```bash
docker compose up --build
```

- Web: http://localhost:5173
- API: http://localhost:8000/api/health
- 默认超管：`admin@example.com` / `admin123456`

## 本地开发（无 Docker）

默认 SQLite + 本地上传目录 `backend/data/uploads`：

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# 可选：复制 .env.example 为 .env，填入 AGNES_API_KEY 等
uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

Vite 已将 `/api` 与 `/uploads` 代理到 `:8000`。

## 目录

```text
backend/    FastAPI：鉴权、余额、渠道、上传、视频任务、工作流执行
frontend/   React：工作室 / 工作流 / 素材 / 作品 / 超管
docker-compose.yml
细化方案.md
项目计划书.md
```

## 页面一览

| 入口 | 说明 |
|------|------|
| 工作室 | 美妆素材墙、并行生成、成片预览；可「回到素材」 |
| 工作流 | React Flow 画布，保存草稿并执行 DAG |
| 素材 | 宣传样例浏览 |
| 作品 | 历史成片与任务状态 |
| 超管后台 | 渠道与用户余额（仅 super_admin） |

## 典型流程

1. （可选）在 `.env` 配置 `AGNES_API_KEY`，超管后台启用 Agnes 渠道；或添加 `fal` 渠道并填 Key
2. 工作室：点素材或上传参考图 → 选模型 → 生成；按 `cost_per_second × 时长` 扣余额
3. 工作流：编辑 Brief / 分镜 / 妆容节点 → 执行 → 轮询节点状态与成片
4. 失败自动退款；作品页只看消耗与余额变化

## Agnes 提示

- 国内 Key 建议 `AGNES_BASE_URL=https://api.agnes-ai.cn`
- 参考图不要用仅本机可访问的绝对 URL；请用「上传」或素材墙（系统会自动处理）
