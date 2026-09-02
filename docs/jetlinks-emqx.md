# JetLinks + EMQX 对接指南（8 路继电器模拟器）

> 本文档描述把 `simulators/relay_jetlinks.py`（8 路继电器模拟器）接入 **EMQX + JetLinks**
> 的完整闭环：设备 → EMQX → JetLinks。
>
> **制作者：第七组（电信专业）**

## 1. 拓扑与角色

```
┌─────────────────────┐   MQTT over TLS + 认证   ┌──────┐   订阅/下发   ┌────────────┐
│  继电器模拟器(8路)     │ ───────────────────────▶ │ EMQX │ ◀───────────── │  JetLinks   │
│  simulators/         │  properties/event/online │ Broker│   读属/下发     │  物联网平台   │
│  relay_jetlinks.py   │ ◀─────────────────────── │      │ ─────────────▶ │  物模型/设备 │
└─────────────────────┘   function/# 下行指令      └──────┘                └────────────┘
```

| 组件 | 职责 |
|------|------|
| 继电器模拟器 | 连 EMQX；按 JetLinks 规范上报属性/事件/在线；订阅并执行平台下发指令，回功能响应 |
| EMQX | MQTT Broker：TLS + 认证、主题路由、遗嘱、消息转发 |
| JetLinks | 订阅 EMQX 上设备消息；通过物模型解析入库；下发指令；提供 API/页面 |

## 2. EMQX 配置要点

> **本环境实测（已通过端到端验证）**：`172.16.4.211` 上跑的 EMQX **v6.1.4**，Dashboard 在 `:9183`，宿主机对外 **MQTT 明文端口是 `9783`**（映射到容器 `1883`）。模拟器用 `emqx.host=172.16.4.211 / port=9783 / username=test / password=123456 / use_tls=false` 即可连接并已被独立订阅者确认收到消息。

- **接入**：本环境用**明文 TCP**（`9783`）即可。若换用 TLS 用默认 `8883`；自签证书时填 `emqx.ca_file` 路径，或临时 `tls_insecure: true`。
- **认证**：`emqx.username` 用 MQTT 客户端用户（本环境为 `test/123456`）。支持 `productId/deviceId/secretKey` 三种凭据之一即可。
- **主题权限（ACL）**：只允许设备访问自己前缀，如 `/product/{deviceId}/#`，防止越权。
- **QoS/遗嘱**：下发指令用 QoS1；状态上报用 QoS1；配置 Last Will 让异常掉线由 Broker 代发 `offline` 到 `/product/{deviceId}/offline`。

## 3. JetLinks 配置要点

1. **建产品**：产品标识（`product_id`）例如 `relay_product`，接入方式选 **MQTT**。
2. **导入物模型**：把 `docs/jetlinks-thing-model.json` 导入到该产品：
   - 属性：`ch1_state`~`ch8_state`（布尔）、`ch1_voltage`~`ch8_voltage`（电压模拟值,double）、`online`(bool)、`ts`(long)
   - 功能：`set_channel`（channel + state）
   - 事件：`online_status`
3. **注册设备**：设备标识（`device_id`）例如 `relay01`，与模拟器 `jetlinks.device_id` 一致。
4. **接 EMQX**：在 JetLinks「设备接入 / MQTT 服务」里配置它能连到你的 EMQX（订阅设备主题、向设备功能主题下发）。JetLinks 通过它订阅 `/product/{deviceId}/#` 并往下发主题发布命令。

> 说明：JetLinks 不同版本对「外接 EMQX」的配置入口不一（一般是网络组件/MQTT 服务/设备接入网关），按你部署版本对应设置即可；主题前缀必须与模拟器 `config.json` 里 `jetlinks.topic` 一致。

## 4. 模拟器配置与运行

**config.json 默认值（本环境实测）**
```json
"emqx":   { "host": "172.16.4.211", "port": 9783, "username": "test",
            "password": "123456", "use_tls": false, "ca_file": "",
            "qos": 1, "keepalive": 60 },
"jetlinks": { "product_id": "relay_product", "device_id": "relay01",
              "channel_count": 8, "report_period_sec": 5, "simulate_voltage": true,
              "log_file": "relay_jetlinks.log",
              "topic": {
                "properties_post": "/product/{deviceId}/properties/post",
                "event": "/product/{deviceId}/event/{eventId}",
                "function_send": "/product/{deviceId}/function/{functionId}",
                "online": "/product/{deviceId}/online",
                "offline": "/product/{deviceId}/offline",
                "command_subscribe": "/product/{deviceId}/function/#"
              } }
```

**运行（项目根目录）**
```bash
.venv\Scripts\python.exe simulators\relay_jetlinks.py            # 持续：监听下发 + 周期上报
.venv\Scripts\python.exe simulators\relay_jetlinks.py --once      # 上报一次属性后退出
.venv\Scripts\python.exe simulators\relay_jetlinks.py --dry-run   # 不连网，打印8路与主题
```

**主题模板占位符**：`{productId}`、`{deviceId}`、`{functionId}`、`{eventId}`。若你们用的前缀是 `/{productId}/{deviceId}/...`，只需把 `topic` 里改成 `"/{productId}/{deviceId}/properties/post"` 等即可，代码零改动。

## 5. 消息示例

> **约定（已实测有效）**：JetLinks 官方 MQTT 协议的主题为 `/{productId}/{deviceId}/...`，属性上报用 `properties/report`，消息体是放在 `properties` 字段里。以下均以 `productId=relay_product_g7`、`deviceId=relay01` 为例。

**上行：属性上报** → `/relay_product_g7/relay01/properties/report`（字段为 `chX_state` 布尔 + `chX_voltage` 电压值 + `online` + `ts`）
```json
{ "properties": { "ch1_state":false,"ch1_voltage":220.0,"ch2_state":true,"ch2_voltage":219.7,
                  "ch3_state":false,"ch3_voltage":0,"ch4_state":false,"ch4_voltage":0,
                  "ch5_state":false,"ch5_voltage":0,"ch6_state":false,"ch6_voltage":0,
                  "ch7_state":false,"ch7_voltage":0,"ch8_state":false,"ch8_voltage":0,
                  "online":true,"ts":1724147200 } }
```

**上行：在线事件** → `/relay_product_g7/relay01/event/online_status`
```json
{ "data": { "online": true } }
```

**下行：平台下发功能调用**（JetLinks 平台「功能调试」按钮触发，订阅 `/{productId}/{deviceId}/#` 即可收到）
`/relay_product_g7/relay01/function/invoke`
```json
{ "messageType":"INVOKE_FUNCTION","messageId":"209...","deviceId":"relay01",
  "functionId":"set_channel","inputs":[{"name":"params","value":{"channel":3,"state":true}}] }
```

**上行：功能回执** → `/relay_product_g7/relay01/function/invoke/reply`
```json
{ "messageId":"209...","success":true,
  "output":{"changed":true,"channels":[{"channel":3,"status":"on","voltage":217.8,"current":2.49}]} }
```

> 下行已实测：JetLinks 调用 `set_channel` → EMQX `function/invoke` → 模拟器执行 → 回执 `function/invoke/reply` → `ch3_state`/`ch3_voltage` 属性更新。

## 6. 两种报文格式满足甲方要求

- **情况B：终端直接输出 JetLinks 物模型格式**（默认）
  ```bash
  .venv\Scripts\python.exe simulators\relay_jetlinks.py --format jetlinks
  ```
  终端发布 `/relay_product_g7/relay01/properties/report` + `{"properties":{"ch1_state":...,"ch1_voltage":...}}`，JetLinks 直接解析。

- **情况A：终端输出原始报文（图格式）+ EMQX 规则转换**
  ```bash
  .venv\Scripts\python.exe simulators\relay_jetlinks.py --format original
  ```
  终端发布原始报文 `/product/relay01/properties/post` + `{"method":"thing.event.property-post","params":{"ch1_state":true,"ch1_voltage":220,...}}`；
  由 EMQX 规则 `relay_original_to_jetlinks_g7`（`POST /api/v5/rules`）转换：取出 `params` 包成 `{"properties":{...}}` 转发到 `/relay_product_g7/${deviceId}/properties/report`。

> 情况B 已实测：JetLinks 里 `relay01` 在线且 18 个属性（`chX_state` + `chX_voltage` + `online` + `ts`）被解析，含电压模拟值。
> 情况A 的 EMQX 规则转换对布尔/数值字段的模板渲染需在平台侧核对（推荐直接用情况B）。

## 7. 本地自测（不依赖 EMQX/JetLinks）

用 `--cmd` 让模拟器连上后立即模拟收到一条下发指令，验证执行与响应链路：
```bash
.venv\Scripts\python.exe simulators\relay_jetlinks.py \
  --cmd '{"method":"thing_service_service_invoke","id":"cmd_001","params":{"functionId":"set_channel","channel":3,"status":"on"}}'
```

## 7. M1 验收对照

- [ ] 模拟器可成功连接 EMQX（`_on_connect` 显示 reason_code=0）
- [ ] `ch1~ch8` 状态按 `report_period_sec` 定时上报，JetLinks 设备详情可见
- [ ] JetLinks 下发指令，模拟器执行并返回 `function` 响应，平台侧显示成功
- [ ] 断线自动退避重连并恢复上报
- [ ] 日志完整（`relay_jetlinks.log`），无致命错误
- [ ] 用 MQTTX 连 EMQX 可订阅 `/product/relay01/#` 观察到全部消息

## 8. 待填写的连接信息

请在 config.json 确认/替换：
- `emqx.host` / `emqx.port` / `emqx.username` / `emqx.password` / `emqx.ca_file`（TLS 证书，若需要）
- `jetlinks.product_id` / `jetlinks.device_id`
- `jetlinks.topic.*`（若你们的前缀不是 `/product/{deviceId}/...`）
- JetLinks 侧「外接 EMQX」的订阅/下发主题，务必与 `jetlinks.topic` 完全一致
