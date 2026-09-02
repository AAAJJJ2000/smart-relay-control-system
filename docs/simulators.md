# 模拟器与采集程序（simulators）

本目录实现「终端模拟软件」，均使用 Python（项目 venv，内含 `paho-mqtt 2.1.0`、`pymodbus 3.15.0`），
经 MQTT 上报 / 控制，并可对接 JetLinks + EMQX。

> **制作者：第七组（电信专业）**

## 目录结构

```
simulators/
  config.example.json          # 配置模板（密码占位；复制为 config.json 使用）
  config.json                  # 本机实际配置（已被 .gitignore 排除，不入库）
  sensor_state.json            # 温湿度当前值（手动编辑触发上报）
  temp_humidity_simulator.py   # 功能1：温湿度传感器模拟器
  modbus_gateway.py            # 功能2：Modbus TCP 采集上报
  relay_simulator.py           # 功能3：8 路继电器模拟器（本地 Broker）
  relay_jetlinks.py            # 功能4：8 路继电器模拟器（JetLinks/EMQX 协议版）
```

## 环境

```bash
# 项目根目录
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 本机已创建 `.venv` 并装好 `paho-mqtt 2.1.0`、`pymodbus 3.15.0`。

## 配置

> 仓库不含真实配置。**复制 `simulators/config.example.json` 为 `simulators/config.json` 并填入实际账号密码**即可运行；
> `config.json` 已被 `.gitignore` 排除。

```powershell
Copy-Item simulators\config.example.json simulators\config.json
```

---

## 功能 1：温湿度传感器模拟器

**原理**：用 JSON 文件 `sensor_state.json` 存温湿度；**手动编辑该文件**改变数值，
脚本每 `poll_interval_sec` 秒检测一次，值发生变化即通过 MQTT 上报；
同时支持按 `sensor.report_period_sec` **周期性自动上报**（0=关闭，仅变化时上报）。

**运行**：
```bash
.venv\Scripts\python.exe simulators\temp_humidity_simulator.py
```

**改值触发上报**：编辑 `sensor_state.json` 的 `temperature` / `humidity`，保存后自动上报。
**周期自动上报**：无论是否改值，每 `report_period_sec` 秒自动上报一次当前值。

**上报主题**：`smart-relay/sensor01/data`（见 config 的 `sensor.topic`）

**payload 格式**（自定义）：
```json
{"deviceId":"sensor01","type":"temp_humidity","temperature":31.5,"humidity":55.5,"ts":1724147200}
```

---

## 功能 2：Modbus TCP 采集上报

**原理**：从从站 `192.168.20.59:5502` 采集寄存器（默认 `0x0009`），经 MQTT 上报。
**周期上报**：每 `modbus.poll_interval_sec`（默认 5s）自动采集并上报一次。
**读写范围**：设备寄存器 `0x0000–0x0009`；每个小组在 `config.json` 里改成自己那段即可避免冲突。

**运行**：
```bash
# 持续采集上报
.venv\Scripts\python.exe simulators\modbus_gateway.py

# 采集一次并退出
.venv\Scripts\python.exe simulators\modbus_gateway.py --once

# 写入一个寄存器一次（如写 0x0009 = 123）
.venv\Scripts\python.exe simulators\modbus_gateway.py --write 0x0009 123
```

**小组防冲突**：修改 `config.json` 的 `modbus.register_start` / `modbus.register_count`，
例如本小组分配 `0x0003–0x0004`：
```json
"register_start": "0x0003",
"register_count": 2
```

**上报主题**：`smart-relay/modbus01/data`（见 config 的 `modbus.read_topic`）

**payload 格式**（自定义）：
```json
{"deviceId":"modbus01","type":"modbus_tcp","register_start":"0x0009",
 "register_count":1,"registers":{"0x0009":0},"values":[0],"ts":1724147200}
```

---

## 功能 3：8 路继电器模拟器（本地 Broker）

**原理**：模拟一台带 8 路开关的继电器设备。它**订阅指令主题** `smart-relay/<device>/cmd` 接收控制命令，
执行后**上报当前状态**到状态主题 `smart-relay/<device>/status`；同时按 `relay.report_period_sec` 周期上报。
上线/下线时发布 `online` 状态。断线自动退避重连，日志输出到控制台与 `relay_simulator.log`。

**运行**（项目根目录）：
```bash
# 持续运行：监听指令 + 每 report_period_sec 秒周期上报
.venv\Scripts\python.exe simulators\relay_simulator.py

# 只上报一次当前状态后退出
.venv\Scripts\python.exe simulators\relay_simulator.py --once

# 不连网络，仅打印当前 8 路状态（本地自检）
.venv\Scripts\python.exe simulators\relay_simulator.py --dry-run
```

**订阅/上报主题**（config 的 `relay.cmd_topic` / `relay.status_topic` / `relay.online_topic`）：
```text
smart-relay/relay01/cmd         # 下行控制指令（订阅，QoS 1）
smart-relay/relay01/status      # 上行状态上报（发布，QoS 1）
smart-relay/relay01/online      # 上线/下线状态（发布）
```

**控制指令（发布到 cmd 主题，JSON）**：

| 指令示例 | 含义 |
|----------|------|
| `{"cmd":"on"}` / `{"cmd":"off"}` | 整机 8 路全部开 / 全部关 |
| `{"cmd":"set","channel":3,"status":"on"}` | 将第 3 路置为 on |
| `{"cmd":"toggle","channel":3}` | 翻转第 3 路（on↔off） |
| `{"cmd":"query"}` | 仅查询，不改状态，触发一次上报 |

> 兼容省略 `cmd` 的形式：`{"channel":3,"status":"on"}` 等价于 `set`。

**状态上报（status 主题）payload 格式**：
```json
{
  "deviceId": "relay01",
  "type": "relay",
  "online": true,
  "reason": "command",
  "channels": [
    {"channel": 1, "status": "off", "voltage": 0, "current": 0},
    {"channel": 2, "status": "on", "voltage": 219.6, "current": 1.8}
  ],
  "ts": 1724147200
}
```

> `reason` 说明本次上报触发原因：`online`（上线）/ `command`（收到指令）/ `periodic`（周期上报）/ `once`（--once）。

---

## 功能 4：8 路继电器模拟器（JetLinks/EMQX 协议版）

**原理**：连接 EMQX（`config.json` 的 `emqx` 段），按 **JetLinks 官方 MQTT 协议**上报属性 / 事件 / 在线状态；
接收 **JetLinks 平台功能下发**（`set_channel`）并执行、回执。断线退避重连，日志输出到 `relay_jetlinks.log`。

**运行**：
```bash
# 情况B：直接输出 JetLinks 物模型格式（推荐，配合平台控制）
.venv\Scripts\python.exe simulators\relay_jetlinks.py --format jetlinks

# 情况A：输出训练图原始报文（由 EMQX 规则转换为 JetLinks 格式）
.venv\Scripts\python.exe simulators\relay_jetlinks.py --format original

# 不连网，打印 8 路状态与将使用的主题
.venv\Scripts\python.exe simulators\relay_jetlinks.py --dry-run
```

**主题**（JetLinks 官方协议，`/{productId}/{deviceId}/...`；见 config 的 `jetlinks.topic`）：
```text
/{productId}/{deviceId}/properties/report      # 属性上报（上行）
/{productId}/{deviceId}/event/{eventId}        # 事件上报（上行）
/{productId}/{deviceId}/function/invoke        # 功能调用（下行，平台→设备）
/{productId}/{deviceId}/function/invoke/reply  # 功能回执（上行，设备→平台）
```

**属性上报 payload**（字段为 `chX_state` 布尔 + `chX_voltage` 电压模拟值 + `online` + `ts`）：
```json
{"properties": {"ch1_state":false,"ch1_voltage":220.0,"ch2_state":true,"ch2_voltage":219.7,
                "ch3_state":false,"ch3_voltage":0,"ch4_state":false,"ch4_voltage":0,
                "ch5_state":false,"ch5_voltage":0,"ch6_state":false,"ch6_voltage":0,
                "ch7_state":false,"ch7_voltage":0,"ch8_state":false,"ch8_voltage":0,
                "online":true,"ts":1724147200}}
```

**平台下发功能调用**（`function/invoke`）：
```json
{"messageType":"INVOKE_FUNCTION","messageId":"...","deviceId":"relay01",
 "functionId":"set_channel","inputs":[{"name":"channel","value":3},{"name":"state","value":true}]}
```
> 原始终端格式的等价指令：`{"id":"cmd_001","method":"thing.service.property.set","params":{"ch1_state":false}}`。

**功能回执**（`function/invoke/reply`）：
```json
{"messageId":"...","success":true,"output":{"changed":true,"channels":[{"channel":3,"status":"on","voltage":220.2,"current":2.05}]}}
```

> 原始终端报文（情况A，交给 EMQX 规则转换）：`{"method":"thing.event.property-post","params":{"ch1_state":true,"ch1_voltage":220,"online":true,"ts":...}}`。

> 对接细节、两种报文格式（情况A 用 EMQX 规则转换 / 情况B 直连）及物模型导入见
> [`docs/jetlinks-emqx.md`](jetlinks-emqx.md) 与 [`docs/jetlinks-thing-model.json`](jetlinks-thing-model.json)。

---

## 启动与关闭（自行管理进程）

> 各模拟器都需要**保持进程运行**才会持续上报 / 响应；进程一旦停止即停止。

### 前台运行 + Ctrl+C 关闭（最常用）
进入项目根目录：
```powershell
cd E:\NEW\smart-relay-control-system
.venv\Scripts\python.exe simulators\temp_humidity_simulator.py   # 启动 sensor
```
- **关闭**：在窗口按 **`Ctrl+C`**。

其它模块同理（另开窗口）：
```powershell
.venv\Scripts\python.exe simulators\modbus_gateway.py           # Modbus 持续采集
.venv\Scripts\python.exe simulators\relay_simulator.py           # 8路继电器(本地)
.venv\Scripts\python.exe simulators\relay_jetlinks.py --format jetlinks   # 8路继电器(JetLinks)
```

### 后台运行 + 按 PID 关闭
```powershell
Start-Process -FilePath "E:\NEW\smart-relay-control-system\.venv\Scripts\python.exe" `
  -ArgumentList "simulators\relay_jetlinks.py","--format","jetlinks" `
  -WorkingDirectory "E:\NEW\smart-relay-control-system"
```
```powershell
Get-Process python* | Select Id, StartTime
Stop-Process -Id <PID> -Force
```

---

## config.json 字段说明

| 段 | 字段 | 说明 |
|----|------|------|
| `mqtt` | `host`/`port`/`username`/`password`/`qos` | Broker 连接与发布 QoS |
| `sensor` | `device_id`/`state_file`/`poll_interval_sec`/`report_period_sec`/`topic` | 设备标识、状态文件、检测间隔、周期上报间隔、上报主题 |
| `modbus` | `host`/`port`/`unit_id`/`device_id`/`register_start`/`register_count`/`poll_interval_sec`/`read_topic` | Modbus 从站、从站地址、寄存器段、采集间隔、上报主题 |
| `relay` | `device_id`/`channel_count`/`initial_state`/`cmd_topic`/`status_topic`/`online_topic`/`report_period_sec`/`simulate_voltage`/`log_file` | 继电器设备标识、路数、初始状态、指令/状态/在线主题、周期上报间隔、是否模拟电压电流、日志文件 |
| `emqx` | `host`/`port`/`username`/`password`/`use_tls`/`ca_file`/`qos`/`keepalive` | JetLinks 版连接的 EMQX Broker 与 TLS/认证 |
| `jetlinks` | `product_id`/`device_id`/`channel_count`/`initial_state`/`report_period_sec`/`simulate_voltage`/`log_file`/`publish_format`/`topic.*` | JetLinks 产品/设备标识、上报周期、输出格式、主题模板 |

> `publish_format` 取值：`jetlinks`（直接输出物模型格式）/ `original`（训练图原始报文，由 EMQX 规则转换）。

## 已验证（本次实测）
- Modbus：`192.168.20.59:5502` 连通，`0x0009` 读取 → MQTT 上报成功。
- 传感器：首次上报 + 修改 `sensor_state.json` 后自动上报，且按 `report_period_sec` 周期上报，均到达 Broker。
- 8 路继电器（本地）：连 Broker、订阅指令、执行 `set/toggle` 并上报状态成功。
- 8 路继电器（JetLinks）：`relay01` 在线、8 路属性解析；JetLinks 功能按钮下发 `set_channel` → 执行 → 回执 → 属性更新。
