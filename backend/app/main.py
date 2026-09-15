# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

import logging
import logging.handlers
import os
import sys
import uuid
import time as _time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Scope, Receive, Send

from app.config import settings, PROJECT_ROOT, DATA_ROOT
from app.routers import auth, staff, users, departments, audit, roles, data_io, uploads, staff_cards, notifications, messages, chunk_upload, system_config, regulations, user_department_scope, signages, floor_plans, signage_alerts, signage_export, signage_batch, campus, signage_categories, suppliers, signage_inspections, signage_repairs, branding, registration, account_settings, staff_change, feature_settings, notification_settings
# [新增 2026-09-14] 功能开关的接口层依赖（见下方 include_router 的 dependencies 参数）
from app.dependencies import require_feature_enabled
from app.utils import get_client_ip

# ── 运行日志（应用内部日志） ──────────────────────────────────────────
log_handlers = [logging.StreamHandler(sys.stdout)]

# [改进] 使用 DATA_ROOT 确保日志目录指向数据根目录的 data/logs，与 backend 完全隔离
log_file = os.path.join(str(DATA_ROOT), "logs", "hospital.log")
# [改进] 运行日志保留天数：当天 + (RETENTION_DAYS - 1) 个历史文件
LOG_RETENTION_DAYS = 7
try:
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file, when="midnight", interval=1,
        backupCount=LOG_RETENTION_DAYS - 1, encoding="utf-8", delay=True
    )
    log_handlers.append(file_handler)
except (PermissionError, OSError) as e:
    print(f"警告：无法创建日志文件 {log_file}，将只使用控制台输出: {e}")

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(name)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=log_handlers
)

# 设置日志时间格式为北京时间
_original_converter = logging.Formatter.converter
def beijing_converter(*args):
    from datetime import datetime, timezone, timedelta
    dt = datetime.now(timezone(timedelta(hours=8)))
    return dt.timetuple()
logging.Formatter.converter = beijing_converter
logger = logging.getLogger("hospital")

# ── 访问日志（每条 HTTP 请求一条记录） ───────────────────────────────
access_logger = logging.getLogger("access")
access_logger.propagate = False
access_fh = logging.handlers.TimedRotatingFileHandler(
    os.path.join(str(DATA_ROOT), "logs", "access.log"),
    when="midnight", interval=1,
    backupCount=LOG_RETENTION_DAYS - 1, encoding="utf-8", delay=True
)
access_fh.setFormatter(logging.Formatter(
    '%(message)s'  # 中间件已拼好完整格式，不再重复加时间
))
access_logger.addHandler(access_fh)


# ── URL → 业务操作分类 ──────────────────────────────────────────────
# [改进] 通过路径前缀将 HTTP 请求归类为业务操作，方便日志阅读和后续审计统计。
# 映射规则：前缀 → 操作标签；按长度降序匹配（最具体优先）。
OPERATION_MAP = [
    ("/api/auth/login",              "登录"),
    ("/api/auth/logout",             "登出"),
    ("/api/auth/refresh",            "刷新令牌"),
    ("/api/auth/change-password",    "修改密码"),
    ("/api/auth/me",                 "获取当前用户"),
    ("/api/auth/profile",            "获取当前用户"),
    ("/api/staff/",                  "人员管理"),
    ("/api/users/",                  "用户管理"),
    ("/api/departments/",            "科室管理"),
    ("/api/roles/",                  "角色管理"),
    ("/api/audit/",                  "审计日志"),
    ("/api/uploads/",                "文件上传"),
    ("/api/staff-cards/",            "工牌管理"),
    ("/api/notifications/",          "通知公告"),
    ("/api/chunk-upload/",           "分片上传"),
    ("/api/system-config/",          "系统配置"),
    ("/api/public/branding",         "品牌信息"),
    ("/api/branding/",               "品牌设置"),
    ("/api/public/registration",     "自助注册"),
    ("/api/registration-requests",   "账号审核"),
    ("/api/account-settings",        "账号设置"),
    # [新增 2026-09-14] 功能开关（公开特性读取 + 设置页汇总）
    ("/api/public/features",         "功能开关"),
    ("/api/feature-settings",        "功能开关"),
    ("/api/regulations/",            "制度管理"),
    ("/api/signages/",               "标识管理"),
    ("/api/floor-plans/",            "平面图管理"),
    ("/api/signage-alerts/",         "标识预警"),
    ("/api/signage-export/",         "标识导出"),
    ("/api/signage-batch/",          "标识批量操作"),
    ("/api/user-department-scope/",  "用户科室范围"),
    ("/api/data-io/",                "数据导入导出"),
    ("/api/health",                  "健康检查"),
]


def classify_operation(path: str) -> str:
    """根据请求路径返回业务操作分类标签，未知路径返回"其他" """
    for prefix, label in OPERATION_MAP:
        if path.startswith(prefix):
            return label
    return "其他"


# ── HTTP 请求日志中间件 ──────────────────────────────────────────────
class RequestLogMiddleware:
    """
    记录每条 HTTP 请求的完整生命周期：
    时间 · 用户 · 方法 · 路径 · 分类 · 状态码 · 耗时 · 错误原因

    日志级别：2xx/3xx → INFO | 4xx → WARNING | 5xx → ERROR
    慢查询（> 1s）自动追加 [SLOW] 标记
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:8]
        start = _time.time()
        method = scope.get("method", "?")
        path = scope.get("path", "?")

        # 尝试从请求头中提取用户信息（由 enforce_password_change 前置中间件已解码）
        # 这里不重复解码 JWT，只读取中间件可能设置的 request.state
        # 因 ASGI 层面无 request.state，后续在 send 中通过 headers 收集
        # 实际用户信息由 enforce_password_change 在前面处理，此处仅简单记录

        status_code = [0]
        error_reason = [""]
        error_exc = [None]
        user_info = [""]

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
                # 尝试从响应头中获取用户标识（enforce_password_change 可注入）
                for name, value in message.get("headers", []):
                    if name == b"x-user-id":
                        user_info[0] = value.decode("utf-8", errors="replace")
                        break
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except HTTPException as exc:
            status_code[0] = exc.status_code
            error_reason[0] = str(exc.detail)
            raise
        except Exception as exc:
            status_code[0] = 500
            error_reason[0] = f"{type(exc).__name__}: {exc}"
            error_exc[0] = exc
            raise
        finally:
            duration = _time.time() - start
            op_label = classify_operation(path)
            sc = status_code[0]
            uid = user_info[0] or "-"
            err = f" | ERROR={error_reason[0]}" if error_reason[0] else ""
            slow = " | SLOW" if duration > 1.0 else ""
            level = logging.WARNING if 400 <= sc < 500 else (logging.ERROR if sc >= 500 else logging.INFO)

            parts = [
                f"[{request_id}]",
                f"[{uid}]",
                f"{method:7s}",
                f"{path:50s}",
                f"({op_label})",
                f"→ {sc}",
                f"in {duration*1000:.0f}ms{slow}",
                err,
            ]
            line = " ".join(p for p in parts if p)

            # [改进 2026-09-09] 5xx 错误附带完整堆栈（exc_info），便于事后定位根因
            if sc >= 500 and error_exc[0] is not None:
                access_logger.error(line, exc_info=error_exc[0])
                logger.error(line, exc_info=error_exc[0])
            else:
                access_logger.log(level, line)
                # 同时输出到运行日志，用于实时跟踪
                logger.log(level, line)


# ── 应用实例 ─────────────────────────────────────────────────────────
app = FastAPI(title=settings.app_name, version="1.1.1")

# 中间件注册顺序：后注册的在外层（先执行）。RequestLogMiddleware 放在最外以捕获所有请求。
app.add_middleware(RequestLogMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With"],
)


def _can_access_upload_path(db, user, rel_path: str) -> bool:
    """判断用户是否有权访问该具体上传文件（对应审计问题 2）。

    背景：/uploads 目录整体挂载为静态文件服务，原中间件只校验「令牌有效且未登出」，
    不校验请求者是否有权查看该文件，导致任意已认证用户只要知道 URL 就能
    跨科室下载他人的人脸照 / 侧面照 / 工牌照等 PHI。

    实现：上传文件命名规范为 {工号}_{类型}_{时间戳}_{随机}.ext，
    因此可从文件名首段解析出归属工号。若能解析出归属人员，
    则按该人员科室走与 staff/users 路由一致的数据范围校验；
    无法归属时（制度附件、标识照片、平面图等）维持原「已认证即可访问」的行为。
    """
    import os as _os

    fname = _os.path.basename(rel_path or "")
    stem = _os.path.splitext(fname)[0]
    if not stem:
        return True
    emp_id = stem.split("_")[0]
    if not emp_id:
        return True

    # 访问本人自己的文件始终允许
    if getattr(user, "employee_id", None) == emp_id:
        return True

    from app.models.staff import Staff
    staff = db.query(Staff).filter(Staff.employee_id == emp_id).first()
    if staff is None:
        # 非人员照片（制度/标识/平面图等），无法按人员归属判定 → 维持原行为
        return True

    try:
        from app.dependencies import has_department_access
        return has_department_access(user, staff.department, db)
    except Exception as _e:
        logger.warning(f"上传文件归属校验异常，按放行处理: {type(_e).__name__}: {_e}")
        return True


# 首次登录强制改密中间件（防止绕过前端直接调用API）
@app.middleware("http")
async def enforce_password_change(request, call_next):
    """如果 must_change_password 为 True，仅允许改密和公共接口"""
    from fastapi.responses import JSONResponse
    from app.utils import decode_token

    path = request.url.path
    # 无需校验的公开端点
    PUBLIC_PATHS = {
        "/api/auth/login", "/api/auth/refresh", "/api/auth/logout",
        "/api/health", "/", "/docs", "/redoc", "/openapi.json",
        # [新增 2026-09-10] 品牌公开只读接口：登录页与强制改密用户均需读取
        "/api/public/branding",
        # [新增 2026-09-10] 登录页自助注册：选项读取与申请提交均免登录
        "/api/public/registration/options",
        "/api/public/registration",
        # [新增 2026-09-14] 功能开关公开读取：登录页/首屏即需据此决定入口显隐
        "/api/public/features",
    }
    if path in PUBLIC_PATHS:
        return await call_next(request)

    # 上传目录（含人员照片/卡片/科室合照等 PHI）受保护：
    # 必须携带有效 Bearer 令牌或短期文件访问令牌（?ftoken=），杜绝未登录下载
    if path.startswith("/uploads"):
        rel_path = path[len("/uploads/"):] if path.startswith("/uploads/") else ""
        if "/_chunks/" in path or path.endswith("/_chunks"):
            return JSONResponse(status_code=404, content={"detail": "资源不存在"})

        from app.database import SessionLocal
        from app.models.user import User

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            from app.utils import decode_token
            from app.services.auth_service import is_token_blacklisted
            token = auth_header[7:]
            payload = decode_token(token)
            if payload:
                _db = SessionLocal()
                try:
                    employee_id = payload.get("sub")
                    user = (
                        _db.query(User).filter(User.employee_id == employee_id).first()
                        if employee_id else None
                    )
                    # [修复/问题13] 与 get_current_user 口径保持一致：
                    # 原实现只验签 + 查黑名单，不校验 is_active / must_change_password，
                    # 已被禁用或强制改密但令牌未过期的账号仍可下载 PHI 文件。
                    if user is None or not user.is_active or user.must_change_password:
                        return JSONResponse(status_code=403, content={"detail": "未授权访问文件"})
                    # [改进/F4] 登出黑名单校验：令已登出/被踢下线的 token 立即失效
                    if is_token_blacklisted(_db, token):
                        return JSONResponse(status_code=403, content={"detail": "未授权访问文件"})
                    # [修复/问题2] 按文件归属做数据范围校验，防止跨科室越权读取
                    if not _can_access_upload_path(_db, user, rel_path):
                        return JSONResponse(status_code=403, content={"detail": "无权访问该文件"})
                finally:
                    _db.close()
                return await call_next(request)

        ftoken = request.query_params.get("ftoken")
        if ftoken:
            from app.utils import verify_file_access_token, decode_file_access_token
            if verify_file_access_token(ftoken):
                _db = SessionLocal()
                try:
                    emp_id = decode_file_access_token(ftoken)
                    user = (
                        _db.query(User).filter(User.employee_id == emp_id).first()
                        if emp_id else None
                    )
                    # [修复/问题13] ftoken 路径同样校验账号状态
                    if user is None or not user.is_active:
                        return JSONResponse(status_code=403, content={"detail": "未授权访问文件"})
                    # [修复/问题2] 与 Bearer 路径一致的文件归属校验
                    if not _can_access_upload_path(_db, user, rel_path):
                        return JSONResponse(status_code=403, content={"detail": "无权访问该文件"})
                finally:
                    _db.close()
                return await call_next(request)
        return JSONResponse(status_code=403, content={"detail": "未授权访问文件"})

    # [新增 2026-09-10] 公开品牌静态资源（/public 下的 Logo）：无需鉴权，直接放行
    if path.startswith("/public"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        payload = decode_token(token)
        if payload:
            employee_id = payload.get("sub")
            if employee_id:
                from app.database import SessionLocal
                from app.models.user import User
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.employee_id == employee_id).first()
                    if user and user.must_change_password:
                        # 仅允许改密接口和获取自身信息
                        if path not in ("/api/auth/change-password", "/api/auth/me", "/api/auth/profile"):
                            return JSONResponse(
                                status_code=403,
                                content={"detail": "首次登录必须修改密码后，才能使用其他功能"}
                            )
                finally:
                    db.close()

    return await call_next(request)


# 注册路由
#
# [新增 2026-09-14] 功能开关（系统设置 → 功能开关）的接口层强制：
# 功能被管理员关闭后，该模块**所有**接口统一返回 403，避免仅靠前端隐藏菜单而被绕过。
# 用 include_router(dependencies=...) 集中声明而非逐个接口挂载 —— 新增接口自动受控、不会漏挂。
_FEATURE_MESSAGES_DEPS = [Depends(require_feature_enabled("messages"))]
_FEATURE_SIGNAGE_DEPS = [Depends(require_feature_enabled("signage"))]
# [新增 2026-09-14] 制度牌（制度管理）
_FEATURE_REGULATION_DEPS = [Depends(require_feature_enabled("regulation"))]

app.include_router(auth.router)
app.include_router(staff.router)
app.include_router(users.router)
app.include_router(departments.router)
app.include_router(audit.router)
app.include_router(roles.router)
app.include_router(data_io.router)
app.include_router(uploads.router)
app.include_router(staff_cards.router)
app.include_router(notifications.router)
# [新增 2026-09-11] 站内信（统一消息中心：系统通知 + 群发/私发 + 标注）
# [调整 2026-09-14] 受功能开关 feature_messages_enabled 控制
app.include_router(messages.router, dependencies=_FEATURE_MESSAGES_DEPS)
app.include_router(chunk_upload.router)
app.include_router(system_config.router)
# [新增 2026-09-10] 品牌设置路由（公开品牌读取 + Logo 上传/重置）
app.include_router(branding.router)
# [新增 2026-09-10] 账号设置汇总 + 自助注册/审核
app.include_router(account_settings.router)
app.include_router(registration.router)
# [新增 2026-09-11] 人员信息变更审核（立即生效 + 追认/回滚；站内信「去审核」跳转）
app.include_router(staff_change.router)
# [调整 2026-09-14] 制度牌（制度管理）受功能开关 feature_regulation_enabled 控制
app.include_router(regulations.router, dependencies=_FEATURE_REGULATION_DEPS)
# [新增 2026-09-14] 功能开关：公开特性读取 + 设置页汇总（自身不受开关控制）
app.include_router(feature_settings.router)
# [新增 2026-09-15] 通知设置（系统设置 → 通知设置：事件级开关 / 文案模板 / 收件人规则）
# 自身不受功能开关控制；权限为独立权限点 feature.notification（「系统设置」分类下的「通知设置」项）
app.include_router(notification_settings.router)
# ── 以下均属「标识平面」或「标识设置」，统一受 feature_signage_enabled 单一开关控制 ──
# （对应需求：将标识平面与标识设置合并为单一开关）
app.include_router(signages.router, dependencies=_FEATURE_SIGNAGE_DEPS)
app.include_router(floor_plans.router, dependencies=_FEATURE_SIGNAGE_DEPS)
app.include_router(signage_alerts.router, dependencies=_FEATURE_SIGNAGE_DEPS)
app.include_router(signage_export.router, dependencies=_FEATURE_SIGNAGE_DEPS)
app.include_router(signage_batch.router, dependencies=_FEATURE_SIGNAGE_DEPS)
# 注意：user_department_scope 属「用户/角色」范畴（角色管理的数据范围配置），不随标识开关关闭
app.include_router(user_department_scope.router)
# [修复 2026-09-03] 注册院区管理路由
app.include_router(campus.router, dependencies=_FEATURE_SIGNAGE_DEPS)
# [修复 2026-09-04] 注册标识分类和供应商路由
app.include_router(signage_categories.router, dependencies=_FEATURE_SIGNAGE_DEPS)
app.include_router(suppliers.router, dependencies=_FEATURE_SIGNAGE_DEPS)
# [新增 2026-09-05] 注册标识巡检路由（移动端巡检打卡与历史查询）
app.include_router(signage_inspections.router, dependencies=_FEATURE_SIGNAGE_DEPS)
# [新增 2026-09-09] 标识维修记录（查看全部维修记录并按条件导出，权限 signage.repair）
app.include_router(signage_repairs.router, dependencies=_FEATURE_SIGNAGE_DEPS)


# ── 全局未处理异常处理器 ────────────────────────────────────────────
# [改进 2026-09-09] 将未捕获的服务端异常（5xx）归集到系统日志（SystemLog 错误分类），
# 保证前端「数据管理-系统日志」可查询到服务端异常留痕；HTTPException 仍走默认处理。
from app.database import SessionLocal as _AuditSessionLocal
from app.models.system_log import SystemLog as _SystemLog


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    logger.error(f"未处理异常: {request.method} {request.url.path}", exc_info=exc)
    _db = None
    try:
        _db = _AuditSessionLocal()
        _ip = get_client_ip(request)
        _db.add(_SystemLog(
            level="ERROR",
            category="error",
            operator=None,
            content=f"未处理异常: {request.method} {request.url.path}: {type(exc).__name__}: {exc}",
            ip_address=_ip,
            details=None,
        ))
        _db.commit()
    except Exception:
        pass
    finally:
        # [修复/问题8] 原实现在 finally 里直接 _db.close()；若 _AuditSessionLocal()
        # 自身抛异常，_db 从未绑定，此处会抛 NameError 使异常处理器崩溃，
        # 导致本应返回的统一 JSON 500 响应根本发不出去，且掩盖真实异常。
        if _db is not None:
            try:
                _db.close()
            except Exception:
                pass
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误"})


@app.get("/")
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/api/health")


@app.get("/api/health")
def health_check():
    # [调整 2026-09-10] 健康检查文案改为引用 settings.app_name，避免品牌名硬编码
    return {"status": "ok", "message": f"{settings.app_name}运行中"}


# [改进] 使用 DATA_ROOT 确保上传目录指向数据根目录的 data/uploads，与 backend 完全隔离
uploads_dir = os.path.join(str(DATA_ROOT), "uploads")
os.makedirs(uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")

# [新增 2026-09-10] 公开品牌资源目录：data/public → /public
# 登录页（未认证）需加载单位 Logo，不能复用受鉴权保护的 /uploads。
# 该目录仅存放由品牌接口生成的文件（文件名服务端生成），StaticFiles 不列目录。
from app.services.branding_service import ensure_brand_dir as _ensure_brand_dir
public_dir = os.path.join(str(DATA_ROOT), "public")
_ensure_brand_dir()
app.mount("/public", StaticFiles(directory=public_dir), name="public")








@app.on_event("startup")
def startup():
    """应用启动时初始化数据库"""
    try:
        from app.database import engine, SessionLocal, Base, init_database
        from app.services.role_initializer import init_default_roles
        from app.services.system_config_service import init_default_configs
        from app.services.admin_initializer import init_default_admin
        from app.services.backup_service import start_scheduler

        Base.metadata.create_all(bind=engine)
        # [修复 2026-08-28] 通用自动补列：扫描所有模型字段，与已有库表比对，
        # 缺失的列自动 ALTER TABLE ADD（幂等、仅新增不删改，绝不破坏存量数据）。
        # 这样以后任何版本只要在模型新增字段，部署重启即自动补齐，无需手工登记补列清单。
        from sqlalchemy import inspect as sa_inspect, text as sa_text
        # 确保全部模型已注册到 Base.metadata（app.models.__init__ 聚合了所有模型）
        from app import models as _all_models  # noqa: F401
        insp = sa_inspect(engine)
        _SQLITE_TYPE_MAP = {
            "VARCHAR": "VARCHAR(255)",
            "CHAR": "VARCHAR(255)",
            "TEXT": "TEXT",
            "INTEGER": "INTEGER",
            "BIGINT": "INTEGER",
            "SMALLINT": "INTEGER",
            "BOOLEAN": "BOOLEAN",
            "FLOAT": "FLOAT",
            "NUMERIC": "FLOAT",
            "DATETIME": "DATETIME",
            "DATE": "DATE",
            "JSON": "TEXT",
        }

        def _map_type(col):
            # 优先使用 server_default / 模型声明的类型字符串
            raw = str(col.type)
            base = raw.split("(")[0].upper()
            return _SQLITE_TYPE_MAP.get(base, "VARCHAR(255)")

        def _render_default(col):
            """[修复 2026-09-05] 将模型列默认值渲染为 SQL 字面量，供 ALTER ADD COLUMN 的 DEFAULT 子句使用。"""
            d = col.default
            if d is not None and getattr(d, "arg", None) is not None:
                val = d.arg
                if callable(val):
                    return None
                if isinstance(val, bool):
                    return "1" if val else "0"
                if isinstance(val, (int, float)):
                    return str(val)
                return "'" + str(val).replace("'", "''") + "'"
            sd = col.server_default
            if sd is not None and getattr(sd, "arg", None) is not None:
                return str(sd.arg)
            return None

        for table_name, table in Base.metadata.tables.items():
            if not insp.has_table(table_name):
                continue  # 新表由 create_all 已创建
            existing_cols = {c["name"] for c in insp.get_columns(table_name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue  # 列已存在则跳过（幂等）
                sql_type = _map_type(col)
                # SQLite 仅支持 ADD COLUMN，且对 NOT NULL 无默认值的列在表非空时会失败。
                # [修复 2026-09-05] 模型列带默认值时一并写入 DEFAULT 子句，
                # 使 NOT NULL 列也能在已有数据的表上成功添加（如 floor_plans.category）。
                not_null = ""
                default_clause = ""
                if not col.nullable and (col.default is not None or col.server_default is not None):
                    not_null = " NOT NULL"
                    dv = _render_default(col)
                    if dv is not None:
                        default_clause = f" DEFAULT {dv}"
                try:
                    with engine.connect() as mig_conn:
                        mig_conn.execute(sa_text(
                            f"ALTER TABLE {table_name} ADD COLUMN {col.name} {sql_type}{not_null}{default_clause}"
                        ))
                        mig_conn.commit()
                    logger.info(f"自动迁移: {table_name} 表已添加 {col.name} 列 ({sql_type}{not_null}{default_clause})")
                except Exception as mig_err:
                    logger.warning(
                        f"自动迁移跳过: {table_name}.{col.name} 添加失败（可能该列需默认值或表非空），"
                        f"请人工处理。错误: {mig_err}"
                    )
            # [修复 2026-09-05] 遗留列诊断：模型中已删除、但旧库仍存在的列，
            # 若带 NOT NULL 且无默认值，会使该表 INSERT 直接失败（表现为 500）。
            # 此处只告警不做破坏性删除，由人工确认后再 DROP COLUMN。
            model_cols = {c.name for c in table.columns}
            for db_col in insp.get_columns(table_name):
                if db_col["name"] in model_cols:
                    continue
                if db_col.get("nullable") or db_col.get("default") is not None:
                    continue
                logger.error(
                    f"自动迁移告警: {table_name}.{db_col['name']} 是模型已删除的遗留列，"
                    f"但库中仍为 NOT NULL 且无默认值，将导致该表 INSERT 失败（500）。"
                    f"请执行 ALTER TABLE {table_name} DROP COLUMN {db_col['name']} 后重启。"
                )
        # [改进] 使用 init_database 替代 set_sqlite_pragma，
        # PRAGMA 通过 connect 事件监听器自动应用到所有连接
        init_database()
        db = SessionLocal()
        try:
            init_default_roles(db)
            init_default_configs(db)
            # [新增 2026-09-10] 确保系统始终存在至少一个超级管理员：
            # 首次部署自动创建 admin / MedPal@admin（首登强制改密）；
            # 已存在超级管理员则跳过，不改动任何既有账号。
            init_default_admin(db)
            db.commit()  # 提交角色/权限等初始数据到数据库
            # [调整 2026-09-15] 按需求**取消**「旧通知并入站内信」的一次性迁移：
            # 历史 notifications 表数据保持原样（不再写入 messages），启动时也不再执行迁移。
            # （迁移函数仍保留在 services/message_service.migrate_notifications_to_messages，
            #   如后续确需导入历史通知，可在运维时手动调用。）
            # [新增 2026-09-11] 人员信息变更审核：启动时扫描一次超时未审的变更
            # （24h 提醒审核人 / 72h 升级超管；日常由列表接口惰性触发）
            try:
                from app.services.staff_change_service import sweep_overdue
                result = sweep_overdue(db)
                if result.get("reminded") or result.get("escalated"):
                    logger.info(
                        f"变更审核超时扫描：提醒 {result['reminded']} 条，"
                        f"升级 {result['escalated']} 条"
                    )
            except Exception as sweep_err:
                db.rollback()
                logger.warning(f"变更审核超时扫描失败（不影响启动）: {sweep_err}")
        finally:
            db.close()

        # 启动定时备份
        start_scheduler()

        # [改进/1.0.9] 启动时清理上次运行残留的临时导出文件
        # 正常情况下 BackgroundTasks 会在响应发送后删除临时文件，
        # 但服务器崩溃/重启时可能导致残留，此处统一清理
        try:
            from app.routers.data_io import cleanup_stale_temp_files
            cleanup_stale_temp_files()
        except Exception as cleanup_err:
            logger.warning(f"启动时清理残留临时文件失败（非致命）: {cleanup_err}")

        logger.info("应用启动完成")
    except Exception as e:
        logger.error(f"应用启动失败: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
def shutdown():
    from app.services.backup_service import stop_scheduler
    stop_scheduler()
    logger.info("应用已关闭")
