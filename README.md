# SeeMeTVC

美妆 TVC 一体仓：项目里编排成片。FastAPI + React。IA 对齐 [原型图.html](原型图.html)；**现行路线**见 [细化方案.md](细化方案.md)。

- **现行细化方案：** [细化方案.md](细化方案.md)
- **产品计划书：** [项目计划书.md](项目计划书.md)（仓库不改此文件）
- 画布参考：[LibTV Canvas](https://www.liblib.tv/canvas)

## 当前能力

| 入口 | 说明 |
|------|------|
| `/` 工作区 | **我的项目**（1 项目 = 1 张编辑画布；封面优先成片，否则最后一张图） |
| `/templates` 模板 | 官方模板 + Lookbook；选用后**新建项目**并打开 |
| `/characters` 人物 | 空态（人物库暂搁） |
| `/history` | 重定向到工作区 |
| `/workflow/:id` | 该项目的编辑画布：保存、一键跑、SSE、trim/拼接、超管模拟；左侧节点 \| 素材 |
| `/admin` 超管 | 渠道 / Key / 用户余额 / 流水 |
| `/studio` | 一键出片暗门（不进左栏） |
| `/showcase` | 重定向到 `/templates` |
| `/login` | 登录 / 注册 |

- 用户点余额芯片看流水；超管可打开某用户流水。每次余额变动落一行（含期初快照）
- 上游：`Seedance LocalSimulate`（本地样片，依赖 ffmpeg） / `ark`（火山方舟 Seedance Lite + 2.5） / `agnes`（免费档易 429）
- 项目实现层仍是 `/api/workflows`；素材见 `/api/workflows/:id/assets`。无全局历史
- 浏览器只打相对路径 `/api`、`/uploads`。主机、端口、超管预填见仓库根目录 `.env`（模板 `.env.example`）。分域部署设 `VITE_API_BASE`
- 空项目 / 没有可出片节点时，「一键跑」直接说明原因，不创建 Run
- **下一个里程碑**：声音工作流（见 [细化方案.md](细化方案.md) §0 / §6）

## 两种启动方式

### A. Docker 一键（体验完整栈）

```bash
# 可选：复制公共环境变量
copy .env.example .env   # Windows
# cp .env.example .env  # macOS / Linux

docker compose up --build
```

- Web：nginx 静态站，端口见 `.env` 的 `WEB_PORT`（默认 5173）；`/api` 与 `/uploads` 已反代
- API 健康检查：`API_PORT`（默认 8000）`/api/health`（镜像内已装 **ffmpeg**；库为 Postgres）
- 改前端源码请用下方「本地开发」，不要指望 compose 里的 HMR

### B. 本地开发（改 UI / 热重载）

```bash
# 仓库根目录复制一份公共 env（前后端 / compose 共用）
copy .env.example .env

# 后端（默认 SQLite → backend/seemetvc.db）
cd backend && python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端（另开终端；Vite 按 .env 的 API_HOST/API_PORT 反代 /api）
cd frontend && npm install && npm run dev
```

- Web / API 端口、超管预填账号、CORS 都在仓库根目录 **`.env`**（模板：`.env.example`）
- **真 Seedance / Pavo**：超管登录 →「超管」→ 对 Seedance 渠道「改 Key」写入**火山方舟 ARK_API_KEY** →「启用」。Lite / 2.5 共用同一把 Key；`upstream_model` 可改为控制台推理接入点 `ep-xxx`；离线演示为「本地seedance模拟版」
- 有参考图 → 图生；无图 → 文生。2.5 默认 `generate_audio=true`；Lite 无原生音频
- **ffmpeg**：本地模拟、trim、拼接都需要；本机 PATH 有 ffmpeg，或在根目录 `.env` 设 `FFMPEG_PATH`
- Agnes 免费档易触发 429；演示全链路请优先用本地模拟或方舟
- 超管账号见 `.env` 的 `BOOTSTRAP_ADMIN_*`（开发构建会预填登录页；`DEV_PREFILL_LOGIN=false` 可关）

## 典型流程

1. 工作区新建项目（空白 = 单镜头快出，或选官方模板）→ 进入 `/workflow/:id`
2. 按槽位连线；出口类上游变化可自动再跑（同时只跑一个 Run，可取消）
3. 节点内看图/播视频；素材 Tab 可上传或复制到其他项目
4. 超管失败时可粘贴/上传模拟结果（前端填入，不计费）
5. 生成失败自动退款并丢掉该次 Run；成功则覆盖为当前成片，在工作区卡片 / 项目里回看
