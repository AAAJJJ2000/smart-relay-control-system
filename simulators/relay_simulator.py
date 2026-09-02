"""8 路继电器模拟器 - smart-relay-control-system

作者：第七组（电信专业）

功能（对应 Day3「多通道继电器模拟器」）：
  1. 连接 MQTT Broker（config.json 的 mqtt 段，默认 172.16.4.211:9783，test/123456）。
  2. 维护 8 路继电器状态（on/off），可模拟电压/电流值。
  3. 订阅下行命令主题，支持：整机开/关、单路开关、单路翻转、状态查询。
  4. 状态变化立即上报 + 按 report_period_sec 周期上报（上报到 status 主题）。
  5. 上线/下线时发布 online 状态。
  6. 断线自动重连（指数退避），日志同时输出到控制台与日志文件。

运行（项目根目录）：
  .venv\\Scripts\\python.exe simulators\\relay_simulator.py            # 持续运行，监听指令并周期上报
  .venv\\Scripts\\python.exe simulators\\relay_simulator.py --once      # 只上报一次当前状态后退出
  .venv\\Scripts\\python.exe simulators\\relay_simulator.py --dry-run   # 不连网络，仅打印 8 路当前状态

停止：Ctrl+C
"""

import argparse
import json
import logging
import os
import random
import signal
import sys
import time

import paho.mqtt.client as mqtt

# 以脚本所在目录为基准，保证从任意路径运行都能找到配置/日志
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

# ---- 日志：同时输出到控制台与日志文件 ----
def setup_logger(log_file):
    logger = logging.getLogger("relay")
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


# ---- 8 路通道状态管理（channel.py 语义）----
class RelayChannels:
    """维护 channel_count 路继电器状态。

    每路状态: {"channel": n, "status": "on"/"off", "voltage": ..., "current": ...}
    """

    def __init__(self, count, initial="off", simulate_voltage=True):
        self.count = count
        self.simulate_voltage = simulate_voltage
        self.channels = [
            self._make(i + 1, initial) for i in range(count)
        ]

    @staticmethod
    def _make(channel, status):
        return {
            "channel": channel,
            "status": status,
            "voltage": 0,   # 开=~220V，关=0
            "current": 0,   # 开=随机负载电流，关=0
        }

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


# ---- 模拟器主逻辑 ----
class RelaySimulator:
    def __init__(self, cfg, logger, simulate_voltage=True):
        self.cfg = cfg
        self.log = logger
        mq = cfg["mqtt"]
        rl = cfg["relay"]

        self.device_id = rl.get("device_id", "relay01")
        self.cmd_topic = rl["cmd_topic"]
        self.status_topic = rl["status_topic"]
        self.online_topic = rl.get("online_topic", f"smart-relay/{self.device_id}/online")
        self.report_period = float(rl.get("report_period_sec", 5))
        self.qos = int(mq.get("qos", 1))

        count = int(rl.get("channel_count", 8))
        initial = str(rl.get("initial_state", "off"))
        self.channels = RelayChannels(count, initial, simulate_voltage)

        # paho-mqtt 2.x 使用 CallbackAPIVersion.VERSION2
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"relay-{self.device_id}-{os.getpid()}",
        )
        self.client.username_pw_set(mq["username"], mq["password"])
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self._last_report = 0.0

    # ---- MQTT 回调 ----
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            self.log.info("[MQTT] 连接成功，订阅指令主题 %s (QoS%d)", self.cmd_topic, self.qos)
            client.subscribe(self.cmd_topic, qos=self.qos)
            self._publish_status(reason="online")
            self._publish_online(True)
        else:
            self.log.warning("[MQTT] 连接失败 reason_code=%s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.log.warning("[MQTT] 已断开 reason_code=%s，等待自动重连", reason_code)
        self._publish_online(False)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.log.warning("[命令] 解析失败: %r 原始=%s", e, msg.payload)
            return
        self.log.info("[命令] 收到 %s -> %s", msg.topic, json.dumps(payload, ensure_ascii=False))
        changed = self._apply_command(payload)
        # 命令执行后统一回一份状态（无论是否真正变化）
        self._publish_status(reason="command")

    # ---- 命令处理（command.py 语义）----
    def _apply_command(self, payload):
        """解析并执行控制指令，返回是否有状态变化。

        支持命令格式（cmd）：
          {"cmd":"on"}                    # 整机 8 路全开
          {"cmd":"off"}                   # 整机 8 路全关
          {"cmd":"set","channel":3,"status":"on"}   # 单路开关
          {"cmd":"toggle","channel":3}              # 单路翻转
          {"cmd":"query"}                            # 仅查询，不改状态
        兼容省略 cmd 的形式：
          {"channel":3,"status":"on"}                # 等价 set
        """
        cmd = str(payload.get("cmd", "")).lower()
        result = False

        if cmd in ("on", "off", "all_on", "all_off"):
            status = "on" if cmd in ("on", "all_on") else "off"
            self.channels.set_all(status)
            result = True
            self.log.info("[执行] 整机全部置为 %s", status)

        elif cmd == "set" or ("channel" in payload and "status" in payload and not cmd):
            channel = payload.get("channel")
            status = str(payload.get("status", "")).lower()
            if channel is not None and status in ("on", "off"):
                self.channels.set_one(channel, status)
                result = True
                self.log.info("[执行] 通道 %s 置为 %s", channel, status)
            else:
                self.log.warning("[执行] 非法参数: %s", payload)

        elif cmd == "toggle":
            channel = payload.get("channel")
            if channel is not None:
                self.channels.toggle_one(channel)
                result = True
                self.log.info("[执行] 翻转通道 %s", channel)
            else:
                self.log.warning("[执行] toggle 缺少 channel")

        elif cmd == "query":
            self.log.info("[执行] 状态查询")
            # query 不改变状态，但会触发一次上报

        else:
            self.log.warning("[执行] 未知命令: %s", payload)

        return result

    # ---- 上报（reporter.py 语义）----
    def _publish_status(self, reason="periodic", force=False):
        now = time.time()
        payload = {
            "deviceId": self.device_id,
            "type": "relay",
            "online": True,
            "reason": reason,
            "channels": self.channels.snapshot(),
            "ts": int(now),
        }
        info = self.client.publish(
            self.status_topic, json.dumps(payload, ensure_ascii=False), qos=self.qos
        )
        self._last_report = now
        self.log.info("[上报] %s -> %s (mid=%s)", self.status_topic, json.dumps(payload, ensure_ascii=False), info.mid)

    def _publish_online(self, online):
        payload = {
            "deviceId": self.device_id,
            "type": "relay",
            "online": online,
            "ts": int(time.time()),
        }
        self.client.publish(
            self.online_topic, json.dumps(payload, ensure_ascii=False), qos=self.qos
        )
        self.log.info("[状态] 上线=%s -> %s", online, self.online_topic)

    # ---- 启动 ----
    def run(self):
        mq = self.cfg["mqtt"]
        self.log.info("[模拟器] 8路继电器 %s 启动，Broker=%s:%s",
                      self.device_id, mq["host"], mq["port"])
        self.log.info("[模拟器] 指令主题=%s，状态主题=%s，上报周期=%ss",
                      self.cmd_topic, self.status_topic, self.report_period)
        try:
            self.client.connect(mq["host"], int(mq["port"]), keepalive=60)
        except Exception as e:
            self.log.error("[MQTT] 连接异常: %r", e)
            return
        self.client.loop_start()
        try:
            while True:
                time.sleep(1)
                # 周期上报
                if time.time() - self._last_report >= self.report_period:
                    self._publish_status(reason="periodic", force=True)
        except KeyboardInterrupt:
            self.log.info("[模拟器] Ctrl+C 停止")
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            self.log.info("[模拟器] 已退出")


def dump_snapshot(sim):
    """--dry-run / --once 用：打印当前 8 路状态，不连网络。"""
    snap = sim.channels.snapshot()
    header = f"{'路':<4}{'状态':<6}{'电压(V)':<10}{'电流(A)':<10}"
    print(header)
    print("-" * len(header))
    for ch in snap:
        print(f"{ch['channel']:<4}{ch['status']:<6}{ch['voltage']:<10}{ch['current']:<10}")
    print("-" * len(header))
    print(f"总计 {len(snap)} 路，当前在线 = 模拟器未连接")


def main():
    ap = argparse.ArgumentParser(description="8 路继电器模拟器")
    ap.add_argument("--once", action="store_true", help="上报一次当前状态后退出")
    ap.add_argument("--dry-run", action="store_true", help="不连网络，仅打印当前8路状态")
    ap.add_argument("--no-voltage", action="store_true", help="关闭电压/电流模拟")
    args = ap.parse_args()

    cfg = load_config()
    rl = cfg["relay"]
    logger = setup_logger(rl.get("log_file"))
    simulate_voltage = not args.no_voltage and bool(rl.get("simulate_voltage", True))

    sim = RelaySimulator(cfg, logger, simulate_voltage=simulate_voltage)

    if args.dry_run:
        dump_snapshot(sim)
        return

    if args.once:
        # 只需发布一次当前状态：短连再断开
        mq = cfg["mqtt"]
        try:
            sim.client.connect(mq["host"], int(mq["port"]), keepalive=30)
            sim.client.loop_start()
            time.sleep(1.5)
            sim._publish_status(reason="once", force=True)
            time.sleep(0.5)
        except Exception as e:
            logger.error("[once] 发布失败: %r", e)
        finally:
            sim.client.loop_stop()
            sim.client.disconnect()
        return

    sim.run()


if __name__ == "__main__":
    main()
