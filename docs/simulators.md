# 模拟器与采集程序（simulators）

本目录实现「终端模拟软件」的两个功能，均使用 Python（项目 venv，内含 `paho-mqtt`、`pymodbus`），

> **制作者：第七组（电信专业）**
经 MQTT 上报到服务器 `172.16.4.211:9783`（`test`/`123456`）。

## 目录结构

```
simulators/
  config.json                # 共享配置文件（MQTT + 传感器 + Modbus）
  sensor_state.json          # 温湿度当前值（手动编辑触发上报）
  temp_humidity_simulator.py # 功能1：温湿度传感器模拟器
  modbus_gateway.py          # 功能2：Modbus TCP 采集上报
```

## 环境

```bash
# 项目根目录
python -m venv .venv
.venv\Scripts\python.exe -m pip install paho-mqtt pymodbus
```

> 本机已创建 `.venv` 并装好 `paho-mqtt 2.1.0`、`pymodbus 3.15.0`。

---

## 功能 1：温湿度传感器模拟器

**原理**：用 JSON 文件 `sensor_state.json` 存温湿度；**手动编辑该文件**改变数值，
脚本每 `poll_interval_sec` 秒检测一次，值发生变化即通过 MQTT 上报。

**运行**：
```bash
.venv\Scripts\python.exe simulators\temp_humidity_simulator.py
```

**改值触发上报**：编辑 `sensor_state.json` 的 `temperature` / `humidity`，保存后自动上报。

**上报主题**：`smart-relay/sensor01/data`（见 config 的 `sensor.topic`）

**payload 格式**（自定义）：
```json
{"deviceId":"sensor01","type":"temp_humidity","temperature":31.5,"humidity":55.5,"ts":1724147200}
```

---

## 功能 2：Modbus TCP 采集上报

**原理**：从从站 `192.168.20.59:5502` 采集寄存器（默认 `0x0009`），经 MQTT 上报。
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

## config.json 字段说明

| 段 | 字段 | 说明 |
|----|------|------|
| `mqtt` | `host`/`port`/`username`/`password`/`qos` | Broker 连接与发布 QoS |
| `sensor` | `device_id`/`state_file`/`poll_interval_sec`/`topic` | 模拟器设备标识、状态文件、检测间隔、上报主题 |
| `modbus` | `host`/`port`/`unit_id`/`device_id`/`register_start`/`register_count`/`poll_interval_sec`/`read_topic` | Modbus 从站、从站地址、寄存器段、采集间隔、上报主题 |

## 已验证（本次实测）
- Modbus：`192.168.20.59:5502` 连通，`0x0009` 读取 → MQTT 上报成功。
- 传感器：首次上报 + 修改 `sensor_state.json` 后自动二次上报，均到达 Broker。
