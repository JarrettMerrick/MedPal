from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, model_validator

class SignageBase(BaseModel):
 code:Optional[str]=None
 name:str
 category:str
 # [修复 2026-09-04] 新增类别类型字段：标识标牌/平面宣传
 category_type:str="标识标牌"
 material:Optional[str]=None
 size_spec:Optional[str]=None
 install_date:Optional[date]=None
 warranty_expire:Optional[date]=None
 # [新增 2026-09-05] 标识有效期：long_term 长期标识（不设到期时间）/ temporary 临时标识（必填到期日）
 validity_type:str="long_term"
 validity_until:Optional[date]=None
 # [修复 2026-09-04] 新增所属区域类型字段：院区导视/宣传、楼栋导视/宣传、楼层导视/宣传
 zone_type:str="院区导视/宣传"
 campus:Optional[str]=None
 building:Optional[str]=None
 floor:Optional[str]=None
 # [新增 2026-09-12] 所属区域（选填，支持多选）：仅「楼层导视/宣传」时可填，存区域名称、逗号分隔
 area:Optional[str]=None
 location_desc:Optional[str]=None
 display_text_cn:Optional[str]=None
 display_text_en:Optional[str]=None
 department_id:Optional[int]=None
 status:str="normal"
 oa_number:Optional[str]=None
 manufacturer:Optional[str]=None
 vendor_contact:Optional[str]=None

class SignageCreate(SignageBase):
 # [新增 2026-09-05] 临时标识必须填写有效期限
 @model_validator(mode="after")
 def check_validity_required(self):
     if self.validity_type == "temporary" and not self.validity_until:
         raise ValueError("临时标识必须填写有效期限")
     return self

class SignageUpdate(BaseModel):
 name:Optional[str]=None
 category:Optional[str]=None
 # [修复 2026-09-04] 新增类别类型字段：标识标牌/平面宣传
 category_type:Optional[str]=None
 material:Optional[str]=None
 size_spec:Optional[str]=None
 install_date:Optional[date]=None
 warranty_expire:Optional[date]=None
 # [新增 2026-09-05] 标识有效期（更新时可改类型/到期日）
 validity_type:Optional[str]=None
 validity_until:Optional[date]=None
 # [修复 2026-09-04] 新增所属区域类型字段：院区导视/宣传、楼栋导视/宣传、楼层导视/宣传
 zone_type:Optional[str]=None
 campus:Optional[str]=None
 building:Optional[str]=None
 floor:Optional[str]=None
 # [新增 2026-09-12] 所属区域（选填，支持多选，逗号分隔）
 area:Optional[str]=None
 location_desc:Optional[str]=None
 display_text_cn:Optional[str]=None
 display_text_en:Optional[str]=None
 department_id:Optional[int]=None
 status:Optional[str]=None
 oa_number:Optional[str]=None
 manufacturer:Optional[str]=None
 vendor_contact:Optional[str]=None
 design_photo:Optional[str]=None
 installation_photo:Optional[str]=None

class SignageResponse(SignageBase):
 id:int
 design_photo:Optional[str]=None
 installation_photo:Optional[str]=None
 # [新增 2026-09-08] 所属科室名称（由 service 关联填充，便于前端展示）
 department_name:Optional[str]=None
 # [新增 2026-09-07] 最近一次巡检日期，由详情接口根据巡检记录计算
 last_inspection_date:Optional[date]=None
 created_by:Optional[str]=None
 created_at:Optional[datetime]=None
 updated_by:Optional[str]=None
 updated_at:Optional[datetime]=None
 class Config:from_attributes=True

class SignageListResponse(BaseModel):
 total:int
 items:List[SignageResponse]
 page:int
 page_size:int

class FloorPlanCreate(BaseModel):
    name:str
    # [修复 2026-09-05] 平面类别取代原 type：院区平面/楼层平面
    category:str
    campus:Optional[str]=None
    building:Optional[str]=None
    floor:Optional[str]=None
    # [修复 2026-09-05] 新增 floor_code 关联楼层编号（如 F3/-1）与 description 描述
    floor_code:Optional[str]=None
    description:Optional[str]=None
    # [修复 2026-09-05] 新增 floor_id：关联「院区管理」中的楼层记录（floors.id），
    # 楼层由院区→楼栋→楼层级联选择产生，不再手工输入；楼层平面必须关联到具体楼层。
    floor_id:Optional[int]=None
    image_url:Optional[str]=None  # [修复 2026-09-03] 添加图像URL字段，支持平面图图片上传

    # [修复 2026-09-05] 校验：楼层平面必须关联具体楼层。
    # floor_id 优先（新数据），floor_code 作为兼容兜底（历史数据仅有编号）。
    @model_validator(mode="after")
    def check_floor_required(self):
        if self.category == "楼层平面" and not self.floor_id and not self.floor_code:
            raise ValueError("楼层平面必须关联具体楼层")
        return self

class FloorPlanResponse(FloorPlanCreate):
 id:int
 image_url:Optional[str]=None
 version:int=1
 is_active:bool=True
 created_at:Optional[datetime]=None
 class Config:from_attributes=True

class FloorPlanListResponse(BaseModel):
 total:int
 items:List[FloorPlanResponse]

class SignagePointCreate(BaseModel):
 signage_id:int
 # [修复 2026-09-05] floor_plan_id 由路径参数 plan_id 决定（路由中会强制赋值覆盖），
 # 因此请求体不必传、也不应必填；此前必填导致前端仅提交 signage_id 与坐标时被校验拦截返回 422
 floor_plan_id:Optional[int]=None
 x_percent:float
 y_percent:float
 pin_icon:Optional[str]=None
 pin_color:Optional[str]=None

class SignagePointUpdate(BaseModel):
 x_percent:Optional[float]=None
 y_percent:Optional[float]=None
 pin_icon:Optional[str]=None
 pin_color:Optional[str]=None

class SignagePointResponse(SignagePointCreate):
 id:int
 # [修复 2026-09-05] 附带标识编码/名称/分类：标记点需按「分类形状+颜色」渲染，
 # 不能依赖前端绑定弹窗的分页标识列表（已被 exclude_marked 过滤，查不到已标记的标识）
 signage_category:Optional[str]=None
 signage_code:Optional[str]=None
 signage_name:Optional[str]=None
 class Config:from_attributes=True

class SignagePointListResponse(BaseModel):
 total:int
 items:List[SignagePointResponse]

class SignagePhotoCreate(BaseModel):
 photo_type:str
 caption:Optional[str]=None

class SignagePhotoResponse(BaseModel):
 id:int
 signage_id:int
 photo_type:Optional[str]=None
 photo_url:Optional[str]=None
 caption:Optional[str]=None
 uploaded_by:Optional[str]=None
 uploaded_at:Optional[datetime]=None
 class Config:from_attributes=True

class SignageHistoryResponse(BaseModel):
    id:int
    signage_id:int
    field_name:Optional[str]=None
    old_value:Optional[str]=None
    new_value:Optional[str]=None
    oa_number:Optional[str]=None
    changed_by:Optional[str]=None
    changed_at:Optional[datetime]=None
    # [修复 2026-09-04] 新增 snapshot 字段，返回完整标识快照
    snapshot:Optional[str]=None
    class Config:from_attributes=True

class SignageHistoryListResponse(BaseModel):
 total:int
 items:List[SignageHistoryResponse]
 page:int
 page_size:int

class SignageInspectionCreate(BaseModel):
 inspection_date:date
 inspector:str
 result:str
 notes:Optional[str]=None

class SignageInspectionResponse(SignageInspectionCreate):
 id:int
 signage_id:int
 created_at:Optional[datetime]=None
 class Config:from_attributes=True

class SignageInspectionListResponse(BaseModel):
 total:int
 items:List[SignageInspectionResponse]
 page:int
 page_size:int
