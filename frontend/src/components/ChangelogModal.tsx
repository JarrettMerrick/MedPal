// Copyright (c) 2026 Jarrett Merrick Zhang (zjm20@vip.qq.com)
// Licensed under the MIT License. See LICENSE file for details.

/**
 * 业务背景说明
 * ============
 * 版本更新记录弹窗组件：
 * 1. 由侧边栏左下角「版本号」点击触发，展示系统版本更新历史
 * 2. 版本历史以数据数组（VERSION_HISTORY）维护，新增版本时在数组头部追加即可
 * 3. 内容为纯静态数据，无网络请求，内网可用
 *
 * 改造说明（v1.1.0）：
 * - [改进] 新增组件，替代原先不可点击的纯文本版本号
 *
 * [重写 2026-09-21] 三条改动：
 *   ① 每个版本条目**默认折叠** —— 原实现把全部版本的明细一次性平铺，
 *      八个版本近百条内容堆在一个弹窗里，用户要滚动很久才能看到想找的版本。
 *      现改为「折叠头常驻、明细按需展开」：收起状态只留「版本号 + 主题 + 日期」，
 *      一屏即可纵览全部版本，想看细节再点开。
 *   ② 文案大幅精简 —— 每条只说清「新增 / 优化 / 修复 / 移除」了什么，
 *      控制在 25 字内。原条目动辄上百字并夹带实现细节（阴影参数、字段名、
 *      内部表名等），对使用者没有价值，反而淹没了真正要传达的信息。
 *   ③ ⚠️ **安全类更新统一表述为「升级系统安全，修复 bug」**，
 *      不再写明具体的漏洞位置、成因与利用方式。
 *      原因：更新日志是任何登录用户都能打开的界面，原实现写着
 *      「阻断 =HYPERLINK(...) 一类窃取表格数据的攻击」「令牌缺少内嵌改密时间时
 *      跳过校验」等描述 —— 这等于把尚未修补完毕系统的攻击路线图公开出去，
 *      属典型的「更新日志信息泄露」（CWE-200）。业界做法（如各大发行版的安全
 *      公告）也是先给概括性说明、细节延后披露或不公开。
 *      因此凡涉及权限、认证、注入、越权、数据泄露等条目，一律归并为统一表述。
 */

import React from 'react';
import { Modal, Typography, Tag, Collapse } from 'antd';
import { ClockCircleOutlined } from '@ant-design/icons';

const { Text } = Typography;

/** 单个版本更新记录的数据结构 */
interface ChangelogEntry {
  /** 版本号，如 v1.1.0 */
  version: string;
  /** 发布日期，格式 YYYY-MM-DD */
  date: string;
  /** 版本代号 / 主题说明（短语，控制在 20 字内） */
  codename: string;
  /** 更新内容列表（每项一条短语，25 字内；安全类统一为固定表述） */
  changes: string[];
}

/**
 * 安全类更新的统一表述。
 *
 * [重写 2026-09-21] 抽成常量而不是散落各处字面量，有两个好处：
 *   ① 表述天然一致 —— 不会出现「安全加固」「会话安全」「部署加固」等
 *      各版本各写一版的情况，用户看到的是同一个说法；
 *   ② 便于统一调整 —— 将来若要改口径（如加一句「详情见内网安全通报」），
 *      只需改这一处。
 *
 * ⚠️ 注意：**不要**在这里或各处补充具体的漏洞细节 —— 见文件头改造说明 ③。
 */
const SECURITY_NOTE = '升级系统安全，修复 bug';

/**
 * 版本更新历史（按时间倒序，最新版本在最前）
 * [改进] 数据集中维护，新增发版时在此追加，无需改动组件渲染逻辑
 *
 * [重写 2026-09-21] 条目统一改为「动词开头 + 一句话」的短语式：
 *   - 新增 / 优化 / 修复 / 移除 / 调整 五类动词打头，扫一眼就知道是什么性质的改动；
 *   - 不再罗列实现细节、内部名称、数值指标与括号补充说明；
 *   - 同类改动尽量合并为一条（原 v1.2.0 的十条已合并为八条）。
 */
const VERSION_HISTORY: ChangelogEntry[] = [
  {
    version: 'v1.2.6',
    date: '2026-09-22',
    codename: '数据恢复与下载修复',
    changes: [
      // 本次围绕「恢复旧版本备份后系统不可用」这一实际故障展开，
      // 并把全项目重复的文件下载逻辑收敛为一处。
      '修复：恢复旧备份后系统不可用，恢复后自动补齐结构',
      '修复：删除员工失败、孤儿图片清理失效等问题',
      '优化：全站文件下载统一，修复个别浏览器点击无反应',
      '修复：导出失败时会下载到打不开的假文件',
      '新增：标识附件导出包支持手动删除',
      '优化：数据库异常时给出可直接照做的提示',
    ],
  },
  {
    version: 'v1.2.5',
    date: '2026-09-19',
    codename: '界面风格与规范优化',
    changes: [
      '新增「时尚」界面风格，支持白天 / 黑夜模式切换',
      '新增：标识维修操作入口与拍照上传',
      '优化：文字颜色与字号规范，提升可读性',
      '优化：表格列宽与超长文本换行，消除横向滚动',
      '优化：后端日志规范',
      SECURITY_NOTE,
    ],
  },
  {
    version: 'v1.2.4',
    date: '2026-09-18',
    codename: '设计文件库与权限修复',
    changes: [
      '新增：设计文件库（分类、标签、历史版本、回收站、打包下载）',
      '新增：标识表单可从标准库选择文件',
      '新增：标识总览独立权限点',
      '新增：维修与巡检照片缩略图',
      '修复：功能开关关闭后部分入口未隐藏',
      '优化：平面设置列宽与错误提示文案',
    ],
  },
  {
    version: 'v1.2.3',
    date: '2026-09-16',
    codename: '时间口径与品牌统一',
    changes: [
      '优化：全站时间显示口径统一',
      '修复：按日期筛选在凌晨时段漏筛',
      '优化：品牌信息与系统名称统一',
      '修复：仓库配置导致构建失败',
      SECURITY_NOTE,
    ],
  },
  {
    version: 'v1.2.2',
    date: '2026-09-16',
    codename: '口令规则与运维工具',
    changes: [
      '优化：重置密码统一使用默认口令模板',
      '新增：运维命令行工具',
    ],
  },
  {
    version: 'v1.2.1',
    date: '2026-09-15',
    codename: '通知中心与功能开关',
    changes: [
      '新增：通知中心（可配置事件、模板与收件人）',
      '新增：消息铃铛未读数实时刷新与待办角标',
      '新增：功能开关（模块可一键启停）',
      '新增：账号设置（初始口令模板、密码重置）',
      '新增：修改历史（字段级变更明细）',
      '新增：演示数据初始化脚本',
    ],
  },
  {
    version: 'v1.2.0',
    date: '2026-09-09',
    codename: '标识管理增强',
    changes: [
      '新增：标识自动编号、三级级联筛选与详情补全',
      '新增：巡检拍照上传与现场照片查看',
      '新增：导入导出重写（Excel / CSV / 打包 / 模板 / 批量导入）',
      '新增：维修记录与版本更新分离',
      '新增：标识总览（指标卡、分布图、趋势、自动刷新）',
      '新增：维修记录菜单与导出',
      '新增：富文本编辑器三模式（可视化 / 源码 / 预览）',
      '修复：图片丢失刷新、附件导出等多项问题',
    ],
  },
  {
    version: 'v1.1.1',
    date: '2026-09-03',
    codename: '图片导出与数据核对',
    changes: [
      '优化：图片打包导出（目录扁平、可筛选、命名规范）',
      '新增：ZIP 批量导入照片',
      '新增：数据核对与混合科室配置',
      '修复：通知文案、空压缩包与启动崩溃',
      SECURITY_NOTE,
    ],
  },
  {
    version: 'v1.1.0',
    date: '2026-08-07',
    codename: '界面升级与稳定性',
    changes: [
      '优化：前端界面全面升级',
      '优化：图片处理（格式转换、缩略图、透明度保留）',
      '新增：制度类别代码、版本自动生成与历史版本',
      '新增：账号不同步人员管理选项',
      '优化：导入导出模板与字段',
      '优化：运维能力（令牌自动刷新、日志轮转、磁盘告警、备份清理）',
      SECURITY_NOTE,
    ],
  },
];

interface Props {
  /** 弹窗是否可见 */
  open: boolean;
  /** 关闭回调 */
  onClose: () => void;
}

const ChangelogModal: React.FC<Props> = ({ open, onClose }) => {
  const newestVersion = VERSION_HISTORY[0]?.version;

  /**
   * 折叠项：每个版本一块。
   *
   * 折叠头必须**自带完整信息**（版本号 + 主题 + 日期）——
   * 因为默认全部收起，用户只能靠这一行判断要不要展开。
   * 日期靠右对齐、用小一号的辅助色，视觉上让「版本号 + 主题」承担主要识别作用。
   */
  const items = VERSION_HISTORY.map((entry) => ({
    key: entry.version,
    label: (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', paddingRight: 4 }}>
        <Tag
          color={entry.version === newestVersion ? 'blue' : 'default'}
          style={{ fontSize: 13, lineHeight: '20px', marginRight: 0, fontWeight: 600 }}
        >
          {entry.version}
        </Tag>
        {/* 最新版本加标记：全部收起时，让用户一眼看出哪个是刚更新的 */}
        {entry.version === newestVersion && (
          <Tag color="green" style={{ fontSize: 11, lineHeight: '18px', marginRight: 0 }}>
            最新
          </Tag>
        )}
        <Text style={{ fontSize: 13 }}>{entry.codename}</Text>
        <Text type="secondary" style={{ fontSize: 12, marginLeft: 'auto', whiteSpace: 'nowrap' }}>
          <ClockCircleOutlined style={{ marginRight: 4 }} />
          {entry.date}
        </Text>
      </div>
    ),
    children: (
      <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.9, fontSize: 13 }}>
        {entry.changes.map((item, index) => (
          <li key={index} style={{ color: item === SECURITY_NOTE ? 'var(--text-2)' : 'var(--text-1)' }}>
            {item}
          </li>
        ))}
      </ul>
    ),
  }));

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      centered
      width={560}
      title={
        <Text strong style={{ fontSize: 16 }}>
          版本更新记录
        </Text>
      }
    >
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
        点击任意版本可展开查看该版本的更新明细
      </Text>

      {/*
        defaultActiveKey 显式传空数组 → **全部默认收起**。
        （不传该属性时 antd 同样默认全收起，但显式写出能防止后人误以为
          「没指定就是全展开」而加上默认项；此处按需求固定为全收起。）

        accordion 保持 false：允许同时展开多个版本，便于跨版本对比同一功能的演进。
      */}
      {/* 只传 bordered={false}：antd 5.x 中它等价于过去「无边框 / 透明底」的 ghost，
          两者同传会触发 deprecated 警告。无边框正是本项目要的效果 ——
          拟物模式下 .ant-collapse-item 的下分隔线由 neumorphism.css 提供。 */}
      <Collapse
        items={items}
        defaultActiveKey={[]}
        bordered={false}
        style={{ maxHeight: '60vh', overflowY: 'auto' }}
      />
    </Modal>
  );
};

export default ChangelogModal;
