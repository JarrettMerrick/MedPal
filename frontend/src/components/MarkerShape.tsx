// [修复 2026-09-05] 标记形状共享模块：
// 分类设置页提供五种形状选择，平面标记页按「所选形状 + 分类颜色」渲染标记点，
// 两处共用同一套 SVG 绘制逻辑，保证设置预览与平面图实际展示一致。
import React from 'react';

export interface MarkerShapeOption {
  value: string;
  label: string;
}

/** 六种预设形状选项（圆形、方形、三角形、菱形、星形、消防栓），与后端 SHAPE_VALUES 一一对应 */
export const MARKER_SHAPES: MarkerShapeOption[] = [
  { value: 'circle', label: '圆形' },
  { value: 'square', label: '方形' },
  { value: 'triangle', label: '三角形' },
  { value: 'diamond', label: '菱形' },
  { value: 'star', label: '星形' },
  { value: 'hydrant', label: '消防栓' },
];

export const MARKER_SHAPE_LABELS: Record<string, string> = MARKER_SHAPES.reduce(
  (acc, s) => ({ ...acc, [s.value]: s.label }),
  {} as Record<string, string>,
);

/** 绘制形状 SVG 节点（白色描边保证在任意底图上可见） */
export function renderMarkerShape(
  shape: string | undefined,
  color: string,
  size: number,
): React.ReactNode {
  const s = size;
  const common = { fill: color, stroke: '#fff', strokeWidth: size >= 20 ? 2 : 1.5 };
  switch (shape) {
    case 'square':
      return <rect x={s * 0.15} y={s * 0.15} width={s * 0.7} height={s * 0.7} rx={s * 0.1} {...common} />;
    case 'triangle':
      return (
        <polygon
          points={`${s / 2},${s * 0.08} ${s * 0.92},${s * 0.88} ${s * 0.08},${s * 0.88}`}
          {...common}
          strokeLinejoin="round"
        />
      );
    case 'diamond':
      return (
        <polygon
          points={`${s / 2},${s * 0.05} ${s * 0.92},${s / 2} ${s / 2},${s * 0.95} ${s * 0.08},${s / 2}`}
          {...common}
          strokeLinejoin="round"
        />
      );
    case 'star': {
      // 五角星：外内半径交替的十个顶点
      const pts: string[] = [];
      for (let i = 0; i < 10; i++) {
        const r = i % 2 === 0 ? s * 0.48 : s * 0.22;
        const a = (Math.PI / 5) * i - Math.PI / 2;
        pts.push(`${s / 2 + r * Math.cos(a)},${s / 2 + r * Math.sin(a)}`);
      }
      return <polygon points={pts.join(' ')} {...common} strokeLinejoin="round" />;
    }
    case 'hydrant': {
      // 消防栓：顶盖 + 主体 + 两侧出水口 + 底座，按 24x24 网格绘制后整体缩放
      const k = s / 24;
      return (
        <g transform={`scale(${k})`}>
          <path
            d="M9.5 10.5 L5 10.5 L5 14 L9.5 14 L9.5 17 L6.5 17 L6.5 20 L17.5 20 L17.5 17 L14.5 17 L14.5 14 L19 14 L19 10.5 L14.5 10.5 L14.5 8.6 A2.6 2.6 0 0 0 9.5 8.6 Z"
            {...common}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        </g>
      );
    }
    case 'circle':
    default:
      return <circle cx={s / 2} cy={s / 2} r={s * 0.42} {...common} />;
  }
}

interface MarkerShapeIconProps {
  shape?: string;
  color?: string;
  size?: number;
}

/** 形状预览图标（表格列 / 表单选项共用） */
const MarkerShapeIcon: React.FC<MarkerShapeIconProps> = ({ shape, color = '#CED4DA', size = 18 }) => (
  <svg
    width={size}
    height={size}
    viewBox={`0 0 ${size} ${size}`}
    style={{ display: 'block', flexShrink: 0, filter: 'drop-shadow(0 1px 1px rgba(0,0,0,0.2))' }}
  >
    {renderMarkerShape(shape, color, size)}
  </svg>
);

export default MarkerShapeIcon;
