# Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.token_blacklist import TokenBlacklist
# [修复/问题14] 限流计数持久化模型（替代进程内存字典）
from app.models.rate_limit import RateLimitRecord
from app.models.user import User
from app.utils import (
    utc_now, decode_token, hash_password, verify_password,
    generate_reset_password,
)

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 60


# ---- 登录 / 刷新限流（基于来源 IP，锁定攻击者而非受害者，防止账号 DoS）----
# [修复/问题14]
# 旧实现把失败计数放在进程内存字典 `_IP_FAIL`，存在两点缺陷：
#   1. 多 worker / 多实例部署时每个进程各持一份计数，攻击者把请求分散到
#      不同进程即可绕过限流；
#   2. 进程重启计数即清零。
# 改为持久化到数据库后，所有进程共享同一份状态，重启亦不失效。
# 同时收紧阈值（登录 20 次/60s → 10 次/60s，封禁 300s → 600s），
# 并为 /refresh 增加了此前完全缺失的频控。
_RATE_POLICY: dict[str, dict[str, int]] = {
    "login":   {"limit": 10, "window": 60, "block": 600},
    "refresh": {"limit": 60, "window": 60, "block": 300},
    # [新增 2026-09-10] 登录页自助注册：每 IP 每小时最多 5 次提交，超限封禁 1 小时
    "registration": {"limit": 5, "window": 3600, "block": 3600},
}
_DEFAULT_POLICY = {"limit": 20, "window": 60, "block": 300}


def _policy(action: str) -> dict[str, int]:
    return _RATE_POLICY.get(action, _DEFAULT_POLICY)


def _get_rate_record(db: Session, client_ip: str, action: str) -> RateLimitRecord | None:
    return (
        db.query(RateLimitRecord)
        .filter(RateLimitRecord.ip_address == client_ip, RateLimitRecord.action == action)
        .first()
    )


def is_rate_limited(db: Session, client_ip: str | None, action: str) -> bool:
    """判断来源 IP 当前是否因超过阈值被封禁。"""
    if not client_ip:
        return False
    rec = _get_rate_record(db, client_ip, action)
    if rec is None or rec.blocked_until is None:
        return False
    return rec.blocked_until > utc_now()


def record_rate_attempt(
    db: Session, client_ip: str | None, action: str, cost: int = 1
) -> None:
    """记录一次尝试；窗口内累计达到阈值即封禁一段时间。

    登录侧对「失败尝试」计数，刷新侧对「全部请求」计数
    （防止被盗令牌被高频反复换发 access_token）。
    """
    if not client_ip:
        return
    policy = _policy(action)
    now = utc_now()
    rec = _get_rate_record(db, client_ip, action)
    if rec is None:
        rec = RateLimitRecord(
            ip_address=client_ip, action=action, attempts=0, window_start=now
        )
        db.add(rec)
        db.flush()

    # 统计窗口过期 → 重新计数
    if (now - rec.window_start) > timedelta(seconds=policy["window"]):
        rec.window_start = now
        rec.attempts = 0
        rec.blocked_until = None
    # 封禁到期 → 自动解除
    if rec.blocked_until is not None and rec.blocked_until <= now:
        rec.blocked_until = None
        rec.attempts = 0
        rec.window_start = now

    rec.attempts += cost
    if rec.attempts >= policy["limit"]:
        rec.blocked_until = now + timedelta(seconds=policy["block"])
    db.flush()


def reset_rate_limit(db: Session, client_ip: str | None, action: str) -> None:
    """登录成功等场景清除该 IP 的失败计数。"""
    if not client_ip:
        return
    rec = _get_rate_record(db, client_ip, action)
    if rec is not None:
        rec.attempts = 0
        rec.blocked_until = None
        rec.window_start = utc_now()
        db.flush()


def authenticate_user(
    db: Session, employee_id: str, password: str, client_ip: str | None = None
) -> tuple[User | None, str | None]:
    """验证用户登录，返回 (user, error_msg)

    安全说明：失败计数基于来源 IP 限流，避免对受害者账号做 blanket 锁定导致 DoS；
    高频爆破会被来源 IP 封禁，而正常用户不会因他人尝试被锁。
    """
    # 来源 IP 级限流（第一道防线，数据库共享计数）
    if is_rate_limited(db, client_ip, "login"):
        return None, "登录尝试过于频繁，请稍后再试"

    user = db.query(User).filter(User.employee_id == employee_id).first()
    if not user:
        record_rate_attempt(db, client_ip, "login")
        return None, "工号或密码错误"

    if not user.is_active:
        record_rate_attempt(db, client_ip, "login")
        return None, "账号已被禁用"

    if not verify_password(password, user.password_hash):
        record_rate_attempt(db, client_ip, "login")
        # 仅记录失败次数用于审计，不再锁定受害者账号
        user.login_attempts = (user.login_attempts or 0) + 1
        db.commit()
        return None, "工号或密码错误"

    # 登录成功，重置失败计数
    user.login_attempts = 0
    user.locked_until = None
    reset_rate_limit(db, client_ip, "login")
    db.commit()
    return user, None


def change_password(db: Session, user: User, old_password: str, new_password: str) -> bool:
    if not verify_password(old_password, user.password_hash):
        return False
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.password_changed_at = utc_now()
    db.commit()
    return True


def get_default_password(db: Session, employee_id: str | None = None) -> str:
    """返回新建账号时使用的初始口令（由「账号设置」中的模板生成）。

    [调整 2026-09-10] 改为读取系统配置 `default_password_template`：
      - 支持 `{工号}` 占位符（替换为传入的员工工号），也可只填固定口令；
      - 未配置（为空）时回退内置默认 `MedPal@2026`；
      - 生成结果不足 6 位时同样回退，避免配置出弱口令。
    账号创建时仍置 `must_change_password=True`，使用者首次登录即被强制修改。
    「重置密码」走另一套规则（`Rici@` + 工号，见 `reset_password`），不受本配置影响。
    """
    from app.services.system_config_service import (
        DEFAULT_PASSWORD_TEMPLATE_KEY,
        DEFAULT_PASSWORD_TEMPLATE_FALLBACK,
        get_config_value,
    )

    template = (get_config_value(db, DEFAULT_PASSWORD_TEMPLATE_KEY, "") or "").strip()
    if not template:
        return DEFAULT_PASSWORD_TEMPLATE_FALLBACK
    password = template.replace("{工号}", (employee_id or "").strip())
    if len(password) < 6:
        return DEFAULT_PASSWORD_TEMPLATE_FALLBACK
    return password


def reset_password(db: Session, user: User) -> str:
    """重置用户密码为随机强口令，并返回该明文口令供管理员转告使用者。

    [修复/问题18] 原实现一律重置为弱口令 `123456`。
    现改为固定格式「Rici@ + 本人 6 位工号」：可预期、便于转告使用者，
    并强制首次登录修改。由于该口令可预期，调用方仍须把服务端返回的明文
    回显给管理员确认（见 users 路由的重置密码接口）。
    """
    new_password = generate_reset_password(user.employee_id)
    user.password_hash = hash_password(new_password)
    user.must_change_password = True
    user.login_attempts = 0
    # 更新密码修改时间，使所有之前签发的 token 失效
    user.password_changed_at = utc_now()
    db.commit()
    return new_password


def blacklist_token(db: Session, token: str, token_type: str, employee_id: str = None, reason: str = "logout") -> bool:
    """将单个 token 加入黑名单"""
    # 解析 token 获取过期时间
    payload = decode_token(token)
    if payload is None:
        return False
    
    expires_at = payload.get("exp")
    if expires_at:
        expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    else:
        # 如果没有过期时间，设置为当前时间（理论上不应该发生）
        expires_at = utc_now()
    
    # 检查是否已在黑名单中
    existing = db.query(TokenBlacklist).filter(TokenBlacklist.token == token).first()
    if existing:
        return True  # 已经在黑名单中
    
    blacklist_entry = TokenBlacklist(
        token=token,
        token_type=token_type,
        employee_id=employee_id or payload.get("sub"),
        reason=reason,
        expires_at=expires_at,
    )
    db.add(blacklist_entry)
    db.flush()
    return True








def is_token_blacklisted(db: Session, token: str) -> bool:
    """检查 token 是否在黑名单中"""
    return db.query(TokenBlacklist).filter(TokenBlacklist.token == token).first() is not None


# [修复/问题3] refresh_token 轮换宽限期（秒）。
# 刷新时旧令牌会立即进入黑名单，但同一浏览器可能因并发请求 / 多标签页在极短时间内
# 重复使用同一旧令牌（此时上一条响应的 Set-Cookie 尚未生效）。若直接判为「已吊销」
# 会导致误登出（本次现象）。故对「因轮换(rotated)进入黑名单」的令牌给出 60 秒宽限；
# 其他原因（logout / 改密 / 禁用）以及超过宽限期的轮换令牌，一律立即拒绝。
ROTATION_GRACE_SECONDS = 60


def is_token_revoked(db: Session, token: str) -> bool:
    """判断 token 是否处于「已吊销」状态（供刷新接口使用）。

    与 is_token_blacklisted 的区别：对 reason=rotated 且在宽限期内的条目返回 False，
    以容忍并发/多标签页刷新；超过宽限期或非轮换原因则返回 True。
    """
    entry = db.query(TokenBlacklist).filter(TokenBlacklist.token == token).first()
    if entry is None:
        return False
    if entry.reason == "rotated":
        created = entry.created_at or utc_now()
        if (utc_now() - created).total_seconds() <= ROTATION_GRACE_SECONDS:
            return False
    return True


def cleanup_expired_blacklist(db: Session) -> int:
    """清理过期的黑名单条目"""
    now = utc_now()
    deleted = db.query(TokenBlacklist).filter(TokenBlacklist.expires_at < now).delete()
    # [修复/问题14] 顺带清理过期超过 1 天的限流记录，避免表无限增长
    db.query(RateLimitRecord).filter(
        RateLimitRecord.window_start < now - timedelta(days=1),
        RateLimitRecord.blocked_until.is_(None),
    ).delete(synchronize_session=False)
    db.commit()
    return deleted


def prune_rate_limits(db: Session) -> int:
    """清理超过保留期的限流记录（由定时任务调用）。

    [修复/问题14] 替代原先清理内存字典的 `prune_ip_failures`：
    限流状态已持久化到数据库，改为清理库中过期记录，避免表无限增长。
    """
    cutoff = utc_now() - timedelta(days=1)
    deleted = db.query(RateLimitRecord).filter(
        RateLimitRecord.window_start < cutoff,
        RateLimitRecord.blocked_until.is_(None),
    ).delete(synchronize_session=False)
    db.commit()
    return deleted
