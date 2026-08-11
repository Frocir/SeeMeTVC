# SeeMeTVC

美妆 TVC 一体仓：工作室一键出片 + LibTV 风格无限画布。FastAPI + React。

- **细化方案（路线 / 能力 / 架构）：** [细化方案.md](细化方案.md)
- **产品计划书：** [项目计划书.md](项目计划书.md)
- 画布参考：[LibTV Canvas](https://www.liblib.tv/canvas)

## 当前能力

| 入口 | 说明 |
|------|------|
| `/` 工作室 | 一键快出片（可并行多 Job） |
| `/workflow` 画布 | 主工作流：模板、节点连线、单飞执行、SSE、trim/拼接、超管模拟 |
| `/showcase` 灵感 | Lookbook 浏览；同款提示词在工作室素材墙可一键套用 |
| `/history` 作品 | 工作室 Job + 画布 Run 成片回看 |
| `/admin` 超管 | 渠道 / Key / 用户余额 |

- 用户只看**余额**与消耗；超管维护渠道（Key、模型、每秒扣费）
- 上游：`mock`（本地样片，依赖 ffmpeg） / `fal` / `agnes`（免费档易 429）
- 画布可命名保存多个草稿；完整「多项目空间 / 素材库抽屉」见细化方案 §0（暂搁）
- **下一个里程碑**：声音工作流（详见细化方案 §0）

## 两种启动方式

### A. Docker 一键（体验完整栈）

```bash
docker compose up --build
```

- Web：**nginx 静态站** → http://localhost:5173（或 http://127.0.0.1:5173；`/api` 与 `/uploads` 已反代）
- API → http://localhost:8000/api/health（镜像内已装 **ffmpeg**，可看 `ffmpeg_ok`；库为 Postgres）
- 改前端源码请用下方「本地开发」，不要指望 compose 里的 HMR

### B. 本地开发（改 UI / 热重载）

```bash
# 后端（默认 SQLite → backend/seemetvc.db）
cd backend && python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
# 可选：复制 .env.example 为 .env，填 AGNES_API_KEY / FFMPEG_PATH
uvicorn app.main:app --reload --port 8000

# 前端（另开终端；Vite 已代理 /api 与 /uploads → :8000）
cd frontend && npm install && npm run dev
```

- Web: Vite → http://localhost:5173（`host: true`，127.0.0.1 也可）
- **ffmpeg**：mock 样片、trim、拼接都需要；本机 PATH 有 ffmpeg，或在 `backend/.env` 设 `FFMPEG_PATH`
- 默认模型：**mock**（优先级高于 Agnes）；启动时会 heal 启用 mock
- Agnes 免费档易触发 429（进程内有最小间隔与退避）；演示全链路请优先用 mock
- 超管：`admin@example.com` / `admin123456`（开发阶段登录页会预填，方便调试）

## 典型流程（画布）

1. 打开「画布」→ 选用美妆模板或添加节点  
2. 按槽位连线；出口类上游变化可自动再跑（同时只跑一个 Run，可取消）  
3. 节点内看图/播视频；进度走 SSE（失败则自动轮询）  
4. 超管失败时可粘贴/上传模拟结果（前端填入，不计费）  
5. 生成失败自动退款；成片在「作品」回看  
