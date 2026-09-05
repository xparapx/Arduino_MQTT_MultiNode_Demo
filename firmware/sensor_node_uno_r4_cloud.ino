/*
 * ============================================================
 *  멀티노드 환경 센싱 펌웨어  ★ UNO R4 WiFi 판  (SEN55 + SCD30) — v3
 *  - 센서1 SEN55(0x69): PM1.0/2.5/4.0/10, 습도, 온도, VOC지수, NOx지수
 *  - 센서2 SCD30(0x61): CO2(ppm), 온도, 습도  ← 온습도 대표값으로 사용
 *  - 전송 : WiFi -> MQTT over TLS (HiveMQ Cloud, 8883)
 *  - 시각 : NTP(WiFi.getTime, UTC) -> 정각 격자 측정·발행
 * ------------------------------------------------------------
 *  v2 (운용 반영분): 센서 동결/쓰레기 값 물리범위 필터(plausibleSEN),
 *      SEN55 연속 무효·SCD30 무응답 감시 → I2C 버스 복구(SCL 9펄스) → MCU 리셋
 *  v3 변경 (2026-09-05 — 통신·시각 계층 자가 복구):
 *   ① 브로커 재접속을 무한 블로킹 루프 → 10초 간격 1회 시도로 변경
 *      (장애 중에도 loop 유지: 샘플링·센서 감시 계속, WiFiS3 고착 시 행 방지)
 *   ② 시각을 매 loop WiFi.getTime() 호출 → epoch 기준점 + millis 경과로 변경
 *      (모뎀 AT 왕복 제거, 순간 0 반환에 의한 1970 타임스탬프 오염 차단)
 *      + NTP 6시간 재동기(표류·millis 롤오버 차단), 미확보 시 10분 재시도
 *   ③ 발행 3버킷 연속 실패(≈15분) → MCU 리셋 (WiFiS3/MQTT 드라이버 고착 탈출)
 *   ④ client.setBufferSize(512) + publish() 반환값 검사
 *      (기본 256B는 11변수 페이로드 ~240B와 여유 20B 미만 — 조용한 전량 미전송 위험)
 *   ⑤ 하드웨어 WDT(RA4M1, 최대 5592ms)를 setup 완료 후 무장 — Wire/WiFiS3
 *      호출 내부의 진짜 행(hang)을 리셋으로 회수. TLS connect가 5.5s를 넘기면
 *      WDT 리셋 후 비무장 setup 경로에서 재접속하므로 부팅 루프에 갇히지 않음.
 *   ⑥ 부팅 때 실패한 센서(begin 실패)는 10분마다 재초기화 시도,
 *      SEN55(또는 SCD30 포함)가 1시간 계속 죽어 있으면 MCU 리셋
 *   ⑦ loop 말미 delay(20) — busy-spin 제거
 * ============================================================
 *  온습도 정책:
 *    - SCD30 온습도 = 대표값(정확, CO2 보정용). 대시보드 표시.
 *    - SEN55 온습도 = 내부발열로 2~5도 높음. DB에 비교용 저장(sen_temp/sen_hum).
 * ------------------------------------------------------------
 *  HW 주의:
 *    1) UNO R4 WiFi 5V 보드 -> Grove Base Shield 토글 5V
 *    2) SEN55 I2C 5V/3.3V 모두 정상(실측). 5V 권장(배럴잭 일관).
 *    3) SCD30 은 5V VIN 권장(Uno 등 5V 보드). I2C 0x61, 클럭스트레칭 필요
 *       (SparkFun 라이브러리가 처리). 두 센서 같은 I2C 버스 공유.
 *    4) SCD30 첫 CO2 유효값까지 수초~수십초. 자동보정(ASC)은 수일 필요.
 *  전원 : USB-C 또는 배럴잭(DC 7~12V)
 * ============================================================
 *  보드매니저: "Arduino UNO R4 Boards"
 *  라이브러리:
 *    - PubSubClient            (by Nick O'Leary)
 *    - Sensirion I2C SEN5X     (+ Sensirion Core 동반)
 *    - SparkFun SCD30          (SCD30, UNO R4/ESP32 지원)
 *    ※ WiFiS3 / WDT 는 보드패키지 내장
 * ============================================================
 */

#include <WiFiS3.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <SensirionI2CSen5x.h>
#include <SparkFun_SCD30_Arduino_Library.h>   // ★ SCD30
#include <WDT.h>                              // v3: RA4M1 하드웨어 워치독
#include <time.h>

// ===================== 사용자 설정 =====================
const char* WIFI_SSID = "your-wifi-ssid";
const char* WIFI_PASS = "your-wifi-password";

const char* BROKER    = "xxxxx.s1.eu.hivemq.cloud";
const int   PORT      = 8883;
const char* MQTT_USER = "여기_username";
const char* MQTT_PASS = "여기_password";

const int           PUBLISH_MIN = 5;
const unsigned long SAMPLE_MS   = 10000;
// ---- v3 자가 복구 파라미터 ----
const unsigned long WDT_MS           = 5592;           // RA4M1 최대치
const unsigned long MQTT_RETRY_MS    = 10000UL;        // 브로커 재접속 시도 간격
const int           PUB_FAIL_LIMIT   = 3;              // 연속 발행 실패 버킷 → 리셋
const unsigned long NTP_RESYNC_MS    = 6UL*3600UL*1000UL;  // 확보 후 재동기 6h
const unsigned long NTP_RETRY_MS     = 10UL*60UL*1000UL;   // 미확보 시 재시도 10분
const unsigned long DEAD_RETRY_MS    = 10UL*60UL*1000UL;   // 죽은 센서 재초기화 10분
const unsigned long DEAD_RESET_MS    = 60UL*60UL*1000UL;   // 1시간 계속 죽음 → 리셋
// ======================================================

WiFiSSLClient net;
PubSubClient  client(net);
SensirionI2CSen5x sen5x;
SCD30 scd30;                       // ★ SCD30 인스턴스

String nodeId, topic;
// SEN55 누적(8) + SCD30 누적(3: co2, scd_temp, scd_hum)
double sPm1=0, sPm25=0, sPm4=0, sPm10=0, sHum=0, sTemp=0, sVoc=0, sNox=0;
double sCo2=0, sScdT=0, sScdH=0;
int n = 0;        // SEN55 샘플 수
int nC = 0;       // SCD30 샘플 수 (측정 주기 달라 별도 카운트)
// ---- 센서 건강 감시 (v2: 값 동결/버스 행 대응) ----
int           senFail    = 0;      // SEN55 연속 무효 샘플 수
unsigned long scdLastOK  = 0;      // SCD30 마지막 유효 수신 시각
int           recoverCnt = 0;      // I2C 복구 시도 누계
const int           SEN_FAIL_LIMIT = 10;       // 연속 10회 무효 → 버스 복구
const unsigned long SCD_STALL_MS   = 180000UL; // SCD30 3분 무응답 → 버스 복구
const int           RECOVER_MAX    = 3;        // 복구 3회 실패 → MCU 리셋
bool senOK  = false;
bool scdOK  = false;
bool timeOK = false;
long curBucket = -1;
unsigned long lastSample = 0;

// ---- v3 상태 ----
static unsigned long epochBase = 0, msBase = 0;    // NTP 기준점 + millis 경과
static unsigned long lastNtp = 0, lastMqttTry = 0, lastDeadTry = 0, deadSince = 0;
static int  pubFails = 0;          // 연속 발행 실패 버킷 수
static bool wdtOn = false;         // WDT 무장 여부 (setup 완료 후 true)

static void wdtFeed() { if (wdtOn) WDT.refresh(); }

void mcuReset() {                    // 보드별 소프트웨어 리셋
  Serial.flush(); delay(200);
#if defined(ARDUINO_ARCH_RENESAS)
  NVIC_SystemReset();                // UNO R4 (RA4M1)
#elif defined(ARDUINO_ARCH_ESP32)
  ESP.restart();                     // Nano ESP32
#endif
}

void makeNodeId() {
  byte mac[6];
  WiFi.macAddress(mac);
  char id[16];
  snprintf(id, sizeof(id), "node_%02X%02X%02X", mac[5], mac[4], mac[3]);  // 앞3바이트=고유
  nodeId = String(id);
  topic  = "multinode_aq/" + nodeId + "/env";    // ★ 통합 토픽 env
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.print("WiFi");
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    wdtFeed();                       // v3: 대기 중 생존 신고
    delay(500); Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " OK" : " FAIL");
}

/* v3: 무한 루프 → 1회 시도. 실패는 호출자가 주기 재시도/카운트로 처리.
 *     (장애 중에도 loop가 계속 돌아 샘플링·센서 감시가 살아 있게) */
bool tryBroker() {
  if (client.connected()) return true;
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return false;
  wdtFeed();                         // TLS 협상 직전 생존 신고 (5.5s 초과 시 WDT 리셋 = 회수)
  String cid = nodeId + "-" + String(random(0xffff), HEX);
  Serial.print("MQTT");
  if (client.connect(cid.c_str(), MQTT_USER, MQTT_PASS)) {
    wdtFeed(); Serial.println(" OK"); return true;
  }
  Serial.print(" rc="); Serial.println(client.state());
  return false;
}

/* v3: 최초 동기 + 주기 재동기 겸용. 기준점(epochBase/msBase)만 갱신하고
 *     이후 시각은 millis 경과로 계산 — 매 loop 모뎀 왕복 제거 */
bool syncTime(int tries) {
  Serial.print("NTP");
  bool first = !timeOK;
  for (int i = 0; i < tries; i++) {
    wdtFeed();
    unsigned long e = WiFi.getTime();
    if (e > 1600000000UL) {
      epochBase = e; msBase = millis(); timeOK = true;
      Serial.println(" OK");
      if (first) { long sec = PUBLISH_MIN * 60L; curBucket = ((long)epochBase / sec) * sec; }
      return true;
    }
    Serial.print("."); delay(500);
  }
  Serial.println(first ? " FAIL -> 정각정렬 없이 동작" : " FAIL -> 기존 시각 유지");
  return false;
}

long nowEpoch() { return (long)(epochBase + (millis() - msBase) / 1000UL); }

String epochToStr(long epoch) {
  time_t t = (time_t)epoch;
  struct tm *tm_utc = gmtime(&t);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", tm_utc);
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

  bool sent = tryBroker() && client.publish(topic.c_str(), p);   // v3: 결과 검사
  if (sent) {
    pubFails = 0;
    Serial.print("PUB: ");
  } else {
    if (++pubFails >= PUB_FAIL_LIMIT) {      // ≈15분 연속 미전송 → 드라이버 고착 의심
      Serial.println("[RESET] 발행 연속 실패");
      mcuReset();
    }
    Serial.print("FAIL(미전송 "); Serial.print(pubFails); Serial.print("/");
    Serial.print(PUB_FAIL_LIMIT); Serial.print("): ");
  }
  Serial.println(p);
}

// v2: I2C 통신은 성공(err==0)해도 센서가 굳어 쓰레기 값을 반복 반환하는
//     고장 모드가 실재 (예: 94.2C / 169.8% / PM2.5 2378). 물리 범위로 걸러냄.
bool plausibleSEN(float t, float h, float pm25, float pm10) {
  return t > -20 && t < 60 && h >= 0 && h <= 100 &&
         pm25 >= 0 && pm25 < 1000 && pm10 >= 0 && pm10 < 2000;
}

void takeSample() {
  // SEN55
  if (senOK) {
    float pm1, pm25, pm4, pm10, hum, temp, voc, nox;
    uint16_t err = sen5x.readMeasuredValues(pm1, pm25, pm4, pm10, hum, temp, voc, nox);
    if (!err && !isnan(pm25) && !isnan(temp) && plausibleSEN(temp, hum, pm25, pm10)) {
      sPm1 += pm1; sPm25 += pm25; sPm4 += pm4; sPm10 += pm10;
      sHum += hum; sTemp += temp; sVoc += voc; sNox += nox;
      n++; senFail = 0; recoverCnt = 0;      // v3: 정상 샘플 → 복구 누계도 청산
    } else {
      senFail++;                     // 통신 실패든 물리범위 밖이든 무효 샘플
    }
  }
  // SCD30 (자체 dataAvailable 주기, 준비됐을 때만 누적)
  if (scdOK && scd30.dataAvailable()) {
    float c = scd30.getCO2();
    float t = scd30.getTemperature();
    float h = scd30.getHumidity();
    if (c > 0 && c < 10000 && !isnan(t)) {
      sCo2 += c; sScdT += t; sScdH += h; nC++;
      scdLastOK = millis();          // 마지막 유효 수신 갱신
    }
  }
}

// v2: 잠긴 I2C 버스 복구 -> 센서 재초기화 -> 실패 누적 시 MCU 리셋
void recoverI2C() {
  recoverCnt++;
  wdtFeed();
  Serial.print("[RECOVER] I2C 복구 시도 "); Serial.println(recoverCnt);
  Wire.end();
  // 슬레이브가 버스를 물고 있을 때: SCL 9펄스로 강제 해제
  pinMode(SCL, OUTPUT);
  for (int i = 0; i < 9; i++) {
    digitalWrite(SCL, LOW);  delayMicroseconds(10);
    digitalWrite(SCL, HIGH); delayMicroseconds(10);
  }
  pinMode(SCL, INPUT);
  Wire.begin();
  Wire.setClock(50000);
  // 센서 재초기화
  sen5x.begin(Wire);
  sen5x.deviceReset(); delay(200);
  senOK = (sen5x.startMeasurement() == 0);
  scdOK = scd30.begin();
  Serial.print("[RECOVER] SEN55="); Serial.print(senOK ? "OK" : "FAIL");
  Serial.print(" SCD30=");          Serial.println(scdOK ? "OK" : "FAIL");
  if ((!senOK && !scdOK) || recoverCnt > RECOVER_MAX) {
    Serial.println("[RECOVER] 복구 불가 -> MCU 리셋");
    mcuReset();
  }
  senFail = 0; scdLastOK = millis();
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
  scdLastOK = millis();              // v2: 무응답 감시 기준점

  connectWiFi();
  makeNodeId();
  client.setServer(BROKER, PORT);
  client.setBufferSize(512);         // v3: 기본 256B는 페이로드와 여유 20B 미만
  client.setSocketTimeout(5);        // v3: CONNACK/read 대기 상한 (기본 15s)
  syncTime(20);
  for (int i = 0; i < 3 && !tryBroker(); i++) delay(2000);   // v3: 유한 시도

  Serial.print("Node: ");  Serial.println(nodeId);
  Serial.print("Topic: "); Serial.println(topic);
  Serial.print("발행주기: "); Serial.print(PUBLISH_MIN); Serial.println("분");

  lastNtp = millis(); lastMqttTry = millis(); lastDeadTry = millis();

  // v3: 부팅 경로가 끝난 뒤에만 무장 — RA4M1 WDT 최대 5592ms라
  //     느린 TLS connect가 부팅 루프를 만드는 것을 피한다.
  //     (WDT 리셋 후에는 비무장 setup에서 재접속하므로 자연 탈출)
  wdtOn = WDT.begin(WDT_MS);
  Serial.println(wdtOn ? "[WDT] 무장 (5.5s)" : "[WDT] begin 실패 — 소프트 감시만");
}

void loop() {
  wdtFeed();                         // v3: 매 루프 생존 신고

  // v3: 브로커 재접속은 10초 간격 1회 — 장애 중에도 loop 유지
  if (!client.connected() && millis() - lastMqttTry >= MQTT_RETRY_MS) {
    lastMqttTry = millis();
    tryBroker();
  }
  client.loop();

  // v2: 센서 동결/버스 행 감지 -> 복구
  if (senFail >= SEN_FAIL_LIMIT ||
      (scdOK && millis() - scdLastOK > SCD_STALL_MS)) {
    recoverI2C();
  }

  // v3: 부팅부터 죽어 있는 센서 재초기화 (10분 간격), 1시간 지속 → 리셋
  if (!senOK || !scdOK) {
    if (deadSince == 0) deadSince = millis();
    if (millis() - deadSince > DEAD_RESET_MS) {
      Serial.println("[RESET] 센서 1시간 무응답");
      mcuReset();
    }
    if (millis() - lastDeadTry >= DEAD_RETRY_MS) {
      lastDeadTry = millis();
      recoverI2C();
    }
  } else deadSince = 0;

  unsigned long now = millis();
  long sec = PUBLISH_MIN * 60L;

  // v3: 시각 재동기 — 확보 전 10분 간격, 확보 후 6시간 간격
  if (WiFi.status() == WL_CONNECTED &&
      now - lastNtp >= (timeOK ? NTP_RESYNC_MS : NTP_RETRY_MS)) {
    lastNtp = now;
    syncTime(3);
  }

  if (timeOK) {
    long bucket = (nowEpoch() / sec) * sec;
    if (curBucket < 0) curBucket = bucket;
    if (bucket > curBucket) {                // 버킷 경계 → 발행
      publishAverage(curBucket);
      resetAccum();
      curBucket = bucket;
    } else if (bucket < curBucket) {         // v3: 재동기로 시계 후퇴 → 중복 발행 방지
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

  delay(20);                         // v3: busy-spin 제거 (모뎀·I2C 부하 완화)
}
