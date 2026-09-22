# Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
# Licensed under the MIT License. See LICENSE file for details.

"""账号设置相关请求模型（见 routers/account_settings.py）。"""

from pydantic import BaseModel, Field, field_validator


class ResetAllPasswordsRequest(BaseModel):
    """「批量重置密码」请求体：以操作者本人的登录密码做二次确认，可选限定科室范围。

    [调整 2026-09-14] 由「只支持全员重置」扩展为「支持单选 / 多选科室定向重置」：
    `departments` 为空 = 沿用原语义（除超级管理员外的全员）。
    """

    # 二次确认：必须重新输入操作者自己的登录密码，避免会话被劫持或误触即批量改密。
    # max_length 与登录 / 修改密码保持一致（128），防止超长输入把 bcrypt 校验放大成资源消耗。
    password: str = Field(
        ..., min_length=1, max_length=128, description="操作者当前登录密码（二次确认）"
    )

    # [新增 2026-09-14] 科室范围：传 1 个 = 单选科室，传多个 = 多选科室，留空/不传 = 不限科室。
    # 元素为「科室名称」而非 ID：账号侧（users.department）存的就是名称字符串，
    # 按名称匹配可避免"科室被改名/删除后 ID 与名称错配"导致的重置到错误范围。
    departments: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="限定重置的科室名称列表；为空表示不限科室（除超级管理员外的全员）",
    )

    @field_validator("departments")
    @classmethod
    def _normalize_departments(cls, v: list[str]) -> list[str]:
        """规范化科室列表：去首尾空白、丢弃空值、去重并限制长度。

        与 routers 侧的 trim 匹配口径保持一致，同时防止前端异常输入
        （如 `["", " "]`）把「未选择科室」误判成「已选择科室」而缩小重置范围。
        """
        cleaned: list[str] = []
        for item in v or []:
            name = (item or "").strip()
            if not name:
                continue
            if len(name) > 50:
                # 与 Department.name（String(100)）/ users.department（String(50)）同量级，
                # 超长值必然是脏输入，直接拒绝而不是静默截断
                raise ValueError("科室名称过长")
            if name not in cleaned:
                cleaned.append(name)
        return cleaned
