"""测试工具：直接查看/修改温湿度模拟数据。

修改的是温湿度模拟器的数据文件（simulators/sensor_state.json）。
若 temp_humidity_simulator.py 正在运行，改后会自动经 MQTT 上报，
配合 MQTTX（订阅 smart-relay/sensor01/data）即可实时看到新值。

用法（项目根目录）：
  .venv\\Scripts\\python.exe tools\\set_sensor.py show                 # 查看当前值
  .venv\\Scripts\\python.exe tools\\set_sensor.py set 33.5 62.0       # 设置温/湿度
  .venv\\Scripts\\python.exe tools\\set_sensor.py random              # 随机生成合理值
  .venv\\Scripts\\python.exe tools\\set_sensor.py --set 28 55         # 直接设置（等价 set）

作者：第七组（电信专业）
"""

import argparse
import json
import os
import random
import sys

# 工具位于 <项目>/tools/，模拟器在 <项目>/simulators/
BASE_DIR = os.path.dirname(os.path.abspath(__file__))   # <项目>/tools
PROJECT_ROOT = os.path.dirname(BASE_DIR)                 # <项目>
SIM_DIR = os.path.join(PROJECT_ROOT, "simulators")
CONFIG_PATH = os.path.join(SIM_DIR, "config.json")


def load_cfg():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def state_file(cfg):
    sf = cfg["sensor"].get("state_file", "sensor_state.json")
    if not os.path.isabs(sf):
        sf = os.path.join(SIM_DIR, sf)
    return sf


def read_current(cfg):
    sf = state_file(cfg)
    try:
        with open(sf, "r", encoding="utf-8") as f:
            return sf, json.load(f)
    except FileNotFoundError:
        return sf, {}


def write_values(cfg, temperature, humidity):
    sf = state_file(cfg)
    # 用 UTF-8（无 BOM）写入，避免模拟器解析报错
    with open(sf, "w", encoding="utf-8") as f:
        json.dump({"temperature": temperature, "humidity": humidity}, f, indent=2)
    return sf


def main():
    ap = argparse.ArgumentParser(description="测试工具：修改温湿度模拟数据")
    ap.add_argument("mode", nargs="?", default="show",
                    choices=["show", "set", "random"])
    ap.add_argument("value", nargs="?", type=float, help="set 模式：温度")
    ap.add_argument("humidity", nargs="?", type=float, help="set 模式：湿度")
    ap.add_argument("--set", nargs=2, type=float, metavar=("T", "H"),
                    help="直接设置温/湿度")
    args = ap.parse_args()

    cfg = load_cfg()

    if args.set:
        args.mode, args.value, args.humidity = "set", args.set[0], args.set[1]

    if args.mode == "show":
        sf, cur = read_current(cfg)
        print(f"当前模拟数据文件: {sf}")
        print(f"temperature = {cur.get('temperature')}")
        print(f"humidity    = {cur.get('humidity')}")
    elif args.mode == "set":
        if args.value is None or args.humidity is None:
            print("用法: set_sensor.py set <温度> <湿度>")
            return 1
        sf = write_values(cfg, args.value, args.humidity)
        print(f"已写入 {sf}: temperature={args.value}, humidity={args.humidity}")
        print("运行中的模拟器将自动上报到 MQTT (smart-relay/sensor01/data)。")
    elif args.mode == "random":
        t = round(random.uniform(15.0, 40.0), 1)
        h = round(random.uniform(30.0, 80.0), 1)
        sf = write_values(cfg, t, h)
        print(f"随机生成并写入 {sf}: temperature={t}, humidity={h}")
        print("运行中的模拟器将自动上报到 MQTT。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
