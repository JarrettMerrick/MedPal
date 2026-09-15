// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 人员新增/编辑表单。核心业务逻辑：
 * 1. 工种联动 → 科室类别 → 可选的职称列表
 * 2. 医生/技师额外显示高级字段（学历、专业擅长、社会任职、荣誉）
 * 3. 编辑模式含照片上传（正面/侧面，受「照片上传」权限控制，本人不受限）+ 工卡照片（权限控制）
 * 4. 前端校验必填字段（工号、姓名、科室）
 * 
 * 改造说明（v1.1.0）：
 * - [改进] useState 大量字段 → Ant Design Form.useForm 声明式管理
 * - [改进] 手写 input/select/textarea → Input/Select/Input.TextArea
 * - [改进] 工种选择按钮组 → Radio.Group (Button 样式) 或 Segmented
 * - [改进] 手写按钮 → Button 组件
 * - [改进] error div → Alert 组件
 * - PhotoUpload 保持不变（已在 Layer 2 改造）
 */

import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { Form, Input, Select, Button, Alert, Typography, Row, Col, App, Flex, theme } from 'antd';

const { useToken } = theme;
import { getStaff, createStaff, updateStaff } from '../../api/staff';
import { getDepartmentsByCategory } from '../../api/departments';
import { getCards, deleteCard } from '../../api/staff-cards';
import { WORK_TYPE_OPTIONS, WORK_TYPE_LABELS, WORK_TYPE_DEPT_CATEGORY, TITLE_OPTIONS_BY_WORK_TYPE } from '../../types/staff';
import type { StaffCard } from '../../types/staff-card';
import PhotoUpload from '../../components/PhotoUpload';
import PageContainer from '../../components/PageContainer';
import PageHeader from '../../components/PageHeader';
import { useAuth } from '../../contexts/AuthContext';
// [调整 2026-09-15] 新增导入 PERM_STAFF_PHOTO_UPLOAD（照片上传权限）与 PERM_STAFF_EDIT
// （删除照片仍属「修改人员信息」范畴），用于照片区的权限门禁与提示
import { hasPermission, PERM_CARD_UPLOAD, PERM_STAFF_EDIT, PERM_STAFF_PHOTO_UPLOAD } from '../../utils/permissions';
// [修复 2026-09-02] P4: 导入统一错误处理函数
import { getErrorMessage } from '../../utils/format';

const { TextArea } = Input;
const { Text } = Typography;

/**
 * 表单分组标题：左侧色条 + 组名，用于区分不同字段分组，增强视觉节奏。
 * 每个分组自带顶部留白（margin: 28px 0 16px），组间形成清晰的疏密层次。
 */
const SectionTitle: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { token } = useToken();
  return (
    <Text strong style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, margin: '28px 0 16px' }}>
      <span style={{ width: 4, height: 14, borderRadius: 2, background: token.colorPrimary }} />
      {children}
    </Text>
  );
};

const StaffForm: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { id } = useParams<{ id: string }>();
  const isEdit = !!id && id !== 'new';
  const { user } = useAuth();
  const { message } = App.useApp();
  const { token } = useToken();

  // [改进] 获取来源页面URL，用于返回按钮恢复原始状态
  const returnTo = (location.state as any)?.returnTo as string | undefined;

  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [departments, setDepartments] = useState<{ id: number; name: string; category: string }[]>([]);
  const [cardData, setCardData] = useState<StaffCard | null>(null);
  // [新增 2026-09-15] 记录页面初次加载时的照片值，用于提交时判断照片是否在本次会话中真正被改动：
  // 上传接口（/api/uploads/photo）已单独登记照片变更审核，若保存时再提交同一个路径会导致重复审核记录。
  const [initialFrontPhoto, setInitialFrontPhoto] = useState<string>('');
  const [initialSidePhoto, setInitialSidePhoto] = useState<string>('');

  const canManageCard = hasPermission(user, PERM_CARD_UPLOAD);

  // 监听工种变化
  const workType = Form.useWatch('work_type', form);
  // [改进] 用 useWatch 而非渲染期 form.getFieldValue，避免 form 未连接时触发
  // "Instance created by useForm is not connected" 警告（photo 字段在 Form 连接前就被读取）。
  const employeeId = Form.useWatch('employee_id', form);
  const frontPhoto = Form.useWatch('front_photo', form);
  const sidePhoto = Form.useWatch('side_photo', form);
  const deptCategory = WORK_TYPE_DEPT_CATEGORY[workType] || '';
  const titleOptions = workType ? TITLE_OPTIONS_BY_WORK_TYPE[workType] || [] : [];
  const showAdvancedFields = workType === 'doctor' || workType === 'technician';
  const isNurse = workType === 'nurse';
  const isAdmin = workType === 'admin';

  // [新增 2026-09-15] 形象照权限（与后端 uploads.py / chunk_upload.py 的校验逻辑保持一致）：
  //  - 本人维护自己的照片始终允许（isSelf 放行，不校验「照片上传」权限）；
  //  - 为他人上传/更换形象照需「照片上传」权限（staff.photo_upload），
  //    可在「角色管理 → 人员管理」中按角色分配/回收，实际范围随角色数据范围
  //    （仅本人/管辖科室/全部人员）与工种范围自动收敛；
  //  - 删除照片属「修改人员信息」（staff.edit）范畴，与上传权限分开控制。
  const isSelf = !!user && !!employeeId && employeeId === user.employee_id;
  const canUploadPhoto = isSelf || hasPermission(user, PERM_STAFF_PHOTO_UPLOAD);
  const canDeletePhoto = isSelf || hasPermission(user, PERM_STAFF_EDIT);

  // [改进] 根据当前用户的工种数据范围（work_type_scope）计算其可新增的工种。
  // 后端 /api/auth/me 返回 work_type_scope：'all'=所有工种，否则为逗号分隔的工种列表（如 'nurse'）。
  // 与后端 _check_staff_create_access → get_user_work_type_scope 的校验保持一致，
  // 将无权新增的工种选项置灰（disabled），避免用户填写完整表单后提交才被拒绝。
  const allowedWorkTypes = user?.work_type_scope === 'all'
    ? null
    : new Set((user?.work_type_scope || '').split(',').filter(Boolean));
  // 工种下拉选项：无权新增的工种置灰不可选
  const workTypeOptions = WORK_TYPE_OPTIONS.map((opt) => ({
    ...opt,
    disabled: allowedWorkTypes !== null && !allowedWorkTypes.has(opt.value),
  }));

  // [改进] 根据当前用户的科室数据范围（department_scope）计算其可选的科室。
  // 后端 /api/auth/me 返回 department_scope（'all'/'managed'/'own'）与 managed_departments（可管理科室名称列表）。
  // 与后端 _check_staff_create_access → has_department_access 的校验保持一致：
  // - 'all'：全部科室可选
  // - 'managed'/'own'：仅 managed_departments 中列出的科室可选，其余置灰
  const isDeptScopeAll = !user || user.department_scope === 'all';
  const allowedDeptNames = new Set(user?.managed_departments || []);
  // 科室下拉选项：无管辖权的科室置灰不可选
  const deptOptions = departments.map((d) => ({
    value: d.name,
    label: d.name,
    disabled: !isDeptScopeAll && !allowedDeptNames.has(d.name),
  }));

  // [修复 2026-09-02] 工种变化时加载全部科室，并按"科室对当前工种是否有效"过滤，
  // 支持混合科室 allowed_work_types；逻辑与后端 staff.py 工种-科室校验保持一致，
  // 不再仅按 category 过滤，确保"消毒供应室"等混合科室在任意允许工种下均出现。
  useEffect(() => {
    if (!workType) {
      setDepartments([]);
      return;
    }
    const expectedCategory = deptCategory; // = WORK_TYPE_DEPT_CATEGORY[workType]
    getDepartmentsByCategory('').then((all) => {
      const valid = all.filter((d) => {
        if (d.allowed_work_types) {
          const allowed = d.allowed_work_types.split(',').map((s) => s.trim()).filter(Boolean);
          return allowed.includes(workType);
        }
        return d.category === expectedCategory;
      });
      setDepartments(valid);
    });
  }, [workType, deptCategory]);

  // 编辑模式加载现有数据
  useEffect(() => {
    if (isEdit && id) {
      getStaff(id).then((data) => {
        form.setFieldsValue({
          employee_id: data.employee_id,
          name: data.name,
          work_type: data.work_type,
          education: data.education || '',
          title: data.title || '',
          department: data.department || '',
          position: data.position || '',
          expertise_short: data.expertise_short || '',
          expertise_standard: data.expertise_standard || '',
          social_appointments: data.social_appointments || '',
          honors: data.honors || '',
          remarks: data.remarks || '',
          front_photo: data.front_photo || '',
          side_photo: data.side_photo || '',
        });
        // [新增 2026-09-15] 记录加载时的照片基线值，供提交时判断照片是否被真正改动
        setInitialFrontPhoto(data.front_photo || '');
        setInitialSidePhoto(data.side_photo || '');
      });
      getCards({ entity_id: id, page_size: 1 }).then((data) => {
        if (data.items.length > 0) setCardData(data.items[0]);
      }).catch(() => {});
    }
  }, [id, isEdit, form]);

  // 工种变化时重置科室和职称
  const handleWorkTypeChange = (newType: string) => {
    form.setFieldsValue({ work_type: newType, department: undefined, title: undefined });
    setError('');
  };

  const handleSubmit = async (values: Record<string, unknown>) => {
    setError('');
    setLoading(true);
    try {
      if (isEdit && id) {
        const data = Object.fromEntries(
          Object.entries(values).map(([key, v]) => [
            key,
            key === 'front_photo' || key === 'side_photo' ? (v || undefined) : (!v && key !== 'work_type' && key !== 'department' ? null : v),
          ])
        );
        // [修复 2026-09-15] 避免「一张照片产生 2 条审核记录」：
        // PhotoUpload 上传成功后已由 /api/uploads/photo 直接落库并登记了变更审核（source=photo），
        // 若此处再把同一个 file_path 提交给 PUT /api/staff/{id}，后端会因「值相同」无法识别为同一次
        // 上传而重复登记一条审核任务（source=admin）。故：当表单中的照片值与页面初始加载值一致时，
        // 说明本次保存并未改动照片（上传动作已自行登记），从提交载荷中剔除，交由上传接口独自登记。
        if ((data.front_photo || undefined) === (initialFrontPhoto || undefined)) {
          delete (data as Record<string, unknown>).front_photo;
        }
        if ((data.side_photo || undefined) === (initialSidePhoto || undefined)) {
          delete (data as Record<string, unknown>).side_photo;
        }
        await updateStaff(id, data as any);
      } else {
        await createStaff(values as any);
      }
      message.success(isEdit ? '修改成功' : '创建成功');
      navigate(returnTo || '/staff');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleCardDelete = async () => {
    if (!cardData) return;
    try {
      await deleteCard(cardData.id);
      setCardData(null);
    } catch (err) {
      message.error(getErrorMessage(err, '删除卡片失败'));
    }
  };

  return (
    <PageContainer maxWidth={800}>
      <PageHeader
        title={isEdit ? '编辑人员信息' : '新增人员'}
        onBack={() => navigate(returnTo || '/staff')}
      />

      {error && <Alert message={error} type="error" showIcon closable onClose={() => setError('')} style={{ marginBottom: 16 }} />}

      <Form form={form} layout="vertical" onFinish={handleSubmit} initialValues={{}}>
        {/* ① 基本信息 */}
        <SectionTitle>基本信息</SectionTitle>
        <Row gutter={16}>
          <Col xs={24} sm={12}>
            <Form.Item
              name="employee_id"
              label="工号"
              rules={[
                { required: true, message: '请输入工号' },
                { pattern: /^\d{6}$/, message: '请填写完整6位数工号' },
              ]}
            >
              <Input disabled={isEdit} maxLength={6} placeholder="请输入6位数字工号" />
            </Form.Item>
          </Col>
          <Col xs={24} sm={12}>
            <Form.Item name="name" label="姓名" rules={[{ required: true, message: '请输入姓名' }]}>
              <Input placeholder="请输入姓名" />
            </Form.Item>
          </Col>
        </Row>

        {/* ② 岗位信息 */}
        <SectionTitle>岗位信息</SectionTitle>
        <Form.Item name="work_type" label="工种" rules={[{ required: true, message: '请选择工种' }]}>
          <Select placeholder="请选择工种" onChange={handleWorkTypeChange} options={workTypeOptions} />
        </Form.Item>
        <Form.Item
          name="department"
          label={isNurse ? '所属病区' : isAdmin ? '所属部门' : '所属科室'}
          rules={[{ required: true, message: `请选择${isNurse ? '病区' : isAdmin ? '部门' : '科室'}` }]}
        >
          <Select
            placeholder={`请选择${isNurse ? '病区' : isAdmin ? '部门' : '科室'}`}
            options={deptOptions}
            showSearch
          />
        </Form.Item>
        <Text type="secondary" style={{ fontSize: 12, marginTop: -12, display: 'block', marginBottom: 16 }}>
          当前工种「{WORK_TYPE_LABELS[workType] || workType}」仅可选支持该工种的科室（含混合科室配置）
          {allowedWorkTypes !== null && '；灰色选项为当前账号无权新增的工种/科室'}
        </Text>
        <Row gutter={16}>
          {/* 职称（非行政）：与学历/职务同行等分 */}
          {!isAdmin && (
            <Col xs={24} sm={showAdvancedFields ? 8 : 12}>
              <Form.Item name="title" label="职称">
                <Select placeholder="请选择职称" options={titleOptions.map((t) => ({ value: t, label: t }))} />
              </Form.Item>
            </Col>
          )}
          {/* 学历（医生/技师）：与职称/职务同行等分 */}
          {showAdvancedFields && (
            <Col xs={24} sm={8}>
              <Form.Item name="education" label="学历">
                <Select
                  placeholder="请选择学历"
                  options={['博士', '硕士', '本科', '大专', '中专'].map((v) => ({ value: v, label: v }))}
                />
              </Form.Item>
            </Col>
          )}
          {/* 职务（公共）：医生/技师占 1/3，护士占 1/2，行政独占一行 */}
          <Col xs={24} sm={isAdmin ? 24 : showAdvancedFields ? 8 : 12}>
            <Form.Item name="position" label="职务">
              <Input placeholder={isNurse ? '如：护士长' : '如：科室主任'} />
            </Form.Item>
          </Col>
        </Row>

        {/* ③ 形象照片（编辑模式；[调整 2026-09-15] 上传受「照片上传」权限控制，本人不受限） */}
        {isEdit && (
          <>
            <SectionTitle>形象照片</SectionTitle>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <Form.Item name="front_photo">
                  <PhotoUpload
                    type={workType as any}
                    employeeId={employeeId}
                    photoType="front"
                    currentPhoto={frontPhoto}
                    label="正面形象照"
                    cropAspect={0.75}
                    // 无「照片上传」权限时禁用上传/更换（组件内展示禁用原因），删除仍由 staff.edit 控制
                    disabled={!canUploadPhoto}
                    canDelete={canDeletePhoto}
                    disabledHint="无「照片上传」权限，仅可查看/下载照片；请联系管理员在「角色管理 → 人员管理」中授予"
                    onUploadSuccess={(v) => form.setFieldsValue({ front_photo: v })}
                    onDeleteSuccess={() => form.setFieldsValue({ front_photo: '' })}
                  />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="side_photo">
                  <PhotoUpload
                    type={workType as any}
                    employeeId={employeeId}
                    photoType="side"
                    currentPhoto={sidePhoto}
                    label="侧面形象照"
                    cropAspect={0.75}
                    // 无「照片上传」权限时禁用上传/更换（组件内展示禁用原因），删除仍由 staff.edit 控制
                    disabled={!canUploadPhoto}
                    canDelete={canDeletePhoto}
                    disabledHint="无「照片上传」权限，仅可查看/下载照片；请联系管理员在「角色管理 → 人员管理」中授予"
                    onUploadSuccess={(v) => form.setFieldsValue({ side_photo: v })}
                    onDeleteSuccess={() => form.setFieldsValue({ side_photo: '' })}
                  />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}

        {/* ④ 工卡照片（编辑模式 + 权限） */}
        {isEdit && canManageCard && (
          <>
            <SectionTitle>工卡照片</SectionTitle>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <Text strong style={{ fontSize: 14 }}>工卡照片</Text>
              {cardData && (
                <Text type={cardData.status === 'confirmed' ? 'success' : cardData.status === 'rejected' ? 'danger' : 'warning'}>
                  {cardData.status === 'confirmed' ? '已确认' : cardData.status === 'rejected' ? '已拒绝' : '待确认'}
                </Text>
              )}
            </div>
            {cardData?.status === 'rejected' && cardData.reject_reason && (
              <Alert message={`拒绝原因：${cardData.reject_reason}`} type="error" style={{ marginBottom: 8 }} />
            )}
            <PhotoUpload
              type={workType as any}
              employeeId={employeeId}
              photoType="card"
              currentPhoto={cardData?.card_photo || null}
              label="工卡照片"
              onUploadSuccess={() => {
                if (id) getCards({ entity_id: id, page_size: 1 }).then((d) => {
                  if (d.items.length > 0) setCardData(d.items[0]);
                });
              }}
              onDeleteSuccess={handleCardDelete}
            />
          </>
        )}

        {/* ⑤ 专业信息（医生/技师） */}
        {showAdvancedFields && (
          <>
            <SectionTitle>专业信息</SectionTitle>
            <Form.Item
              name="expertise_short"
              label="专业擅长（短）"
              extra="100 字以内，用于文字排版不能显示太多的地方"
              rules={[{ max: 100, message: '专业擅长（短）不能超过 100 字' }]}
            >
              <TextArea maxLength={100} showCount rows={2} placeholder="如：冠心病介入治疗" />
            </Form.Item>
            <Form.Item name="expertise_standard" label="专业擅长（标准）">
              <TextArea rows={4} placeholder="详细描述专业擅长领域" />
            </Form.Item>
            <Row gutter={16}>
              <Col xs={24} sm={12}>
                <Form.Item name="social_appointments" label="社会任职">
                  <TextArea rows={3} placeholder="如：XX医学会委员" />
                </Form.Item>
              </Col>
              <Col xs={24} sm={12}>
                <Form.Item name="honors" label="获得荣誉">
                  <TextArea rows={3} placeholder="如：XX科技进步奖" />
                </Form.Item>
              </Col>
            </Row>
          </>
        )}

        {/* ⑥ 备注（全宽） */}
        <SectionTitle>备注</SectionTitle>
        <Form.Item name="remarks" label="备注" style={{ marginBottom: 0 }}>
          <TextArea rows={2} placeholder="其他需要说明的信息" />
        </Form.Item>

        {/* 操作区：右侧对齐 + 顶部分隔线，滚动时吸底便于操作 */}
        <Flex
          justify="flex-end"
          gap={12}
          style={{
            marginTop: 28,
            paddingTop: 20,
            borderTop: `1px solid ${token.colorBorderSecondary}`,
            position: 'sticky',
            bottom: 0,
            background: token.colorBgContainer,
          }}
        >
          <Button onClick={() => navigate(returnTo || '/staff')}>取消</Button>
          <Button type="primary" htmlType="submit" loading={loading}>
            {isEdit ? '保存修改' : '创建人员'}
          </Button>
        </Flex>
      </Form>
    </PageContainer>
  );
};

export default StaffForm;
