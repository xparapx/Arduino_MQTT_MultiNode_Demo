"""
환경 센싱 Hub  —  MQTT subscriber + SQLite writer  (실수집용)
- 수신   : 로컬 mosquitto broker (localhost), 토픽 multinode_sensor_demo/+/bme688
- 저장   : SQLite (sensor_data.db)
- 페어   : dashboard.py(읽기 전용)
- 실행   : App Lab 앱으로 / 또는 systemd 서비스로 24/7 무인 운영
- 데이터 : 노드가 보낸 5분 평균 1건 = DB 1행
"""
import json, sqlite3, signal, sys
import paho.mqtt.client as mqtt

# ── 설정 ─────────────────────────────────────────
BROKER = "localhost"             # Q보드에서 직접 돌리므로 로컬 브로커
PORT   = 1883
TOPIC  = "multinode_sensor_demo/+/bme688"        # + = 모든 노드
DB     = "sensor_data.db"             # 실수집용 새 파일 (없으면 자동 생성)

# stdout 라인버퍼링 → systemd journalctl에 print가 즉시 보임
sys.stdout.reconfigure(line_buffering=True)

# ── DB 초기화 (확정 스키마) ─────────────────────
conn = sqlite3.connect(DB, check_same_thread=False)
conn.execute("""
CREATE TABLE IF NOT EXISTS readings(
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  ts    TEXT    DEFAULT CURRENT_TIMESTAMP,    -- 도착시각(UTC). 분석 시 +9h(KST)
  node  TEXT,
  temp  REAL,
  hum   REAL,
  press REAL,
  gas   REAL,
  n     INTEGER,                               -- 평균에 쓴 샘플 수(품질지표)
  co2   REAL                                   -- 추후 SCD30 라벨(없으면 NULL)
)""")
conn.commit()

# ── MQTT 콜백 (paho 2.x VERSION2 시그니처) ──────
def on_connect(client, userdata, flags, reason_code, properties):
    print(f"broker connect: {reason_code}")
    client.subscribe(TOPIC)

def on_message(client, userdata, msg):
    try:
        d = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"parse 실패: {e}")
        return
    conn.execute(
        "INSERT INTO readings(node,temp,hum,press,gas,n) VALUES(?,?,?,?,?,?)",
        (d.get("node"), d.get("temp"), d.get("hum"),
         d.get("press"), d.get("gas"), d.get("n"))
    )
    conn.commit()
    print(f"저장: {d}")

# ── 우아한 종료 (systemd stop·재시작 시 SIGTERM) ─
def shutdown(signum, frame):
    print("종료 중...")
    try: client.disconnect()
    except Exception: pass
    try: conn.close()
    except Exception: pass
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT,  shutdown)

# ── MQTT 클라이언트 ─────────────────────────────
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)   # ★ deprecation 없음
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, keepalive=60)
client.loop_forever()