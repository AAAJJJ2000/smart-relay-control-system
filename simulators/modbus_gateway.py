"""Modbus TCP 采集上报 - smart-relay-control-system

作者：第七组（电信专业）

功能：
  通过 Modbus TCP 从从站（config.json 的 modbus.host:port，默认 192.168.20.59:5502）
  采集指定寄存器（默认 0x0009；设备寄存器范围 0x0000-0x0009），并经 MQTT 上报到服务器。

  每个小组只需在 config.json 的 modbus.register_start / register_count 里
  改成自己分配到的寄存器段，即可避免与其他小组冲突（只读写自己那一段）。

  默认只读并持续上报；如需写入用 --write。

运行（项目根目录）：
  采集上报（持续）:  .venv\\Scripts\\python.exe simulators\\modbus_gateway.py
  采集一次并退出:     .venv\\Scripts\\python.exe simulators\\modbus_gateway.py --once
  写入一个寄存器一次: .venv\\Scripts\\python.exe simulators\\modbus_gateway.py --write 0x0009 123
"""

import argparse
import json
import os
import time

import paho.mqtt.client as mqtt
from pymodbus.client import ModbusTcpClient

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_mqtt(cfg):
    mq = cfg["mqtt"]
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"modbus-gw-{os.getpid()}",
    )
    client.username_pw_set(mq["username"], mq["password"])
    client.connect(mq["host"], int(mq["port"]), keepalive=60)
    client.loop_start()
    print(f"[MQTT] 已连接 {mq['host']}:{mq['port']}")
    return client


def parse_addr(text):
    """支持 0x0009 / 0x9 / 9 等写法。"""
    return int(text, 0)


def read_holding(client, unit, address, count):
    rr = client.read_holding_registers(address, count=count, device_id=unit)
    if rr is None or rr.isError():
        raise RuntimeError(f"读取失败: {rr!r}")
    return rr.registers


def report(mcpub, topic, payload, qos):
    info = mcpub.publish(topic, json.dumps(payload), qos=qos)
    print(f"[上报] {topic} -> {json.dumps(payload)} (mid={info.mid})")


def main():
    ap = argparse.ArgumentParser(description="Modbus TCP -> MQTT 采集上报")
    ap.add_argument("--write", nargs=2, metavar=("ADDR", "VALUE"),
                    help="写入单个寄存器一次并退出，如 --write 0x0009 123")
    ap.add_argument("--once", action="store_true",
                    help="只读到一次并上报后退出（默认持续采集）")
    args = ap.parse_args()

    cfg = load_config()
    mq = cfg["mqtt"]
    mb = cfg["modbus"]

    host = mb["host"]
    port = int(mb["port"])
    unit = int(mb.get("unit_id", 1))
    start = parse_addr(mb["register_start"])
    count = int(mb.get("register_count", 1))
    poll = float(mb.get("poll_interval_sec", 5))
    topic = mb["read_topic"]
    device_id = mb.get("device_id", "modbus01")
    qos = int(mq.get("qos", 1))

    # ---- 连接 Modbus ----
    client = ModbusTcpClient(host, port=port, timeout=5)
    if not client.connect():
        print(f"[Modbus] 无法连接 {host}:{port}")
        return
    print(f"[Modbus] 已连接 {host}:{port} unit={unit} "
          f"寄存器 0x{start:04X} 起 {count} 个")

    # ---- 写入模式 ----
    if args.write:
        addr = parse_addr(args.write[0])
        value = int(args.write[1], 0)
        wr = client.write_register(addr, value, device_id=unit)
        if wr is not None and wr.isError():
            print(f"[Modbus] 写入失败 0x{addr:04X}: {wr!r}")
        else:
            print(f"[Modbus] 已写入 0x{addr:04X} = {value}")
            mcpub = build_mqtt(cfg)
            report(mcpub, topic, {
                "deviceId": device_id,
                "type": "modbus_write",
                "register": f"0x{addr:04X}",
                "value": value,
                "ts": int(time.time()),
            }, qos)
            time.sleep(1)
            mcpub.loop_stop()
            mcpub.disconnect()
        client.close()
        return

    # ---- 采集上报模式 ----
    mcpub = build_mqtt(cfg)
    print(f"[采集] 每 {poll}s 读取 0x{start:04X} 起 {count} 个寄存器并上报 {topic}")
    try:
        while True:
            try:
                regs = read_holding(client, unit, start, count)
                regmap = {f"0x{start + i:04X}": v for i, v in enumerate(regs)}
                report(mcpub, topic, {
                    "deviceId": device_id,
                    "type": "modbus_tcp",
                    "register_start": f"0x{start:04X}",
                    "register_count": count,
                    "registers": regmap,
                    "values": regs,
                    "ts": int(time.time()),
                }, qos)
            except Exception as e:
                print(f"[采集] 异常: {e!r}，尝试重连...")
                try:
                    client.connect()
                except Exception:
                    pass
            if args.once:
                break
            time.sleep(poll)
    except KeyboardInterrupt:
        print("\n[采集] 停止")
    finally:
        mcpub.loop_stop()
        mcpub.disconnect()
        client.close()


if __name__ == "__main__":
    main()
