/*
 * ============================================================
 * 멀티노드 환경 센싱 펌웨어  (Arduino Nano ESP32 + Grove Shield for Nano)
 *  - 센서 : Grove BME688  (I2C, 주소 0x76)  ← Grove I2C 포트에 연결
 *  - 전송 : WiFi -> MQTT (Q보드 mosquitto 브로커)
 *  - 시각 : NTP 로 동기화 → 정각 격자에 맞춰 측정·발행 (노드 간 동기화)
 *  - 방식 : SAMPLE_MS 마다 샘플 → PUBLISH_MIN 분 평균 → 정각에 1건 발행
 *           발행 페이로드에 측정시각(t, UTC)을 포함 → 분석 시 노드 정렬 용이
 * ============================================================
 *  ⚠️ 하드웨어 주의 (★ 전원 넣기 전에 반드시 확인)
 *    Grove Shield의 VCC 스위치를 반드시 [3.3V]로!
 *    Nano ESP32는 3.3V 보드 — 5V로 두면 보드가 손상될 수 있음.
 * ============================================================
 *  보드 매니저:  "Arduino ESP32 Boards"  (보드: Arduino Nano ESP32)
 *  필요 라이브러리(라이브러리 매니저에서 설치):
 *    - PubSubClient            (by Nick O'Leary)
 *    - Adafruit BME680 Library (+ Adafruit Unified Sensor 자동 동반)
 *    ※ WiFi · 시각(time.h) 은 ESP32 코어 내장 — 따로 설치 안 함
 * ============================================================
 */

#include <WiFi.h>            // ESP32 코어 내장 (UNO R4의 WiFiS3.h 아님!)
#include <PubSubClient.h>
#include <Wire.h>
#include "Adafruit_BME680.h"
#include <time.h>            // NTP 시각 (ESP32 내장)

// ===================== 사용자 설정 =====================
const char* WIFI_SSID = "your-wifi-ssid";      // ★ 교실 WiFi 이름 (영문 권장)
const char* WIFI_PASS = "your-wifi-password";  // ★ WiFi 암호

// ★ 브로커 주소 = Q보드.
//   · systemd 트랙(호스트 직접 실행) : "<BoardName>.local" 또는 "192.168.x.x"
//   · App Lab 트랙(컨테이너 실행)     : Q보드의 Docker 게이트웨이 IP (예 172.19.0.1)
//   확인: Q보드에서  hostname -I  /  docker exec <c> ip route | grep default
const char* BROKER    = "192.168.0.21";        // ★ 환경에 맞게 교체 (끝 공백 주의!)
const int   PORT      = 1883;

// ★ 발행 주기(분). 1 / 5 / 10 등으로 자유 변경.
//   ※ 모든 노드를 반드시 같은 값으로! (달라지면 정각 격자가 어긋나 정렬 깨짐)
//   샘플은 SAMPLE_MS 간격 → 1분이면 6개, 5분이면 30개, 10분이면 60개 평균.
const int           PUBLISH_MIN = 5;
const unsigned long SAMPLE_MS   = 10000;       // 샘플 간격(10초). 보통 그대로

// NTP 서버 (인터넷 필요). 학교망이 막으면 시각동기화 실패 → fallback 동작.
const char* NTP1 = "pool.ntp.org";
const char* NTP2 = "time.google.com";
// ======================================================

WiFiClient   net;
PubSubClient client(net);
Adafruit_BME680 bme;        // I2C

String nodeId, topic;
double  sT=0, sH=0, sP=0, sG=0;  int n = 0;     // 평균 누적기
bool    bmeOK = false;
bool    timeOK = false;                          // NTP 동기화 성공 여부
long    curBucket = -1;                          // 현재 측정 중인 정각 버킷(epoch초)
unsigned long lastSample = 0;

// nodeId = MAC 끝 3바이트 → 보드마다 고유
void makeNodeId() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char id[16];
  snprintf(id, sizeof(id), "node_%02X%02X%02X", mac[3], mac[4], mac[5]);
  nodeId = String(id);
  topic  = "multinode_sensor_demo/" + nodeId + "/bme688";
}

void connectWiFi() {
  // 이미 연결 + 유효 IP 있으면 통과
  if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0,0,0,0)) return;

  Serial.print("WiFi");
  WiFi.disconnect();           // 깨끗하게 재연결 (밤사이 끊김 복구에 도움)
  delay(100);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  // 1단계: WiFi 인증(연결)까지 대기 (최대 15초)
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    delay(500); Serial.print(".");
  }
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println(" FAIL (인증 실패 - SSID/암호/신호 확인)");
    return;
  }
  Serial.println(" OK");

  // 2단계: ★ 유효 IP(DHCP) 받을 때까지 대기 (최대 12초)
  //   WiFi는 붙어도 IP가 0.0.0.0이면 NTP/MQTT 전부 실패 → 이 대기가 핵심
  Serial.print("  IP 획득");
  unsigned long t1 = millis();
  while (WiFi.localIP() == IPAddress(0,0,0,0) && millis() - t1 < 12000) {
    delay(500); Serial.print("+");
  }
  IPAddress ip = WiFi.localIP();
  if (ip == IPAddress(0,0,0,0)) {
    Serial.println(" FAIL (DHCP IP 미수신 - 라우터/망 문제)");
  } else {
    Serial.println(" OK");
  }
  // 진단 출력: IP/게이트웨이/DNS (0.0.0.0이면 망 문제)
  Serial.print("  IP : "); Serial.println(ip);
  Serial.print("  GW : "); Serial.println(WiFi.gatewayIP());
  Serial.print("  DNS: "); Serial.println(WiFi.dnsIP());
  Serial.print("  RSSI: "); Serial.print(WiFi.RSSI()); Serial.println(" dBm (신호; -50좋음 -80약함)");
}

void connectBroker() {
  while (!client.connected()) {
    connectWiFi();
    String cid = nodeId + "-" + String(random(0xffff), HEX);
    Serial.print("MQTT");
    if (client.connect(cid.c_str())) Serial.println(" OK");
    else { Serial.print(" rc="); Serial.println(client.state()); delay(2000); }
  }
}

// NTP 동기화 (UTC). 성공하면 timeOK=true.
void syncTime() {
  configTime(0, 0, NTP1, NTP2);        // 0,0 = UTC (오프셋 0). 분석은 UTC 기준
  Serial.print("NTP 동기화");
  struct tm tinfo;
  unsigned long t0 = millis();
  while (!getLocalTime(&tinfo, 500) && millis() - t0 < 10000) {
    Serial.print(".");
  }
  timeOK = getLocalTime(&tinfo, 500);
  if (timeOK) {
    char buf[32]; strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tinfo);
    Serial.print(" OK (UTC "); Serial.print(buf); Serial.println(")");
  } else {
    Serial.println(" FAIL -> 정각정렬 없이 동작(측정시각은 허브 도착시각 사용)");
  }
}

long nowEpoch() { time_t now; time(&now); return (long)now; }

// 버킷 epoch초 → "YYYY-MM-DD HH:MM:SS" (UTC)
String epochToStr(long epoch) {
  time_t t = (time_t)epoch; struct tm tinfo;
  gmtime_r(&t, &tinfo);
  char buf[32]; strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tinfo);
  return String(buf);
}

void publishAverage(long bucketEpoch) {
  if (n <= 0) return;
  char p[220];
  if (timeOK) {
    String ts = epochToStr(bucketEpoch);   // 측정시각 = 구간 시작 정각(UTC)
    snprintf(p, sizeof(p),
      "{\"node\":\"%s\",\"t\":\"%s\",\"temp\":%.2f,\"hum\":%.2f,"
      "\"press\":%.2f,\"gas\":%lu,\"n\":%d}",
      nodeId.c_str(), ts.c_str(), sT/n, sH/n, sP/n,
      (unsigned long)(sG/n), n);
  } else {
    snprintf(p, sizeof(p),                 // NTP 실패 → t 생략(허브가 도착시각)
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
    sP += bme.pressure / 100.0;        // Pa -> hPa
    sG += bme.gas_resistance;          // Ohm
    n++;
  }
}

void resetAccum() { sT=sH=sP=sG=0; n=0; }

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin();              // Grove I2C 자동 매핑
  Wire.setClock(100000);     // 다중장치 안정성 위해 100kHz

  bmeOK = bme.begin(0x76);   // Grove BME688 = 0x76
  if (bmeOK) {
    bme.setTemperatureOversampling(BME680_OS_8X);
    bme.setHumidityOversampling(BME680_OS_2X);
    bme.setPressureOversampling(BME680_OS_4X);
    bme.setIIRFilterSize(BME680_FILTER_SIZE_3);
    bme.setGasHeater(320, 150);
  } else {
    Serial.println("BME688 not found @0x76 - 배선/전압스위치(3.3V) 확인");
  }

  connectWiFi();
  makeNodeId();
  syncTime();                // ★ NTP 동기화 (UTC)
  client.setServer(BROKER, PORT);
  connectBroker();

  Serial.print("Node: ");  Serial.println(nodeId);
  Serial.print("Topic: "); Serial.println(topic);
  Serial.print("발행주기: "); Serial.print(PUBLISH_MIN); Serial.println("분");

  if (timeOK) {
    long sec = PUBLISH_MIN * 60L;
    curBucket = (nowEpoch() / sec) * sec;   // 현재 속한 정각 버킷
  }
}

void loop() {
  // WiFi가 끊겼거나 IP를 잃으면 먼저 재연결 (밤사이 망 변동 복구)
  if (WiFi.status() != WL_CONNECTED || WiFi.localIP() == IPAddress(0,0,0,0)) {
    connectWiFi();
  }
  if (!client.connected()) connectBroker();
  client.loop();             // MQTT 연결 유지

  unsigned long now = millis();
  long sec = PUBLISH_MIN * 60L;

  if (timeOK) {
    // ── 정각 정렬 모드 (NTP 성공) ──
    long epoch  = nowEpoch();
    long bucket = (epoch / sec) * sec;       // 지금 속한 정각 버킷

    if (curBucket < 0) curBucket = bucket;
    if (bucket != curBucket) {               // 정각 경과 → 직전 버킷 발행
      publishAverage(curBucket);
      resetAccum();
      curBucket = bucket;
    }
    if (now - lastSample >= SAMPLE_MS) {
      lastSample = now; takeSample();
      Serial.printf("sample %d (bucket %s)\n", n, epochToStr(curBucket).c_str());
    }
  } else {
    // ── fallback 모드 (NTP 실패) — millis 기준 주기 발행 ──
    static unsigned long lastPub = 0;
    if (now - lastSample >= SAMPLE_MS) {
      lastSample = now; takeSample();
      Serial.printf("sample %d (no-NTP)\n", n);
    }
    if (now - lastPub >= (unsigned long)PUBLISH_MIN * 60000UL) {
      lastPub = now; publishAverage(0); resetAccum();
    }
  }
}
