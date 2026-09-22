// [修复 2026-09-05] 标识标记页面：可视化缩放/平移、点击绑定标识、Pin 分类着色、详情/解绑/重绑
import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
// [修复 2026-09-17] 移除静态 message：改用 App.useApp() 实例（静态方法无法消费动态主题）
import { App, Card, Select, Button, Space, Tag, Modal, Table, Input, Typography } from 'antd';
import { ZoomInOutlined, ZoomOutOutlined, ReloadOutlined, EnvironmentOutlined } from '@ant-design/icons';
import {
  getFloorPlanList, getFloorPlanPoints, createFloorPlanPoint, deleteFloorPlanPoint, getSignageList, getSignage,
  // [新增 2026-09-14] 预警标识清单：用于把预警标识渲染为红色方框 + 感叹号
  getAlertedSignages,
} from '../../api/signage';
import type { FloorPlan, SignagePoint, Signage } from '../../api/signage';
import { getActiveSignageCategories } from '../../api/signage-settings';
import type { SignageCategory } from '../../api/signage-settings';
import SafeImage from '../../components/SafeImage';
// [修复 2026-09-05] 标记形状渲染：与分类设置共用同一套形状定义
// [新增 2026-09-14] 追加预警标识专用形状（红色方框 + 白色感叹号）
import { renderMarkerShape, renderAlertMarkerShape, ALERT_MARKER_COLOR } from '../../components/MarkerShape';
// [修复 2026-09-05] 标识状态映射：与标识巡检共用同一套状态常量
import { SIGNAGE_STATUS_MAP } from '../../constants/signageStatus';

const { Text } = Typography;

const DEFAULT_PIN_COLOR = '#1565B8';
const CATEGORY_OPTIONS = ['院区平面', '楼层平面'];
// [修复 2026-09-05] 状态映射改用共享常量：与标识巡检等页面统一状态口径
const STATUS_MAP = SIGNAGE_STATUS_MAP;

// [修复 2026-09-05] Pin 标记点（React.memo 提升 500+ 点位渲染性能）：
// 形状取自标识分类配置，与分类颜色组合渲染，形状中心对准点位坐标
// [调整 2026-09-14] 预警标识不再按分类渲染，统一为红色方框 + 白色感叹号，突出「需要处理」
const PIN_SIZE = 24;
interface PinProps {
  point: SignagePoint;
  color: string;
  shape: string;
  /** [新增 2026-09-14] 是否处于预警状态：为 true 时忽略分类形状/颜色，渲染预警样式 */
  alerted?: boolean;
  /**
   * [修复 2026-09-09] 反向缩放系数（= 1 / zoom）：
   * 舞台带 scale(zoom)，若不做抵消记号会随缩放变大变小；此处按 1/zoom 反向缩放，
   * 使记号在屏幕上始终保持固定尺寸（同地图 App 的图钉），而位置仍随平面图缩放。
   */
  scale?: number;
  onSelect: (p: SignagePoint) => void;
}
const Pin = React.memo(({ point, color, shape, alerted = false, scale = 1, onSelect }: PinProps) => (
  <div
    onClick={(e) => { e.stopPropagation(); onSelect(point); }}
    style={{
      position: 'absolute',
      left: `${point.x_percent}%`,
      top: `${point.y_percent}%`,
      // 位置由百分比定位（随平面图缩放移动），尺寸用反向缩放保持恒定
      transform: `translate(-50%, -50%) scale(${scale})`,
      cursor: 'pointer',
      // 预警标识层级略高，避免被相邻的普通标记遮挡
      zIndex: alerted ? 11 : 10,
      filter: 'drop-shadow(0 2px 3px rgba(0,0,0,0.35))',
      transition: 'transform 0.12s ease',
    }}
    onMouseEnter={(e) => { e.currentTarget.style.transform = `translate(-50%, -50%) scale(${scale * 1.15})`; }}
    onMouseLeave={(e) => { e.currentTarget.style.transform = `translate(-50%, -50%) scale(${scale})`; }}
  >
    <svg width={PIN_SIZE} height={PIN_SIZE} viewBox={`0 0 ${PIN_SIZE} ${PIN_SIZE}`}>
      {alerted ? renderAlertMarkerShape(PIN_SIZE) : renderMarkerShape(shape, color, PIN_SIZE)}
    </svg>
  </div>
));

const MarkerEditor: React.FC = () => {
  // [修复 2026-09-17] 从 App context 获取 message：与全局主题、国际化保持一致
  const { message } = App.useApp();
  const [floorPlans, setFloorPlans] = useState<FloorPlan[]>([]);
  const [selectedPlan, setSelectedPlan] = useState<number | undefined>();
  const [points, setPoints] = useState<SignagePoint[]>([]);
  const [signages, setSignages] = useState<Signage[]>([]);
  // [修复 2026-09-05] 分类标记样式映射：分类名 -> { 颜色, 形状 }
  const [catStyleMap, setCatStyleMap] = useState<Record<string, { color: string; shape: string }>>({});
  // [新增 2026-09-14] 预警标识映射：标识ID -> 预警类型名数组；不在映射中即为正常标识
  const [alertedMap, setAlertedMap] = useState<Record<number, string[]>>({});
  const [loading, setLoading] = useState(false);
  // [修复 2026-09-05] 标记模式开关：进入标记模式后才允许点击平面图放置标识
  const [markerMode, setMarkerMode] = useState(false);
  // [新增 2026-09-14] 分类图例折叠状态：窄屏下可收起，避免遮挡底图与底部悬浮工具栏
  const [legendCollapsed, setLegendCollapsed] = useState(false);

  // [修复 2026-09-05] 缩放/平移状态
  const [zoom, setZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  // [新增 2026-09-09] 底图自适应画板：测量视口与底图尺寸，计算"完整可见"的基准显示尺寸（contain 适配）
  const [viewportSize, setViewportSize] = useState({ w: 0, h: 0 });
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const fitRef = useRef<{ offsetX: number; offsetY: number } | null>(null);
  // 拖拽状态
  const draggingRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const movedRef = useRef(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const transformRef = useRef({ zoom: 1, panX: 0, panY: 0 });

  // 绑定 / 详情模态
  const [bindModal, setBindModal] = useState(false);
  const [pendingCoord, setPendingCoord] = useState<{ x: number; y: number } | null>(null);
  const [rebindPoint, setRebindPoint] = useState<SignagePoint | null>(null);
  const [detailPoint, setDetailPoint] = useState<SignagePoint | null>(null);
  // [修复 2026-09-05] 点位详情对应的标识完整信息：按标识 ID 单独拉取，
  // 避免依赖绑定弹窗那套分页列表（每页仅 20 条）导致点了点位却查不到标识
  const [detailSignage, setDetailSignage] = useState<Signage | null>(null);
  const [bindSearch, setBindSearch] = useState('');
  const [bindPage, setBindPage] = useState(1);
  const [selectedSignageId, setSelectedSignageId] = useState<number | undefined>();
  const [bindLoading, setBindLoading] = useState(false);

  const plan = floorPlans.find((p) => p.id === selectedPlan);

  useEffect(() => {
    getFloorPlanList()
      .then((list) => {
        setFloorPlans(list);
        // [修复 2026-09-05] 默认选中第一张平面图，避免进入页面后底图空白、必须手动选择才显示
        if (list.length) setSelectedPlan(list[0].id);
      })
      .catch(() => message.error('获取平面图列表失败'));
    // [修复 2026-09-05] 改用 /signage-categories/active：
    // 原 page_size=200 超出后端上限(le=100)导致 422；该接口无分页且只返回启用分类，正适合构建点位配色表
    getActiveSignageCategories().then((list) => {
      const m: Record<string, { color: string; shape: string }> = {};
      list.forEach((c: SignageCategory) => {
        m[c.name] = { color: c.color || DEFAULT_PIN_COLOR, shape: c.shape || 'circle' };
      });
      setCatStyleMap(m);
    }).catch(() => {});
    // [新增 2026-09-14] 加载预警标识清单（地图上以红色方框 + 感叹号突出显示）。
    // 接口需要「查看标识预警」权限，无权限时静默降级为空集合，不影响标记功能本身。
    getAlertedSignages().then((items) => {
      const m: Record<number, string[]> = {};
      items.forEach((it) => { m[it.id] = it.alerts; });
      setAlertedMap(m);
    }).catch(() => setAlertedMap({}));
    loadSignages('');
  }, []);

  useEffect(() => {
    if (selectedPlan) {
      setLoading(true);
      setZoom(1); setPanX(0); setPanY(0);
      setImgSize(null); // [新增 2026-09-09] 切换平面图后等新底图加载完成再重新适配
      getFloorPlanPoints(selectedPlan)
        .then(setPoints)
        .catch(() => message.error('获取点位失败'))
        .finally(() => setLoading(false));
    } else {
      setPoints([]);
    }
  }, [selectedPlan]);

  useEffect(() => { transformRef.current = { zoom, panX, panY }; }, [zoom, panX, panY]);

  // [新增 2026-09-09] 测量画布视口尺寸（ResizeObserver 跟随窗口/卡片宽度变化），用于底图 contain 适配
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const measure = () => setViewportSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    window.addEventListener('resize', measure);
    return () => { ro.disconnect(); window.removeEventListener('resize', measure); };
  }, [selectedPlan]);

  // [新增 2026-09-09] 底图加载完成后记录固有尺寸（SVG 无固有尺寸属性时用渲染尺寸推算比例）
  const handleBaseImageLoad = (e: React.SyntheticEvent<HTMLImageElement, Event>) => {
    const el = e.currentTarget;
    const nw = el.naturalWidth || el.clientWidth;
    const nh = el.naturalHeight || el.clientHeight;
    if (nw > 0 && nh > 0) setImgSize({ w: nw, h: nh });
  };

  // [新增 2026-09-09] 计算底图"完整可见"的显示尺寸与居中偏移（等比 contain 适配视口），
  // 解决此前按宽度铺满导致大图超高、需滚动才能看全的问题
  const fit = useMemo(() => {
    if (!imgSize || !viewportSize.w || !viewportSize.h) return null;
    const scale = Math.min(viewportSize.w / imgSize.w, viewportSize.h / imgSize.h);
    const w = imgSize.w * scale;
    const h = imgSize.h * scale;
    return { w, h, offsetX: (viewportSize.w - w) / 2, offsetY: (viewportSize.h - h) / 2 };
  }, [imgSize, viewportSize]);

  useEffect(() => { fitRef.current = fit ? { offsetX: fit.offsetX, offsetY: fit.offsetY } : null; }, [fit]);

  // [新增 2026-09-09] 悬浮工具栏动作（缩放按钮沿用原有 1.2 倍步进与 0.2~5 倍限幅）
  const toggleMarkerMode = () => {
    if (!markerMode && !selectedPlan) { message.warning('请先选择平面图'); return; }
    setMarkerMode((m) => !m);
  };
  const zoomIn = () => { setZoom((z) => Math.min(5, z * 1.2)); setPanX(0); setPanY(0); };
  const zoomOut = () => { setZoom((z) => Math.max(0.2, z / 1.2)); setPanX(0); setPanY(0); };
  const resetView = () => { setZoom(1); setPanX(0); setPanY(0); };

  // [修复 2026-09-05] 绑定列表：普通绑定排除已被标记的标识（每个标识仅可标记一次）；
  // 重新绑定时不过滤，允许在全部标识中替换选择
  const loadSignages = useCallback((search: string, page = 1, forRebind = false) => {
    setBindLoading(true);
    getSignageList({
      page_size: 20,
      page,
      search: search || undefined,
      exclude_marked: forRebind ? undefined : true,
    })
      .then((r) => { setSignages(r.items); })
      .catch(() => message.error('获取标识列表失败'))
      .finally(() => setBindLoading(false));
  }, []);

  // [修复 2026-09-05] 滚轮缩放（以光标为锚点），需 passive:false 阻止页面滚动。
  // 关键修复：依赖改为 selectedPlan——此前空依赖导致 effect 在首帧执行时底图尚未挂载
  // （viewportRef.current 为 null），wheel 监听器永远绑定不上，滚轮缩放完全失效
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const { zoom: z, panX: px, panY: py } = transformRef.current;
      // [修复 2026-09-09] 底图 contain 居中后舞台存在基准偏移，缩放锚点计算需扣除，
      // 否则以光标为锚的缩放会出现位置漂移
      const ox = fitRef.current?.offsetX ?? 0;
      const oy = fitRef.current?.offsetY ?? 0;
      const factor = e.deltaY < 0 ? 1.12 : 0.89;
      const newZoom = Math.min(5, Math.max(0.2, z * factor));
      const cx = (mx - ox - px) / z;
      const cy = (my - oy - py) / z;
      setZoom(newZoom);
      setPanX(mx - ox - cx * newZoom);
      setPanY(my - oy - cy * newZoom);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [selectedPlan]);

  // [修复 2026-09-05] 拖拽平移
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current) return;
      movedRef.current = true;
      const dx = e.clientX - draggingRef.current.x;
      const dy = e.clientY - draggingRef.current.y;
      setPanX(draggingRef.current.panX + dx);
      setPanY(draggingRef.current.panY + dy);
    };
    const onUp = () => { draggingRef.current = null; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, []);

  const onStageMouseDown = (e: React.MouseEvent) => {
    movedRef.current = false;
    draggingRef.current = { x: e.clientX, y: e.clientY, panX, panY };
  };

  // [修复 2026-09-05] 点击画布添加标记（非拖拽时），坐标基于底图实际渲染矩形计算百分比。
  // 仅在标记模式下允许放置标识，其余时候点击不触发任何放置动作
  const onStageClick = (e: React.MouseEvent) => {
    if (movedRef.current) return;
    if (!markerMode) { message.info('请先点击「标识标记」按钮进入标记模式'); return; }
    if (!selectedPlan) { message.warning('请先选择平面图'); return; }
    const stage = stageRef.current;
    if (!stage) return;
    const rect = stage.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * 1000) / 10;
    const y = Math.round(((e.clientY - rect.top) / rect.height) * 1000) / 10;
    if (x < 0 || x > 100 || y < 0 || y > 100) return;
    setPendingCoord({ x, y });
    setRebindPoint(null);
    setSelectedSignageId(undefined);
    setBindSearch('');
    setBindPage(1);
    loadSignages('', 1, false);
    setBindModal(true);
  };

  // [修复 2026-09-05] 点位标记样式：直接使用点位自带的分类信息（后端随点位返回）。
  // 修复 Bug：此前依赖绑定弹窗的分页标识列表查分类，而该列表已被 exclude_marked 过滤，
  // 已标记的标识不在其中，导致标记点永远回退为默认蓝色圆形
  const styleOf = useCallback((p: SignagePoint): { color: string; shape: string } => {
    if (p.signage_category && catStyleMap[p.signage_category]) return catStyleMap[p.signage_category];
    return { color: p.pin_color || DEFAULT_PIN_COLOR, shape: 'circle' };
  }, [catStyleMap]);

  // [新增 2026-09-14] 分类图例数据：直接复用标记点位的配色表（同一数据源），
  // 保证「图例所示形状/颜色」与「地图上实际标记」完全一致；
  // 顺序沿用「标识分类设置」返回的顺序（catStyleMap 按接口列表顺序构建）。
  const legendItems = useMemo(
    () => Object.entries(catStyleMap).map(([name, v]) => ({ name, color: v.color, shape: v.shape })),
    [catStyleMap],
  );

  const handleBindOk = async () => {
    if (!selectedSignageId || !pendingCoord) { message.warning('请选择一条标识'); return; }
    try {
      const payload: any = {
        signage_id: selectedSignageId,
        x_percent: pendingCoord.x,
        y_percent: pendingCoord.y,
      };
      if (rebindPoint) {
        // [修复 2026-09-05] 先建后删：创建成功后再移除旧点位，避免创建失败导致旧标记丢失；
        // exclude_point_id 使后端重复校验豁免本点位自身的旧绑定
        const created = await createFloorPlanPoint(rebindPoint.floor_plan_id, payload, rebindPoint.id);
        await deleteFloorPlanPoint(rebindPoint.id);
        setPoints((prev) => prev.filter((p) => p.id !== rebindPoint.id).concat(created));
      } else {
        const created = await createFloorPlanPoint(selectedPlan as number, payload);
        setPoints((prev) => prev.concat(created));
      }
      message.success('绑定成功');
      setBindModal(false);
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '绑定失败');
    }
  };

  const handleUnbind = async (p: SignagePoint) => {
    try {
      await deleteFloorPlanPoint(p.id);
      setPoints((prev) => prev.filter((x) => x.id !== p.id));
      setDetailPoint(null);
      message.success('已解绑');
    } catch {
      message.error('解绑失败');
    }
  };

  const openRebind = (p: SignagePoint) => {
    setDetailPoint(null);
    setRebindPoint(p);
    setPendingCoord({ x: p.x_percent, y: p.y_percent });
    setSelectedSignageId(undefined);
    setBindSearch('');
    setBindPage(1);
    loadSignages('', 1, true);
    setBindModal(true);
  };

  // [修复 2026-09-05] 打开点位详情时按标识 ID 拉取完整信息（含安装/质保时间与现场安装照片）
  useEffect(() => {
    if (!detailPoint) { setDetailSignage(null); return; }
    let alive = true;
    setDetailSignage(null);
    getSignage(detailPoint.signage_id)
      .then((s) => { if (alive) setDetailSignage(s); })
      .catch(() => { if (alive) setDetailSignage(null); });
    return () => { alive = false; };
  }, [detailPoint]);

  // [修复 2026-09-05] 位置精确到楼层：院区 / 楼栋 / 楼层；标识自身楼层缺失时回退到当前平面图关联的楼层
  const locationOf = (s: Signage): string => {
    const parts = [s.campus, s.building, s.floor || plan?.floor || plan?.floor_code].filter(Boolean);
    return parts.length ? parts.join(' / ') : '-';
  };

  const renderCatTag = (c?: string) => {
    const color = c ? catStyleMap[c]?.color : undefined;
    return <Tag color={color ? 'cyan' : 'default'} style={color ? { borderColor: color, color } : undefined}>{c}</Tag>;
  };

  const bindColumns = [
    { title: '编码', dataIndex: 'code', key: 'code', width: 120, render: (t: string) => <Text strong>{t}</Text> },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '分类', dataIndex: 'category', key: 'category', width: 120, render: (c: string) => renderCatTag(c) },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => {
        const m = STATUS_MAP[s] || { color: 'default', label: s };
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
  ];

  // [修复 2026-09-09] 记号保持固定屏幕尺寸（同地图 App 图钉）：
  // 传入 1/zoom 反向缩放，抵消舞台 scale(zoom)；位置仍按百分比随平面图缩放移动。
  const markerScale = 1 / (zoom || 1);

  const markers = useMemo(() => points.map((p) => {
    const st = styleOf(p);
    // [新增 2026-09-14] 预警标识统一以红色方框 + 感叹号渲染（忽略分类的形状与颜色）
    const alerted = !!alertedMap[p.signage_id];
    return <Pin key={p.id} point={p} color={st.color} shape={st.shape} alerted={alerted} scale={markerScale} onSelect={setDetailPoint} />;
  }), [points, styleOf, markerScale, alertedMap]);

  return (
    <div>
      <Card style={{ marginBottom: 16 }}>
        <Space wrap>
          <Select
            placeholder="选择平面图"
            style={{ width: 320 }}
            value={selectedPlan}
            onChange={setSelectedPlan}
            showSearch
            optionFilterProp="label"
            options={floorPlans.map((p) => ({ value: p.id, label: `${p.name}（${p.category}）` }))}
          />
          <Tag color="blue">类别筛选</Tag>
          <Select
            placeholder="按类别筛选"
            style={{ width: 150 }}
            allowClear
            onChange={(c) => getFloorPlanList(c ? { category: c } : {})
              .then((list) => {
                setFloorPlans(list);
                // [修复 2026-09-05] 筛选后同步重置选中项，避免残留已不在结果内的平面图
                setSelectedPlan(list.length ? list[0].id : undefined);
              })
              .catch(() => {})}
            options={CATEGORY_OPTIONS.map((c) => ({ value: c, label: c }))}
          />
          <Tag>点位: {points.length}</Tag>
          {/* [修复 2026-09-09] 标记开关与缩放控件移至地图悬浮工具栏（随地图显示），无需上下滚动找按钮 */}
          <Text type="secondary">滚轮缩放 · 拖拽平移 · 点击地图下方「标识标记」进入标记模式后放置标识</Text>
        </Space>
      </Card>

      <Card title="标识标记">
        {plan?.image_url ? (
          <div
            ref={viewportRef}
            onMouseDown={onStageMouseDown}
            onClick={onStageClick}
            style={{
              position: 'relative', overflow: 'hidden', height: 600,
              background: 'var(--neu-page-bg)', borderRadius: 8,
              // [修复 2026-09-05] 标记模式下用十字光标提示可放置，其余时候抓取光标提示可平移
              cursor: markerMode ? 'crosshair' : 'grab',
              border: '1px solid var(--line-soft)',
            }}
          >
            <div
              ref={stageRef}
              style={fit ? {
                // [新增 2026-09-09] 底图按 contain 等比适配并居中：默认完整可见，不再超出画板需滚动查看
                position: 'absolute', left: fit.offsetX, top: fit.offsetY,
                width: fit.w, height: fit.h,
                transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
                transformOrigin: '0 0',
              } : {
                // 底图加载完成前的过渡布局：按宽度铺满、高度随比例
                position: 'absolute', top: 0, left: 0, width: '100%', height: 'auto',
                transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
                transformOrigin: '0 0',
              }}
            >
              <SafeImage
                src={plan.image_url}
                alt={plan.name}
                preview={false}
                onLoad={handleBaseImageLoad}
                wrapperStyle={{ display: 'block', width: '100%' }}
                style={{ display: 'block', width: '100%', maxWidth: 'none', userSelect: 'none' }}
              />
              {markers}
            </div>
            {/* [新增 2026-09-09] 标记模式提示条：进入标记模式后顶部提示当前操作 */}
            {markerMode && (
              <div style={{ position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)', zIndex: 20, background: 'var(--accent)', color: '#fff', fontSize: 12.5, padding: '5px 14px', borderRadius: 999, boxShadow: 'var(--neu-accent-raised)' }}>
                标记模式：点击地图放置标识
              </div>
            )}
            {/* [新增 2026-09-09] 悬浮工具栏：标记开关/缩放/复位随地图悬浮显示，阻止冒泡避免触发放置标记 */}
            <div
              style={{
                position: 'absolute', left: '50%', bottom: 16, transform: 'translateX(-50%)', zIndex: 20,
                display: 'flex', alignItems: 'center', gap: 8,
                background: 'var(--neu-bg)', border: '1px solid var(--line-soft)',
                borderRadius: 999, padding: '6px 12px', boxShadow: 'var(--neu-raised-md)',
              }}
              onClick={(e) => e.stopPropagation()}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <Button type={markerMode ? 'primary' : 'default'} danger={markerMode} icon={<EnvironmentOutlined />} onClick={toggleMarkerMode}>
                {markerMode ? '退出标记模式' : '标识标记'}
              </Button>
              <Button size="small" icon={<ZoomOutOutlined />} onClick={zoomOut} title="缩小" />
              <span style={{ fontSize: 12, color: 'var(--text-2)', minWidth: 44, textAlign: 'center' }}>{Math.round(zoom * 100)}%</span>
              <Button size="small" icon={<ZoomInOutlined />} onClick={zoomIn} title="放大" />
              <Button size="small" icon={<ReloadOutlined />} onClick={resetView}>复位</Button>
            </div>

            {/* [新增 2026-09-14] 分类图例：置于地图左下角，说明各标识分类对应的标记图标样式（形状 + 颜色）。
                数据与地图上的标记点同源，说明即所见；点击面板头部可折叠，避免窄屏时遮挡底图。
                沿用悬浮工具栏的做法阻止冒泡，避免点击图例被误判为「在地图上放置标记」或触发拖拽平移 */}
            {legendItems.length > 0 && (
              <div
                style={{
                  position: 'absolute', left: 12, bottom: 12, zIndex: 20,
                  background: 'var(--neu-bg)', border: '1px solid var(--line-soft)',
                  borderRadius: 10, boxShadow: 'var(--neu-raised-md)',
                  padding: legendCollapsed ? '6px 10px' : '9px 12px',
                  maxWidth: 208,
                }}
                onClick={(e) => e.stopPropagation()}
                onMouseDown={(e) => e.stopPropagation()}
              >
                <div
                  onClick={() => setLegendCollapsed((v) => !v)}
                  title={legendCollapsed ? '展开分类图例' : '收起分类图例'}
                  style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none' }}
                >
                  <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-1)' }}>分类图例</span>
                  <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{legendCollapsed ? '展开' : '收起'}</span>
                </div>
                {!legendCollapsed && (
                  <div
                    style={{
                      marginTop: 8, maxHeight: 220, overflowY: 'auto',
                      display: 'flex', flexDirection: 'column', gap: 6,
                    }}
                  >
                    {legendItems.map((it) => (
                      <div key={it.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {/* 与标记点位共用同一套形状绘制逻辑，保证图例与地图展示一致 */}
                        <svg width={18} height={18} viewBox="0 0 18 18" style={{ flexShrink: 0 }}>
                          {renderMarkerShape(it.shape, it.color, 18)}
                        </svg>
                        <span
                          style={{
                            fontSize: 12.5, color: 'var(--text-1)',
                            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                          }}
                        >
                          {it.name}
                        </span>
                      </div>
                    ))}
                    {/* [新增 2026-09-14] 预警标识样式：不按分类渲染，统一为红色方框 + 感叹号 */}
                    <div
                      style={{
                        marginTop: 2, paddingTop: 8, borderTop: '1px dashed var(--line-soft)',
                        display: 'flex', alignItems: 'center', gap: 8,
                      }}
                    >
                      <svg width={18} height={18} viewBox="0 0 18 18" style={{ flexShrink: 0 }}>
                        {renderAlertMarkerShape(18)}
                      </svg>
                      <span
                        style={{
                          fontSize: 12.5, color: ALERT_MARKER_COLOR, fontWeight: 600, whiteSpace: 'nowrap',
                        }}
                      >
                        预警标识
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ) : (
          <div style={{ height: 400, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px dashed var(--line-soft)', borderRadius: 8, color: 'var(--text-3)' }}>
            <Space direction="vertical" align="center">
              <EnvironmentOutlined style={{ fontSize: 32 }} />
              {!floorPlans.length
                ? '暂无平面图，请先到「平面设置」创建'
                : selectedPlan
                  ? '该平面图暂无底图，请到「平面设置」上传图片'
                  : '请选择平面图开始标记'}
            </Space>
          </div>
        )}
      </Card>

      {/* [修复 2026-09-05] 绑定标识模态框 */}
      <Modal
        title={rebindPoint ? '重新绑定标识' : '绑定标识'}
        open={bindModal}
        onOk={handleBindOk}
        onCancel={() => setBindModal(false)}
        okText="确定绑定"
        cancelText="取消"
        width={680}
      >
        {/* [修复 2026-09-05] 每个标识仅可被标记一次：普通绑定仅列出尚未被标记的标识 */}
        <Text type="secondary" style={{ display: 'block', marginBottom: 8 }}>
          {rebindPoint
            ? '重新绑定：可选择任意标识替换当前标记'
            : '仅显示尚未被标记的标识（每个标识仅可被标记一次）'}
        </Text>
        <Input.Search
          // [修复 2026-09-05] 补充 id：消除「表单元素缺少 id/name」可访问性告警
          id="bind-signage-search"
          placeholder="搜索标识编码或名称"
          value={bindSearch}
          onChange={(e) => setBindSearch(e.target.value)}
          onSearch={(v) => { setBindPage(1); loadSignages(v, 1, !!rebindPoint); }}
          style={{ marginBottom: 12 }}
          allowClear
        />
        <Table
          rowKey="id"
          size="small"
          loading={bindLoading}
          dataSource={signages}
          columns={bindColumns}
          pagination={{ pageSize: 6, current: bindPage, onChange: (p) => { setBindPage(p); loadSignages(bindSearch, p, !!rebindPoint); } }}
          rowSelection={{
            type: 'radio',
            selectedRowKeys: selectedSignageId ? [selectedSignageId] : [],
            onChange: (keys) => setSelectedSignageId(keys[0] as number),
          }}
          onRow={(record) => ({ onClick: () => setSelectedSignageId(record.id) })}
        />
      </Modal>

      {/* [修复 2026-09-05] 点位详情 */}
      <Modal
        title="标记详情"
        open={!!detailPoint}
        onCancel={() => setDetailPoint(null)}
        width={560}
        footer={[
          <Button key="unbind" danger onClick={() => detailPoint && handleUnbind(detailPoint)}>解绑</Button>,
          <Button key="rebind" type="primary" onClick={() => detailPoint && openRebind(detailPoint)}>重新绑定</Button>,
          <Button key="close" onClick={() => setDetailPoint(null)}>关闭</Button>,
        ]}
      >
        {detailPoint && (
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            <div><Text type="secondary">坐标：</Text>{detailPoint.x_percent}% , {detailPoint.y_percent}%</div>
            {detailSignage ? (
              <>
                <div><Text type="secondary">标识编码：</Text><Text strong>{detailSignage.code}</Text></div>
                <div><Text type="secondary">名称：</Text>{detailSignage.name}</div>
                <div>
                  <Text type="secondary">分类：</Text>{renderCatTag(detailSignage.category)}
                  <Text type="secondary" style={{ marginLeft: 16 }}>状态：</Text>
                  <Tag color={(STATUS_MAP[detailSignage.status] || { color: 'default' }).color}>
                    {(STATUS_MAP[detailSignage.status] || { label: detailSignage.status }).label}
                  </Tag>
                </div>
                {/* [新增 2026-09-14] 预警原因：与地图上的红色方框 + 感叹号对应，点开即知为何被标记为预警 */}
                {!!alertedMap[detailSignage.id]?.length && (
                  <div>
                    <Text type="secondary">预警：</Text>
                    {alertedMap[detailSignage.id].map((a) => (
                      <Tag key={a} color="red" style={{ marginInlineEnd: 4 }}>{a}</Tag>
                    ))}
                  </div>
                )}
                {/* [修复 2026-09-05] 位置精确到楼层 */}
                <div><Text type="secondary">位置：</Text>{locationOf(detailSignage)}</div>
                <div><Text type="secondary">安装时间：</Text>{detailSignage.install_date || '-'}</div>
                <div><Text type="secondary">质保时间：</Text>{detailSignage.warranty_expire || '-'}</div>
                <div>
                  <Text type="secondary">现场安装照片：</Text>
                  <div style={{ marginTop: 8 }}>
                    {detailSignage.installation_photo ? (
                      <SafeImage
                        src={detailSignage.installation_photo}
                        alt="现场安装照片"
                        style={{ width: '100%', maxHeight: 320, objectFit: 'contain', borderRadius: 6 }}
                      />
                    ) : (
                      <Text type="secondary">未上传现场安装照片</Text>
                    )}
                  </div>
                </div>
              </>
            ) : <Text type="secondary">标识信息加载中，或该标识已被删除</Text>}
          </Space>
        )}
      </Modal>
    </div>
  );
};

export default MarkerEditor;
