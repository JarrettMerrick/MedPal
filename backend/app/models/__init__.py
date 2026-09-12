from app.database import Base
from app.models.user import User
from app.models.staff import Staff
from app.models.department import Department, DepartmentSpecialty, SpecialtyImage, DepartmentEquipment, EquipmentImage
from app.models.audit_log import ModificationHistory
from app.models.role import Role, Permission, role_permissions
from app.models.staff_card import StaffCard
from app.models.notification import Notification
# [新增 2026-09-11] 站内信（统一消息中心：系统通知 + 人工群发/私发）
from app.models.message import Message, MessageRecipient, MessageTag
from app.models.upload_session import UploadSession
from app.models.export_package import ExportPackage
from app.models.regulation import Regulation, RegulationCategory, RegulationHistory
from app.models.token_blacklist import TokenBlacklist
# [修复/问题14] 登录/刷新限流计数持久化模型（替代进程内存字典）
from app.models.rate_limit import RateLimitRecord
from app.models.system_config import SystemConfig
# [新增 2026-09-10] 注册申请（登录页自助注册 → 科室管理员审核）
from app.models.registration_request import RegistrationRequest
# [新增 2026-09-11] 人员信息变更审核（立即生效 + 追认/回滚）
from app.models.staff_change import StaffChangeRequest
from app.models.user_department_scope import UserDepartmentScope
# [修复 2026-09-01] 新增 SystemLog 模型导入，支持系统日志查询/导出功能
from app.models.system_log import SystemLog
# [新增 2026-09-03] 标识管理模型导入
from app.models.signage import Signage, FloorPlan, SignagePoint, SignagePhoto, SignageHistory, SignageInspection
# [修复 2026-09-03] 院区-楼栋-楼层-区域模型导入
from app.models.campus import Campus, Building, Floor, Area
# [修复 2026-09-04] 标识分类和供应商模型导入
from app.models.signage_settings import SignageCategory, Supplier

__all__ = ["Base", "User", "Staff", "Department", "DepartmentSpecialty", "SpecialtyImage", "DepartmentEquipment", "EquipmentImage", "ModificationHistory", "Role", "Permission", "StaffCard", "Notification", "UploadSession", "ExportPackage", "Regulation", "RegulationCategory", "RegulationHistory", "TokenBlacklist", "SystemConfig", "UserDepartmentScope", "SystemLog", "Signage", "FloorPlan", "SignagePoint", "SignagePhoto", "SignageHistory", "SignageInspection", "Campus", "Building", "Floor", "Area", "SignageCategory", "Supplier", "RateLimitRecord", "RegistrationRequest", "Message", "MessageRecipient", "MessageTag", "StaffChangeRequest"]
