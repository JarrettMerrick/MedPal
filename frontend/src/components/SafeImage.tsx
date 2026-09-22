// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.
import { setFileToken } from '../utils/tokenStore';

/**
 * 业务背景说明
 * ============
 * 安全的图片展示组件，含多级回退策略：
 * 1. 尝试加载缩略图（getThumbnailUrl）
 * 2. 缩略图失败 → 回退原图（getOriginalUrl）
 * 3. 原图也失败 → 显示"文件已丢失·请重新上传"占位符（或隐藏 hideOnError）
 *
 * [改进] 增加两种对外能力：
 * - ref.preview()：通过 forwardRef + useImperativeHandle 暴露 antd Image 的
 *   preview 方法，供外部"预览"按钮触发大图预览。
 * - onLoad 透传：把 img 的 onLoad 回调透传给调用方，便于读取 naturalWidth/
 *   naturalHeight 等原始尺寸（如卡片照片按实际比例自适应显示框）。
 *
 * 改造说明（v1.1.0）：
 * - [改进] 原生 <img> → Ant Design Image 组件（支持内置预览、fallback）
 * - [改进] 失败占位符内联 SVG → @ant-design/icons PictureOutlined
 * - 多级回退逻辑保留不变
 */

import React from 'react';
import { Image, theme } from 'antd';
import { PictureOutlined } from '@ant-design/icons';
import { getThumbnailUrl, getOriginalUrl } from '../utils/imageUtils';

const { useToken } = theme;

// [修复 2026-09-07] 已确认丢失的文件路径缓存（存不含 token 的基础路径）：
// 完整重试链（含一次成功刷新后的重试）仍失败即视为真实丢失，后续挂载直接显示
// "文件已丢失"占位，不再反复发起请求。重新上传会生成新文件名，缓存不会误伤新文件。
const missingFileCache = new Set<string>();

// [修复 2026-09-07] 全局共享的 file_token 刷新：并发失败只发一次刷新请求，
// 且 30 秒冷却内直接复用新令牌，避免多个丢失图片互相触发刷新形成请求风暴
let lastTokenRefreshAt = 0;
let refreshInFlight: Promise<boolean> | null = null;

async function refreshFileTokenOnce(): Promise<boolean> {
  if (Date.now() - lastTokenRefreshAt < 30_000) return true;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        // [修复/问题3] refresh_token 已迁至 HttpOnly Cookie，前端无法读取，
        // 直接携带凭据(Cookie)调用刷新接口即可，不再从 localStorage 取值。
        const resp = await fetch('/api/auth/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({}),
        });
        if (!resp.ok) return false;
        const data = await resp.json();
        if (data?.file_token) {
          setFileToken(data.file_token);
          lastTokenRefreshAt = Date.now();
          return true;
        }
        return false;
      } catch {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

export interface SafeImageRef {
  /** 打开图片大图预览（对应 antd Image 的 preview 方法） */
  preview: () => void;
}

interface SafeImageProps {
  src: string | null;
  alt: string;
  className?: string;
  /** 是否在加载失败时隐藏整个元素（默认显示占位提示） */
  hideOnError?: boolean;
  style?: React.CSSProperties;
  /** [改进] 图片加载完成回调，透传到内部 <img>，可读取 naturalWidth/naturalHeight */
  onLoad?: (e: React.SyntheticEvent<HTMLImageElement, Event>) => void;
  /** [改进] 未上传（src 为空）时的占位文案；不传则保持"不渲染"默认行为（不影响其他调用方） */
  emptyText?: string;
  /** [修复 2026-09-05] 是否允许点击大图预览，默认开启；标记底图等场景可关闭以免劫持点击 */
  preview?: boolean;
  /** [修复 2026-09-09] antd Image 外层包裹层样式，用于让图片在父容器中真正铺满宽度 */
  wrapperStyle?: React.CSSProperties;
}

const SafeImage = React.forwardRef<SafeImageRef, SafeImageProps>(
  ({ src, alt, className, hideOnError = false, style, wrapperStyle, onLoad, emptyText, preview = true }, ref) => {
    const { token } = useToken();

    // 图片地址与加载状态（hooks 全部置于顶层，保证调用顺序稳定）
    // [修复 2026-09-07] 挂载时先查丢失缓存：已确认丢失的文件直接进入占位态，不发任何请求
    const isKnownMissing = !!src && missingFileCache.has(src);
    const thumbUrl = src ? getThumbnailUrl(src) : null;
    const originalUrl = src ? getOriginalUrl(src) : null;
    const [failed, setFailed] = React.useState(isKnownMissing);
    const [imgSrc, setImgSrc] = React.useState<string | undefined>(
      isKnownMissing ? undefined : (thumbUrl || originalUrl || ''),
    );
    // [改进] 防止 file_token 过期导致图片 403 后无限重试的标记
    const triedRefresh = React.useRef(isKnownMissing);
    // [修复 2026-09-07] 记录当前基础路径：仅当 src 本身变化（如切换平面图底图）才重置重试状态；
    // token 变化引起的 URL 变化不再重置，否则组件自己刷新 token 会把自己刚设的标记清掉，形成无限循环
    const lastSrcRef = React.useRef(src);
    // [改进] 大图预览改为受控模式（antd Image 为函数组件不接受 ref 调用 preview）：
    // 用 preview.visible / preview.src 控制预览，避免 react 警告"Function components cannot be given refs"
    const [previewOpen, setPreviewOpen] = React.useState(false);
    const [previewSrc, setPreviewSrc] = React.useState<string | undefined>(undefined);

    React.useImperativeHandle(ref, () => ({
      preview: () => {
        if (failed) return;
        // 预览使用原图（更高清）；无原图地址时回退当前展示图
        setPreviewSrc(originalUrl || imgSrc);
        setPreviewOpen(true);
      },
    }));

    // [修复 2026-09-07] 仅当 src 基础路径变化时重置地址与失败状态（此前的依赖是
    // 拼好 token 的 URL，组件自身刷新 file_token 后依赖变化会把 triedRefresh 重置，
    // 导致"缩略图→原图→刷新token→重试"无限循环；已确认丢失的文件仍保持占位态）
    React.useEffect(() => {
      if (lastSrcRef.current === src) return;
      lastSrcRef.current = src;
      const missing = !!src && missingFileCache.has(src);
      setFailed(missing);
      triedRefresh.current = missing;
      setImgSrc(missing ? undefined : (getThumbnailUrl(src) || getOriginalUrl(src) || ''));
    }, [src]);

    /**
     * 多级回退：缩略图 → 原图 → （刷新一次 file_token）原图重试 → 失败占位。
     * [修复 2026-09-07] 重试链收敛并防循环：
     * - 刷新改用全局共享的 refreshFileTokenOnce（30 秒冷却，多实例并发只发一次请求）；
     * - 刷新成功后直接用原图重试（跳过必然再次失败的缩略图），少一次无效请求；
     * - 刷新成功后仍失败 => 记入丢失缓存，本页面周期内不再对该文件发起任何请求；
     * - 刷新失败（网络/无 rt）=> 仅显示占位，不缓存，下次挂载允许再试。
     */
    const handleError = React.useCallback(async () => {
      const markFailed = (cache: boolean) => {
        if (cache && src) missingFileCache.add(src);
        setFailed(true);
        setImgSrc(undefined);
      };
      if (imgSrc === thumbUrl && originalUrl) {
        // 缩略图失败，尝试原图
        setImgSrc(originalUrl);
        return;
      }
      if (!triedRefresh.current) {
        triedRefresh.current = true;
        const ok = await refreshFileTokenOnce();
        if (ok) {
          // 用新令牌重拼原图地址重试（getOriginalUrl 实时读取最新 file_token）
          const retryUrl = getOriginalUrl(src) || getThumbnailUrl(src) || '';
          // [修复 2026-09-07] 冷却期内令牌未变化时 retryUrl 与当前地址相同，
          // setImgSrc 会被 React 短路导致不再重试、占位符永不显示；此时令牌是新的，
          // 文件必然真实丢失，直接判失败并缓存
          if (retryUrl === imgSrc) {
            markFailed(true);
            return;
          }
          setImgSrc(retryUrl);
          return;
        }
        // 刷新失败：显示占位但不缓存（可能是网络问题，下次挂载允许重试）
        markFailed(false);
        return;
      }
      // 刷新后仍失败：确认文件真实丢失，记入缓存，后续挂载零请求直接显示占位
      markFailed(true);
    }, [imgSrc, thumbUrl, originalUrl, src]);

    // [改进] 未上传（src 为空）时：传了 emptyText 则显示占位背景，否则保持"不渲染"默认行为
    if (!src) {
      if (!emptyText) return null;
      return (
        <div
          className={className}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: token.colorFillQuaternary,
            border: `1px dashed ${token.colorBorderSecondary}`,
            borderRadius: token.borderRadius,
            color: token.colorTextQuaternary,
            fontSize: token.fontSizeSM,
            padding: `${token.paddingMD}px ${token.paddingSM}px`,
            ...style,
          }}
        >
          <PictureOutlined style={{ fontSize: 28, color: token.colorBorder, marginBottom: token.marginXS }} />
          <span>{emptyText}</span>
        </div>
      );
    }

    if (failed) {
      if (hideOnError) return null;
      return (
        <div
          className={className}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: token.colorFillQuaternary,
            border: `1px dashed ${token.colorBorderSecondary}`,
            borderRadius: token.borderRadius,
            color: token.colorTextQuaternary,
            fontSize: token.fontSizeSM,
            padding: `${token.paddingMD}px ${token.paddingSM}px`,
            ...style,
          }}
        >
          <PictureOutlined style={{ fontSize: 28, color: token.colorBorder, marginBottom: token.marginXS }} />
          <span>文件已丢失</span>
          <span style={{ fontSize: token.fontSizeSM, marginTop: token.marginXXS, color: token.colorTextQuaternary }}>请重新上传</span>
        </div>
      );
    }

    return (
      <Image
        src={imgSrc}
        alt={alt}
        className={className}
        style={style}
        wrapperStyle={wrapperStyle}
        onLoad={onLoad}
        onError={handleError}
        preview={preview === false ? false : {
          // 受控预览：visible/src/onVisibleChange，点击图片本身同样会触发
          visible: previewOpen,
          src: previewSrc,
          onVisibleChange: (v) => setPreviewOpen(v),
        }}
      />
    );
  }
);

SafeImage.displayName = 'SafeImage';

export default SafeImage;
