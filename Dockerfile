# ============================================================================
# MedPal 医院宣传信息管理系统 —— 单镜像构建（前端构建 + 后端运行）
# ----------------------------------------------------------------------------
# 构建：docker build -t medpal:1.2.6 .
# 运行：见 README「Docker 部署」（必须注入 SECRET_KEY，并挂载 /app/data）
#
# 镜像内布局：
#   /app/backend/       后端源码与启动入口 run.py
#   /app/frontend/dist  前端构建产物，由后端同源托管（无需额外部署 Nginx）
#   /app/data           数据根目录（数据库 / 上传 / 备份 / 日志），运行时挂载卷
#
# 说明：前端与后端同处一个镜像，同源提供页面与接口，因此不涉及跨域，
#       对外只需暴露 5000 一个端口。
#
# 国内网络环境拉取依赖较慢时，可按下方注释改用国内镜像源。
# ============================================================================

# ---------- 阶段 1：构建前端静态资源 ----------
FROM node:20-alpine AS frontend-builder
WORKDIR /build/frontend

# 先只拷贝依赖清单：源码变更时可复用本层缓存，无需每次构建都重装依赖
COPY frontend/package.json frontend/package-lock.json ./
# 国内加速：把下面一行换成
#   RUN npm ci --no-audit --no-fund --registry=https://registry.npmmirror.com
RUN npm ci --no-audit --no-fund

# 拷贝前端源码并构建（vite 默认输出 dist/）
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端运行环境 ----------
FROM python:3.11-slim

# 不生成 .pyc；日志实时输出到 stdout，便于 docker logs 观察
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 后端依赖单独成层：仅 requirements.txt 变化时才重新安装
COPY requirements.txt ./
# 国内加速：把下面一行换成
#   RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -r requirements.txt

# 后端代码：保持与源码一致的 backend/ 目录结构，config.py 据此推算数据根目录
COPY backend/ ./backend/

# 前端构建产物：由后端在根路径 / 下托管（含 BrowserRouter 子路由回退）
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# 数据目录（数据库 / 上传附件 / 备份 / 日志）；
# 运行时必须挂载卷，否则删除容器即丢数据 —— docker-compose 已挂载 ./data → /app/data
RUN mkdir -p /app/data

EXPOSE 5000

# 健康检查：调用免认证的 /api/health，避免仅凭进程存活造成误判
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=3)"

# 启动入口：run.py 固定监听 0.0.0.0:5000，生产模式不启用热重载
WORKDIR /app/backend
CMD ["python", "run.py"]
