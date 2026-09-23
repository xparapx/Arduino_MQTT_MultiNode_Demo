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

from aq import autoctl, energy

BROKER = os.environ["MQTT_BROKER"]
PORT = int(os.environ.get("MQTT_PORT", "8883"))
USERNAME = os.environ["MQTT_USERNAME"]
PASSWORD = os.environ["MQTT_PASSWORD"]

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGS_PATH = os.path.join(HERE, "config", "plugs.json")
STATE_PATH = os.path.join(HERE, "plug_state.json")
CMD_PATH = os.path.join(HERE, "plug_cmd.json")
ENERGY_PATH = os.path.join(HERE, "plug_energy.json")
CTRL_PATH = os.path.join(HERE, "control.json")
DB_PATH = os.path.join(HERE, "sensor_data.db")
NODES_PATH = os.path.join(HERE, "nodes.json")
TS_FMT = "%Y-%m-%d %H:%M:%S"
SRC = "aq-plugwatch"          # RPC response topic prefix
POLL_S = 60                   # GetStatus round for every configured plug
WRITE_S = 15                  # state-file refresh + command-file check
RECON_S = 60                  # auto mode: reconcile plugs to actuator_state
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
    flush_energy()


try:
    with open(ENERGY_PATH, encoding="utf-8") as f:
        energy_doc = json.load(f)
except (OSError, ValueError):
    energy_doc = {}
energy_doc.setdefault("days", {})
energy_doc.setdefault("acc", {})


def flush_energy():
    """Fold finalized 5-min buckets into daily Wh (plug_energy.json, ours alone).
    Writes only when a bucket actually closed (~5 min cadence, SD-friendly)."""
    now_bucket = int(time.time()) // BUCKET_S * BUCKET_S
    dirty = False
    for room, devs in state.items():
        for dev, s in devs.items():
            if not s or not s["hist"]:
                continue
            marker = int((energy_doc["acc"].get(room) or {}).get(dev) or 0)
            adds, new_marker = energy.accumulate(s["hist"], marker, now_bucket)
            if adds:
                energy.merge(energy_doc, room, dev, adds, new_marker)
                dirty = True
    if not dirty:
        return
    energy.prune(energy_doc)
    tmp = ENERGY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(energy_doc, f, ensure_ascii=False)
    os.replace(tmp, ENERGY_PATH)


def run_command(client) -> bool:
    """Execute + delete plug_cmd.json (webapp writes it in manual mode only).
    Returns True when a command was executed (caller boosts state writes)."""
    if not os.path.isfile(CMD_PATH):
        return False
    try:
        with open(CMD_PATH, encoding="utf-8") as f:
            cmd = json.load(f)
    except (OSError, ValueError) as e:
        print(f"cmd parse failed: {e}")
        os.remove(CMD_PATH)
        return False
    os.remove(CMD_PATH)
    if cmd.get("action") == "all":
        payload = "on" if cmd.get("on") else "off"
        for mac in MAC2LOC:
            client.publish(f"shellyplugsg3-{mac}/command/switch:0", payload, qos=1)
        print(f"command: ALL {payload.upper()} -> {len(MAC2LOC)} plugs")
        return True
    print(f"command ignored (unknown action): {cmd}")
    return False


def control_mode() -> str:
    try:
        with open(CTRL_PATH, encoding="utf-8") as f:
            return json.load(f).get("mode", "auto")
    except (OSError, ValueError):
        return "auto"


def reconcile(client):
    """Auto mode: bring online plugs to the state analyst judged (actuator_state).
    Publishes only differences; matching states cost nothing. 수동 모드에선 무동작."""
    mode = control_mode()
    acts = autoctl.plan(autoctl.desired_states(DB_PATH, NODES_PATH), state, mode)
    for room, dev, mac, payload in acts:
        client.publish(f"shellyplugsg3-{mac}/command/switch:0", payload, qos=1)
        print(f"auto: {room} {dev} -> {payload.upper()}")


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
# 명령 체크는 2초 주기(반응성), 상태 기록은 평시 15초 / 명령 직후 45초간 3초(SD 마모 억제)
last_poll = 0.0
last_write = 0.0
last_recon = 0.0
boost_until = 0.0
while True:
    now = time.monotonic()
    if now - last_poll >= POLL_S:
        last_poll = now
        poll(client)
    if run_command(client):
        boost_until = now + 45
    if now - last_write >= (3 if now < boost_until else WRITE_S):
        last_write = now
        write_state()                      # refreshes each device's "online" flag
        if now - last_recon >= RECON_S:    # 자동 제어: 판정 상태로 수렴 (write 직후 = online 최신)
            last_recon = now
            reconcile(client)
    time.sleep(2)
