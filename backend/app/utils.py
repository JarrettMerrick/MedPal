# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext

from app.config import settings
import warnings

# 北京时间时区
BEIJING_TZ = timezone(timedelta(hours=8))


def utc_now() -> datetime:
    """获取当前 UTC 时间（naive，不带时区信息，统一所有写入时间的时区基准）

    [改进] TZ1：全项目统一使用 UTC 作为写入时区，避免 UTC 与北京时间混用导致数据时间差 8 小时。
    返回 naive datetime（去掉 +00:00 时区后缀），使所有 datetime 列（无论 default 还是 server_default）
    在 Python 比较与 SQLite 存储时口径一致，规避 tz-aware 与 tz-naive 混用引发的 TypeError。
    前端会根据浏览器本地时区自动转换显示。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# [修复 2026-09-08] 业务日期口径辅助：巡检日期、预警"今天"等属于业务语义，
# 必须使用北京日期（而非 UTC 或服务器本地时区），否则北京时间 00:00-08:00 之间
# 提交的巡检会记成前一天、预警到期判定偏移一天。

def beijing_now() -> datetime:
    """当前北京时间（naive，不含时区后缀）"""
    return utc_now() + timedelta(hours=8)


def beijing_today() -> date:
    """当前北京日期（业务日期统一口径）"""
    return beijing_now().date()


def to_beijing_date(dt: datetime) -> date:
    """将 naive UTC datetime 转换为北京业务日期（用于 created_at 等存量字段）"""
    return (dt + timedelta(hours=8)).date()


def get_client_ip(request) -> Optional[str]:
    """从请求中获取真实客户端 IP。

    [改进 2026-09-09] 统一 IP 获取逻辑，兼容反向代理（如阿里云 Nginx）：
    优先读取 X-Forwarded-For 的第一个地址（真实客户端），其次 X-Real-IP，
    最后回退到直连 IP（request.client.host）。确保审计/系统日志里的 IP 为真实用户而非代理。
    """
    if request is None:
        return None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # 格式可能为 "client, proxy1, proxy2"，取最左侧真实客户端
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else None


# 保留 to_beijing 函数但添加警告
def to_beijing(dt: datetime) -> datetime:
    """将任意datetime转换为北京时间（已废弃，前端自动处理时区转换）"""
    import warnings
    warnings.warn("to_beijing() 已废弃，前端会自动根据浏览器时区转换显示", DeprecationWarning)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def generate_secure_password(length: int = 12) -> str:
    """生成随机强口令（用于新建账号 / 重置密码时的默认口令）。

    [修复/问题18] 原默认口令为固定弱口令 `123456`，任何人在用户首登之前都能猜到，
    与 `must_change_password` 兜底叠加后仍存在被抢先登录的窗口。
    改为每次调用随机生成（大小写字母 + 数字 + 符号），
    调用方必须把返回值回显给管理员以便转告使用者。
    """
    import secrets
    import string

    symbols = "!@#$%^&*"
    alphabet = string.ascii_letters + string.digits + symbols
    # 保证四类字符各至少一位，满足常见复杂度策略
    chars = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(symbols),
    ]
    chars += [secrets.choice(alphabet) for _ in range(max(0, length - len(chars)))]
    # 打乱顺序，避免字符类别出现在固定位置
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


# [调整 2026-09-10] 新建账号初始口令改为由「账号设置」中的模板生成，
# 相关常量与逻辑迁移至 app/services/system_config_service.py
# （DEFAULT_PASSWORD_TEMPLATE_FALLBACK）与 auth_service.get_default_password()。


# 「重置密码」场景的临时口令前缀（运维要求：可预期、便于口头/书面转告）
RESET_PASSWORD_PREFIX = "Rici@"


def generate_reset_password(employee_id: str) -> str:
    """生成「重置密码」场景下的临时口令：固定前缀 `Rici@` + 本人 6 位工号。

    运维要求：重置后的口令需可预期、便于转告使用者
    （原先的随机强口令包含大小写与符号，难以口头传达）。
    安全性由以下两点兜底：
      1) 重置后 `must_change_password=True`，使用者首次登录被强制修改；
      2) 重置会刷新 `password_changed_at`，此前签发的所有 token 立即失效。
    """
    return f"{RESET_PASSWORD_PREFIX}{(employee_id or '').strip()}"


def _to_utc_timestamp(dt: datetime) -> float:
    """将 naive UTC datetime 正确转换为 Unix 时间戳。

    [修复/问题7] `datetime.timestamp()` 对 naive datetime 会按「系统本地时区」解释，
    而全项目写入的 `password_changed_at` 均为 UTC naive（见 utc_now）。
    若服务器本地时区非 UTC（如 Asia/Shanghai），写入侧与读取侧两种口径会相差数小时，
    导致改密后旧 refresh token 在 /refresh 路径上仍被判定为有效，
    使「密码轮换即令旧令牌失效」的保护出现绕过窗口。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.refresh_token_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_access_token_with_password_info(data: dict, password_changed_at: Optional[datetime] = None, expires_delta: Optional[timedelta] = None) -> str:
    """创建包含密码修改时间的 access token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    if password_changed_at:
        to_encode.update({"pwd_changed_at": _to_utc_timestamp(password_changed_at)})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token_with_password_info(
    data: dict,
    password_changed_at: Optional[datetime] = None,
    remember_me: bool = False,
) -> str:
    """创建包含密码修改时间的 refresh token

    Args:
        remember_me: 勾选"记住我"时使用 3 天有效期，否则使用默认 60 分钟。
            该标志同时写入令牌声明，供刷新轮换时按同一策略续期（滑动会话）。

    说明：采用「滑动会话」——每次刷新都按 remember_me 策略续满有效期，
    活跃用户不会因到期被强制登出；安全性由 HttpOnly Cookie + 每次轮换
    （旧令牌立即入黑名单）共同保障。
    """
    to_encode = data.copy()
    if remember_me:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.remember_me_refresh_token_expire_days)
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.refresh_token_expire_minutes)
    to_encode.update({"exp": expire, "remember_me": bool(remember_me)})
    if password_changed_at:
        to_encode.update({"pwd_changed_at": _to_utc_timestamp(password_changed_at)})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except jwt.PyJWTError:
        return None


import hmac
import hashlib
import time as _time
import base64


def create_file_access_token(employee_id: str, expires_in: int = 3600) -> str:
    """生成短期文件访问令牌，用于静态文件 URL 的 ?ftoken= 参数。

    与 JWT 不同，该令牌仅含工号与过期时间并经 HMAC 签名，
    泄露危害有限（短期且无法用于 API 调用），用于替代把完整 JWT 放进 URL。
    """
    exp = int(_time.time()) + expires_in
    payload = f"{employee_id}:{exp}"
    sig = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def verify_file_access_token(token: str) -> bool:
    """校验文件访问令牌有效性（格式/签名/过期）"""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) != 3:
            return False
        employee_id, exp, sig = parts
        if _time.time() > int(exp):
            return False
        payload = f"{employee_id}:{exp}"
        expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


def decode_file_access_token(token: str) -> str | None:
    """从文件访问令牌中解析出工号（用于下载等场景定位用户）"""
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        employee_id, exp, sig = parts
        if _time.time() > int(exp):
            return None
        return employee_id
    except Exception:
        return None
