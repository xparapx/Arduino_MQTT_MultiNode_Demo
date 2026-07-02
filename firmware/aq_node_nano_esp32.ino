/*
 * ============================================================
 *  멀티노드 환경 센싱 펌웨어  ★ Nano ESP32 판  (SEN55 + SCD30, 로컬)
 *  - 센서1 SEN55(0x69): PM1.0/2.5/4.0/10, 습도, 온도, VOC지수, NOx지수
 *  - 센서2 SCD30(0x61): CO2(ppm), 온도, 습도  ← 온습도 대표값으로 사용
 *  - 전송 : WiFi -> MQTT (로컬 mosquitto, 1883)
 *  - 시각 : NTP(WiFi.getTime, UTC) -> 정각 격자 측정·발행
 * ============================================================
 *  온습도 정책:
 *    - SCD30 온습도 = 대표값(정확, CO2 보정용). 대시보드 표시.
 *    - SEN55 온습도 = 내부발열로 2~5도 높음. DB에 비교용 저장(sen_temp/sen_hum).
 * ------------------------------------------------------------
 *  HW 주의:
 *    1) Nano ESP32 는 3.3V 보드 -> Grove Shield 토글 3.3V
 *    2) SEN55 I2C 3.3V. (ESP32는 3.3V 보드)
 *    3) SCD30 은 VIN 3.3V(ESP32 3.3V 보드). I2C 0x61, 클럭스트레칭 필요
 *       (SparkFun 라이브러리가 처리). 두 센서 같은 I2C 버스 공유.
 *    4) SCD30 첫 CO2 유효값까지 수초~수십초. 자동보정(ASC)은 수일 필요.
 *  전원 : USB-C
 * ============================================================
 *  보드매니저: "esp32 by Espressif" (보드: Arduino Nano ESP32)
 *  라이브러리:
 *    - PubSubClient            (by Nick O'Leary)
 *    - Sensirion I2C SEN5X     (+ Sensirion Core 동반)
 *    - SparkFun SCD30          (SCD30, UNO R4/ESP32 지원)
 *    ※ WiFi.h 는 ESP32 코어 내장
 * ============================================================
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <SensirionI2CSen5x.h>
#include <SparkFun_SCD30_Arduino_Library.h>   // ★ SCD30
#include <time.h>

// ===================== 사용자 설정 =====================
const char* WIFI_SSID = "your-wifi-ssid";
const char* WIFI_PASS = "your-wifi-password";

const char* BROKER    = "192.168.0.21";        // ★ 허브(UNO Q) IP
const int   PORT      = 1883;

const int           PUBLISH_MIN = 5;
const unsigned long SAMPLE_MS   = 10000;
const char* NTP1 = "pool.ntp.org";
const char* NTP2 = "time.google.com";
// ======================================================

WiFiClient net;             // 로컬: TLS 아님
PubSubClient  client(net);
SensirionI2CSen5x sen5x;
SCD30 scd30;                       // ★ SCD30 인스턴스

String nodeId, topic;
// SEN55 누적(8) + SCD30 누적(3: co2, scd_temp, scd_hum)
double sPm1=0, sPm25=0, sPm4=0, sPm10=0, sHum=0, sTemp=0, sVoc=0, sNox=0;
double sCo2=0, sScdT=0, sScdH=0;
int n = 0;        // SEN55 샘플 수
int nC = 0;       // SCD30 샘플 수 (측정 주기 달라 별도 카운트)
bool senOK  = false;
bool scdOK  = false;
bool timeOK = false;
long curBucket = -1;
unsigned long lastSample = 0;

void makeNodeId() {
  byte mac[6];
  WiFi.macAddress(mac);
  char id[16];
  snprintf(id, sizeof(id), "node_%02X%02X%02X", mac[3], mac[4], mac[5]);  // ESP32 뒤3바이트=고유
  nodeId = String(id);
  topic  = "multinode_sensor_demo/" + nodeId + "/env";    // ★ 통합 토픽 env
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
    if (client.connect(cid.c_str())) Serial.println(" OK");   // 로컬: 인증 없음
    else { Serial.print(" rc="); Serial.println(client.state()); delay(2000); }
  }
}

void syncTime() {
  Serial.print("NTP 동기화");
  configTime(0, 0, NTP1, NTP2);          // 0,0 = UTC
  struct tm tinfo;
  unsigned long t0 = millis();
  while (!getLocalTime(&tinfo, 500) && millis() - t0 < 10000) {
    Serial.print("."); delay(500);
  }
  timeOK = getLocalTime(&tinfo, 500);
  if (timeOK) {
    char buf[32]; strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tinfo);
    Serial.print(" OK (UTC "); Serial.print(buf); Serial.println(")");
  } else Serial.println(" FAIL -> 정각정렬 없이 동작");
}

long nowEpoch() { time_t now; time(&now); return (long)now; }

String epochToStr(long epoch) {
  time_t t = (time_t)epoch;
  struct tm tinfo; gmtime_r(&t, &tinfo);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tinfo);
  return String(buf);
}

void publishAverage(long bucketEpoch) {
  if (n <= 0) return;
  int cdiv = (nC > 0) ? nC : 1;              // SCD30 평균 분모(없으면 1)
  char p[420];
  // SEN55(8) + SCD30(3) = 11변수 JSON
  // sen_temp/sen_hum = SEN55 온습도(비교용), scd_temp/scd_hum = SCD30(대표)
  if (timeOK) {
    String ts = epochToStr(bucketEpoch);
    snprintf(p, sizeof(p),
      "{\"node\":\"%s\",\"t\":\"%s\","
      "\"pm1p0\":%.1f,\"pm2p5\":%.1f,\"pm4p0\":%.1f,\"pm10p0\":%.1f,"
      "\"sen_temp\":%.2f,\"sen_hum\":%.2f,\"voc\":%.1f,\"nox\":%.1f,"
      "\"co2\":%.1f,\"scd_temp\":%.2f,\"scd_hum\":%.2f,\"n\":%d}",
      nodeId.c_str(), ts.c_str(),
      sPm1/n, sPm25/n, sPm4/n, sPm10/n,
      sTemp/n, sHum/n, sVoc/n, sNox/n,
      sCo2/cdiv, sScdT/cdiv, sScdH/cdiv, n);
  } else {
    snprintf(p, sizeof(p),
      "{\"node\":\"%s\","
      "\"pm1p0\":%.1f,\"pm2p5\":%.1f,\"pm4p0\":%.1f,\"pm10p0\":%.1f,"
      "\"sen_temp\":%.2f,\"sen_hum\":%.2f,\"voc\":%.1f,\"nox\":%.1f,"
      "\"co2\":%.1f,\"scd_temp\":%.2f,\"scd_hum\":%.2f,\"n\":%d}",
      nodeId.c_str(),
      sPm1/n, sPm25/n, sPm4/n, sPm10/n,
      sTemp/n, sHum/n, sVoc/n, sNox/n,
      sCo2/cdiv, sScdT/cdiv, sScdH/cdiv, n);
  }
  client.publish(topic.c_str(), p);
  Serial.print("PUB: "); Serial.println(p);
}

void takeSample() {
  // SEN55
  if (senOK) {
    float pm1, pm25, pm4, pm10, hum, temp, voc, nox;
    uint16_t err = sen5x.readMeasuredValues(pm1, pm25, pm4, pm10, hum, temp, voc, nox);
    if (!err && !isnan(pm25) && !isnan(temp)) {
      sPm1 += pm1; sPm25 += pm25; sPm4 += pm4; sPm10 += pm10;
      sHum += hum; sTemp += temp; sVoc += voc; sNox += nox;
      n++;
    }
  }
  // SCD30 (자체 dataAvailable 주기, 준비됐을 때만 누적)
  if (scdOK && scd30.dataAvailable()) {
    float c = scd30.getCO2();
    float t = scd30.getTemperature();
    float h = scd30.getHumidity();
    if (c > 0 && !isnan(t)) { sCo2 += c; sScdT += t; sScdH += h; nC++; }
  }
}

void resetAccum() {
  sPm1=sPm25=sPm4=sPm10=sHum=sTemp=sVoc=sNox=0; n=0;
  sCo2=sScdT=sScdH=0; nC=0;
}

void setup() {
  Serial.begin(115200);
  delay(300);

  Wire.begin();
  Wire.setClock(50000);          // 50kHz: SCD30 클럭스트레칭 여유(두 센서 공유 버스)

  // SEN55
  sen5x.begin(Wire);
  uint16_t err = sen5x.deviceReset();
  if (err) Serial.println("SEN55 deviceReset 실패 - 배선/전압토글/0x69 확인");
  err = sen5x.startMeasurement();
  senOK = (err == 0);
  Serial.println(senOK ? "SEN55 측정 시작" : "SEN55 startMeasurement 실패");

  // SCD30
  if (scd30.begin()) { scdOK = true;  Serial.println("SCD30 시작 (CO2 첫값까지 수초~수십초)"); }
  else               { scdOK = false; Serial.println("SCD30 begin 실패 - 0x61/배선/5V 확인"); }

  connectWiFi();
  makeNodeId();
  syncTime();
  client.setServer(BROKER, PORT);
  connectBroker();

  Serial.print("Node: ");  Serial.println(nodeId);
  Serial.print("Topic: "); Serial.println(topic);
  Serial.print("발행주기: "); Serial.print(PUBLISH_MIN); Serial.println("분");

  if (timeOK) { long sec = PUBLISH_MIN * 60L; curBucket = (nowEpoch()/sec)*sec; }
}

void loop() {
  if (!client.connected()) connectBroker();
  client.loop();

  unsigned long now = millis();
  long sec = PUBLISH_MIN * 60L;

  if (timeOK) {
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
      Serial.print("sample sen="); Serial.print(n);
      Serial.print(" scd="); Serial.print(nC);
      Serial.print(" (bucket "); Serial.print(epochToStr(curBucket)); Serial.println(")");
    }
  } else {
    static unsigned long lastPub = 0;
    if (now - lastSample >= SAMPLE_MS) {
      lastSample = now; takeSample();
      Serial.print("sample sen="); Serial.print(n);
      Serial.print(" scd="); Serial.print(nC); Serial.println(" (no-NTP)");
    }
    if (now - lastPub >= (unsigned long)PUBLISH_MIN * 60000UL) {
      lastPub = now; publishAverage(0); resetAccum();
    }
  }
}
