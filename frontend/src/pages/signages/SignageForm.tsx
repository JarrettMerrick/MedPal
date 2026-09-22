import React, { useState, useEffect, useCallback } from 'react';
// [新增 2026-09-17] Popconfirm：编辑页「删除标识」二次确认
import { Form, Input, Select, DatePicker, Button, App, Space, Row, Col, Typography, Upload, Image, Popconfirm } from 'antd';
import type { UploadProps } from 'antd';
import { useNavigate, useParams } from 'react-router-dom';
// [新增 2026-09-17] deleteSignage：删除入口由标识列表移入本页
import { getSignage, createSignage, updateSignage, uploadSignagePhoto, deleteSignage } from '../../api/signage';
import { campusApi } from '../../api/campus';
// [调整 2026-09-12] 新增 Area 类型：楼层导视/宣传时支持多选所属区域
import type { Campus, Building, Floor, Area } from '../../types/campus';
// [修复 2026-09-04] 导入标识分类和供应商API
import { getActiveSignageCategories, getActiveSuppliers } from '../../api/signage-settings';
import type { SignageCategory, Supplier } from '../../api/signage-settings';
// [新增 2026-09-08] 标识所属科室下拉数据源
import { getAllDepartments } from '../../api/departments';
import dayjs from 'dayjs';
import { InboxOutlined, DeleteOutlined, EyeOutlined, FileOutlined, LeftOutlined } from '@ant-design/icons';
import { getOriginalUrl } from '../../utils/imageUtils';
// [调整 2026-09-17] 楼层文本统一走 utils/floor（楼层号已为 F3/B1 字母编号）
import { floorLabel } from '../../utils/floor';
// [新增 2026-09-17] 标准设计文件选择器：从文件库搜索并引用标准设计文件（引用共享）
import StandardFilePicker from '../files/components/StandardFilePicker';
import type { StandardFileOption } from '../../api/designFiles';
// [新增 2026-09-17] 删除标识的权限判断（signage.delete）
import { hasPermission, PERM_SIGNAGE_DELETE, PERM_FILE_VIEW } from '../../utils/permissions';
import { useAuth } from '../../contexts/AuthContext';
// [重构 2026-09-21 / Q-8] 标识状态统一引用权威源（原本地副本缺 repair_in_progress）。
// 说明：本页的状态字段是**只读展示**（无选择控件，状态由巡检/维修流程驱动），
// 因此只需要 getSignageStatusLabel 取显示名；权威源里的
// SIGNAGE_STATUS_SELECT_OPTIONS 是为"将来若开放状态编辑"预留的，此处不导入。
import { getSignageStatusLabel } from '../../constants/signageStatus';

const { Option } = Select;
const { TextArea } = Input;
const { Text, Title } = Typography;

// [修复 2026-09-04] 内联样式定义
const styles = {
  container: {
    maxWidth: 920,
    margin: '0 auto',
    padding: '0 16px',
  },
  formCard: {
    background: 'var(--neu-bg)',
    border: '1px solid var(--line-soft)',
    borderRadius: 12,
    padding: '14px 16px',
    marginBottom: 12,
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 13.5,
    fontWeight: 600,
    marginBottom: 12,
  },
  sectionIndicator: {
    width: 4,
    height: 14,
    background: 'var(--accent)',
    borderRadius: 2,
    display: 'inline-block',
  },
  formLabel: {
    fontSize: 12,
    color: 'var(--text-2)',
    marginBottom: 5,
  },
  requiredMark: {
    color: 'var(--danger)',
  },
  optionalMark: {
    fontSize: 12,
    color: 'var(--text-placeholder)',
  },
  headerBar: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    alignItems: 'center',
    gap: 12,
    padding: '12px 16px',
    background: 'var(--neu-bg)',
    border: '1px solid var(--line-soft)',
    borderRadius: 12,
    marginBottom: 12,
  },
  statusBadge: {
    padding: '2px 10px',
    background: 'var(--ok-soft)',
    color: 'var(--ok)',
    borderRadius: 20,
    fontSize: 12,
  },
  saveButton: {
    background: 'var(--accent)',
    borderColor: 'var(--accent)',
    borderRadius: 8,
    padding: '8px 18px',
    height: 'auto',
  },
  cancelButton: {
    border: '1px solid var(--line-soft)',
    borderRadius: 8,
    padding: '8px 18px',
    height: 'auto',
  },
  footerBar: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 10,
    padding: '12px 16px',
    background: 'var(--neu-bg)',
    border: '1px solid var(--line-soft)',
    borderRadius: 12,
  },

  uploadArea: {
    border: '1px dashed var(--line-soft)',
    borderRadius: 10,
    padding: 12,
    marginBottom: 12,
  },
  uploadBox: {
    height: 64,
    border: '1px solid var(--line-soft)',
    background: 'var(--neu-bg)',
    borderRadius: 8,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: 'var(--text-placeholder)',
    fontSize: 12,
  },
  formInput: {
    height: 34,
    background: 'var(--neu-bg)',
    borderColor: 'var(--line-soft)',
  },
  dashedInput: {
    height: 34,
    background: 'var(--neu-bg)',
    borderColor: 'var(--line-soft)',
    borderStyle: 'dashed',
  },

  helpText: {
    fontSize: 12,
    color: 'var(--text-2)',
    marginTop: 4,
  },
};

// [修复 2026-09-04] 根据参考页面重新设计的标识编辑页面
// [新增 2026-09-09] recordHistory：版本更新入口（/signages/version-update/:id）传入 true，
// 保存后本次修改写入历史版本；普通「编辑」入口不传（false），不产生历史版本记录
interface SignageFormProps {
  recordHistory?: boolean;
}

const SignageForm: React.FC<SignageFormProps> = ({ recordHistory = false }) => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const [form] = Form.useForm();
  // [新增 2026-09-05] 监听有效期类型：临时标识才显示/必填有效期限
  const validityType = Form.useWatch('validity_type', form);
  // [新增 2026-09-17] 监听标识分类：用于「从标准库选择」时限定只能选同分类的标准设计文件
  const selectedCategory = Form.useWatch<string>('category', form);
  const [loading, setLoading] = useState(false);
  // [新增 2026-09-17] 删除标识的提交中状态（入口由标识列表移入本页）
  const [deleting, setDeleting] = useState(false);
  const isEdit = !!id;
  const { message: messageApi } = App.useApp();
  
  // 院区/楼栋/楼层级联选择状态
  const [campuses, setCampuses] = useState<Campus[]>([]);
  const [buildings, setBuildings] = useState<Building[]>([]);
  const [floors, setFloors] = useState<Floor[]>([]);
  const [selectedCampusId, setSelectedCampusId] = useState<number | undefined>();
  const [selectedBuildingId, setSelectedBuildingId] = useState<number | undefined>();
  const [selectedFloorId, setSelectedFloorId] = useState<number | undefined>();
  
  // 所属区域类型状态
  const [selectedZoneType, setSelectedZoneType] = useState<string>('院区导视/宣传');

  // [新增 2026-09-12] 当前楼层的区域列表：仅「楼层导视/宣传」时供多选（选填项）
  const [areas, setAreas] = useState<Area[]>([]);
  
  // 设计文件和现场照片状态
  const [designPhotoUrl, setDesignPhotoUrl] = useState<string | undefined>();
  const [installationPhotoUrl, setInstallationPhotoUrl] = useState<string | undefined>();
  const [uploadingDesign, setUploadingDesign] = useState(false);
  const [uploadingInstallation, setUploadingInstallation] = useState(false);
  
  // [修复 2026-09-04] 本地文件存储，用于新建标识时暂存上传的文件
  const [localDesignFile, setLocalDesignFile] = useState<File | null>(null);
  const [localInstallationFile, setLocalInstallationFile] = useState<File | null>(null);
  // [新增 2026-09-17] 文件库引用：从标准库选择的设计文件ID（引用共享，路径同步到 designPhotoUrl）
  const [designFileId, setDesignFileId] = useState<number | undefined>(undefined);
  /**
   * [新增 2026-09-17] 设计文件的展示名。
   * 来源优先级：文件库中的使用名（引用标准设计文件）> 本地待上传文件名 > 路径文件名。
   * 目的：引用标准设计文件时展示「文件管理」里为该文件设置的使用名，
   * 而不是带时间戳随机串的原始落盘名。
   */
  const [designFileName, setDesignFileName] = useState<string | undefined>(undefined);
  /**
   * [新增 2026-09-17] 已引用标准设计文件所属的分类名。
   * 用于在标识分类被改动后提示「引用与新分类不一致，保存会被拒绝」，
   * 避免用户提交时才遇到后端 400 而不知原因。
   */
  const [designFileCategoryName, setDesignFileCategoryName] = useState<string | undefined>(undefined);
  const [standardPickerOpen, setStandardPickerOpen] = useState(false);

  // [新增 2026-09-17] 分类变更后，若已引用的标准文件不属于新分类，提前提示（后端仍会兜底拦截）
  useEffect(() => {
    if (!designFileName || !designFileCategoryName || !selectedCategory) return;
    if (designFileCategoryName === selectedCategory) return;
    messageApi.warning(
      `标识分类已改为「${selectedCategory}」，而当前引用的标准设计文件属于「${designFileCategoryName}」；`
      + '保存会被拒绝，请重新选择同分类文件或解除引用。',
    );
  }, [selectedCategory, designFileName, designFileCategoryName, messageApi]);

  // 标识分类和供应商状态
  const [categories, setCategories] = useState<SignageCategory[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [currentStatus, setCurrentStatus] = useState<string>('normal');
  // [新增 2026-09-08] 所属科室下拉数据源（id + name）
  const [departments, setDepartments] = useState<{ id: number; name: string }[]>([]);

  // 加载院区列表
  useEffect(() => {
    campusApi.getAllCampuses()
      .then(setCampuses)
      .catch(() => messageApi.error('获取院区列表失败'));
  }, []);

  // 加载标识分类和供应商列表
  useEffect(() => {
    // 加载标识分类
    getActiveSignageCategories()
      .then(setCategories)
      .catch(() => messageApi.error('获取标识分类列表失败'));
    
    // 加载供应商列表（仅制作厂商）
    getActiveSuppliers()
      .then(setSuppliers)
      .catch(() => messageApi.error('获取供应商列表失败'));

    // [新增 2026-09-08] 加载科室列表，供“所属科室”下拉选择
    getAllDepartments()
      .then((list) => setDepartments(list.map((d) => ({ id: d.id, name: d.name }))))
      .catch(() => messageApi.error('获取科室列表失败'));
  }, []);

  // 当选择院区时，加载对应的楼栋列表
  useEffect(() => {
    if (selectedCampusId) {
      campusApi.getBuildings(selectedCampusId)
        .then(r => setBuildings(r.items))
        .catch(() => messageApi.error('获取楼栋列表失败'));
      setSelectedBuildingId(undefined);
      setSelectedFloorId(undefined);
      setFloors([]);
    } else {
      setBuildings([]);
      setFloors([]);
    }
  }, [selectedCampusId]);

  // 当选择楼栋时，加载对应的楼层列表
  useEffect(() => {
    if (selectedBuildingId) {
      campusApi.getFloors(selectedBuildingId)
        .then(r => setFloors(r.items))
        .catch(() => messageApi.error('获取楼层列表失败'));
      setSelectedFloorId(undefined);
    } else {
      setFloors([]);
    }
  }, [selectedBuildingId]);

  // [新增 2026-09-12] 当选择楼层时，加载该楼层已划分的区域列表（供「楼层导视/宣传」多选）
  // 区域数据来源于「院区管理」→ 楼层 → 区域，与院区管理保持同一数据源
  useEffect(() => {
    if (selectedFloorId) {
      // 单楼层区域数量有限，一次性取足（后端上限 500）避免分页遗漏
      campusApi.getAreas(selectedFloorId, 1, 500)
        .then(r => setAreas(r.items))
        .catch(() => messageApi.error('获取区域列表失败'));
    } else {
      setAreas([]);
    }
  }, [selectedFloorId]);

  // 编辑模式下加载现有数据
  useEffect(() => {
    if (isEdit) {
      setLoading(true);
      getSignage(Number(id))
        .then((data) => {
          form.setFieldsValue({
            ...data,
            // [新增 2026-09-12] 区域为多选，需把「逗号分隔字符串」还原为数组供 Select mode="multiple" 回填
            area: data.area ? data.area.split(',').map(v => v.trim()).filter(Boolean) : [],
            install_date: data.install_date ? dayjs(data.install_date) : undefined,
            warranty_expire: data.warranty_expire ? dayjs(data.warranty_expire) : undefined,
            // [新增 2026-09-05] 编辑回填有效期字段（validity_until 需转为 dayjs 供 DatePicker 使用）
            validity_until: data.validity_until ? dayjs(data.validity_until) : undefined,
          });
          
          // 更新状态
          if (data.zone_type) {
            setSelectedZoneType(data.zone_type);
          }
          if (data.status) {
            setCurrentStatus(data.status);
          }
          
          // 加载设计文件和现场照片URL
          // [调整 2026-09-17] 后端字段允许 null（未关联），state 用 undefined 表达"无"
          setDesignPhotoUrl(data.design_photo ?? undefined);
          setInstallationPhotoUrl(data.installation_photo ?? undefined);
          // [新增 2026-09-17] 回填文件库引用（从标准库选择/上传登记的设计文件）
          setDesignFileId(data.design_file_id ?? undefined);
          // [新增 2026-09-17] 回填设计文件使用名（引用文件库时为使用名，否则为空走路径兜底）
          setDesignFileName(data.design_file_name ?? undefined);
          
          // 设置院区/楼栋/楼层选中值
          if (data.campus) {
            const foundCampus = campuses.find(c => c.name === data.campus);
            if (foundCampus) {
              setSelectedCampusId(foundCampus.id);
              // 加载楼栋列表
              campusApi.getBuildings(foundCampus.id).then(r => {
                setBuildings(r.items);
                if (data.building) {
                  const foundBuilding = r.items.find(b => `${b.building_number}-${b.name}` === data.building || b.name === data.building);
                  if (foundBuilding) {
                    setSelectedBuildingId(foundBuilding.id);
                    // 加载楼层列表
                    campusApi.getFloors(foundBuilding.id).then(r2 => {
                      setFloors(r2.items);
                      if (data.floor) {
                        // [调整 2026-09-17] 统一用 floorLabel 匹配（如 F3-门诊层），
                        // 并兼容仅存楼层名称 / 仅存楼层编号的历史数据
                        const foundFloor = r2.items.find(f =>
                          floorLabel(f) === data.floor
                          || f.floor_name === data.floor
                          || f.floor_number === data.floor,
                        );
                        if (foundFloor) {
                          setSelectedFloorId(foundFloor.id);
                        }
                      }
                    });
                  }
                }
              });
            }
          }
        })
        .catch(() => messageApi.error('获取标识信息失败'))
        .finally(() => setLoading(false));
    }
  }, [id]);

  // [修复 2026-09-04] 提交表单（支持新建模式下上传本地保存的文件）
  const handleSubmit = async (values: Record<string, unknown>) => {
    const oa_number = values.oa_number as string || '';

    setLoading(true);
    try {
      // [修复 2026-09-04] 新建时oa_number通过请求体传递（SignageCreate包含oa_number字段），
      // 更新时oa_number通过query参数传递，需从请求体中移除（后端SignageUpdate不含oa_number字段）
      const submitData = {
        ...values,
        status: currentStatus,
        install_date: values.install_date ? (values.install_date as dayjs.Dayjs).format('YYYY-MM-DD') : undefined,
        warranty_expire: values.warranty_expire ? (values.warranty_expire as dayjs.Dayjs).format('YYYY-MM-DD') : undefined,
        // [新增 2026-09-05] 提交有效期字段：长期标识置空到期日
        validity_type: (values.validity_type as string) || 'long_term',
        validity_until: values.validity_until ? (values.validity_until as dayjs.Dayjs).format('YYYY-MM-DD') : undefined,
        // [新增 2026-09-12] 所属区域：多选数组 → 逗号分隔字符串。
        // 仅在「楼层导视/宣传」下取值；区域为选填，未选即空串（不影响保存）。
        // 注意：此处必须"始终提交该键"（清空时提交空串 '')，不能省略为 undefined。
        // 后端更新接口使用 model_dump(exclude_unset=True)，省略键 == 不更新该字段，
        // 会导致「清空区域」与「切换所属区域类型后清除区域」都不落库、旧区域残留。
        area: selectedZoneType === '楼层导视/宣传' && Array.isArray(values.area)
          ? (values.area as string[]).join(',')
          : '',
        // [修复 2026-09-17] 显式传 null 而非 undefined：
        // undefined 会被 JSON.stringify 省略，后端 update 用 exclude_unset 便不会更新该字段，
        // 导致「删除设计文件 / 现场照片」保存后旧路径残留 —— 详情页仍显示已解除的关联。
        // 口径与下方 design_file_id、area 保持一致：清空必须提交 null（或空串）。
        design_photo: designPhotoUrl ?? null,
        installation_photo: installationPhotoUrl ?? null,
        // [新增 2026-09-17] 文件库引用：从标准库选择或上传登记后回填，
        // 引用统计与删除保护（共享文件不可删）依赖该字段
        // [调整 2026-09-17] 显式传 null：解除引用（改用本地新文件）时需要真正落库，
        // 若传 undefined 会被 JSON 序列化省略、后端 exclude_unset 会保留旧引用
        design_file_id: designFileId ?? null,
      };

      let newSignageId: number;
      
      if (isEdit) {
        delete (submitData as Record<string, unknown>).oa_number;
        // [新增 2026-09-09] 版本更新入口（recordHistory=true）保存后写入历史版本；普通编辑不记录
        await updateSignage(Number(id), submitData, oa_number, recordHistory);
        newSignageId = Number(id);
        messageApi.success(recordHistory ? '版本更新成功，本次修改已记录到历史版本' : '更新成功');
      } else {
        const result = await createSignage(submitData);
        newSignageId = result.id;
        messageApi.success('创建成功');
      }
      
      // [修复 2026-09-04] 上传本地保存的文件
      if (!isEdit) {
        const uploadPromises: Promise<void>[] = [];
        
        if (localDesignFile) {
          uploadPromises.push(
            uploadSignagePhoto(newSignageId, localDesignFile, 'design')
              .then(result => {
                setDesignPhotoUrl(result.file_path);
                console.log('设计文件上传成功');
              })
              .catch(error => {
                console.error('设计文件上传失败:', error);
                messageApi.warning('设计文件上传失败，请稍后手动上传');
              })
          );
        }
        
        if (localInstallationFile) {
          uploadPromises.push(
            uploadSignagePhoto(newSignageId, localInstallationFile, 'installation')
              .then(result => {
                setInstallationPhotoUrl(result.file_path);
                console.log('现场照片上传成功');
              })
              .catch(error => {
                console.error('现场照片上传失败:', error);
                messageApi.warning('现场照片上传失败，请稍后手动上传');
              })
          );
        }
        
        // 等待所有文件上传完成
        if (uploadPromises.length > 0) {
          await Promise.all(uploadPromises);
        }
      }
      
      navigate('/signages');
    } catch {
      messageApi.error(isEdit ? '更新失败' : '创建失败');
    } finally {
      setLoading(false);
    }
  };

  // [新增 2026-09-17] 删除标识：入口由标识列表移至编辑页，需 signage.delete 权限。
  // 成功后退回标识列表；失败则保留当前页面并恢复按钮，便于重试。
  const handleDelete = async () => {
    if (!id) return;
    setDeleting(true);
    try {
      await deleteSignage(Number(id));
      messageApi.success('删除成功');
      navigate('/signages');
    } catch {
      messageApi.error('删除失败');
      setDeleting(false);
    }
  };

  // [修复 2026-09-04] 上传设计文件（支持新建模式下保存到本地）
  const handleDesignUpload: UploadProps['customRequest'] = async (options) => {
    const file = options.file as File;
    
    if (!isEdit) {
      // [修复 2026-09-04] 新建模式：保存文件到本地，创建标识后再上传
      setLocalDesignFile(file);
      // 创建本地预览URL
      const localUrl = URL.createObjectURL(file);
      setDesignPhotoUrl(localUrl);
      messageApi.success('设计文件已选择，创建标识后将自动上传');
      options.onSuccess?.({ message: '文件已保存到本地' });
      return;
    }
    
    setUploadingDesign(true);
    try {
      const result = await uploadSignagePhoto(Number(id), file, 'design');
      setDesignPhotoUrl(result.file_path);
      // [调整 2026-09-17] 改为上传本地新文件后，不再指向原文件库记录：
      // 清空引用 ID 并展示本地文件名，避免出现「路径是新文件、名称却是旧引用名」的不一致。
      setDesignFileId(undefined);
      setDesignFileName(file.name);
      messageApi.success('设计文件上传成功');
      options.onSuccess?.(result);
    } catch (error) {
      messageApi.error('设计文件上传失败');
      options.onError?.(error as Error);
    } finally {
      setUploadingDesign(false);
    }
  };

  // [修复 2026-09-04] 上传现场照片（支持新建模式下保存到本地）
  const handleInstallationUpload: UploadProps['customRequest'] = async (options) => {
    const file = options.file as File;
    
    if (!isEdit) {
      // [修复 2026-09-04] 新建模式：保存文件到本地，创建标识后再上传
      setLocalInstallationFile(file);
      // 创建本地预览URL
      const localUrl = URL.createObjectURL(file);
      setInstallationPhotoUrl(localUrl);
      messageApi.success('现场照片已选择，创建标识后将自动上传');
      options.onSuccess?.({ message: '文件已保存到本地' });
      return;
    }
    
    setUploadingInstallation(true);
    try {
      const result = await uploadSignagePhoto(Number(id), file, 'installation');
      setInstallationPhotoUrl(result.file_path);
      messageApi.success('现场照片上传成功');
      options.onSuccess?.(result);
    } catch (error) {
      messageApi.error('现场照片上传失败');
      options.onError?.(error as Error);
    } finally {
      setUploadingInstallation(false);
    }
  };

  // [修复 2026-09-04] 根据参考页面重新设计的表单布局
  return (
    <div style={styles.container}>
      {/* 头部操作栏 */}
      <div style={styles.headerBar}>
        <div 
          style={{ fontSize: 14.5, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}
          onClick={() => navigate('/signages')}
        >
          <LeftOutlined /> 返回标识列表
        </div>
        <div style={{ flex: '1 1 40px', minWidth: 0 }}></div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, color: 'var(--text-2)' }}>
          状态
          <span style={styles.statusBadge}>
            {/* [修正 2026-09-21 / Q-8] 改用统一的 getSignageStatusLabel：
                原写法 `|| '正常'` 会把未知状态悄悄显示成「正常」，掩盖数据异常；
                现在取不到时回显原值，异常可见。 */}
            {getSignageStatusLabel(currentStatus)}
          </span>

        </div>
        {/* [新增 2026-09-09] 版本更新模式提示：此入口保存的修改才会写入历史版本 */}
        {recordHistory && (
          <span style={{
            fontSize: 12,
            color: 'var(--warn)',
            background: 'var(--warn-soft)',
            border: '1px solid var(--warn)',
            borderRadius: 6,
            padding: '4px 10px',
          }}>
            版本更新模式：保存后本次修改将记录到历史版本
          </span>
        )}
        {/* [新增 2026-09-17] 删除标识：入口由标识列表移入编辑页。
            仅编辑既有标识时提供，需 signage.delete 权限；版本更新模式不提供删除。 */}
        {isEdit && !recordHistory && hasPermission(user, PERM_SIGNAGE_DELETE) && (
          <Popconfirm
            title="确认删除该标识？"
            description="删除后不可恢复，该标识的照片、平面点位等关联数据会一并清理。"
            okText="确认删除"
            cancelText="取消"
            okButtonProps={{ danger: true, loading: deleting }}
            onConfirm={handleDelete}
          >
            <Button danger icon={<DeleteOutlined />} loading={deleting}>删除标识</Button>
          </Popconfirm>
        )}
        <Button
          type="primary"
          onClick={() => form.submit()}
          loading={loading}
          style={styles.saveButton}
        >
          {isEdit ? (recordHistory ? '保存版本更新' : '保存修改') : '创建标识'}
        </Button>
      </div>

      <Form form={form} layout="vertical" onFinish={handleSubmit}
        initialValues={{ status: 'normal', category_type: '标识标牌', zone_type: '院区导视/宣传', validity_type: 'long_term' }}>
        
        {/* 基本信息 */}
        <div style={styles.formCard}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionIndicator}></span> 基本信息
          </div>

          
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={12} md={8}>
              <div style={styles.formLabel}>标识名称 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="name" noStyle rules={[{ required: true, message: '请输入标识名称' }]}>
                <Input placeholder="请输入标识名称" style={styles.formInput} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <div style={styles.formLabel}>分类 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="category" noStyle rules={[{ required: true, message: '请选择分类' }]}>
                <Select placeholder="请选择分类" style={{ height: 34 }}>
                  {categories.map((c) => (
                    <Option key={c.id} value={c.name}>{c.name}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <div style={styles.formLabel}>类别 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="category_type" noStyle rules={[{ required: true, message: '请选择类别' }]}>
                <Select placeholder="请选择类别" style={{ height: 34 }}>
                  {CATEGORY_TYPE_OPTIONS.map((item) => (
                    <Option key={item.value} value={item.value}>{item.label}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>

          {/* [新增 2026-09-05] 标识有效期：长期标识不设到期时间；临时标识必须填写有效期限 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={12} md={8}>
              <div style={styles.formLabel}>标识有效期 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="validity_type" noStyle rules={[{ required: true, message: '请选择有效期类型' }]}>
                <Select
                  style={{ height: 34 }}
                  onChange={(v) => {
                    // 切换为长期标识时清空到期日；临时标识必须填写
                    if (v === 'long_term') form.setFieldsValue({ validity_until: undefined });
                  }}
                >
                  <Option value="long_term">长期标识</Option>
                  <Option value="temporary">临时标识</Option>
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={8}>
              <div style={styles.formLabel}>
                有效期限
                {validityType === 'temporary' && <span style={styles.requiredMark}> *</span>}
              </div>
              <Form.Item
                name="validity_until"
                noStyle
                rules={[({ getFieldValue }) => ({
                  validator(_, value) {
                    // 仅临时标识强制填写到期日
                    if (getFieldValue('validity_type') !== 'temporary' || value) return Promise.resolve();
                    return Promise.reject(new Error('临时标识必须填写有效期限'));
                  },
                })]}
              >
                <DatePicker
                  style={{ width: '100%', height: 34, background: 'var(--neu-bg)', borderStyle: 'dashed' }}
                  placeholder={validityType === 'temporary' ? '请选择有效期限' : '长期标识无需选择'}
                  disabled={validityType !== 'temporary'}
                />
              </Form.Item>
            </Col>
            {/* [新增 2026-09-08] 所属科室：单选可搜索下拉，数据源为科室管理列表；选择后标识即与对应科室关联 */}
            <Col xs={24} sm={12} md={8}>
              <div style={styles.formLabel}>所属科室 <span style={styles.optionalMark}>（选填）</span></div>
              <Form.Item name="department_id" noStyle>
                <Select
                  placeholder="请选择所属科室"
                  style={{ height: 34 }}
                  showSearch
                  allowClear
                  optionFilterProp="label"
                  filterOption={(input, option) => (option?.label ?? '').toLowerCase().includes(input.toLowerCase())}
                  options={departments.map((d) => ({ value: d.id, label: d.name }))}
                />
              </Form.Item>
            </Col>
          </Row>
          
          <div>
            <div style={styles.formLabel}>OA单号 <span style={styles.optionalMark}>（选填）</span></div>
            <Form.Item name="oa_number" noStyle>
              <Input placeholder="请输入OA单号（选填）" style={styles.dashedInput} />
            </Form.Item>

          </div>
        </div>

        {/* 物理规格 */}
        <div style={styles.formCard}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionIndicator}></span> 物理规格
          </div>
          
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <div style={styles.formLabel}>材质 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="material" noStyle>
                <Input placeholder="请输入材质" style={styles.formInput} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <div style={styles.formLabel}>规格尺寸（宽 × 高，mm）<span style={styles.requiredMark}>*</span></div>
              <Form.Item name="size_spec" noStyle>
                <Input placeholder="如：1200 x 800" style={styles.formInput} />
              </Form.Item>

            </Col>
          </Row>
        </div>

        {/* 位置信息 */}
        <div style={styles.formCard}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionIndicator}></span> 位置信息
          </div>
          
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>所属区域 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="zone_type" noStyle rules={[{ required: true, message: '请选择所属区域' }]}>
                <Select 
                  placeholder="请选择所属区域"
                  style={{ height: 34 }}
                  onChange={(value) => {
                    setSelectedZoneType(value);
                    if (value === '院区导视/宣传') {
                      form.setFieldsValue({ building: undefined, floor: undefined });
                    }
                    // [新增 2026-09-12] 区域仅在「楼层导视/宣传」下有意义，切换到其他类型时清空原选择
                    if (value !== '楼层导视/宣传') {
                      form.setFieldsValue({ area: [] });
                    }
                  }}
                >
                  {ZONE_TYPE_OPTIONS.map((item) => (
                    <Option key={item.value} value={item.value}>{item.label}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>院区 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="campus" noStyle rules={[{ required: true, message: '请选择院区' }]}>
                <Select 
                  placeholder="请选择院区"
                  style={{ height: 34 }}
                  value={selectedCampusId}
                  onChange={(value) => {
                    setSelectedCampusId(value);
                    const campusName = campuses.find(c => c.id === value)?.name;
                    // [调整 2026-09-12] 院区变更会重置楼栋/楼层，区域同属楼层维度，一并清空
                    form.setFieldsValue({ campus: campusName, building: undefined, floor: undefined, area: [] });
                  }}
                  showSearch
                  optionFilterProp="label"
                >
                  {campuses.map(c => (
                    <Option key={c.id} value={c.id}>{c.name}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>楼栋 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="building" noStyle rules={[{ 
                required: selectedZoneType === '楼栋导视/宣传' || selectedZoneType === '楼层导视/宣传', 
                message: '请选择楼栋' 
              }]}>
                <Select 
                  placeholder="请选择楼栋"
                  style={{ height: 34 }}
                  value={selectedBuildingId}
                  onChange={(value) => {
                    setSelectedBuildingId(value);
                    const b = buildings.find(b => b.id === value);
                    // [调整 2026-09-12] 楼栋变更会重置楼层，区域同属楼层维度，一并清空
                    form.setFieldsValue({ building: b ? `${b.building_number}-${b.name}` : undefined, floor: undefined, area: [] });
                  }}
                  allowClear
                  disabled={!selectedCampusId}
                  showSearch
                  optionFilterProp="label"
                >
                  {buildings.map(b => (
                    <Option key={b.id} value={b.id} label={`${b.building_number}-${b.name}`}>{b.building_number}-{b.name}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>楼层 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="floor" noStyle rules={[{ 
                required: selectedZoneType === '楼栋导视/宣传' || selectedZoneType === '楼层导视/宣传', 
                message: '请选择楼层' 
              }]}>
                <Select 
                  placeholder="请选择楼层"
                  style={{ height: 34 }}
                  value={selectedFloorId}
                  onChange={(value) => {
                    setSelectedFloorId(value);
                    const selected = floors.find(item => item.id === value);
                    // [调整 2026-09-12] 楼层变更后区域归属随之变化，清空原区域选择（区域列表由 useEffect 重新加载）
                    // [调整 2026-09-17] 楼层文本统一走 floorLabel（F3-门诊层）；
                    // 原局部变量名 floorLabel 与工具函数重名，已改为直接调用工具函数
                    form.setFieldsValue({ floor: selected ? floorLabel(selected) : undefined, area: [] });
                  }}
                  allowClear
                  disabled={!selectedBuildingId}
                  showSearch
                  optionFilterProp="label"
                >
                  {floors.map(f => (
                    // [调整 2026-09-17] 楼层选项统一展示 floorLabel（如 F3-门诊层）
                    <Option key={f.id} value={f.id} label={floorLabel(f)}>
                      {floorLabel(f)}
                    </Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
          </Row>
          

          
          {/* [新增 2026-09-12] 所属区域：仅「楼层导视/宣传」时显示。
              按需求「区域字段为非必选条件」——选填且支持多选：可不选、可选一个、也可选多个。
              选项来自「院区管理」中该楼层下已划分的区域；未选楼层时禁用。 */}
          {selectedZoneType === '楼层导视/宣传' && (
            <div style={{ marginBottom: 16 }}>
              <div style={styles.formLabel}>
                区域 <span style={styles.optionalMark}>（选填，可多选）</span>
              </div>
              <Form.Item name="area" noStyle>
                <Select
                  mode="multiple"
                  placeholder={selectedFloorId ? '可不选，也可以选择多个区域' : '请先选择楼层'}
                  style={{ width: '100%' }}
                  allowClear
                  disabled={!selectedFloorId}
                  optionFilterProp="label"
                  options={buildAreaOptions(areas)}
                />
              </Form.Item>
              <div style={styles.helpText}>
                {selectedFloorId
                  ? (areas.length > 0
                    ? '区域数据来源于「院区管理」中该楼层的区域划分；不选或选择多个均可保存'
                    : '该楼层尚未划分区域，可前往「院区管理」添加后再选（本项为选填，可直接保存）')
                  : '请先选择楼层后再选择区域（本项为选填）'}
              </div>
            </div>
          )}

          <div>
            <div style={styles.formLabel}>安装位置描述 <span style={styles.requiredMark}>*</span></div>
            <Form.Item name="location_desc" noStyle rules={[{ required: true, message: '请输入安装位置描述' }]}>
              <TextArea 
                rows={2} 
                placeholder="如：门诊前立柱旁" 
                style={{ background: 'var(--neu-bg)', borderColor: 'var(--line-soft)' }} 
              />
            </Form.Item>
            <div style={styles.helpText}>示例：门诊前立柱旁</div>
          </div>
        </div>

        {/* 显示文本 */}
        <div style={styles.formCard}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionIndicator}></span> 显示文本
          </div>
          
          <Row gutter={16} style={{ marginBottom: 16 }}>
            <Col xs={24} sm={12}>
              <div style={styles.formLabel}>中文文本 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="display_text_cn" noStyle rules={[{ required: true, message: '请输入中文文本' }]}>
                <Input 
                  placeholder="请输入中文展示文本" 
                  style={{ height: 44, background: 'var(--neu-bg)', borderColor: 'var(--line-soft)' }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <div style={styles.formLabel}>英文文本 <span style={styles.optionalMark}>（选填）</span></div>
              <Form.Item name="display_text_en" noStyle>
                <Input 
                  placeholder="请输入英文展示文本" 
                  style={{ height: 44, background: 'var(--neu-bg)', borderColor: 'var(--line-soft)', borderStyle: 'dashed' }}
                />
              </Form.Item>
            </Col>
          </Row>
          

        </div>

        {/* 安装信息 */}
        <div style={styles.formCard}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionIndicator}></span> 安装信息
          </div>
          
          <Row gutter={16}>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>安装日期 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="install_date" noStyle rules={[{ required: true, message: '请选择安装日期' }]}>
                <DatePicker 
                  style={{ width: '100%', height: 34, background: 'var(--neu-bg)' }} 
                  placeholder="选择安装日期"
                  onChange={(date) => {
                    if (date) {
                      // 计算质保到期日：安装日期 + 365天
                      const warrantyDate = date.add(365, 'day');
                      form.setFieldsValue({ warranty_expire: warrantyDate });
                    }
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>质保到期日 <span style={styles.optionalMark}>（自动计算）</span></div>
              <Form.Item name="warranty_expire" noStyle>
                <DatePicker style={{ width: '100%', height: 34, background: 'var(--neu-bg)', borderStyle: 'dashed' }} placeholder="选择质保到期日" />
              </Form.Item>
              <div style={styles.helpText}>默认安装日期 + 365天，可手动修改</div>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>供应商 <span style={styles.requiredMark}>*</span></div>
              <Form.Item name="manufacturer" noStyle rules={[{ required: true, message: '请选择供应商' }]}>
                <Select 
                  placeholder="请选择供应商" 
                  style={{ height: 34 }} 
                  allowClear
                  onChange={(value) => {
                    // 根据选择的供应商自动填充联系电话
                    if (value) {
                      const selectedSupplier = suppliers.find(s => s.name === value);
                      if (selectedSupplier?.phone) {
                        form.setFieldsValue({ vendor_contact: selectedSupplier.phone });
                      }
                    }
                  }}
                >
                  {suppliers.map((s) => (
                    <Option key={s.id} value={s.name}>{s.name}</Option>
                  ))}
                </Select>
              </Form.Item>
            </Col>
            <Col xs={24} sm={12} md={6}>
              <div style={styles.formLabel}>联系电话 <span style={styles.optionalMark}>（选填）</span></div>
              <Form.Item name="vendor_contact" noStyle>
                <Input placeholder="支持手机或固定电话" style={styles.formInput} />
              </Form.Item>
              <div style={styles.helpText}>默认使用供应商设置中的联系电话</div>
            </Col>
          </Row>
        </div>

        {/* 附件上传 */}
        <div style={styles.formCard}>
          <div style={styles.sectionHeader}>
            <span style={styles.sectionIndicator}></span> 附件上传
          </div>
          
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <div style={styles.uploadArea}>
                {/* [修复 2026-09-07] 设计文件为非必填项，移除必填标记 */}
                <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>
                  设计文件
                  {/* [新增 2026-09-17] 从文件库选择标准设计文件（引用共享，不复制文件）。
                      仅对拥有文件库查看权限（file.view）的账号展示该入口，
                      避免无权限用户打开选择器后接口返回 403 */}
                  {hasPermission(user, PERM_FILE_VIEW) && (
                    <a
                      style={{ marginLeft: 8, fontSize: 12 }}
                      onClick={() => {
                        // [新增 2026-09-17] 同分类约束：未选分类时无法判定可选范围，先引导选择
                        if (!selectedCategory) {
                          messageApi.warning('请先选择标识分类，再选择标准设计文件');
                          return;
                        }
                        setStandardPickerOpen(true);
                      }}
                    >
                      从标准库选择
                    </a>
                  )}
                </div>
                <div style={styles.uploadBox}>
                  <Upload
                    accept=".jpg,.jpeg,.png,.webp,.ai,.pdf"
                    showUploadList={false}
                    customRequest={handleDesignUpload}
                    disabled={uploadingDesign}
                  >
                    <div style={{ cursor: 'pointer' }}>
                      点击或拖拽上传 · 支持 JPG/PNG/WebP/AI/PDF · ≤20MB
                    </div>
                  </Upload>
                </div>
                {designPhotoUrl && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                    <span style={{ fontSize: 12, background: 'var(--accent-soft)', color: 'var(--accent)', borderRadius: 4, padding: '2px 6px' }}>
                      {designPhotoUrl.startsWith('blob:') && localDesignFile
                        ? localDesignFile.name.split('.').pop()?.toUpperCase()
                        : getFileExtension(designPhotoUrl).toUpperCase()}
                    </span>
                    <div>
                      <span style={{ fontSize: 12 }}>
                        {/* [调整 2026-09-17] 名称优先级：文件库使用名 > 本地待上传文件名 > 路径文件名。
                            引用标准设计文件时展示「文件管理」中设置的使用名，不再显示落盘随机名 */}
                        {designFileName
                          || (designPhotoUrl.startsWith('blob:') && localDesignFile
                            ? localDesignFile.name
                            : designPhotoUrl.split('/').pop())}
                      </span>
                      {!isEdit && localDesignFile && (
                        <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>
                          创建标识后自动上传
                        </div>
                      )}
                    </div>
                    <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--accent)', cursor: 'pointer' }}>
                      预览
                    </span>
                    <span 
                      style={{ fontSize: 12, color: 'var(--danger)', cursor: 'pointer' }}
                      onClick={() => {
                        setDesignPhotoUrl(undefined);
                        setLocalDesignFile(null);
                        // [新增 2026-09-17] 解除文件库引用（随之释放共享引用保护）
                        setDesignFileId(undefined);
                        setDesignFileName(undefined);
                        setDesignFileCategoryName(undefined);
                      }}
                    >
                      删除
                    </span>
                  </div>
                )}
              </div>
            </Col>
            <Col xs={24} sm={12}>
              <div style={styles.uploadArea}>
                <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 6 }}>现场照片</div>
                <div style={styles.uploadBox}>
                  <Upload
                    accept="image/*"
                    showUploadList={false}
                    customRequest={handleInstallationUpload}
                    disabled={uploadingInstallation}
                  >
                    <div style={{ cursor: 'pointer' }}>
                      点击或拖拽上传 · 支持 JPG/PNG/WebP · ≤20MB
                    </div>
                  </Upload>
                </div>

                {installationPhotoUrl && (
                  <div style={{ marginTop: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <Image
                        src={installationPhotoUrl?.startsWith('blob:') ? installationPhotoUrl : (getOriginalUrl(installationPhotoUrl) || installationPhotoUrl)}
                        width={60}
                        height={60}
                        style={{ objectFit: 'cover', borderRadius: 4 }}
                        preview={{ mask: <EyeOutlined /> }}
                      />
                      <div>
                        <span 
                          style={{ fontSize: 12, color: 'var(--danger)', cursor: 'pointer' }}
                          onClick={() => {
                            setInstallationPhotoUrl(undefined);
                            setLocalInstallationFile(null);
                          }}
                        >
                          删除
                        </span>
                        {!isEdit && localInstallationFile && (
                          <div style={{ fontSize: 12, color: 'var(--text-2)', marginTop: 2 }}>
                            创建标识后自动上传
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </Col>
          </Row>
        </div>

        {/* 底部操作栏 */}
        <div style={styles.footerBar}>
          <Button onClick={() => navigate('/signages')} style={styles.cancelButton}>取消</Button>
          <Button type="primary" htmlType="submit" loading={loading} style={styles.saveButton}>
            {isEdit ? (recordHistory ? '保存版本更新' : '保存修改') : '创建标识'}
          </Button>

        </div>
      </Form>

      {/* [新增 2026-09-17] 标准设计文件选择器：选中即引用该文件（路径 + 文件库引用ID） */}
      <StandardFilePicker
        open={standardPickerOpen}
        onClose={() => setStandardPickerOpen(false)}
        // [新增 2026-09-17] 传入当前标识分类：只允许选择同分类的标准设计文件（限制跨类别引用）
        categoryName={selectedCategory || undefined}
        onSelect={(file: StandardFileOption) => {
          setDesignPhotoUrl(file.stored_path);
          setDesignFileId(file.id);
          // [新增 2026-09-17] 使用文件库中的「使用名」作为展示名（需求：引用时用文件管理里的使用名）
          setDesignFileName(file.name);
          // [新增 2026-09-17] 记录该文件的分类，供分类变更时提前提示引用不一致
          setDesignFileCategoryName(file.category_name || undefined);
          setLocalDesignFile(null);
          messageApi.success(`已引用标准设计文件「${file.name}」，保存后生效`);
        }}
      />
    </div>
  );
};

// [重构 2026-09-21 / 代码质量审计 Q-8] 原先此处另有一份 STATUS_OPTIONS 副本，
// ⚠️ 它**缺少 repair_in_progress（维修处理中）** —— 编辑一个正处于维修中的标识时，
// 状态下拉框无法回显该状态（会显示为空或错值），且用户一旦保存就会把状态改错。
// 现统一引用权威源 constants/signageStatus.ts 的 SIGNAGE_STATUS_SELECT_OPTIONS。

const CATEGORY_TYPE_OPTIONS = [
  { value: '标识标牌', label: '标识标牌' },
  { value: '平面宣传', label: '平面宣传' },
];

const ZONE_TYPE_OPTIONS = [
  { value: '院区导视/宣传', label: '院区导视/宣传', description: '只需选择所属院区' },
  { value: '楼栋导视/宣传', label: '楼栋导视/宣传', description: '需要选择到具体楼层' },
  { value: '楼层导视/宣传', label: '楼层导视/宣传', description: '需要选择到具体楼层' },
];

// [新增 2026-09-12] 区域类型中文名，用于区域多选下拉的辅助说明（与「院区管理」展示口径一致）
const AREA_TYPE_LABELS: Record<string, string> = {
  east: '东区',
  west: '西区',
  merged: '合并区域',
};

/**
 * [新增 2026-09-12] 构建区域多选下拉选项。
 * 说明：区域选择以「区域名称」作为取值（与 campus/building/floor 的存名口径一致），
 * 而取消区域类型互斥后同一楼层允许出现重名区域，若不按名称去重会产生重复选项、
 * 导致多选值冲突与 React key 重复告警，故此处按名称去重保留首个。
 */
const buildAreaOptions = (areas: Area[]) => {
  const seen = new Set<string>();
  return areas
    .filter(a => (seen.has(a.name) ? false : (seen.add(a.name), true)))
    .map(a => ({
      value: a.name,
      label: `${a.name}（${AREA_TYPE_LABELS[a.area_type] || a.area_type}）`,
    }));
};

// [修复 2026-09-04] 获取文件扩展名
const getFileExtension = (filePath: string): string => {
  return filePath.split('.').pop() || '';
};

export default SignageForm;