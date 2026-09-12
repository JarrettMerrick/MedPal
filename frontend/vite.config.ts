import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import svgr from 'vite-plugin-svgr' // [改进] 支持 SVG 作为 React 组件导入（?react，备用图标能力）

export default defineConfig({
  plugins: [react(), svgr()],
  // [修复 2026-09-02] P1: 添加构建分包优化，拆分 vendor 依赖提升缓存命中率
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-antd': ['antd', '@ant-design/icons'],
          'vendor-charts': ['recharts'],
          'vendor-editor': ['@wangeditor/editor', '@wangeditor/editor-for-react'],
        },
      },
    },
    cssCodeSplit: true,
  },
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      '/uploads': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
      // [新增 2026-09-10] 公开品牌资源（单位 Logo）：
      // 后端将 data/public 挂载为 /public，需与 /api、/uploads 一样代理到后端，
      // 否则本地开发时 <img src="/public/brand/..."> 会落到 Vite 自身而 404。
      '/public': {
        target: 'http://localhost:5000',
        changeOrigin: true,
      },
    },
  },
})
