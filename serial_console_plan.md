# 串口调试功能开发方案

## 目标
给当前桌面程序新增“串口终端”能力，作为现有 SSH 终端的并列连接方式，后续逐步替代 MobaXterm 在网络设备本地调试场景中的使用。

目标不是先做一个孤立的小工具，而是把现有终端能力抽象成统一的“终端会话层”，让 SSH / 串口共用标签页、日志、快捷命令和资产入口。

---

## 当前代码现状

### 1. 资产模型当前偏向网络登录
- 文件：`core/db.py`
- `assets` 表当前已有字段：
  - `ip`
  - `port`
  - `protocol`
  - `username`
  - `password`
  - `enable_password`
- 目前没有串口专用字段，比如：
  - 串口端口名（COM3 / /dev/ttyUSB0）
  - 波特率
  - 数据位
  - 校验位
  - 停止位
  - 流控

### 2. 资产编辑界面只支持 ssh / telnet
- 文件：`ui/asset_panel.py`
- `AssetEditDialog.setup_ui()` 里：
  - `self.proto_combo.addItems(["ssh", "telnet"])`
- 当前表单强依赖 IP、端口、用户名、密码输入，不适合串口资产。

### 3. 主窗口只会走统一“打开终端”入口
- 文件：`ui/main_window.py`
- 双击资产后走：
  - `MainWindow._on_connect()`
  - `self.terminal_panel.open_terminal(asset)`
- 这说明串口功能最适合接入 `TerminalPanel.open_terminal()` 分流，而不是另起一个完全独立窗口。

### 4. 终端实现现在直接绑定 SSHConnection
- 文件：`ui/terminal_widget.py`
- 关键点：
  - `TerminalTab.connect_to_device()` 里直接实例化 `SSHConnection`
  - `TerminalView.set_ssh_connection()` 直接绑定 SSH 对象
  - `TerminalView.keyPressEvent()` 依赖连接对象提供 `send_keys()`
  - 底部命令栏依赖连接对象提供 `send_command()`
- 当前 UI 虽然结构通用，但接口命名是 SSH 专属，需要抽象。

### 5. 会话管理器当前也是 SSH 专属
- 文件：`core/ssh_manager.py`
- 当前有：
  - `SSHConnection`
  - `ConnectionManager`
- `ConnectionManager` 只是一个按 `asset_id` 保存 SSH 连接的简单容器，并没有形成协议无关抽象。

---

## 推荐实现路径

分三阶段做，先可用，再替代。

---

## 阶段一：最小可用串口终端

### 目标
先支持本地串口直连，做到：
- 资产里可配置串口参数
- 双击串口资产可打开终端标签
- 可收发数据
- 支持基础断开、重连、日志

### 需要改动的文件

#### 1. `core/db.py`
为 `assets` 表补充串口字段，并在初始化阶段做兼容性补齐：
- `serial_port TEXT DEFAULT ''`
- `baud_rate INTEGER DEFAULT 9600`
- `data_bits INTEGER DEFAULT 8`
- `parity TEXT DEFAULT 'N'`
- `stop_bits INTEGER DEFAULT 1`
- `flow_control TEXT DEFAULT 'none'`

同时更新：
- `add_asset()`
- `update_asset()`
- 允许这些字段参与 CRUD

> 建议继续沿用当前这个文件里的轻量“自愈式初始化”风格，不单独做复杂 migration 框架。

#### 2. `requirements.txt`
新增：
- `pyserial>=3.5`

#### 3. 新建 `core/serial_manager.py`
实现一个和 `SSHConnection` 尽量对齐的串口会话类，例如：
- `SerialConnection`

建议提供的接口：
- `connect()`
- `disconnect()`
- `send_keys(data)`
- `send_command(command, wait_time=None)`
- `set_output_callback(callback)`
- `set_disconnect_callback(callback)`
- `resize(cols, rows)`（可保留空实现，保证 UI 层统一调用不炸）
- `connected` 属性

实现原则：
- 使用 `pyserial.Serial`
- 后台线程持续读串口输出
- 输出统一按文本回调给 UI
- `send_command()` 默认补 `\r` 或 `\r\n`，优先兼容网络设备 CLI

#### 4. `ui/asset_panel.py`
扩展资产编辑对话框：
- 协议增加 `serial`
- 根据协议动态切换表单显示

建议行为：
- `ssh/telnet`：显示现有 IP/端口/用户名/密码字段
- `serial`：重点显示串口配置字段
  - 串口端口
  - 波特率
  - 数据位
  - 校验位
  - 停止位
  - 流控
- 对于 `serial`，IP 可以允许为空或写占位值，但更推荐直接放宽校验逻辑

还要同步更新：
- `get_data()`
- `validate_and_accept()`

#### 5. `ui/terminal_widget.py`
把当前“SSH 专属终端标签”抽成“通用终端标签”：

##### 推荐改法
- 保留 `TerminalView`
- 把 `set_ssh_connection()` 改成更通用的 `set_connection()`
- `TerminalTab.connect_to_device()` 内根据 `asset['protocol']` 分流：
  - `ssh` → `SSHConnection`
  - `serial` → `SerialConnection`
  - `telnet` 暂时仍按现状处理或显式提示未实现

##### 关键点
UI 层只依赖统一接口：
- `send_keys()`
- `send_command()`
- `disconnect()`
- `connected`

这样串口与 SSH 可共用：
- 标签页
- 底部快捷命令栏
- 状态栏
- 日志逻辑

#### 6. `ui/main_window.py`
主窗口逻辑改动应该很少：
- 保持 `self.terminal_panel.open_terminal(asset)` 不变
- 在状态文案上支持串口资产显示，例如：
  - `正在打开 SW-Core 串口终端...`
  - tooltip 里显示 `COM3` 或 `/dev/ttyUSB0`

---

## 阶段二：做成真正可长期替代 MobaXterm 的版本

### 目标
把“能连”升级成“好用”。

### 功能点

#### 1. 终端标签信息增强
- 串口标签名显示：设备名 + 串口号
- 状态栏显示当前参数：
  - `COM3 | 9600 8N1`

#### 2. 快捷发送增强
在 `ui/terminal_widget.py` 现有快捷命令基础上增加：
- 发送 Break（如果 pyserial 和平台支持，可后续补）
- Ctrl+C
- Ctrl+Z
- 回车模式切换（CR / LF / CRLF）
- 本地回显开关

#### 3. 会话日志
复用现有 `db.log_command()` 思路，但建议补充：
- 串口连接日志
- 发送命令日志
- 可选保存接收内容到本地文本文件

#### 4. 资产级串口模板
允许快速复用常见配置：
- Cisco Console：9600 8N1 none
- 华为 Console：9600 8N1 none
- Linux Serial：115200 8N1 none

#### 5. 端口枚举
在资产编辑对话框中增加“扫描本机串口”：
- Windows: COM1, COM2...
- Linux: `/dev/ttyUSB*`, `/dev/ttyS*`
- 通过 `serial.tools.list_ports.comports()` 获取

---

## 阶段三：靠近 MobaXterm 替代体验

### 可选增强项
这些不是首版必须，但如果你真打算替代 MobaXterm，很值得做：

#### 1. 串口会话快速入口
- 工具菜单新增“新建串口会话”
- 不必先创建资产，也能临时打开串口终端
- 之后可选择“保存为资产”

#### 2. 会话配置收藏
- 最近使用串口
- 收藏会话模板
- 自动恢复上次串口参数

#### 3. 原始模式增强
- 十六进制发送/查看
- 自动发送脚本
- 文本捕获导出

#### 4. 自动重连
- USB 转串口短暂断开后自动重试
- 明确提示“设备被拔出 / 端口不存在 / 被其他程序占用”

---

## 建议的代码结构调整

### 推荐抽象方向
当前不要一上来大改成复杂继承体系，但至少做一层“鸭子类型统一接口”。

#### 最小统一接口
SSH 和串口连接对象都实现：
- `connect()`
- `disconnect()`
- `send_keys(data)`
- `send_command(command, wait_time=None)`
- `set_output_callback(callback)`
- `set_disconnect_callback(callback)`
- `connected`

这样 `TerminalView` / `TerminalTab` 不再关心协议类型。

### 后续可再演进
如果未来还想支持：
- 真 Telnet
- 本地 shell
- Serial over TCP
- Reverse SSH

再把它们收敛成：
- `core/session_types.py` 或 `core/terminal_session.py`

首版不建议现在就过度抽象。

---

## 建议修改文件清单

### 必改
- `core/db.py`
- `core/ssh_manager.py`
- `ui/asset_panel.py`
- `ui/terminal_widget.py`
- `requirements.txt`

### 新增
- `core/serial_manager.py`
- `serial_console_plan.md`（本方案文件）

### 可选修改
- `ui/main_window.py`
- `README.md`

---

## 详细实施顺序

### Step 1
先扩数据库和资产表单：
- 加串口字段
- 表单能编辑串口参数
- 资产可保存 `protocol=serial`

### Step 2
新增 `SerialConnection`：
- 完成连接、收发、断开、后台读线程
- 接口尽量对齐 `SSHConnection`

### Step 3
改造终端 UI 为协议无关：
- `set_ssh_connection()` → `set_connection()`
- `TerminalTab.connect_to_device()` 分协议构造连接对象
- 完成串口标签打开

### Step 4
补主窗口和资产入口体验：
- 串口资产双击可直连
- 标签和状态显示更清晰

### Step 5
做离屏回归测试：
- 串口资产表单创建/编辑
- 串口标签页创建
- 非真实串口环境下的失败提示
- 不影响现有 SSH 路径

### Step 6
有真实环境时做联调：
- Windows COM 口实测
- USB 转串口实测
- Cisco / 华为控制台登录验证

---

## 验证清单

### 离线验证
1. `python -m py_compile` 校验：
   - `core/db.py`
   - `core/serial_manager.py`
   - `ui/asset_panel.py`
   - `ui/terminal_widget.py`
   - `ui/main_window.py`

2. 启动程序：
   - `python main.py`

3. 手工验证：
   - 新建设备，协议选 `serial`
   - 保存后重新编辑，确认串口参数保留
   - 双击串口资产，能打开终端标签
   - 无效串口号时，看到明确报错
   - SSH 资产双击连接仍保持正常

### 有设备时的联调验证
1. 连接真实串口设备
2. 验证回车、退格、方向键、Ctrl+C
3. 验证长输出连续滚动
4. 验证断开后状态变化
5. 验证多标签并行：SSH + 串口同时打开

---

## 关键风险与处理建议

### 风险 1：资产模型现在强制 IP
- 建议对 `serial` 放宽 `ip` 必填校验
- UI 上应把“IP 地址”改为协议感知，不然会让串口资产体验很怪

### 风险 2：TerminalView 命名和耦合太 SSH 化
- `set_ssh_connection()` 应尽快改名
- 否则后续每加一种协议都要继续打补丁

### 风险 3：Windows / WSL / Linux 串口名不同
- 端口选择不要写死
- 尽量用 `serial.tools.list_ports`

### 风险 4：真实串口行为比 SSH 更原始
- 有些设备只认 `\r`
- 有些需要本地回显
- 首版最好把换行策略做成可调

---

## 我建议的首版范围

如果你想尽快开始替代 MobaXterm，首版建议只做这些：
- 资产支持 `serial`
- 串口参数可配置
- `SerialConnection` 可连接/收发/断开
- 串口资产双击可打开终端标签
- 复用现有终端视图和快捷命令栏
- 失败提示清晰
- 不破坏现有 SSH 功能

这版做完，就已经是一个真正可用的基础版本了。后面再往“好用”和“MobaXterm 替代”上迭代。