# MQTT 连接配置与使用规范

> 本文档记录 smart-relay-control-system 项目使用 MQTT 的 Broker 连接信息、主题设计与各模块职责。
>
> **制作者：第七组（电信专业）**

## 1. Broker 连接配置

| 参数 | 值 |
|------|-----|
| Broker 地址（IP） | `172.16.4.211` |
| 端口 | `9783` |
| 用户名 | `test` |
| 密码 | `123456` |

**连接注意事项**

- 端口 `9783` 为非标准 MQTT 端口（标准为 `1883` 明文 / `8883` TLS）。默认按**明文 TCP** 连接。
- 若客户端连接失败，可尝试以下变体：
  - WebSocket：`ws://172.16.4.211:9783`
  - TLS：`mqtts://172.16.4.211:9783`
- 需要携带账号密码做身份认证：`username_pw_set("test", "123456")`。
- 已确认该 IP:端口（`172.16.4.211:9783`）在本机 TCP 可达（`TcpTestSucceeded=True`）。ICMP ping 通常被防火墙拦截，属正常现象。

## 2. 主题（Topic）设计

```
smart-relay/<device-id>/cmd        # 控制指令：ON / OFF / 状态查询
smart-relay/<device-id>/status     # 设备状态上报：开/关、电流、温度等
smart-relay/broadcast/ota          # 广播：固件升级等
```

- 控制指令（cmd）建议使用 **QoS 1**（至少一次投递）。
- 状态上报（status）使用 **QoS 0/1** 均可。

## 3. 各模块的 MQTT 角色

| 目录 | 角色 | 说明 |
|------|------|------|
| `backend/` | 服务端客户端 | 连接 Broker，发布 `cmd` 指令，订阅 `status` 状态并转发给前端 |
| `firmware/` | 设备端客户端 | 继电器模块连接 Broker，订阅 `cmd` 控制继电器，发布 `status` |
| `frontend/` | 非 MQTT | 只与 backend 通信（REST/WebSocket），由 backend 桥接 MQTT |
| `tools/` | 调试工具 | 用 `test`/`123456` 直接连 Broker，模拟设备或下发指令 |
| `tests/` | 集成测试 | 端到端验证「指令 → 继电器 → 状态上报」链路 |
| `docs/` | 文档 | 本文档 |

## 4. Python 客户端示例（paho-mqtt）

```bash
# 在项目内创建虚拟环境并安装客户端库（避免系统权限问题）
python -m venv .venv
.venv\Scripts\python.exe -m pip install paho-mqtt
```

```python
import paho.mqtt.client as mqtt

BROKER = "172.16.4.211"
PORT   = 9783
USER   = "test"
PASS   = "123456"

def on_connect(client, userdata, flags, rc):
    print(f"连接成功，返回码={rc}")  # rc==0 表示认证通过
    client.subscribe("smart-relay/demo/status")

def on_message(client, userdata, msg):
    print(f"{msg.topic}: {msg.payload.decode()}")

client = mqtt.Client()
client.username_pw_set(USER, PASS)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_forever()
```

发布消息：
```python
client.publish("smart-relay/demo/cmd", "ON")
```

## 5. 命令行调试（若服务器装有 mosquitto 工具）

```bash
mosquitto_sub -h 172.16.4.211 -p 9783 -u test -P 123456 -t "smart-relay/#"
mosquitto_pub -h 172.16.4.211 -p 9783 -u test -P 123456 -t "smart-relay/demo/cmd" -m "ON"
```
