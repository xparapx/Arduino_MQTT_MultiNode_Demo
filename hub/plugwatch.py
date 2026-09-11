"""Plug watcher -- read-only MQTT observer for the Shelly classroom plugs.

- subscribe : shellyplugsg3-<mac>/status/switch:0, .../online  (macs from config/plugs.json)
- poll      : Switch.GetStatus via RPC-over-MQTT every POLL_S (status topics only
              fire on change; the poll keeps "online" and apower fresh)
- write     : plug_state.json next to the DB, atomically (tmp + os.replace).
              The web layer (aq.webdata.plugs) serves it as /api/plugs, so a plug
              appears on the dashboard the moment it is powered and provisioned.

Sends NO switch commands -- control stays with the future actuator phase.
Credentials come from secrets.env (systemd EnvironmentFile), as hub.py.
"""
import json
import os
import signal
import sys
import time
from datetime import UTC, datetime

import paho.mqtt.client as mqtt

BROKER = os.environ["MQTT_BROKER"]
PORT = int(os.environ.get("MQTT_PORT", "8883"))
USERNAME = os.environ["MQTT_USERNAME"]
PASSWORD = os.environ["MQTT_PASSWORD"]

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGS_PATH = os.path.join(HERE, "config", "plugs.json")
STATE_PATH = os.path.join(HERE, "plug_state.json")
TS_FMT = "%Y-%m-%d %H:%M:%S"
SRC = "aq-plugwatch"          # RPC response topic prefix
POLL_S = 60                   # GetStatus round for every configured plug
WRITE_S = 15                  # state-file refresh
OFFLINE_S = 180               # no message for this long -> online: false

sys.stdout.reconfigure(line_buffering=True)

with open(PLUGS_PATH, encoding="utf-8") as f:
    ROOMS = json.load(f)                     # {"CLASS_01": "80b54e292d24", ...}
MAC2ROOM = {mac: room for room, mac in ROOMS.items()}

state = {room: {"mac": mac, "last": None, "online": False, "output": None,
                "apower": None, "voltage": None, "tC": None}
         for room, mac in ROOMS.items()}


def now_str():
    return datetime.now(UTC).replace(tzinfo=None).strftime(TS_FMT)


def note(mac: str, d: dict):
    room = MAC2ROOM.get(mac)
    if not room:
        return
    s = state[room]
    s["last"] = now_str()
    if "output" in d:
        s["output"] = bool(d["output"])
    if "apower" in d:
        s["apower"] = d["apower"]
    if "voltage" in d:
        s["voltage"] = d["voltage"]
    if isinstance(d.get("temperature"), dict):
        s["tC"] = d["temperature"].get("tC")


def write_state():
    now = datetime.now(UTC).replace(tzinfo=None)
    for s in state.values():
        alive = (s["last"] and
                 (now - datetime.strptime(s["last"], TS_FMT)).total_seconds() < OFFLINE_S)
        s["online"] = bool(alive)
    doc = {"updated": now.strftime(TS_FMT), "plugs": state}
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"broker connect: {reason_code}")
    client.subscribe(f"{SRC}/rpc")
    for mac in MAC2ROOM:
        client.subscribe(f"shellyplugsg3-{mac}/status/switch:0")
        client.subscribe(f"shellyplugsg3-{mac}/online")


def on_message(client, userdata, msg):
    try:
        parts = msg.topic.split("/")
        if msg.topic == f"{SRC}/rpc":                       # GetStatus response
            d = json.loads(msg.payload.decode())
            note(d.get("src", "").replace("shellyplugsg3-", ""), d.get("result") or {})
        elif parts[-1] == "online":                          # birth/LWT: just liveness
            mac = parts[0].replace("shellyplugsg3-", "")
            if msg.payload == b"true":
                note(mac, {})
        else:                                                # status/switch:0 on change
            note(parts[0].replace("shellyplugsg3-", ""), json.loads(msg.payload.decode()))
    except (ValueError, KeyError, IndexError) as e:
        print(f"parse failed: {e}")


def poll(client):
    for i, mac in enumerate(MAC2ROOM):
        client.publish(f"shellyplugsg3-{mac}/rpc",
                       json.dumps({"id": i, "src": SRC,
                                   "method": "Switch.GetStatus", "params": {"id": 0}}), qos=0)


def shutdown(signum, frame):
    print("shutting down...")
    write_state()
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aq-plugwatch")
client.username_pw_set(USERNAME, PASSWORD)
client.tls_set()
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, keepalive=60)
client.loop_start()

print(f"plugwatch: {len(ROOMS)} plugs, poll {POLL_S}s, state -> {STATE_PATH}")
last_poll = 0.0
while True:
    if time.monotonic() - last_poll >= POLL_S:
        last_poll = time.monotonic()
        poll(client)
    write_state()
    time.sleep(WRITE_S)
