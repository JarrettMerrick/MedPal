// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.
import { getFileToken } from './tokenStore';

/** 为受保护的静态文件 URL 拼接短期文件访问令牌（后端 S1 鉴权要求） */
function withFileToken(url: string): string {
  const ftoken = getFileToken();
  if (!ftoken) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}ftoken=${encodeURIComponent(ftoken)}`;
}

/** 获取缩略图访问URL（前端展示用） */
export function getThumbnailUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith('http')) return path;
  // [修复 2026-09-09] SVG 矢量图不生成位图缩略图（后端对 SVG 已跳过缩略图生成），
  // 若仍拼接 thumb_ 前缀会请求一个不存在的文件导致 404 日志噪声。SVG 由浏览器原生渲染、
  // 矢量缩放清晰，直接返回 null（调用方回退原图即可）。
  if (path.toLowerCase().endsWith('.svg')) return null;
  const idx = path.lastIndexOf('/');
  let url: string;
  if (idx === -1) url = `/uploads/thumb_${path}`;
  else {
    const dir = path.substring(0, idx);
    const file = path.substring(idx + 1);
    url = `/uploads/${dir}/thumb_${file}`;
  }
  return withFileToken(url);
}

/** 获取原图访问URL */
export function getOriginalUrl(path: string | null): string | null {
  if (!path) return null;
  if (path.startsWith('http')) return path;
  return withFileToken(`/uploads/${path}`);
}

/**
 * 获取"原始照片"（orig_ 前缀副本）的候选访问URL列表（供下载/查看溯源）。
 * 说明：orig_ 副本的扩展名与正式图（裁剪 JPEG）可能不同——原文件若是 PNG/WebP，
 * 后端会以原文件自身格式保存 orig_ 副本。因此不能从正式图路径直接派生唯一 URL，
 * 需按扩展名逐级探测（正式图原扩展名 → png → webp → jpg）。
 * 旧数据没有 orig_ 文件，调用方需自行回退到 getOriginalUrl。
 */
export function getOriginalPreferredCandidates(path: string | null): string[] {
  if (!path) return [];
  if (path.startsWith('http')) return [path];
  const idx = path.lastIndexOf('/');
  const dir = idx === -1 ? '' : path.substring(0, idx);
  const file = idx === -1 ? path : path.substring(idx + 1);
  const dot = file.lastIndexOf('.');
  const stem = dot === -1 ? file : file.substring(0, dot);
  const origExt = dot === -1 ? '' : file.substring(dot + 1).toLowerCase();
  const base = idx === -1 ? '/uploads/' : `/uploads/${dir}/`;
  // 候选扩展名去重：正式图原扩展名优先，其次常见原图格式
  const exts = Array.from(new Set([origExt, 'png', 'webp', 'jpg'].filter(Boolean)));
  return exts.map((e) => withFileToken(`${base}orig_${stem}.${e}`));
}

/**
 * [新增 2026-09-07] 客户端图片压缩（巡检现场照片等场景）：
 * - 分辨率保持不变：画布尺寸与原图一致，不做缩放裁剪；
 * - 通过 JPEG 有损编码 + 自适应质量档位尽可能减小文件体积；
 * - 不保留原始图片文件：仅以压缩后的 JPEG 重建 File 对象返回，原 File 不再使用。
 *
 * @param file   用户选择的原始图片文件（拍照或相册）
 * @param target 目标体积上限（字节），默认 400KB；从高质量档位向下尝试，取首个达标档位
 */
export function compressImageFile(file: File, target = 400 * 1024): Promise<File> {
  const encode = (quality: number): Promise<Blob | null> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const img = new window.Image();
        img.onload = () => {
          const canvas = document.createElement('canvas');
          // 分辨率保持不变：画布尺寸 = 原图尺寸
          canvas.width = img.naturalWidth;
          canvas.height = img.naturalHeight;
          const ctx = canvas.getContext('2d');
          if (!ctx) { reject(new Error('无法创建画布')); return; }
          // 透明 PNG 合成白底，避免转 JPEG 后出现黑底
          ctx.fillStyle = '#FFFFFF';
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.drawImage(img, 0, 0);
          canvas.toBlob((blob) => resolve(blob), 'image/jpeg', quality);
        };
        img.onerror = () => reject(new Error('图片解码失败'));
        img.src = reader.result as string;
      };
      reader.onerror = () => reject(new Error('图片读取失败'));
      reader.readAsDataURL(file);
    });

  return (async () => {
    // 质量档位从高到低尝试：取首个达到目标体积的档位；均未达标则取最小体积档位
    const qualities = [0.8, 0.6, 0.45, 0.3];
    let smallest: { blob: Blob; quality: number } | null = null;
    for (const q of qualities) {
      const blob = await encode(q);
      if (!blob) continue;
      if (!smallest || blob.size < smallest.blob.size) smallest = { blob, quality: q };
      if (blob.size <= target) break;
    }
    if (!smallest) throw new Error('图片压缩失败');
    // 不保留原始图片文件：仅以压缩后的 JPEG 重建 File 对象
    const name = (file.name || 'photo').replace(/\.[^.]+$/, '') + '.jpg';
    return new File([smallest.blob], name, { type: 'image/jpeg' });
  })();
}
