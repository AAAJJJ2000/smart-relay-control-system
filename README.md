# smart-relay-control-system（智能继电器控制系统）

基于 **MQTT** 的智能继电器控制 / 数据采集实践项目。

> **制作者：第七组（电信专业）**

项目通过 MQTT 实现「设备数据上报 + 控制指令下发」闭环，包含**温湿度传感器模拟器**、**Modbus TCP 采集上报**、**8 路继电器模拟器**，
并支持对接 **JetLinks 物联网平台 + EMQX MQTT Broker**（设备接入、物模型、功能下发控制）。配合 **MQTTX** 图形工具可实时观察消息流。

---

## 目录结构

```
smart-relay-control-system/
├── backend/                  # 服务端（占位，后续接入业务逻辑）
├── frontend/                 # 前端界面（占位）
├── firmware/                 # 网关/设备端固件（占位）
├── simulators/               # 终端模拟软件（Python 实现）
│   ├── config.example.json   # 配置模板（密码占位，复制为 config.json 使用）
│   ├── config.json           # 本机实际配置（已被 .gitignore 排除，不入库）
│   ├── sensor_state.json     # 温湿度当前值（改它触发上报）
│   ├── temp_humidity_simulator.py  # 温湿度传感器模拟器
│   ├── modbus_gateway.py           # Modbus TCP 采集/写入并上报
│   ├── relay_simulator.py          # 8 路继电器模拟器（本地 Broker）
│   └── relay_jetlinks.py           # 8 路继电器模拟器（JetLinks/EMQX 协议版）
├── docs/                     # 项目文档
│   ├── mqtt.md               # MQTT 连接配置与主题设计
│   ├── mqtt-workflow.md      # MQTTX 6 步实操流程
│   ├── simulators.md         # 模拟器与采集程序使用说明
│   ├── jetlinks-emqx.md      # JetLinks + EMQX 对接指南
│   └── jetlinks-thing-model.json   # JetLinks 物模型（可导入）
├── tools/                    # 工具脚本
│   └── set_sensor.py         # 查看/修改温湿度模拟数据
├── tests/                    # 测试（占位）
├── requirements.txt          # Python 依赖清单
├── .gitignore
└── README.md
```

---

## 环境要求

- Python 3.11+
- 在项目根目录创建虚拟环境并安装依赖：

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

- 图形化 MQTT 客户端：**MQTTX**（观察消息流用，可选）。

---

## 配置说明

> 敏感/本机配置不入库。仓库提供 **`simulators/config.example.json`** 模板（密码为占位），
> **复制为 `simulators/config.json` 并填入真实值**即可运行（`config.json` 已被 `.gitignore` 排除）。

```powershell
Copy-Item simulators\config.example.json simulators\config.json
# 编辑 simulators\config.json，把 your_mqtt_user / your_mqtt_password 换成实际账号
```

`config.json` 包含 `mqtt`（Broker）、`sensor`、`modbus`、`relay`、`emqx`、`jetlinks` 六段配置。

---

## MQTT Broker 配置

| 项 | 值 |
|----|-----|
| Broker 地址 | `172.16.4.211` |
| 端口 | `9783`（明文 TCP MQTT） |
| 用户名 | `test` |
| 密码 | `123456` |

> 详细说明见 [`docs/mqtt.md`](docs/mqtt.md)。上述为共享测试 Broker 账号，实际以 `config.json` 为准。

---

## 主题（Topic）设计

### 本地 Broker（`smart-relay/...`）
```
smart-relay/<device-id>/cmd        # 控制指令：ON / OFF / 查询
smart-relay/<device-id>/status     # 设备状态上报
smart-relay/sensor01/data          # 温湿度传感器上报
smart-relay/modbus01/data          # Modbus 采集上报
```

### JetLinks 对接（官方协议，`/{productId}/{deviceId}/...`）
```
/{productId}/{deviceId}/properties/report      # 属性上报（上行）
/{productId}/{deviceId}/event/{eventId}        # 事件上报（上行）
/{productId}/{deviceId}/function/invoke        # 功能调用（下行，平台→设备）
/{productId}/{deviceId}/function/invoke/reply  # 功能回执（上行，设备→平台）
```

- 控制指令建议 **QoS 1**；状态上报 QoS 0/1。

---

## 功能模块

### 1. 温湿度传感器模拟器
- 用 `simulators/sensor_state.json` 存储温湿度值；
- **手动改该文件**（值变化）即自动通过 MQTT 上报；
- 支持按 `sensor.report_period_sec` **周期性自动上报**（如每 10s）；
- 上报主题：`smart-relay/sensor01/data`。

### 2. Modbus TCP 采集上报
- 从从站 `192.168.20.59:5502` 采集寄存器，经 MQTT 上报；
- 每 `modbus.poll_interval_sec`（默认 5s）**周期性采集上报**；
- 寄存器段（`register_start`/`register_count`）在 `config.json` 里配置，**各小组读写自己那段避免冲突**；
- 支持读取（持续/一次）与写入（`--write`）。

### 3. 8 路继电器模拟器（本地 Broker）——`relay_simulator.py`
- 模拟 8 路继电器开关，维护每路 `on/off` 状态（可模拟电压/电流）；
- 订阅 `smart-relay/<device-id>/cmd` 接收指令（整机开/关、单路开关、单路翻转、查询）；
- 状态变化立即上报 + 按 `report_period_sec` 周期上报到 `smart-relay/<device-id>/status`；
- 上线/下线发布到 `<online_topic>`；断线自动退避重连；日志输出到控制台与日志文件。

### 4. 8 路继电器模拟器（JetLinks/EMQX 协议版）——`relay_jetlinks.py`
- 连接 EMQX（`config.json` 的 `emqx` 段），按 **JetLinks 官方 MQTT 协议**上报属性、事件、在线状态；
- 接收 **JetLinks 平台功能下发**（`set_channel`）并执行、回执；
- 支持 `--format jetlinks`（直接输出物模型格式）与 `--format original`（训练图原始报文，由 EMQX 规则转换）；
- 断线退避重连、日志（`relay_jetlinks.log`）。

---

## JetLinks + EMQX 对接

> 设备 → EMQX(`172.16.4.211:9783`) → JetLinks(`local_mqtt` 网络组件订阅)。详细见 [`docs/jetlinks-emqx.md`](docs/jetlinks-emqx.md)。

**满足甲方两种报文格式要求：**

### 情况A：终端输出原始报文 + EMQX 规则转换
```bash
.venv\Scripts\python.exe simulators\relay_jetlinks.py --format original
```
- 终端发布训练图原始报文：`/product/{deviceId}/properties/post` + `{"method":"thing_service_property_post","params":{"ch1_status":...}}`；
- 由 **EMQX 规则** `relay_original_to_jetlinks_g7`（`POST /api/v5/rules`）转换：订阅 `/product/${deviceId}/properties/post`，取出 `ch1_status~ch8_status`，republish 到 `/{productId}/{deviceId}/properties/report`。

### 情况B：终端直接输出 JetLinks 物模型格式
```bash
.venv\Scripts\python.exe simulators\relay_jetlinks.py --format jetlinks
```
- 终端发布 `/{productId}/{deviceId}/properties/report` + `{"properties":{"ch1_status":...}}`，JetLinks 直接解析。

**设备控制（功能下发）**：JetLinks 平台「功能调试」点 `set_channel` → EMQX `function/invoke` → 模拟器执行 → 回执 `function/invoke/reply` → 属性更新。

**物模型**：导入 [`docs/jetlinks-thing-model.json`](docs/jetlinks-thing-model.json) 到产品（`ch1_status~ch8_status` + `online` 属性，`set_channel` 功能）。

---

## 工具

### `tools/set_sensor.py`
查看 / 修改温湿度模拟数据（修改 `simulators/sensor_state.json`，运行中的温湿度模拟器会因此触发上报）：
```powershell
# 查看当前值
.venv\Scripts\python.exe tools\set_sensor.py show
# 设置温/湿度
.venv\Scripts\python.exe tools\set_sensor.py set 33.5 62.0
# 随机生成合理值
.venv\Scripts\python.exe tools\set_sensor.py random
```

---

## 运行

```powershell
# 温湿度传感器模拟器（监视文件，改值即上报 + 周期上报）
.venv\Scripts\python.exe simulators\temp_humidity_simulator.py

# Modbus 持续采集上报（每 5 秒一次）
.venv\Scripts\python.exe simulators\modbus_gateway.py

# Modbus 采集一次并退出 / 写一个寄存器一次
.venv\Scripts\python.exe simulators\modbus_gateway.py --once
.venv\Scripts\python.exe simulators\modbus_gateway.py --write 0x0009 123

# 8 路继电器模拟器（本地 Broker）：持续监听指令 + 周期上报
.venv\Scripts\python.exe simulators\relay_simulator.py

# 8 路继电器模拟器（JetLinks/EMQX 协议版）
.venv\Scripts\python.exe simulators\relay_jetlinks.py --format jetlinks    # 情况B（用于平台控制）
.venv\Scripts\python.exe simulators\relay_jetlinks.py --format original    # 情况A（配合 EMQX 规则）
.venv\Scripts\python.exe simulators\relay_jetlinks.py --dry-run            # 不连网，打印8路状态与主题
```

配合 **MQTTX**：连接 `172.16.4.211:9783`（test/123456），订阅 `smart-relay/#` 或 JetLinks 相关主题即可实时查看消息。

> 程序需**保持运行**才会持续上报；启动/关闭（前台 Ctrl+C / 后台 PID）见 [`docs/simulators.md`](docs/simulators.md)。

---

## 文档

- [`docs/mqtt.md`](docs/mqtt.md)：MQTT 连接配置与主题设计
- [`docs/mqtt-workflow.md`](docs/mqtt-workflow.md)：MQTTX 6 步实操流程
- [`docs/simulators.md`](docs/simulators.md)：模拟器与采集程序使用说明
- [`docs/jetlinks-emqx.md`](docs/jetlinks-emqx.md)：JetLinks + EMQX 对接指南
- [`docs/jetlinks-thing-model.json`](docs/jetlinks-thing-model.json)：JetLinks 物模型（导入用）

---

## 说明

- 本项目为教学/实践性质；MQTT Broker 为共享测试服务器，账号密码为教学用。
- `config.json`（含真实密码）已被 `.gitignore` 排除，请勿提交；仓库仅提供 `config.example.json` 模板。
- `sensor_state.json` 为便于演示的模拟数据源；Modbus 为真实设备/端点采集。
- `relay_jetlinks.py` 对接 JetLinks 时涉及的产品（`relay_product_g7`）、设备（`relay01`）、EMQX 规则（`relay_original_to_jetlinks_g7`）需在对应平台按 [`docs/jetlinks-emqx.md`](docs/jetlinks-emqx.md) 配置。
