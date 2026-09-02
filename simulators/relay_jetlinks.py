"""8 路继电器模拟器 - JetLinks 协议版（设备 → EMQX → JetLinks）

作者：第七组（电信专业）

用途（对接 Day3「模拟设备客户端 + JetLinks/EMQX」）：
  该脚本模拟一台接入 EMQX 的 8 路继电器设备，并遵循 JetLinks 设备的 MQTT Topic 与消息规范：
    - 上行：属性上报（properties/post）、事件（event/{eventId}）、功能调用响应（function/{functionId}）、上线/下线
    - 下行：订阅平台下发（function/#、properties/write）
  消息体 method 采用 JetLinks thing 服务规范（thing_service_property_post / thing_service_service_invoke 等）。

拓扑：继电器模拟器 ─(MQTT over TLS + 认证)─> EMQX <─(订阅/下发)─ JetLinks

依赖：项目 .venv 内 paho-mqtt 2.1.0。

运行（项目根目录）：
  .venv\\Scripts\\python.exe simulators\\relay_jetlinks.py            # 持续：监听下发 + 周期上报
  .venv\\Scripts\\python.exe simulators\\relay_jetlinks.py --once      # 上报一次属性后退出
  .venv\\Scripts\\python.exe simulators\\relay_jetlinks.py --dry-run   # 不连网，仅打印 8 路状态与主题
  .venv\\Scripts\\python.exe simulators\\relay_jetlinks.py --cmd '{"..."}'
                                     # 连上后模拟收到一条下发指令(用于自测)
"""

import argparse
import json
import logging
import os
import random
import sys
import time

import paho.mqtt.client as mqtt

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def setup_logger(log_file):
    logger = logging.getLogger("relay-jetlinks")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    if log_file:
        if not os.path.isabs(log_file):
            log_file = os.path.join(BASE_DIR, log_file)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class RelayChannels:
    """8 路继电器状态管理。每路: {channel, status, voltage, current}"""

    def __init__(self, count, initial="off", simulate_voltage=True):
        self.count = count
        self.simulate_voltage = simulate_voltage
        self.channels = [self._make(i + 1, initial) for i in range(count)]

    @staticmethod
    def _make(channel, status):
        return {"channel": channel, "status": status, "voltage": 0, "current": 0}

    def _refresh(self, ch):
        if self.simulate_voltage:
            if ch["status"] == "on":
                ch["voltage"] = round(random.uniform(215.0, 225.0), 1)
                ch["current"] = round(random.uniform(0.5, 3.0), 2)
            else:
                ch["voltage"] = 0
                ch["current"] = 0

    def set_all(self, status):
        for ch in self.channels:
            ch["status"] = status
            self._refresh(ch)

    def set_one(self, channel, status):
        ch = self._find(channel)
        if ch:
            ch["status"] = status
            self._refresh(ch)
        return ch

    def toggle_one(self, channel):
        ch = self._find(channel)
        if ch:
            ch["status"] = "off" if ch["status"] == "on" else "on"
            self._refresh(ch)
        return ch

    def _find(self, channel):
        for ch in self.channels:
            if ch["channel"] == int(channel):
                return ch
        return None

    def snapshot(self):
        return [dict(ch) for ch in self.channels]

    def as_properties(self, include_ts=True):
        """按图格式转为属性字段（chX_state:bool + chX_voltage:number + ts）"""
        props = {}
        for ch in self.channels:
            props[f"ch{ch['channel']}_state"] = (ch["status"] == "on")
            props[f"ch{ch['channel']}_voltage"] = ch["voltage"]
        if include_ts:
            props["ts"] = int(time.time())
        return props


class TopicBuilder:
    """根据 config.jetlinks.topic 模板 + 占位符生成实际主题。"""

    def __init__(self, templates, product_id, device_id):
        self.templates = templates
        self.product_id = product_id
        self.device_id = device_id

    def _render(self, template, **extra):
        fmt = {"productId": self.product_id, "deviceId": self.device_id}
        fmt.update(extra)
        out = template
        for k, v in fmt.items():
            out = out.replace("{" + k + "}", str(v))
        return out

    def properties_post(self):
        return self._render(self.templates["properties_post"])

    def event(self, event_id):
        return self._render(self.templates["event"], eventId=event_id)

    def function_send(self, function_id):
        return self._render(self.templates["function_send"], functionId=function_id)

    def online(self):
        return self._render(self.templates["online"])

    def offline(self):
        return self._render(self.templates["offline"])

    def command_subscribe(self):
        return self._render(self.templates["command_subscribe"])


class RelaySimulatorJetlinks:
    def __init__(self, cfg, logger, simulate_voltage=True, publish_format=None):
        self.cfg = cfg
        self.log = logger
        em = cfg["emqx"]
        jl = cfg["jetlinks"]

        self.product_id = jl.get("product_id", "relay_product")
        self.device_id = jl.get("device_id", "relay01")
        self.qos = int(em.get("qos", 1))
        self.keepalive = int(em.get("keepalive", 60))
        self.report_period = float(jl.get("report_period_sec", 5))
        # publish_format: "jetlinks" 直接输出物模型格式；"original" 输出训练图原始报文(由EMQX规则转换)
        self.publish_format = str(publish_format or jl.get("publish_format", "jetlinks")).lower()

        self.topics = TopicBuilder(jl["topic"], self.product_id, self.device_id)

        count = int(jl.get("channel_count", 8))
        initial = str(jl.get("initial_state", "off"))
        self.channels = RelayChannels(count, initial, simulate_voltage)

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"relay-{self.device_id}-{os.getpid()}",
        )
        self.client.username_pw_set(em["username"], em["password"])
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # MQTT 遗嘱(Last Will)：设备异常断开/掉线时，由 EMQX 代发 offline 事件，
        # 使 JetLinks 能立刻将设备标记为离线（而不是等超时）。
        will_payload = json.dumps({
            "method": "thing_event_post",
            "id": "evt_will_%d" % int(time.time() * 1000),
            "params": {"eventId": "online_status", "online": False, "ts": int(time.time())},
        }, ensure_ascii=False)
        try:
            self.client.will_set(self.topics.offline(), will_payload, qos=self.qos, retain=False)
        except Exception as e:
            self.log.warning("[遗嘱] 设置失败(忽略): %r", e)

        self._use_tls = bool(em.get("use_tls", True))
        self._ca_file = em.get("ca_file", "") or None
        self._tls_insecure = bool(em.get("tls_insecure", False))
        self._last_report = 0.0

    # ---- MQTT 连接回调 ----
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            sub = self.topics.command_subscribe()
            self.log.info("[MQTT] 连接成功，订阅下发主题 %s (QoS%d)", sub, self.qos)
            client.subscribe(sub, qos=self.qos)
            self._publish_online(True)
            self._publish_properties(reason="online", force=True)
        else:
            self.log.warning("[MQTT] 连接失败 reason_code=%s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.log.warning("[MQTT] 已断开 reason_code=%s，等待自动重连", reason_code)
        try:
            self._publish_online(False)
        except Exception:
            pass

    # ---- 下行指令处理 ----
    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.log.warning("[下发] 解析失败: %r 原始=%s", e, msg.payload)
            return
        self.log.info("[下发] %s -> %s", msg.topic, json.dumps(payload, ensure_ascii=False))
        method = str(payload.get("method", ""))
        mid = payload.get("id", "unknown")
        message_type = payload.get("messageType", "")
        function_id = payload.get("functionId", "")

        if message_type == "INVOKE_FUNCTION" or function_id:
            # JetLinks 官方功能调用格式（含仅有 functionId 而无 messageType 的变体）
            self._handle_jetlinks_invoke(payload)
        elif method == "thing.service.property.set":
            self._handle_raw_property_set(payload)
        elif method == "thing_service_service_invoke":
            self._handle_invoke(mid, payload.get("params", {}))
        elif method == "thing_service_property_write":
            self._handle_property_write(mid, payload.get("params", {}))
        else:
            self.log.warning("[下发] 未识别 payload=%s (method=%r messageType=%r)",
                             json.dumps(payload, ensure_ascii=False), method, message_type)

    def _handle_invoke(self, mid, params):
        """平台下发功能调用。params 里解析出通道与目标状态。"""
        if not isinstance(params, dict):
            params = {}
        function_id = params.get("functionId", "set_channel")
        changed = self._apply_action(params)
        self._publish_function_ack(mid, function_id, changed)

    def _handle_raw_property_set(self, payload):
        """处理图格式平台下发：{"method":"thing.service.property.set","params":{"ch1_state":false}}"""
        params = payload.get("params", {}) or {}
        changed = False
        for key, val in params.items():
            if key.startswith("ch") and key.endswith("_state") and isinstance(val, bool):
                try:
                    channel = int(key[2:-len("_state")])
                    changed |= self.channels.set_one(channel, "on" if val else "off") is not None
                except (ValueError, TypeError):
                    pass
        self.log.info("[执行] property.set %s -> 变化=%s", params, changed)
        self._publish_properties(reason="property_set", force=True)

    def _handle_jetlinks_invoke(self, payload):
        """处理 JetLinks 官方 INVOKE_FUNCTION 格式：
        {messageType:"INVOKE_FUNCTION", functionId, messageId, inputs:[{name,value},...]}"""
        function_id = str(payload.get("functionId", "set_channel"))
        message_id = payload.get("messageId", "")
        inputs = payload.get("inputs", []) or []
        params = {}
        for item in inputs:
            if not isinstance(item, dict):
                continue
            if item.get("name") == "params" and isinstance(item.get("value"), dict):
                params = item["value"]
                break
            if "value" in item:
                params[item.get("name")] = item.get("value")
        changed = self._apply_action(params)
        self._publish_function_invoke_reply(message_id, function_id, {
            "changed": bool(changed),
            "channels": self.channels.snapshot(),
        })

    def _publish_function_invoke_reply(self, message_id, function_id, output):
        tops = [f"/{self.product_id}/{self.device_id}/function/invoke/reply"]
        payload = {
            "messageId": message_id,
            "success": True,
            "output": output,
        }
        self.log.info("[响应] %s -> %s", tops, json.dumps(payload, ensure_ascii=False))
        self.client.publish(tops[0], json.dumps(payload, ensure_ascii=False), qos=self.qos)

    def _handle_property_write(self, mid, params):
        """平台写属性（如 ch3_status:on）。"""
        if not isinstance(params, dict):
            params = {}
        changed = False
        for key, val in params.items():
            if key.startswith("ch") and key.endswith("_status"):
                midnum = key[2:-len("_status")] if key[2:-len("_status")].isdigit() else None
                channel = int(midnum) if midnum is not None else None
                if channel is not None and str(val).lower() in ("on", "off"):
                    changed |= self.channels.set_one(channel, str(val).lower()) is not None
        self.log.info("[执行] 属性写 %s -> 变化=%s", params, changed)
        self._publish_properties(reason="property_write", force=True)

    def _apply_action(self, params):
        """从 params 提取命令并执行，返回是否有变化。

        支持:
          {"channel":3,"status":"on"} / {"command":"on"} / {"ch_command":"on"}
          {"channel":3,"command":"toggle"} / {"channel":"all","status":"off"}
        """
        channel = params.get("channel", params.get("ch", "all"))
        state = params.get("state")
        if isinstance(state, bool):
            value = "on" if state else "off"
        elif isinstance(state, str) and state.lower() in ("on", "off"):
            value = state.lower()
        elif isinstance(state, str) and state.lower() in ("true", "false"):
            value = "on" if state.lower() == "true" else "off"
        else:
            value = params.get("status") or params.get("command") or params.get("ch_command") or params.get("action")
            value = str(value).lower() if value is not None else "toggle"
        result = False

        if value not in ("on", "off", "toggle"):
            self.log.warning("[执行] 非法指令值 %r\n%s", value, params)
            return result

        def apply_target(target):
            nonlocal result
            if target in ("all", "*", None):
                if value == "toggle":
                    for ch in self.channels.channels:
                        self.channels.toggle_one(ch["channel"])
                    result = True
                else:
                    self.channels.set_all(value)
                    result = True
                return True
            try:
                t = int(target)
            except (TypeError, ValueError):
                return False
            if value == "toggle":
                return self.channels.toggle_one(t) is not None
            return self.channels.set_one(t, value) is not None

        ok = apply_target(channel)
        self.log.info("[执行] 通道=%s 指令=%s -> 变化=%s", channel, value, ok or result)
        return ok or result

    # ---- 上行上报 ----
    def _publish_properties(self, reason="periodic", force=True):
        props = self.channels.as_properties()
        props["online"] = True
        if self.publish_format == "original":
            # 图格式原始终端报文（交给 EMQX 规则转换）： /product/{deviceId}/properties/post
            topic = "/product/%s/properties/post" % self.device_id
            payload = {
                "method": "thing.event.property-post",
                "id": "prop_%d" % int(time.time() * 1000),
                "params": props,
            }
        else:
            # JetLinks 物模型报文（JetLinks 直接解析）： /{productId}/{deviceId}/properties/report
            topic = self.topics.properties_post()
            payload = {"properties": props}
        info = self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=self.qos)
        self._last_report = time.time()
        self.log.info("[上报] %s -> %s (mid=%s)", topic, json.dumps(payload, ensure_ascii=False), info.mid)

    def _publish_function_ack(self, mid, function_id, changed):
        payload = {
            "method": "thing_service_service_invoke_reply",
            "id": mid,
            "params": {
                "success": True,
                "message": "ok",
                "changed": bool(changed),
                "data": self.channels.snapshot(),
                "ts": int(time.time()),
            },
        }
        topic = self.topics.function_send(function_id)
        self.log.info("[响应] %s -> %s", topic, json.dumps(payload, ensure_ascii=False))

    def _publish_online(self, online):
        payload = {
            "method": "thing_event_post",
            "id": f"evt_{int(time.time()*1000)}",
            "params": {"eventId": "online_status", "online": online, "ts": int(time.time())},
        }
        topic = self.topics.online() if online else self.topics.offline()
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=self.qos)
        self.log.info("[状态] 上线=%s -> %s", online, topic)

    # ---- 连接与运行 ----
    def connect(self):
        em = self.cfg["emqx"]
        host = em["host"]
        port = int(em["port"])
        if self._use_tls:
            if self._ca_file and not os.path.isabs(self._ca_file):
                self._ca_file = os.path.join(BASE_DIR, self._ca_file)
            ca = self._ca_file if self._ca_file else None
            self.client.tls_set(ca_certs=ca)
            if self._tls_insecure:
                self.client.tls_insecure_set(True)
            self.log.info("[EMQX] 使用 TLS 连接 %s:%s (ca=%s)", host, port, ca or "<系统CA>")
        else:
            self.log.info("[EMQX] 明文连接 %s:%s", host, port)
        self.client.connect(host, port, keepalive=self.keepalive)
        self.client.loop_start()

    def run(self, cmd_override=None):
        self.log.info("[模拟器] JetLinks 8路继电器 %s 启动，productId=%s",
                      self.device_id, self.product_id)
        self.log.info("[模拟器] 上报主题=%s，上报周期=%ss，命令订阅=%s",
                      self.topics.properties_post(), self.report_period,
                      self.topics.command_subscribe())
        try:
            self.connect()
        except Exception as e:
            self.log.error("[EMQX] 连接异常: %r", e)
            return
        try:
            if cmd_override:
                self.log.info("[自测] 模拟收到下发指令: %s", cmd_override)
                msg = type("M", (), {
                    "topic": self.topics.command_subscribe(),
                    "payload": json.dumps(cmd_override).encode("utf-8"),
                })()
                self._on_message(self.client, None, msg)
            while True:
                time.sleep(1)
                if time.time() - self._last_report >= self.report_period:
                    self._publish_properties(reason="periodic", force=True)
        except KeyboardInterrupt:
            self.log.info("[模拟器] Ctrl+C 停止")
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            self.log.info("[模拟器] 已退出")


def dump_snapshot(sim):
    snap = sim.channels.snapshot()
    print(f"productId={sim.product_id}  deviceId={sim.device_id}")
    print(f"上报主题: {sim.topics.properties_post()}")
    print(f"订阅主题: {sim.topics.command_subscribe()}")
    header = f"{'路':<4}{'状态':<6}{'电压(V)':<10}{'电流(A)':<10}"
    print(header)
    print("-" * len(header))
    for ch in snap:
        print(f"{ch['channel']:<4}{ch['status']:<6}{ch['voltage']:<10}{ch['current']:<10}")
    print("-" * len(header))
    print("属性上报 params:", json.dumps(sim.channels.as_properties(), ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="8 路继电器模拟器 - JetLinks 协议版")
    ap.add_argument("--once", action="store_true", help="上报一次属性后退出")
    ap.add_argument("--dry-run", action="store_true", help="不连网，打印8路状态与主题")
    ap.add_argument("--cmd", type=str, default=None,
                    help='连上后模拟收到一条下发指令，如 --cmd \'{"method":"thing_service_service_invoke","id":"x","params":{"channel":3,"status":"on"}}\'')
    ap.add_argument("--format", type=str, default=None, choices=["jetlinks", "original"],
                    help='输出格式：jetlinks(直接物模型格式) / original(训练图原始报文,由EMQX规则转换)')
    args = ap.parse_args()

    cfg = load_config()
    jl = cfg["jetlinks"]
    logger = setup_logger(jl.get("log_file"))
    sim = RelaySimulatorJetlinks(cfg, logger, publish_format=args.format)

    if args.dry_run:
        dump_snapshot(sim)
        return

    if args.once:
        try:
            sim.connect()
            time.sleep(1.5)
            sim._publish_properties(reason="once", force=True)
            time.sleep(0.5)
        except Exception as e:
            logger.error("[once] 发布失败: %r", e)
        finally:
            sim.client.loop_stop()
            sim.client.disconnect()
        return

    sim.run(cmd_override=json.loads(args.cmd) if args.cmd else None)


if __name__ == "__main__":
    main()
