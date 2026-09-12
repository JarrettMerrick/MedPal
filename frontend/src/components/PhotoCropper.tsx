// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 上传照片时的统一裁剪组件（原生 Canvas 实现，不引入第三方裁剪库）：
 * 1. 解决人员管理列表卡片上人像高度/大小不统一的问题：上传前把照片裁成统一比例（默认 3:4）
 * 2. 裁剪框锁定 aspect 比例，可拖拽移动、滑块缩放（保持中心点不变）
 * 3. 确认后输出固定尺寸 JPEG（默认 750×1000，白底兜底透明通道），最短边满足后端 ≥700×700 校验
 * 4. 允许"跳过裁剪"：取消时由调用方（PhotoUpload）决定是否直传原图
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Modal, Button, Slider, Space, Typography } from 'antd';
import { ScissorOutlined } from '@ant-design/icons';

const { Text } = Typography;

/** 裁剪输出尺寸（宽:高 = 3:4，最短边满足后端 700×700 校验） */
const OUTPUT_WIDTH = 750;
const OUTPUT_HEIGHT = 1000;
/** 输出 JPEG 质量 */
const OUTPUT_QUALITY = 0.9;
/** 裁剪框占图片显示宽度的最小比例 */
const MIN_CROP_RATIO = 0.3;
/** 初始裁剪框占图片显示宽度的比例 */
const INIT_CROP_RATIO = 0.85;

interface PhotoCropperProps {
  /** 待裁剪的原文件 */
  file: File;
  /** 裁剪框宽高比（宽/高），如 3:4 传 0.75 */
  aspect: number;
  /** 确认裁剪：回调输出 JPEG Blob（750×1000） */
  onConfirm: (blob: Blob) => void;
  /** 取消/跳过裁剪 */
  onCancel: () => void;
}

/** 图片在舞台内的 contain 显示矩形（像素） */
interface DisplayRect {
  dw: number;
  dh: number;
  dx: number;
  dy: number;
}

/** 裁剪框（舞台显示坐标系） */
interface CropBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

const PhotoCropper: React.FC<PhotoCropperProps> = ({ file, aspect, onConfirm, onCancel }) => {
  const imgRef = useRef<HTMLImageElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [imgUrl, setImgUrl] = useState('');
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [display, setDisplay] = useState<DisplayRect | null>(null);
  const [crop, setCrop] = useState<CropBox | null>(null);
  const [scale, setScale] = useState(INIT_CROP_RATIO);
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);

  // 加载文件 → objectURL
  useEffect(() => {
    const url = URL.createObjectURL(file);
    setImgUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // 图片加载完成 → 计算 contain 显示矩形与初始裁剪框（居中、占显示宽 85%）
  useEffect(() => {
    if (!natural || !stageRef.current) return;
    const stageW = stageRef.current.clientWidth;
    const stageH = stageRef.current.clientHeight;
    const ratio = Math.min(stageW / natural.w, stageH / natural.h);
    const dw = natural.w * ratio;
    const dh = natural.h * ratio;
    const rect: DisplayRect = { dw, dh, dx: (stageW - dw) / 2, dy: (stageH - dh) / 2 };
    setDisplay(rect);

    // 初始裁剪框：宽 = 显示宽 × INIT_CROP_RATIO，高按 aspect 锁定，超限则收缩
    const cw = Math.min(dw * INIT_CROP_RATIO, dh * aspect, dw);
    const ch = cw / aspect;
    setCrop({ x: rect.dx + (dw - cw) / 2, y: rect.dy + (dh - ch) / 2, w: cw, h: ch });
    setScale(cw / dw);
  }, [natural, aspect]);

  /** 滑块缩放：重算裁剪框宽高（保持中心点不变，且不超出图片显示区域） */
  const handleScaleChange = useCallback((value: number) => {
    if (!display || !crop) return;
    const cw = Math.min(display.dw * value, display.dh * aspect, display.dw);
    const ch = cw / aspect;
    const cx = crop.x + crop.w / 2;
    const cy = crop.y + crop.h / 2;
    let x = cx - cw / 2;
    let y = cy - ch / 2;
    x = Math.max(display.dx, Math.min(display.dx + display.dw - cw, x));
    y = Math.max(display.dy, Math.min(display.dy + display.dh - ch, y));
    setCrop({ x, y, w: cw, h: ch });
    setScale(value);
  }, [display, crop, aspect]);

  /** 拖拽移动裁剪框 */
  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!crop) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: crop.x, origY: crop.y };
  };
  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragRef.current || !display || !crop) return;
    const dx = e.clientX - dragRef.current.startX;
    const dy = e.clientY - dragRef.current.startY;
    let nx = dragRef.current.origX + dx;
    let ny = dragRef.current.origY + dy;
    nx = Math.max(display.dx, Math.min(display.dx + display.dw - crop.w, nx));
    ny = Math.max(display.dy, Math.min(display.dy + display.dh - crop.h, ny));
    setCrop({ ...crop, x: nx, y: ny });
  };
  const handlePointerUp = () => {
    dragRef.current = null;
  };

  /** 确认裁剪：将裁剪区域绘制为 750×1000 JPEG（白底兜底透明通道） */
  const handleConfirm = () => {
    if (!natural || !display || !crop || !imgRef.current) return;
    const canvas = document.createElement('canvas');
    canvas.width = OUTPUT_WIDTH;
    canvas.height = OUTPUT_HEIGHT;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    // 白底兜底：透明 PNG 源图合成白色背景
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);
    // 显示坐标 → 原始像素坐标
    const sx = ((crop.x - display.dx) / display.dw) * natural.w;
    const sy = ((crop.y - display.dy) / display.dh) * natural.h;
    const sw = (crop.w / display.dw) * natural.w;
    const sh = (crop.h / display.dh) * natural.h;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(imgRef.current, sx, sy, sw, sh, 0, 0, OUTPUT_WIDTH, OUTPUT_HEIGHT);
    canvas.toBlob((b) => {
      if (b) onConfirm(b);
    }, 'image/jpeg', OUTPUT_QUALITY);
  };

  return (
    <Modal
      open
      footer={null}
      onCancel={onCancel}
      width={560}
      centered
      closable
      title="裁剪照片（统一 3:4 比例）"
    >
      {/* 图片舞台 */}
      <div
        ref={stageRef}
        style={{
          position: 'relative',
          width: '100%',
          height: 420,
          background: '#f0f0f0',
          borderRadius: 8,
          overflow: 'hidden',
          touchAction: 'none',
          userSelect: 'none',
        }}
      >
        <img
          ref={imgRef}
          src={imgUrl}
          alt="裁剪预览"
          draggable={false}
          onLoad={() => {
            if (imgRef.current) {
              setNatural({ w: imgRef.current.naturalWidth, h: imgRef.current.naturalHeight });
            }
          }}
          style={{
            position: 'absolute',
            left: display?.dx,
            top: display?.dy,
            width: display?.dw,
            height: display?.dh,
            pointerEvents: 'none',
          }}
        />
        {/* 裁剪框：白色描边 + 主题色内框 + box-shadow 压暗框外区域 */}
        {display && crop && (
          <div
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerCancel={handlePointerUp}
            style={{
              position: 'absolute',
              left: crop.x,
              top: crop.y,
              width: crop.w,
              height: crop.h,
              border: '2px solid #ffffff',
              outline: '1px solid #0E7F8A',
              boxSizing: 'border-box',
              cursor: 'move',
              zIndex: 2,
              boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.55)',
            }}
          >
            {/* 三分构图线 */}
            <div style={{ position: 'absolute', left: '33.33%', top: 0, bottom: 0, width: 1, background: 'rgba(255,255,255,0.7)' }} />
            <div style={{ position: 'absolute', left: '66.66%', top: 0, bottom: 0, width: 1, background: 'rgba(255,255,255,0.7)' }} />
            <div style={{ position: 'absolute', top: '33.33%', left: 0, right: 0, height: 1, background: 'rgba(255,255,255,0.7)' }} />
            <div style={{ position: 'absolute', top: '66.66%', left: 0, right: 0, height: 1, background: 'rgba(255,255,255,0.7)' }} />

            {/* [改进] 人形构图示意图：高度占裁剪框 90%，水平居中、底部对齐，辅助把人物放满画面 */}
            <svg
              viewBox="0 0 100 140"
              style={{
                position: 'absolute',
                bottom: 0,
                left: '50%',
                transform: 'translateX(-50%)',
                height: crop.h * 0.9,
                width: 'auto',
                opacity: 0.4,
                pointerEvents: 'none',
                filter: 'drop-shadow(0 0 2px rgba(0,0,0,0.5))',
              }}
            >
              <circle cx="50" cy="30" r="16" fill="#ffffff" />
              <path
                d="M50 48 C 28 48, 14 64, 14 88 L 14 140 L 86 140 L 86 88 C 86 64, 72 48, 50 48 Z"
                fill="#ffffff"
              />
            </svg>
          </div>
        )}
      </div>

      {/* 大小滑块 */}
      <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <Text type="secondary" style={{ fontSize: 13, whiteSpace: 'nowrap' }}>裁剪框大小</Text>
        <Slider
          min={MIN_CROP_RATIO}
          max={1}
          step={0.01}
          value={scale}
          onChange={handleScaleChange}
          style={{ flex: 1, margin: '0 8px' }}
        />
        <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{Math.round(scale * 100)}%</Text>
      </div>

      {/* 底部操作 */}
      <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          输出 750×1000；原图保留用于下载溯源
        </Text>
        <Space>
          <Button onClick={onCancel}>跳过裁剪</Button>
          <Button type="primary" icon={<ScissorOutlined />} onClick={handleConfirm}>
            确认裁剪
          </Button>
        </Space>
      </div>
    </Modal>
  );
};

export default PhotoCropper;
