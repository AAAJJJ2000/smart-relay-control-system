# MQTT 收发实操流程（工作计划）

> 参考《MQTT 收发实操流程图》，按 6 步在我们自己的项目 smart-relay-control-system 上完成完整收发闭环。
> 图中是公共示例服务器 `broker.emqx.io:1883`，这里**全部适配到本项目自己的 Broker**。
>
> **制作者：第七组（电信专业）**

## 我们的 MQTT 服务器（替代图中的公共服务器）

| 项 | 图中 | 本项目实际 |
|----|------|-----------|
| Broker 地址 | `broker.emqx.io:1883` | `172.16.4.211:9783` |
| 账号/密码 | 无（公共匿名） | `test` / `123456` |
| 端口类型 | 标准公开（1883） | 已确认**明文 TCP**（9783 连通且认证通过） |

## 6 步流程

### 1. 准备环境
- 图形化客户端 **MQTTX**（或 Web 版）。
- 本项目也可用已装好的 Python 客户端：`E:\NEW\smart-relay-control-system\.venv` 内已含 `paho-mqtt 2.1.0`。

### 2. 连接 Broker
- 连接到 `172.16.4.211:9783`，使用 `test`/`123456` 认证。
- 已验证：TCP 可达、`reason_code=Success`、明文 TCP 端口（非 WS/TLS）。

### 3. 订阅主题（SUB）
- 订阅设备状态主题：`smart-relay/+/status`，QoS 1。
- （图中 `device/+/status` → 本项目命名为 `smart-relay/+/status`）

### 4. 发布消息（模拟控制，PUB）
- 发布控制命令主题：`smart-relay/relay01/cmd`，QoS 1。
- 负载：`{"cmd":"on"}`。
- （图中 `device/relay01/cmd` 与 `{"cmd":"on"}` → 本项目命名/负载保持一致）

### 5. 接收响应
- 接收设备状态上报，JSON 负载示例：
  ```json
  {"deviceId":"relay01","channel":1,"status":"on","ts":1724147200}
  ```

### 6. 观察与分析
- 查看消息流向、理解主题结构、分析 QoS 行为、体验订阅/发布模型。

## 适配说明
- 图中为 `device/...` 主题，本项目统一采用 `smart-relay/...` 主题前缀。
- 图中为公共匿名 broker，本项目使用带账号密码认证的私有 broker。
