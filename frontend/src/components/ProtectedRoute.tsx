// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();

  // [改造 2026-09-19] 原用 Tailwind 调色板类（bg-gray-50 / text-gray-500 为固定色，
  // 深色模式下会失效）与硬编码品牌色，统一改为语义变量
  if (isLoading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: 'var(--neu-page-bg)' }}
      >
        <div className="text-center">
          <div
            className="inline-block w-8 h-8 rounded-full animate-spin mb-4"
            style={{
              border: '4px solid var(--accent)',
              borderTopColor: 'transparent',
            }}
          ></div>
          <p style={{ color: 'var(--text-2)' }}>正在验证登录状态...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
};

export default ProtectedRoute;
