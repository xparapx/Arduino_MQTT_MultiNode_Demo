"""Plug watcher -- MQTT observer + manual-command relay for the Shelly plugs.

- subscribe : shellyplugsg3-<mac>/status/switch:0, .../online  (config/plugs.json,
              schema {room: {purifier: mac|null, fan: mac|null}})
- poll      : Switch.GetStatus via RPC-over-MQTT every POLL_S (status topics only
              fire on change; the poll keeps "online" and apower fresh)
- history   : per device, 24 h of 5-min mean apower buckets (ring, persisted)
- write     : plug_state.json next to this file, atomically (tmp + os.replace).
              aq.webdata.plugs() serves it as /api/plugs -- a plug appears on the
              dashboard the moment it is powered and provisioned.
- commands  : plug_cmd.json (written by webapp.py POST /api/control, manual mode
              only) -- {"action": "all", "on": bool}. Executed once, then deleted.
              This is the ONLY path that publishes switch commands.

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
CMD_PATH = os.path.join(HERE, "plug_cmd.json")
TS_FMT = "%Y-%m-%d %H:%M:%S"
SRC = "aq-plugwatch"          # RPC response topic prefix
POLL_S = 60                   # GetStatus round for every configured plug
WRITE_S = 15                  # state-file refresh + command-file check
OFFLINE_S = 180               # no message for this long -> online: false
BUCKET_S = 300                # apower history: 5-min buckets ...
HIST_N = 288                  # ... x 288 = 24 h

sys.stdout.reconfigure(line_buffering=True)

with open(PLUGS_PATH, encoding="utf-8") as f:
    ROOMS = json.load(f)                     # {room: {purifier: mac|null, fan: mac|null}}
MAC2LOC = {mac: (room, dev) for room, devs in ROOMS.items()
           for dev, mac in devs.items() if mac}

state = {room: {dev: ({"mac": mac, "last": None, "online": False, "output": None,
                       "apower": None, "voltage": None, "tC": None, "hist": []}
                      if mac else None)
                for dev, mac in devs.items()}
         for room, devs in ROOMS.items()}
# hist entries live as [bucket_epoch, sum, n]; serialized as [bucket_epoch, mean]
try:
    with open(STATE_PATH, encoding="utf-8") as f:
        for room, devs in (json.load(f).get("plugs") or {}).items():
            for dev, s in (devs or {}).items():
                cur = state.get(room, {}).get(dev)
                if cur and s and s.get("mac") == cur["mac"]:
                    cur["hist"] = [[b, m, 1] for b, m in (s.get("hist") or [])][-HIST_N:]
except (OSError, ValueError):
    pass


def now_str():
    return datetime.now(UTC).replace(tzinfo=None).strftime(TS_FMT)


def note(mac: str, d: dict):
    loc = MAC2LOC.get(mac)
    if not loc:
        return
    s = state[loc[0]][loc[1]]
    s["last"] = now_str()
    if "output" in d:
        s["output"] = bool(d["output"])
    if "voltage" in d:
        s["voltage"] = d["voltage"]
    if isinstance(d.get("temperature"), dict):
        s["tC"] = d["temperature"].get("tC")
    if "apower" in d and isinstance(d["apower"], (int, float)):
        s["apower"] = d["apower"]
        b = int(time.time()) // BUCKET_S * BUCKET_S
        h = s["hist"]
        if h and h[-1][0] == b:
            h[-1][1] += d["apower"]
            h[-1][2] += 1
        else:
            h.append([b, d["apower"], 1])
            del h[:-HIST_N]


def write_state():
    now = datetime.now(UTC).replace(tzinfo=None)
    out = {}
    for room, devs in state.items():
        out[room] = {}
        for dev, s in devs.items():
            if not s:
                out[room][dev] = None
                continue
            alive = (s["last"] and
                     (now - datetime.strptime(s["last"], TS_FMT)).total_seconds() < OFFLINE_S)
            s["online"] = bool(alive)
            out[room][dev] = {**{k: s[k] for k in
                                 ("mac", "last", "online", "output", "apower", "voltage", "tC")},
                              "hist": [[b, round(tot / n, 1)] for b, tot, n in s["hist"]]}
    doc = {"updated": now.strftime(TS_FMT), "plugs": out}
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, STATE_PATH)


def run_command(client):
    """Execute + delete plug_cmd.json (webapp writes it in manual mode only)."""
    if not os.path.isfile(CMD_PATH):
        return
    try:
        with open(CMD_PATH, encoding="utf-8") as f:
            cmd = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cmd parse failed: {e}")
        os.remove(CMD_PATH)
        return
    os.remove(CMD_PATH)
    if cmd.get("action") == "all":
        payload = "on" if cmd.get("on") else "off"
        for mac in MAC2LOC:
            client.publish(f"shellyplugsg3-{mac}/command/switch:0", payload, qos=1)
        print(f"command: ALL {payload.upper()} -> {len(MAC2LOC)} plugs")
    else:
        print(f"command ignored (unknown action): {cmd}")


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"broker connect: {reason_code}")
    client.subscribe(f"{SRC}/rpc")
    for mac in MAC2LOC:
        client.subscribe(f"shellyplugsg3-{mac}/status/switch:0")
        client.subscribe(f"shellyplugsg3-{mac}/online")


def on_message(client, userdata, msg):
    try:
        parts = msg.topic.split("/")
        if msg.topic == f"{SRC}/rpc":                       # GetStatus response
            d = json.loads(msg.payload.decode())
            note(d.get("src", "").replace("shellyplugsg3-", ""), d.get("result") or {})
        elif parts[-1] == "online":                          # birth/LWT: just liveness
            if msg.payload == b"true":
                note(parts[0].replace("shellyplugsg3-", ""), {})
        else:                                                # status/switch:0 on change
            note(parts[0].replace("shellyplugsg3-", ""), json.loads(msg.payload.decode()))
    except (ValueError, KeyError, IndexError) as e:
        print(f"parse failed: {e}")


def poll(client):
    for i, mac in enumerate(MAC2LOC):
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

print(f"plugwatch: {len(MAC2LOC)} plugs, poll {POLL_S}s, state -> {STATE_PATH}")
last_poll = 0.0
while True:
    if time.monotonic() - last_poll >= POLL_S:
        last_poll = time.monotonic()
        poll(client)
    run_command(client)
    write_state()
    time.sleep(WRITE_S)
