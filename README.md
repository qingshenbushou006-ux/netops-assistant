# NetOps Assistant - 网络运维资产管理工具

桌面 GUI 程序，集资产管理与网络设备调试于一体。
双击设备自动 SSH 连接，直接进入 CLI 配置界面。

## 功能特性

- 资产管理：添加/删除/分组/搜索/标签
- SSH 终端：嵌入式交互终端，支持 Tab 多窗口
- 双击连接：点击设备自动 SSH 登录
- 多厂商支持：Cisco / Huawei / H3C / Linux
- 在线检测：批量 Ping + 端口扫描
- 批量命令：一键对多台设备下发配置
- **配置备份：自动/手动备份设备配置，支持历史对比**
- **网络拓扑：LLDP/CDP自动发现，可视化拓扑图编辑**
- CSV 导入导出
- 深色主题界面

## 快速开始

### 环境要求

- Windows 10/11（推荐）或 Linux / macOS
- Python 3.10+

### 安装

```
# Windows: 双击 install.bat

# 或手动安装:
pip install -r requirements.txt
```

### 启动

```
# Windows: 双击 start.bat

# 或手动启动:
python main.py
```

## 使用方法

### 1. 添加设备

点击底部 "+ 添加设备" 按钮，填写：
- 设备名称、IP 地址、端口
- 协议（SSH/Telnet）
- 用户名、密码
- 分组、位置、标签

### 2. 导入设备（批量）

菜单 -> 文件 -> 导入资产，选择 CSV 文件。

CSV 格式：
```
name,ip,port,protocol,vendor,model,username,password,location,tags
核心交换机,10.1.1.1,22,ssh,Huawei,S5735,admin,Admin@123,主机房,核心
```

### 3. 连接设备

双击左侧设备树中的设备，右侧自动打开 SSH 终端标签页。

### 4. 终端操作

- 直接在终端窗口输入命令
- 底部输入框可快速输入命令
- 快捷按钮：Show Run / Config T 等
- 支持 Ctrl+C / Ctrl+D / Tab / 上下箭头

### 5. 扫描在线状态

点击左侧 "⟳" 按钮或按 F5，自动检测所有设备在线状态。

### 6. 配置备份

菜单 -> 工具 -> 配置备份管理 (Ctrl+B)

**手动备份:**
1. 选择要备份的设备（支持全选/选择在线设备）
2. 点击"备份选中设备"或"备份所有在线设备"
3. 自动连接设备获取配置并保存

**备份计划:**
- 支持Cron表达式定时备份
- 示例: `0 2 * * *` = 每天凌晨2点

**配置对比:**
- 选择设备，点击"对比最近两次备份"
- 自动显示配置差异（类似diff）

### 7. 网络拓扑图

菜单 -> 工具 -> 网络拓扑图 (Ctrl+T)

**自动发现:**
- 点击"自动发现"扫描所有在线设备的LLDP/CDP邻居
- 自动绘制设备间链路

**手动编辑:**
- 点击"手动添加链路"选择源/目标设备
- 支持拖拽移动节点
- 选中节点后按Delete删除

**布局算法:**
- 圆形布局：适合小型网络
- 网格布局：适合大型网络

**导入导出:**
- 导出拓扑为JSON文件
- 从JSON文件导入拓扑

## 项目结构

```
netops-assistant/
├── main.py              # 主入口
├── install.bat          # Windows 安装脚本
├── start.bat            # Windows 启动脚本
├── requirements.txt     # 依赖包
├── sample_assets.csv    # 示例资产 CSV
├── ui/
│   ├── main_window.py   # 主窗口布局 + 主题
│   ├── asset_panel.py   # 左侧资产树
│   ├── terminal_widget.py  # 右侧终端面板
│   ├── backup_dialog.py # 配置备份管理对话框
│   └── topology_widget.py  # 网络拓扑图组件
├── core/
│   ├── db.py            # SQLite 数据库操作
│   ├── ssh_manager.py   # SSH 连接管理 (Paramiko + Pyte)
│   ├── scanner.py       # 网络扫描 (Ping / Port)
│   ├── backup_manager.py  # 配置备份管理器
│   └── topology.py      # 网络拓扑发现
├── database/
│   └── assets.db        # SQLite 数据库文件（自动创建）
└── logs/                # 日志目录
```

## 技术栈

| 模块 | 技术 | 说明 |
|------|------|------|
| GUI | PySide6 (Qt6) | 跨平台桌面框架 |
| SSH | Paramiko | Python SSH2 库 |
| 终端模拟 | Pyte | 终端模拟器 |
| 数据库 | SQLite | 轻量嵌入式数据库 |
| 网络扫描 | socket + subprocess | Ping / 端口检测 |

## 后续扩展

- [x] 网络拓扑图（LLDP自动发现 + 可视化编辑）
- [x] 配置自动备份（手动/定时备份 + 配置对比）
- [ ] SNMP 接口监控
- [ ] WebSocket 实时日志
- [ ] 权限管理 / 堡垒机模式
- [ ] Web 管理界面
- [ ] 打包成 EXE (PyInstaller)
