# SeeMeTVC

一体部署的轻度 Seedance 视频工作室：前后端分离开发，`docker compose up` 一次拉起。

**细化方案（五个 GitHub 参考 + 当前架构）：** [细化方案.md](细化方案.md)

## 产品边界（当前）

- 用户侧只展示**余额**与历史中的**消耗/余额变化**，不展示 token
- 超管可添加/启停上游 token 来源（渠道 + Key + 模型 + 每秒扣费）
- 后台 token 审计暂不做
- 默认内置 `mock` 渠道，便于无 Key 联调；真实生成改为 `fal` 并填 Key

## 快速启动

```bash
docker compose up --build
```

- Web: http://localhost:5173
- API: http://localhost:8000/api/health
- 默认超管：`admin@example.com` / `admin123456`

## 本地开发（无 Docker）

默认使用 SQLite，开箱可跑：

```bash
# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev
```

有 Docker 时仍可用 `docker compose up --build`（Postgres + API + Nginx）。

## 目录

```text
backend/   FastAPI：鉴权、余额、渠道、Seedance 任务
frontend/  React：工作室 / 记录 / 超管
docker-compose.yml
```

## 典型流程

1. 超管在「管理」添加 fal Seedance Lite / 2.5 渠道（Key、上游模型路径、每秒消耗）
2. 用户在「工作室」选模型生成，按 `cost_per_second × 时长` 扣余额
3. 失败自动退回余额；记录页只看消耗与余额变化
