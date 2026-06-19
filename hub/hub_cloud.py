"""
Sensor Hub [CLOUD]  --  MQTT subscriber + SQLite writer
- broker    : HiveMQ Cloud (TLS 8883) -- bypasses school-WiFi client isolation
- NOTE      : separate file from local (mosquitto) version; use one or the other
- subscribe : HiveMQ Cloud broker, topic multinode_sensor_demo/+/bme688
- store     : SQLite (sensor_data.db)
- pair      : dashboard.py (read-only)
- run       : via App Lab app, or as a systemd service for 24/7 unattended operation
- data      : one averaged record from a node = one DB row
"""
import json, sqlite3, signal, sys, ssl     # ssl: for TLS (cloud)
import paho.mqtt.client as mqtt

# ---- Config (HiveMQ Cloud) ----
BROKER   = "xxxxx.s1.eu.hivemq.cloud"   # HiveMQ Overview Host
PORT     = 8883                          # TLS port (local mosquitto was 1883)
USERNAME = "여기_username"               # HiveMQ Access Management
PASSWORD = "여기_password"
TOPIC    = "multinode_sensor_demo/+/bme688"        # + = all nodes
DB       = "sensor_data.db"             # data file (auto-created if absent)

# line-buffered stdout -> print() shows up immediately in journalctl
sys.stdout.reconfigure(line_buffering=True)

# ---- DB init (schema) ----
conn = sqlite3.connect(DB, check_same_thread=False)
conn.execute("""
CREATE TABLE IF NOT EXISTS readings(
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  ts    TEXT    DEFAULT CURRENT_TIMESTAMP,    -- time (UTC); +9h for KST in analysis
  node  TEXT,
  temp  REAL,
  hum   REAL,
  press REAL,
  gas   REAL,
  n     INTEGER,                               -- sample count in the average (quality)
  co2   REAL                                   -- optional future SCD30 label (NULL if unused)
)""")
conn.commit()

# ---- MQTT callbacks (paho 2.x VERSION2 signature) ----
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"broker connect: {reason_code}")
    client.subscribe(TOPIC)

def on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"parse failed: {e}")
        return
    # If measurement time (t, UTC) is present, store it as ts (node NTP sync).
    # If absent (NTP-fail fallback), omit ts -> DB fills arrival time (CURRENT_TIMESTAMP).
    t = d.get("t")
    if t:
        conn.execute(
            "INSERT INTO readings(ts,node,temp,hum,press,gas,n) VALUES(?,?,?,?,?,?,?)",
            (t, d.get("node"), d.get("temp"), d.get("hum"),
             d.get("press"), d.get("gas"), d.get("n")))
    else:
        conn.execute(
            "INSERT INTO readings(node,temp,hum,press,gas,n) VALUES(?,?,?,?,?,?)",
            (d.get("node"), d.get("temp"), d.get("hum"),
             d.get("press"), d.get("gas"), d.get("n")))
    conn.commit()
    print(f"saved: {d}")

# ---- graceful shutdown (SIGTERM on systemd stop/restart) ----
def shutdown(signum, frame):
    print("shutting down...")
    try: client.disconnect()
    except Exception: pass
    try: conn.close()
    except Exception: pass
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT,  shutdown)

# ---- MQTT client (TLS + auth for cloud) ----
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)   # no deprecation warning
client.username_pw_set(USERNAME, PASSWORD)               # cloud: login
client.tls_set(tls_version=ssl.PROTOCOL_TLS_CLIENT)      # cloud: enable TLS
# client.tls_insecure_set(True)   # uncomment to skip cert verification (matches node setInsecure)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, keepalive=60)
client.loop_forever()
