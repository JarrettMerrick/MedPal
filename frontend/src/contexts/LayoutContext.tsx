// Copyright (c) 2026 Jiamin Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

import React, { createContext, useContext } from 'react';

export interface LayoutContextType {
  sidebarCollapsed: boolean;
}

const LayoutContext = createContext<LayoutContextType>({
  sidebarCollapsed: false,
});

export const useLayout = () => useContext(LayoutContext);
export default LayoutContext;
