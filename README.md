# Arduino MQTT MultiNode Demo — 멀티노드 환경 센싱 모니터

> 여러 공간에 둔 **센서 노드**가 환경변수(온도·습도·기압·가스)를 측정해 **MQTT**로 보내면, **허브**가 한 데이터베이스에 모아 웹 대시보드로 실시간 표시하는 멀티노드 IoT 프로젝트.

🔗 **프로젝트 개요:** https://xparapx.github.io/Arduino_MQTT_MultiNode_Demo/

`Arduino UNO R4 WiFi` · `Nano ESP32` · `BME688` · `MQTT` · `mosquitto · HiveMQ` · `Arduino UNO Q` · `SQLite` · `Streamlit`

---

MQTT·온디바이스 센싱·실시간 대시보드를 한 번에 경험해보고 싶은 누구나 따라 할 수 있는 입문용 데모입니다. **센서 측정 → 무선 발행(MQTT) → 수집·저장 → 시각화**의 전 과정을 직접 구성하며, 노드를 늘리면 대시보드에 칸이 자동으로 추가됩니다.

---

## 프로젝트 개요

`docs/index.html`을 브라우저로 열면 준비물·전체 구조·단계별 구축 가이드(WiFi·브로커·hub.py·펌웨어·대시보드·systemd·트러블슈팅)를 한눈에 볼 수 있습니다.

| 단계 | 내용 | 도구 |
|---|---|---|
| ① 측정 | 각 지점에서 환경변수 측정 | BME688 (I2C) |
| ② 발행 | NTP 정각정렬, 5분 평균 1건 MQTT 발행 | WiFi · MQTT |
| ③ 중계 | 노드 메시지를 구독자에게 전달 | mosquitto / HiveMQ |
| ④ 수집 | 메시지를 받아 DB에 저장 | hub.py · SQLite |
| ⑤ 시각화 | 게이지·차트·CSV 내보내기 | Streamlit |

---

## 시스템 구조

```
노드 (각 지점)            브로커                  허브 (UNO Q)
Nano ESP32 / UNO R4   →   로컬 mosquitto   →   hub.py ─→ SQLite ─→ dashboard.py
+ BME688                  또는                  (수집·저장)        (웹 :8501)
5분 평균 발행             클라우드 HiveMQ
       └──────── WiFi · MQTT ────────┘
```

- **노드 → 브로커**: WiFi 위 MQTT 발행(publish)
- **hub.py → 브로커**: 토픽 구독(subscribe) 후 SQLite에 1행씩 저장
- **dashboard.py**: 같은 SQLite를 읽기 전용으로 표시 (수집과 표시 분리)
- 데이터 흐름은 로컬/클라우드 어느 브로커든 동일

### 브로커 두 방식 (택일)
| | 로컬 (mosquitto) | 클라우드 (HiveMQ) |
|---|---|---|
| 위치 | 허브(UNO Q) 안 | 인터넷 |
| 포트 | 1883 (평문) | 8883 (TLS) |
| 인증 | 익명 | username/password |
| 클라이언트 격리 망 | 막힘 ✗ | 우회됨 ✓ |
| 인터넷 의존 | 불필요 | 필요 |

> 집·독립공유기 등 기기 간 통신이 자유로운 망이면 **로컬**, 기기 간 통신이 막히는 망(`rc=-2`)이면 **클라우드**로 우회합니다.

### MQTT 토픽 / 페이로드
- 발행 토픽: `multinode_sensor_demo/<node_id>/bme688`
- 구독: `multinode_sensor_demo/+/bme688` (`+` = 모든 노드)
- 페이로드(JSON): `{"node","t","temp","hum","press","gas","n"}` — `t`=측정시각(UTC), `n`=평균 샘플 수

---

## 하드웨어 구성

- **센서 노드**: Arduino **UNO R4 WiFi**(기본, 5V) 또는 **Nano ESP32**(대안, 3.3V) + Grove Base Shield + **Grove BME688**(I2C `0x76`)
- **허브**: Arduino **UNO Q** (Linux / App Lab) — 브로커·수집·대시보드 구동
- 공통: 노드·허브·열람 기기 모두 **같은 WiFi**(노드 ESP32는 2.4GHz 전용)

> ⚠️ **전압 스위치** — UNO R4 WiFi는 Grove Shield를 **5V**, Nano ESP32는 **3.3V**로. 잘못 두면 보드가 손상될 수 있습니다.

---

## 폴더 구조

```
firmware/    노드 펌웨어 (.ino)
hub/         허브 파이썬 (수집·대시보드·서비스)
docs/        구축 가이드 (HTML)
```

### firmware
| 파일 | 기종 | 브로커 |
|---|---|---|
| `sensor_node_uno_r4_cloud.ino` | UNO R4 WiFi (기본) | 클라우드 HiveMQ (TLS 8883) |
| `sensor_node_uno_r4.ino` | UNO R4 WiFi | 로컬 mosquitto (1883) |
| `aq_node_nano_esp32_cloud.ino` | Nano ESP32 (대안) | 클라우드 HiveMQ (TLS 8883) |
| `aq_node_nano_esp32.ino` | Nano ESP32 | 로컬 mosquitto (1883) |

### hub
| 파일 | 역할 |
|---|---|
| `hub.py` | MQTT(로컬) 구독 → SQLite 저장 |
| `hub_cloud.py` | MQTT(클라우드, TLS+인증) 구독 → SQLite 저장 |
| `dashboard.py` | SQLite 읽어 게이지·차트 표시 (Streamlit) |
| `nodes.json` | 노드 ID → 표시 이름 매핑 (없으면 ID 그대로) |
| `systemd/*.service` | 전원만 켜면 자동 실행되는 무인 운영 서비스 |
| `en/hub.py`, `en/dashboard.py` | 보드에 직접 붙여넣을 때 한글 깨짐을 피하는 **영문 ASCII판** |

---

## 허브 셋업 (UNO Q)

```bash
# 1) 파이썬 환경 (uv)
mkdir -p ~/multinode_sensor_demo && cd ~/multinode_sensor_demo
uv init --no-readme && rm -f main.py
uv add paho-mqtt pandas plotly streamlit streamlit-autorefresh

# 2) 로컬 브로커 (mosquitto) — 클라우드면 생략
sudo apt install -y mosquitto mosquitto-clients
# /etc/mosquitto/conf.d/multinode_sensor_demo.conf 에 listener 1883 0.0.0.0 / allow_anonymous true

# 3) 수집 + 대시보드 실행
.venv/bin/python hub.py                      # 로컬   (또는 hub_cloud.py)
.venv/bin/streamlit run dashboard.py --server.address 0.0.0.0 --server.port 8501
```

대시보드: `http://<허브 IP>:8501`

> ⚠️ `python dashboard.py`로는 실행되지 않습니다. 반드시 `streamlit run`(또는 `uv run streamlit run`)을 사용하세요.

### 무인 자동화 (systemd)
`hub/systemd/`의 두 서비스 파일을 `/etc/systemd/system/`에 복사한 뒤:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now multinode_sensor_demo_hub multinode_sensor_demo_dashboard
```
> 서비스 파일의 경로(`/home/arduino/multinode_sensor_demo/...`)·`User`는 실제 환경에 맞게 수정하세요. 클라우드로 운영하면 hub 서비스의 `hub.py`를 `hub_cloud.py`로 바꿉니다.

---

## 펌웨어 업로드 (노드)

1. Arduino IDE 2.x → 보드 패키지 설치: **Arduino UNO R4 Boards** (또는 **Arduino ESP32 Boards**)
2. 라이브러리 설치: **PubSubClient**(by Nick O'Leary), **Adafruit BME680**(의존 라이브러리 Install All)
3. 펌웨어 상단 사용자 설정 수정 후 업로드:
   - `WIFI_SSID` / `WIFI_PASS` — 현장 WiFi
   - `BROKER` — 클라우드면 HiveMQ Host, 로컬이면 허브 IP
   - 클라우드는 `MQTT_USER` / `MQTT_PASS` 추가
   - `PUBLISH_MIN` — 발행 주기(분). **모든 노드 동일 값!**

> `WiFiS3`(R4) / `WiFi`(ESP32), TLS 클라이언트는 보드 패키지에 내장되어 별도 설치가 필요 없습니다.

---

## 노드 추가 / 라벨 변경

- 노드는 MAC 끝 3바이트로 ID(`node_XXXXXX`)를 자동 생성하므로, **펌웨어를 그대로 올리기만 하면** 대시보드에 칸이 자동 추가됩니다.
- 사람이 읽는 이름을 붙이려면 `hub/nodes.json`에 `"node_XXXXXX": "거실"` 형태로 추가합니다(허브에서만 수정, 노드 재업로드 불필요).

---

## 사용 라이브러리

- **노드**: PubSubClient, Adafruit BME680(+Unified Sensor), WiFiS3/WiFi(내장)
- **허브**: paho-mqtt, pandas, plotly, streamlit, streamlit-autorefresh (uv 프로젝트로 관리)

---

## 작업 로그

- **2026-06**: 멀티노드 환경 센싱 모니터 초기 공개 (UNO R4 WiFi 기본 / Nano ESP32 대안)
- **2026-06**: 브로커 로컬(mosquitto) / 클라우드(HiveMQ TLS) 양방식 지원 — 클라이언트 격리 망 우회
- **2026-06**: NTP 정각정렬 + 5분 평균 발행으로 노드 간 시각 정렬
- **2026-06**: 보드 직접 붙여넣기용 영문 ASCII판(`hub/en/`) 추가 (한글 깨짐 회피)

---

*Maintainer: physics-jh*
