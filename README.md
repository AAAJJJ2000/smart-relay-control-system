# smart-relay-control-system（智能继电器控制系统）

基于 **MQTT** 的智能继电器控制 / 数据采集实践项目。

> **制作者：第七组（电信专业）**

项目通过 MQTT 实现「设备数据上报 + 控制指令下发」，
内含**温湿度传感器模拟器**、**Modbus TCP 采集上报**，
并配合 **MQTTX** 图形工具实时观察消息流。

---

## 目录结构

```
smart-relay-control-system/
├── backend/                  # 服务端（占位，后续接入业务逻辑）
├── firmware/                 # 网关/设备端固件（占位）
├── frontend/                 # 前端界面（占位）
├── docs/                     # 项目文档
│   ├── mqtt.md               # MQTT 连接配置与主题设计
│   ├── mqtt-workflow.md      # MQTTX 6 步实操流程
│   └── simulators.md         # 模拟器与采集程序使用说明
├── simulators/               # 终端模拟软件（Python 实现）
│   ├── config.json           # 共享配置（MQTT/传感器/Modbus）
│   ├── sensor_state.json     # 温湿度当前值（改它触发上报）
│   ├── temp_humidity_simulator.py  # 温湿度传感器模拟器
│   └── modbus_gateway.py     # Modbus TCP 采集/写入并上报 MQTT
├── tests/                    # 测试（占位）
├── tools/                    # 工具脚本（占位）
├── .gitignore
└── README.md
```

---

## 环境要求

- Python 3.11+
- 虚拟环境（项目根目录建 `.venv`）内安装依赖：

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install paho-mqtt pymodbus
```

- 图形化 MQTT 客户端：**MQTTX**（观察消息流用）。

---

## MQTT Broker 配置

| 项 | 值 |
|----|-----|
| Broker 地址 | `172.16.4.211` |
| 端口 | `9783`（明文 TCP MQTT） |
| 用户名 | `test` |
| 密码 | `123456` |

> 详细说明见 [`docs/mqtt.md`](docs/mqtt.md)。

---

## 主题（Topic）设计

```
smart-relay/<device-id>/cmd        # 控制指令：ON / OFF / 查询
smart-relay/<device-id>/status     # 设备状态上报
smart-relay/sensor01/data          # 温湿度传感器上报
smart-relay/modbus01/data          # Modbus 采集上报
```

- 控制指令建议 QoS 1；状态上报 QoS 0/1。

---

## 功能模块

### 1. 温湿度传感器模拟器
- 用 `simulators/sensor_state.json` 存储温湿度值；
- **手动改该文件**（值发生变化）即自动通过 MQTT 上报；
- 上报主题：`smart-relay/sensor01/data`。

### 2. Modbus TCP 采集上报
- 从从站 `192.168.20.59:5502` 采集寄存器 `0x0000–0x0009`，上报 MQTT；
- 寄存器地址在 `config.json` 的 `register_start/register_count` 配置，**每个小组读写自己那段，避免冲突**；
- 支持读取（持续/一次）与写入（`--write`）；
- 上报主题：`smart-relay/modbus01/data`。

---

## 运行

```powershell
# 温湿度传感器模拟器（持续监视文件，改值即上报）
.venv\Scripts\python.exe simulators\temp_humidity_simulator.py

# Modbus 持续采集上报（每 5 秒一次）
.venv\Scripts\python.exe simulators\modbus_gateway.py

# Modbus 采集一次并退出
.venv\Scripts\python.exe simulators\modbus_gateway.py --once

# Modbus 写入一个寄存器一次（如写 0x0009 = 123）
.venv\Scripts\python.exe simulators\modbus_gateway.py --write 0x0009 123
```

配合 **MQTTX**：订阅 `smart-relay/#`（或对应主题），连接 `172.16.4.211:9783` 即可实时查看上报消息。
完整实操见 [`docs/mqtt-workflow.md`](docs/mqtt-workflow.md)。

---

## 文档

- [docs/mqtt.md](docs/mqtt.md)：MQTT 连接配置与主题设计
- [docs/mqtt-workflow.md](docs/mqtt-workflow.md)：MQTTX 6 步实操流程
- [docs/simulators.md](docs/simulators.md)：模拟器与采集程序使用说明

---

## 说明
- 本项目为教学/实践性质，MQTT Broker 为共享测试服务器，账号密码为教学用。
- `sensor_state.json` 为便于演示的模拟数据源；Modbus 为真实设备/端点采集。
