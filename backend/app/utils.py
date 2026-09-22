# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
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


def beijing_date_start_utc(v, end_of_day: bool = False) -> datetime:
    """把「北京业务日期」转换为对应 UTC 边界 datetime（日期范围筛选唯一口径）。

    北京 00:00 = 前一日 16:00 UTC；end_of_day=True 时取「次日 00:00（北京）」，
    配合 `<` 使用即可覆盖 end 当天全天。

    [统一时间口径] 原先多处直接用 datetime.fromisoformat("2026-09-16")（按 UTC 零点解释），
    导致按北京日期筛选时 00:00-08:00 的记录被漏筛（或边界多筛 8 小时），
    与界面显示（北京时间）不一致。
    """
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    else:
        d = datetime.strptime(str(v).strip(), "%Y-%m-%d").date()
    if end_of_day:
        d = d + timedelta(days=1)
    return datetime(d.year, d.month, d.day) - timedelta(hours=8)


def to_iso_utc(dt: Optional[datetime]) -> Optional[str]:
    """将 naive UTC datetime 序列化为带 Z 的 ISO-8601 UTC 字符串（API 输出唯一口径）。

    [统一时间口径] 原先各接口混用 str(dt) / dt.isoformat()，产物都**不含时区标记**
    （如 "2026-09-16 07:27:03" / "2026-09-16T07:27:03"）。JS 的 new Date() 对无时区
    标记的字符串按**本地时区**解析，于是 UTC 值被原样显示，比北京时间少 8 小时
    （如标识维修时间显示 07:27:03 而实际为 15:27:03）。
    统一输出 "2026-09-16T07:27:03Z" 后，任何标准解析器都会正确地按 UTC 转本地时区。
    """
    if dt is None:
        return None
    # 兼容误传入的 aware datetime：先折算 UTC 再去掉 tz，保证输出恒为 UTC
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_utc(v) -> Optional[datetime]:
    """解析时间字符串为 naive UTC datetime（全项目唯一的反向解析口径）。

    兼容带 Z、带 ±HH:MM 偏移、无时区标记（按 UTC 解释，与存储口径一致）、
    以及空格分隔（"2026-09-16 07:27:03"）等历史写法。
    """
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00").replace("z", "+00:00")
    # 兼容空格分隔的日期时间
    if len(s) > 10 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def to_beijing_str(dt: Optional[datetime], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """将 naive UTC datetime 格式化为**北京时间**可读字符串。

    适用场景：Excel/CSV 导出、ZIP 内清单、下载文件名、备份清单等**离线产物**。
    这类内容不经过前端时区转换、直接呈现给人看，因此必须在此显式转成北京时间；
    API 返回给前端的字段请改用 to_iso_utc，由前端按浏览器时区统一转换。
    """
    if dt is None:
        return ""
    return (dt + timedelta(hours=8)).strftime(fmt)


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
# [调整 2026-09-16] 「重置密码」场景不再使用独立的硬编码规则（原「固定前缀 + 工号」），
# 统一改由 auth_service.get_default_password() 渲染账户设置模板，
# 保证重置密码与账户规则一致，故本文件不再保留重置口令相关常量/函数。


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


def is_token_stale_after_password_change(
    token_pwd_changed_at,
    user_pwd_changed_at: Optional[datetime],
) -> bool:
    """判断 token 是否因「密码已被修改/重置」而失效（所有校验点统一口径）。

    [修复] 原实现在 get_current_user / /refresh 各写了一份比对，且存在两个缺陷：
      1) 漏判：写成 `if 内嵌值 and 用户值`，当 token 未内嵌 pwd_changed_at
         （签发时该账号还没有改密记录，值为 None）时整体跳过校验 ——
         此后无论改密还是管理员重置，该 token 都被判为有效，且 /refresh 还会用
         新的 password_changed_at 重新签发令牌，等于被窃会话可被"洗白"继续使用，
         使「重置密码找回账号」失效；
      2) 时区偏移：把存储的 UTC naive 时间当作北京时间再转 UTC（整体 -8 小时），
         导致"上次改密在 8 小时内"时旧 token 不被失效（8 小时吊销盲区）。
         现已统一按 UTC 比较，见 _to_utc_timestamp。

    规则：
      - 用户从未改过密码（user 值为 None）→ 无从比较，不判失效；
      - 用户有改密记录，但 token 未内嵌改密时间 → 说明签发于首次改密之前 → 失效；
      - 两者都有 → 内嵌时间早于当前改密时间即失效（留 1 秒容差规避浮点精度误差）。
    """
    if not user_pwd_changed_at:
        return False
    if token_pwd_changed_at is None:
        return True
    try:
        token_ts = float(token_pwd_changed_at)
    except (TypeError, ValueError):
        # 声明值非法（被篡改/格式错误）→ 按失效处理，不放行
        return True
    return token_ts < _to_utc_timestamp(user_pwd_changed_at) - 1


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
    """从文件访问令牌中解析出工号（用于下载等场景定位用户）。

    必须先在内部校验 HMAC 签名再返回工号，否则攻击者可自行构造
    `employee_id:exp:任意sig` 的 base64 串冒充任意用户（身份伪造漏洞）。
    原实现漏校验签名，已在导出包下载接口被直接利用，导致可绕过鉴权下载包。
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        employee_id, exp, sig = parts
        if _time.time() > int(exp):
            return None
        payload = f"{employee_id}:{exp}"
        expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        return employee_id
    except Exception:
        return None
