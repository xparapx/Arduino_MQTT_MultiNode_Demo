/*
 * ============================================================
 *  멀티노드 환경 센싱 펌웨어  ★ Arduino UNO R4 WiFi 판
 *  (Nano ESP32 판과 동일 동작 — WiFi/NTP 부분만 R4 방식)
 *  - 센서 : Grove BME688 (I2C 0x76)  ← Grove 실드의 I2C 포트
 *  - 전송 : WiFi -> MQTT over TLS (HiveMQ Cloud 브로커, 8883)
 *  - 시각 : NTP(WiFi.getTime, UTC) → 정각 격자 측정·발행
 *  - 방식 : SAMPLE_MS 마다 샘플 → PUBLISH_MIN 분 평균 → 정각 발행
 *           페이로드에 측정시각(t, UTC) 포함 → 노드 간 정렬
 * ============================================================
 *  ⚠️ 하드웨어 주의 — Nano ESP32 와 반대!
 *    UNO R4 WiFi 는 [5V] 보드 → Grove Shield 전압 스위치를 [5V] 로!
 *    (Nano ESP32 는 3.3V 였지만, R4 는 5V 입니다)
 *  전원 : USB-C 또는 배럴잭(DC, 7~12V, KC인증 아두이노 전용 어댑터) 사용 가능
 * ============================================================
 *  보드 매니저:  "Arduino UNO R4 Boards"  (보드: Arduino UNO R4 WiFi)
 *  필요 라이브러리:
 *    - PubSubClient            (by Nick O'Leary)
 *  [클라우드 브로커 버전] HiveMQ Cloud(TLS 8883). 로컬 버전과 별개 파일.
 *    - Adafruit BME680 Library (+ Adafruit Unified Sensor 동반)
 *    ※ WiFiS3 는 UNO R4 보드 패키지에 내장 — 따로 설치 안 함
 * ============================================================
 */

#include <WiFiS3.h>          // ★ R4 WiFi 전용 (ESP32의 WiFi.h 아님)
#include <PubSubClient.h>
#include <Wire.h>
#include "Adafruit_BME680.h"
#include <time.h>            // gmtime/strftime (측정시각 문자열 변환)

// ===================== 사용자 설정 =====================
const char* WIFI_SSID = "your-wifi-ssid";      // ★ 현장 WiFi 이름 (영문 권장)
const char* WIFI_PASS = "your-wifi-password";  // ★ WiFi 암호

// ★ HiveMQ Cloud 접속 정보 (Manage Cluster 에서 확인/생성)
const char* BROKER    = "xxxxx.s1.eu.hivemq.cloud";  // Overview 의 Host (끝 공백 주의!)
const int   PORT      = 8883;                         // TLS 포트 (로컬은 1883)
const char* MQTT_USER = "여기_username";              // Access Management 에서 생성
const char* MQTT_PASS = "여기_password";

// ★ 발행 주기(분). 1 / 5 / 10 등. 모든 노드를 같은 값으로!
const int           PUBLISH_MIN = 5;
const unsigned long SAMPLE_MS   = 10000;       // 샘플 간격(10초)
// ======================================================

WiFiSSLClient net;             // ★ 클라우드: R4 TLS 클라이언트 (로컬은 WiFiClient)
PubSubClient  client(net);
Adafruit_BME680 bme;

String nodeId, topic;
double  sT=0, sH=0, sP=0, sG=0;  int n = 0;
bool    bmeOK = false;
bool    timeOK = false;                          // NTP→RTC 동기화 성공 여부
long    curBucket = -1;
unsigned long lastSample = 0;

// nodeId = MAC 끝 3바이트
void makeNodeId() {
  byte mac[6];
  WiFi.macAddress(mac);
  char id[16];
  // R4 WiFi.macAddress 는 mac[0]이 끝 바이트인 구현이 있어 역순 주의.
  // 보드마다 고유하기만 하면 되므로 끝 3바이트 사용.
  snprintf(id, sizeof(id), "node_%02X%02X%02X", mac[2], mac[1], mac[0]);
  nodeId = String(id);
  topic  = "multinode_sensor_demo/" + nodeId + "/bme688";
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(500); Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " OK" : " FAIL");
}

void connectBroker() {
  while (!client.connected()) {
    connectWiFi();
    String cid = nodeId + "-" + String(random(0xffff), HEX);
    Serial.print("MQTT");
    if (client.connect(cid.c_str(), MQTT_USER, MQTT_PASS)) Serial.println(" OK");  // ★ 인증
    else { Serial.print(" rc="); Serial.println(client.state()); delay(2000); }
  }
}

// NTP(UTC epoch) 동기화 확인. R4 WiFi는 WiFi.getTime()이 현재 UTC epoch 반환.
// → RTC 객체에 굳이 안 넣고 WiFi.getTime()을 직접 시각원으로 사용(단순·안전).
//   (RTCTime 생성자/분해 API의 보드패키지 버전차를 피함)
void syncTime() {
  Serial.print("NTP 동기화");
  unsigned long epoch = 0;
  unsigned long t0 = millis();
  while ((epoch = WiFi.getTime()) == 0 && millis() - t0 < 10000) {
    Serial.print("."); delay(500);
  }
  if (epoch > 0) {
    timeOK = true;
    Serial.print(" OK (UTC epoch "); Serial.print(epoch); Serial.println(")");
  } else {
    timeOK = false;
    Serial.println(" FAIL -> 정각정렬 없이 동작(측정시각은 허브 도착시각 사용)");
  }
}

// 현재 epoch초 (UTC) — WiFi.getTime() 직접 사용
long nowEpoch() {
  unsigned long e = WiFi.getTime();
  return (long)e;
}

// 버킷 epoch초 → "YYYY-MM-DD HH:MM:SS" (UTC)
// RTCTime 분해 API(버전차) 대신 표준 C gmtime 사용 → 안전·이식적
String epochToStr(long epoch) {
  time_t t = (time_t)epoch;
  struct tm *tm_utc = gmtime(&t);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", tm_utc);
  return String(buf);
}

void publishAverage(long bucketEpoch) {
  if (n <= 0) return;
  char p[220];
  if (timeOK) {
    String ts = epochToStr(bucketEpoch);
    snprintf(p, sizeof(p),
      "{\"node\":\"%s\",\"t\":\"%s\",\"temp\":%.2f,\"hum\":%.2f,"
      "\"press\":%.2f,\"gas\":%lu,\"n\":%d}",
      nodeId.c_str(), ts.c_str(), sT/n, sH/n, sP/n,
      (unsigned long)(sG/n), n);
  } else {
    snprintf(p, sizeof(p),
      "{\"node\":\"%s\",\"temp\":%.2f,\"hum\":%.2f,"
      "\"press\":%.2f,\"gas\":%lu,\"n\":%d}",
      nodeId.c_str(), sT/n, sH/n, sP/n, (unsigned long)(sG/n), n);
  }
  client.publish(topic.c_str(), p);
  Serial.print("PUB: "); Serial.println(p);
}

void takeSample() {
  if (bmeOK && bme.performReading()) {
    sT += bme.temperature;
    sH += bme.humidity;
    sP += bme.pressure / 100.0;     // Pa -> hPa
    sG += bme.gas_resistance;       // Ohm
    n++;
  }
}

void resetAccum() { sT=sH=sP=sG=0; n=0; }

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin();
  Wire.setClock(100000);

  bmeOK = bme.begin(0x76);
  if (bmeOK) {
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
    bme.setGasHeater(320, 150);
  } else {
    Serial.println("BME688 not found @0x76 - 배선/전압스위치(5V) 확인");
  }

  connectWiFi();
  makeNodeId();
  syncTime();                // ★ NTP → RTC
  client.setServer(BROKER, PORT);
  connectBroker();

  Serial.print("Node: ");  Serial.println(nodeId);
  Serial.print("Topic: "); Serial.println(topic);
  Serial.print("발행주기: "); Serial.print(PUBLISH_MIN); Serial.println("분");

  if (timeOK) {
    long sec = PUBLISH_MIN * 60L;
    curBucket = (nowEpoch() / sec) * sec;
  }
}

void loop() {
  if (!client.connected()) connectBroker();
  client.loop();

  unsigned long now = millis();
  long sec = PUBLISH_MIN * 60L;

  if (timeOK) {
    // ── 정각 정렬 모드 (NTP 성공) ──
    long epoch  = nowEpoch();
    long bucket = (epoch / sec) * sec;

    if (curBucket < 0) curBucket = bucket;
    if (bucket != curBucket) {
      publishAverage(curBucket);
      resetAccum();
      curBucket = bucket;
    }
    if (now - lastSample >= SAMPLE_MS) {
      lastSample = now; takeSample();
      Serial.print("sample "); Serial.print(n);
      Serial.print(" (bucket "); Serial.print(epochToStr(curBucket)); Serial.println(")");
    }
  } else {
    // ── fallback (NTP 실패) — millis 기준 주기 발행 ──
    static unsigned long lastPub = 0;
    if (now - lastSample >= SAMPLE_MS) {
      lastSample = now; takeSample();
      Serial.print("sample "); Serial.print(n); Serial.println(" (no-NTP)");
    }
    if (now - lastPub >= (unsigned long)PUBLISH_MIN * 60000UL) {
      lastPub = now; publishAverage(0); resetAccum();
    }
  }
}
