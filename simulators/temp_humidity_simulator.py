"""温湿度传感器模拟器 - smart-relay-control-system

功能：
  用 JSON 文件（sensor_state.json）存储温湿度当前值。
  当文件值发生变化（手动编辑该文件）时，脚本检测到变化，
  立即通过 MQTT 上报到服务器（172.16.4.211:9783，test/123456）。

运行（项目根目录）：
  .venv\\Scripts\\python.exe simulators\\temp_humidity_simulator.py

停止：Ctrl+C
"""

import hashlib
import json
import os
import time

import paho.mqtt.client as mqtt

# 以脚本所在目录为基准，保证从任意路径运行都能找到配置/状态文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_STATE_FILE = os.path.join(BASE_DIR, "sensor_state.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    cfg = load_config()
    mq = cfg["mqtt"]
    se = cfg["sensor"]

    device_id = se.get("device_id", "sensor01")
    state_file = se.get("state_file", "sensor_state.json")
    if not os.path.isabs(state_file):
        state_file = os.path.join(BASE_DIR, state_file)
    topic = se["topic"]
    qos = int(mq.get("qos", 1))
    poll = float(se.get("poll_interval_sec", 2))

    # ---- 连接 MQTT（唯一 client_id）----
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"temp-sensor-{os.getpid()}",
    )
    client.username_pw_set(mq["username"], mq["password"])
    client.connect(mq["host"], int(mq["port"]), keepalive=60)
    client.loop_start()
    print(f"[MQTT] 已连接 {mq['host']}:{mq['port']}")

    last_signature = None  # 上次已上报值的签名
    print(f"[模拟器] 监视 {state_file}，值变化即上报主题 {topic}")

    try:
        while True:
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                temperature = float(data["temperature"])
                humidity = float(data["humidity"])

                # 用保留2位小数的值做签名，判断是否真的变了
                signature = hashlib.md5(
                    f"{temperature:.2f}|{humidity:.2f}".encode()
                ).hexdigest()

                if signature != last_signature:
                    payload = {
                        "deviceId": device_id,
                        "type": "temp_humidity",
                        "temperature": temperature,
                        "humidity": humidity,
                        "ts": int(time.time()),
                    }
                    info = client.publish(topic, json.dumps(payload), qos=qos)
                    print(f"[上报] {topic} -> {json.dumps(payload)} "
                          f"(mid={info.mid})")
                    last_signature = signature
            except FileNotFoundError:
                print(f"[模拟器] 状态文件不存在，等待创建: {state_file}")
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                print(f"[模拟器] 读取/解析失败: {e!r}，等待下次重试...")
            time.sleep(poll)
    except KeyboardInterrupt:
        print("\n[模拟器] 停止")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
