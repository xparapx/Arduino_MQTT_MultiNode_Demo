"""
Sensor Hub [LOCAL]  --  MQTT subscriber + SQLite writer  (SEN55 + SCD30)
- broker    : local mosquitto (localhost:1883)
- subscribe : topic multinode_sensor_demo/+/env   (combined SEN55+SCD30 node)
- store     : SQLite (sensor_data.db), table readings
- pair      : dashboard.py (read-only)
- vars(11)  : SEN55 -> pm1p0 pm2p5 pm4p0 pm10p0 (ug/m3), sen_temp(C), sen_hum(%),
                       voc(idx), nox(idx)
              SCD30 -> co2(ppm), scd_temp(C), scd_hum(%)   [scd = representative T/H]
- policy    : temp/hum representative = SCD30 (sen_temp/sen_hum kept for comparison)
"""
import json, sqlite3, signal, sys
import paho.mqtt.client as mqtt

# ---- Config (HiveMQ Cloud) ----
BROKER   = "localhost"
PORT     = 1883
TOPIC    = "multinode_sensor_demo/+/env"       # + = all nodes ; combined env topic
DB       = "sensor_data.db"

sys.stdout.reconfigure(line_buffering=True)

# ---- DB init (SEN55 + SCD30 schema, 11 vars) ----
conn = sqlite3.connect(DB, check_same_thread=False)
conn.execute("""
CREATE TABLE IF NOT EXISTS readings(
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts       TEXT    DEFAULT CURRENT_TIMESTAMP,   -- UTC; +9h KST in analysis
  node     TEXT,
  pm1p0    REAL,                                -- SEN55 PM1.0  (ug/m3)
  pm2p5    REAL,                                -- SEN55 PM2.5  (ug/m3)
  pm4p0    REAL,                                -- SEN55 PM4.0  (ug/m3)
  pm10p0   REAL,                                -- SEN55 PM10   (ug/m3)
  sen_temp REAL,                                -- SEN55 temp (C) -- comparison only
  sen_hum  REAL,                                -- SEN55 humidity (%) -- comparison
  voc      REAL,                                -- SEN55 VOC index
  nox      REAL,                                -- SEN55 NOx index
  co2      REAL,                                -- SCD30 CO2 (ppm)
  scd_temp REAL,                                -- SCD30 temp (C) -- REPRESENTATIVE
  scd_hum  REAL,                                -- SCD30 humidity (%) -- REPRESENTATIVE
  n        INTEGER                              -- sample count (quality)
)""")
conn.commit()

COLS = ["pm1p0","pm2p5","pm4p0","pm10p0","sen_temp","sen_hum","voc","nox",
        "co2","scd_temp","scd_hum"]

# ---- MQTT callbacks (paho 2.x VERSION2) ----
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"broker connect: {reason_code}")
    client.subscribe(TOPIC)

def on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"parse failed: {e}")
        return
    vals = [d.get(c) for c in COLS]
    t = d.get("t")
    cols_sql = ",".join(COLS)
    ph = ",".join(["?"] * len(COLS))
    if t:
        conn.execute(
            f"INSERT INTO readings(ts,node,{cols_sql},n) VALUES(?,?,{ph},?)",
            (t, d.get("node"), *vals, d.get("n")))
    else:
        conn.execute(
            f"INSERT INTO readings(node,{cols_sql},n) VALUES(?,{ph},?)",
            (d.get("node"), *vals, d.get("n")))
    conn.commit()
    print(f"saved: {d}")

# ---- graceful shutdown ----
def shutdown(signum, frame):
    print("shutting down...")
    try: client.disconnect()
    except Exception: pass
    try: conn.close()
    except Exception: pass
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT,  shutdown)

# ---- MQTT client ----
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, keepalive=60)
client.loop_forever()
