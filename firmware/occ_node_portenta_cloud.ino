/*
 * ============================================================
 *  멀티노드 재실 인원 노드  ★ Portenta H7 + Vision Shield 판 (운용 v3)
 *  - Arduino_MQTT_MultiNode_Demo 발행 계약 정렬 (occ 서브토픽)
 *  - 탐지 : 10초 단발 FOMO 추론 (듀티 ~0.7% → 발열 최소)
 *  - 통계 : 5분 버킷당 ~30샘플 → 평균·중앙값·최대 동시 발행
 *  - 좌표 : "버킷 내 최대 인원 시점"의 centroid 보존 (UI 대표 좌표)
 *  - 감시 : 하드웨어 워치독 30초 — 행(hang) 시 자동 리셋 (무인 운용 보험)
 * ------------------------------------------------------------
 *  v3 변경 (2026-09-05 — "영구 다운" 원인 제거):
 *   ① wd.start()를 setup() 첫 줄로 — 모든 초기화 경로가 WDT 보호下
 *   ② while(1) 데드엔드 제거 — cam.begin/관문1 실패는 재시도 후 NVIC_SystemReset()
 *   ③ 웜 리셋 후 카메라 안정화 지연 3초 (WDT 리셋은 HM0360을 리셋하지 못함)
 *   ④ 발행 3버킷 연속 실패(≈15분) → 자가 리셋 (WiFi/MQTT 드라이버 고착 복구)
 *   ⑤ 캡처/추론 6회 연속 실패(≈1분) → 카메라 재초기화, 2회 무효 → 자가 리셋
 *   ⑥ NTP 6시간 재동기화 (millis 49.7일 롤오버·시계 표류 차단), 실패 시 10분 재시도
 *   ⑦ WiFi 대기·NTP 루프에 wd.kick() 보강, endMessage() 반환값 검사
 *   ⑧ 부팅 시 리셋 사유 출력 (전원/워치독/소프트웨어 구분 — 현장 진단용)
 *   ※ 최종 안전망은 별도: 비전 노드 전원을 플러그 스케줄로 매일 재인가 (PROGRESS 09-01)
 * ============================================================
 *  전제: 경량 모델 (FOMO 0.1 + Grayscale) — Nicla와 동일 라이브러리 사용
 *  카메라: HM0360 (Rev2 실드, 흑백). CAP_QVGA=1이면 320x240 QVGA 전체(검증 모드),
 *          관문 실패 시 0으로 후퇴(160x120, 동일 4:3 산수)
 *
 *  발행 계약 (env 노드와 정렬):
 *    토픽   : multinode_aq/<node_id>/occ
 *    노드ID : MAC 뒤 3바이트 node_XXXXXX 자동 생성
 *    시각   : "t" = UTC 버킷 문자열 → env readings와 정확 조인
 *  페이로드 예:
 *    {"node":"node_2A8454","t":"2026-07-09 13:35:00",
 *     "occ":2.4,"occ_med":3,"occ_max":4,"occ_last":2,
 *     "c":[[48,30],[62,55]],"w":96,"n":30}
 *      occ*  : 분석용 정형 지표 (DB 컬럼)
 *      c     : occ_max 시점의 centroid — UI(조준선 맵)용, len(c)=occ_max와 짝
 *              (항상 프레임 전체(4:3) 기준 상대좌표)
 *      w     : c의 좌표계 크기 (모델 입력 폭)
 *      n     : 버킷 내 유효 샘플 수 (품질 지표, 정상 ~30)
 * ------------------------------------------------------------
 *  설치 절차: Portenta_AimingStream 펌웨어로 방향·화각 확정
 *             → CAM_ROTATE_180에 반영 → 본 펌웨어 업로드
 *  필요 라이브러리: ArduinoMqttClient
 *  보드: Portenta H7 (M7 core) + Vision Shield
 *        (WiFiFirmwareUpdater 실행 완료 상태 · 보드 전환 시 캐시 삭제!)
 *  업로드 팁: WiFi 펌웨어 구동 중엔 리셋 더블탭(부트로더) 후 업로드
 * ============================================================
 */

#include <Person_Detection_FOMO_inferencing.h>
// ↑ 추론엔진 헤더 = 본인 EI 프로젝트 라이브러리 이름으로 교체!
//   확인: 문서\Arduino\libraries\<설치된 폴더>\src\ 안의 *_inferencing.h 파일명
//   (예: My_Person_FOMO_inferencing.h — zip 재설치 시 이 줄만 맞추면 됨)
#include "camera.h"
#include "hm0360.h"          // ★ Vision Shield Rev2 (HM0360, 흑백)
#include <WiFi.h>
#include <WiFiSSLClient.h>
#include <ArduinoMqttClient.h>
#include <time.h>
#include <mbed.h>                          // Watchdog · ResetReason · NVIC_SystemReset

// ===================== 사용자 설정 =====================
const char* WIFI_SSID = "your-wifi-ssid";
const char* WIFI_PASS = "your-wifi-password";

const char* BROKER    = "e311c7ffc26f4b7990382b5e43469c89.s1.eu.hivemq.cloud";
const int   PORT      = 8883;
const char* MQTT_USER = "여기_username";
const char* MQTT_PASS = "여기_password";

#define CAM_ROTATE_180   1                 // ★ 조준 테스트에서 확정한 값 (0/1)
#define CAP_QVGA         1                 // 1=320x240 QVGA 전체(검증 모드) / 0=160x120(경량)
                                           //   관문1~3 실패 시 0으로 후퇴 — c는 항상 '프레임 전체' 상대좌표
const int PUBLISH_MIN  = 5;                // 버킷(분) — env 노드와 동일! (테스트 시 1)
#define DETECT_MS        10000UL           // 탐지 주기 10초 (테스트 시 2000UL)
#define BUCKET_MAX_S     40                // 버킷 내 샘플 상한
#define WATCHDOG_MS      30000             // 30초 무응답 → 자동 리셋
// --- v3 자가 복구 파라미터 ---
#define CAM_SETTLE_MS    3000              // 웜 리셋 후 HM0360 안정화 대기
#define CAM_TRIES        3                 // cam.begin / 관문1 재시도 횟수
#define PUB_FAIL_LIMIT   3                 // 연속 발행 실패 버킷 수 → 자가 리셋 (≈15분)
#define CAP_FAIL_LIMIT   6                 // 연속 캡처/추론 실패 → 카메라 재초기화 (≈1분)
#define CAM_REINIT_LIMIT 2                 // 재초기화 무효 횟수 → 자가 리셋
#define NTP_RESYNC_MS    (6UL*3600UL*1000UL) // 시각 재동기 주기 6h (롤오버·표류 차단)
#define NTP_RETRY_MS     (10UL*60UL*1000UL)  // 시각 미확보 시 재시도 10분
// ======================================================

/* ---------- 카메라 ---------- */
HM0360 himax;
Camera cam(himax);
FrameBuffer fb;

#if CAP_QVGA
  #define RAW_W 320
  #define RAW_H 240
  #define CAM_MODE CAMERA_R320x240
#else
  #define RAW_W 160
  #define RAW_H 120
  #define CAM_MODE CAMERA_R160x120
#endif

static uint8_t model_in[EI_CLASSIFIER_INPUT_WIDTH *
                        EI_CLASSIFIER_INPUT_HEIGHT * 3];

/* ---------- 탐지 결과 ---------- */
#define MAX_BOXES 12
typedef struct { uint8_t cx, cy; } cent_t;
static cent_t  g_cents[MAX_BOXES];         // 직전 추론의 centroid
static uint8_t g_cent_cnt = 0;
static cent_t  best_cents[MAX_BOXES];      // ★ 버킷 내 최대 인원 시점 좌표 보존
static uint8_t best_cnt = 0;
static uint32_t g_infer_ms = 0;

/* ---------- 버킷 샘플 ---------- */
static int8_t  samples[BUCKET_MAX_S];
static uint8_t s_n = 0;
static int     occLast = 0;

/* ---------- 시각 ---------- */
static bool timeOK = false;
static unsigned long epochBase = 0, msBase = 0;
static long curBucket = -1;
static unsigned long lastDetect = 0, lastPubFallback = 0, lastNtp = 0;

/* ---------- v3 자가 복구 카운터 ---------- */
static uint8_t pubFails = 0;               // 연속 발행 실패 버킷 수
static uint8_t capFails = 0;               // 연속 캡처/추론 실패 수
static uint8_t camReinits = 0;             // 성공 없이 반복된 카메라 재초기화 수

WiFiSSLClient tls;
MqttClient mqtt(tls);
String nodeId, topic;
mbed::Watchdog &wd = mbed::Watchdog::get_instance();

/* WDT를 먹이면서 기다린다 — 긴 delay 대체 (v3) */
static void settle(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) { wd.kick(); delay(100); }
}

static void selfReset(const char* why) {
  Serial.print("[RESET] "); Serial.println(why);
  Serial.flush(); delay(200);
  NVIC_SystemReset();
}

/* ================= 프로젝트 관례 함수 ================= */
void makeNodeId() {
  uint8_t mac[6];
  WiFi.macAddress(mac);
  char id[16];
  snprintf(id, sizeof(id), "node_%02X%02X%02X", mac[3], mac[4], mac[5]);
  nodeId = String(id);
  topic  = "multinode_aq/" + nodeId + "/occ";
}

bool connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;
  Serial.print("WiFi");
  // 숨김 SSID 대응: 보안모드(WPA2-AES) 명시 → 스캔 생략하고 직접 join
  // (mbed 코어의 2-인자 begin은 스캔에서 SSID를 못 찾으면 즉시 실패함)
  WiFi.begin(WIFI_SSID, WIFI_PASS, ENC_TYPE_CCMP);
  unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < 15000) {
    wd.kick();                              // v3: 대기 중 생존 신고
    delay(500); Serial.print(".");
  }
  bool ok = (WiFi.status() == WL_CONNECTED);
  Serial.println(ok ? " OK" : " FAIL");
  return ok;
}

bool connectBroker() {
  if (mqtt.connected()) return true;
  if (!connectWiFi()) return false;
  wd.kick();                                // TLS 협상 전 생존 신고
  mqtt.setId(String("occ-") + nodeId);
  mqtt.setUsernamePassword(MQTT_USER, MQTT_PASS);
  mqtt.setKeepAliveInterval(60 * 1000L);
  Serial.print("MQTT");
  if (mqtt.connect(BROKER, PORT)) { wd.kick(); Serial.println(" OK"); return true; }
  Serial.print(" rc="); Serial.println(mqtt.connectError());
  return false;
}

/* v3: 최초 동기 + 주기 재동기 겸용. 성공 시 epochBase/msBase 갱신 →
 *     millis 롤오버(49.7일)와 수정 표류가 버킷 시각을 오염시키지 못함 */
bool syncTime(uint8_t tries) {              // WiFi 모듈 내장 NTP
  Serial.print("NTP");
  bool first = !timeOK;
  for (uint8_t i = 0; i < tries; i++) {
    wd.kick();
    unsigned long e = WiFi.getTime();
    if (e > 1600000000UL) {
      epochBase = e; msBase = millis(); timeOK = true;
      Serial.println(" OK");
      if (first && PUBLISH_MIN > 0) {       // 최초 확보 시 버킷 정렬
        long sec = PUBLISH_MIN * 60L;
        curBucket = ((epochBase) / sec) * sec;
      }
      return true;
    }
    Serial.print("."); delay(1000);
  }
  Serial.println(first ? " FAIL -> 정각정렬 없이 동작" : " FAIL -> 기존 시각 유지");
  return false;
}

long nowEpoch() {
  return (long)(epochBase + (millis() - msBase) / 1000UL);
}

String epochToStr(long epoch) {
  time_t t = (time_t)epoch;
  struct tm tinfo; gmtime_r(&t, &tinfo);
  char buf[32];
  strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &tinfo);
  return String(buf);
}

/* ================= 카메라/추론 ================= */
static bool cameraInit() {                  // v3: 재시도 가능한 초기화
  for (uint8_t i = 0; i < CAM_TRIES; i++) {
    wd.kick();
    if (cam.begin(CAM_MODE, CAMERA_GRAYSCALE, 30)) return true;
    Serial.println("[CAM] begin 실패 — 재시도");
    settle(2000);
  }
  return false;
}

static inline uint8_t pxg(const uint8_t *raw, int sx, int sy) {
#if CAM_ROTATE_180
  sx = RAW_W - 1 - sx;  sy = RAW_H - 1 - sy;
#endif
  return raw[sy * RAW_W + sx];              // 흑백 1바이트
}

static bool capture_and_prepare() {
  if (cam.grabFrame(fb, 3000) != 0) return false;
  const uint8_t *raw = fb.getBuffer();
  const float stepx = (float)RAW_W / EI_CLASSIFIER_INPUT_WIDTH;   // 프레임 전체 →
  const float stepy = (float)RAW_H / EI_CLASSIFIER_INPUT_HEIGHT;   // 96x96
  uint8_t *d = model_in;
  for (int y = 0; y < EI_CLASSIFIER_INPUT_HEIGHT; y++) {
    int sy = (int)(y * stepy);
    for (int x = 0; x < EI_CLASSIFIER_INPUT_WIDTH; x++) {
      uint8_t g = pxg(raw, (int)(x * stepx), sy);
      d[0] = d[1] = d[2] = g;                 // 흑백 → 3채널 복제
      d += 3;
    }
  }
  return true;
}

static int ei_get_data(size_t offset, size_t length, float *out_ptr) {
  size_t ix = offset * 3;
  for (size_t i = 0; i < length; i++) {
    out_ptr[i] = (model_in[ix + 2] << 16) + (model_in[ix + 1] << 8) + model_in[ix];
    ix += 3;
  }
  return 0;
}

static int infer_once() {
  if (!capture_and_prepare()) return -1;
  ei::signal_t signal;
  signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
  signal.get_data = &ei_get_data;
  ei_impulse_result_t result = { 0 };
  uint32_t t0 = millis();
  if (run_classifier(&signal, &result, false) != EI_IMPULSE_OK) return -1;
  g_infer_ms = millis() - t0;

  uint8_t n = 0;
  for (uint32_t i = 0; i < result.bounding_boxes_count && n < MAX_BOXES; i++) {
    auto &bb = result.bounding_boxes[i];
    if (bb.value == 0) continue;
    g_cents[n].cx = (uint8_t)(bb.x + bb.width / 2);
    g_cents[n].cy = (uint8_t)(bb.y + bb.height / 2);
    n++;
  }
  g_cent_cnt = n;
  return n;
}

/* 10초 단발 샘플 + 최대 시점 좌표 보존 + v3 카메라 자가 복구 */
void takeSample() {
  int c = infer_once();
  if (c < 0) {
    Serial.println("detect 실패 - 결측");
    if (++capFails >= CAP_FAIL_LIMIT) {     // ≈1분 연속 실패 → 센서 고착 의심
      capFails = 0;
      if (++camReinits > CAM_REINIT_LIMIT) selfReset("카메라 재초기화 무효");
      Serial.println("[CAM] 재초기화 시도");
      if (!cameraInit()) selfReset("카메라 재초기화 실패");
    }
    return;
  }
  capFails = 0; camReinits = 0;             // 성공 → 카운터 청산
  occLast = c;
  if (s_n < BUCKET_MAX_S) samples[s_n++] = (int8_t)c;
  if (c > 0 && (uint8_t)c >= best_cnt) {          // ★ 최대 경신 시 좌표 보존
    memcpy(best_cents, g_cents, sizeof(cent_t) * g_cent_cnt);
    best_cnt = g_cent_cnt;
  }
}

/* 버킷 통계 발행: 평균 + 중앙값 + 최대 + 마지막 + 최대 시점 centroid */
void publishBucket(long bucketEpoch) {
  if (s_n == 0) return;

  int sum = 0, mx = 0;
  int8_t sorted[BUCKET_MAX_S];
  memcpy(sorted, samples, s_n);
  for (uint8_t i = 1; i < s_n; i++) {
    int8_t key = sorted[i]; int j = i - 1;
    while (j >= 0 && sorted[j] > key) { sorted[j + 1] = sorted[j]; j--; }
    sorted[j + 1] = key;
  }
  for (uint8_t i = 0; i < s_n; i++) { sum += samples[i]; if (samples[i] > mx) mx = samples[i]; }
  float avg = (float)sum / s_n;
  int   med = sorted[s_n / 2];

  char cbuf[140] = ""; size_t ci = 0;
  for (uint8_t i = 0; i < best_cnt && ci < sizeof(cbuf) - 12; i++)
    ci += snprintf(cbuf + ci, sizeof(cbuf) - ci, "%s[%d,%d]",
                   i ? "," : "", best_cents[i].cx, best_cents[i].cy);

  char p[380];
  if (timeOK) {
    String ts = epochToStr(bucketEpoch);
    snprintf(p, sizeof(p),
      "{\"node\":\"%s\",\"t\":\"%s\","
      "\"occ\":%.2f,\"occ_med\":%d,\"occ_max\":%d,\"occ_last\":%d,"
      "\"c\":[%s],\"w\":%d,\"n\":%d}",
      nodeId.c_str(), ts.c_str(), avg, med, mx, occLast,
      cbuf, EI_CLASSIFIER_INPUT_WIDTH, s_n);
  } else {
    snprintf(p, sizeof(p),
      "{\"node\":\"%s\","
      "\"occ\":%.2f,\"occ_med\":%d,\"occ_max\":%d,\"occ_last\":%d,"
      "\"c\":[%s],\"w\":%d,\"n\":%d}",
      nodeId.c_str(), avg, med, mx, occLast,
      cbuf, EI_CLASSIFIER_INPUT_WIDTH, s_n);
  }

  bool sent = false;                        // v3: 전송 성공을 끝까지 확인
  if (connectBroker()) {
    mqtt.beginMessage(topic);
    mqtt.print(p);
    sent = (mqtt.endMessage() == 1);
  }
  if (sent) {
    pubFails = 0;
    Serial.print("PUB: ");
  } else {
    if (++pubFails >= PUB_FAIL_LIMIT)       // 3버킷(≈15분) 연속 실패 → 드라이버 고착 의심
      selfReset("발행 연속 실패");
    Serial.print("FAIL(미전송 "); Serial.print(pubFails); Serial.print("/");
    Serial.print(PUB_FAIL_LIMIT); Serial.print("): ");
  }
  Serial.println(p);
}

void resetBucket() { s_n = 0; best_cnt = 0; }

/* v3: 부팅 원인 출력 — 전원 재인가/워치독/소프트리셋 구분 (현장 진단) */
static void printResetReason() {
  Serial.print("[BOOT] reset = ");
  switch (mbed::ResetReason::get()) {
    case RESET_REASON_POWER_ON:  Serial.println("전원 인가");        break;
    case RESET_REASON_WATCHDOG:  Serial.println("워치독 (행 복구)"); break;
    case RESET_REASON_SOFTWARE:  Serial.println("자가 리셋");        break;
    case RESET_REASON_PIN_RESET: Serial.println("리셋 버튼");        break;
    default:                     Serial.println("기타");             break;
  }
}

/* ================================================================= */
void setup() {
  Serial.begin(115200);
  delay(500);
  wd.start(WATCHDOG_MS);                    // ★v3 첫 줄 무장 — 이후 모든 경로가 WDT 보호下
  Serial.println("\n[BOOT] Portenta occ node v3 (10s 단발 / 5분 버킷 / 워치독)");
  printResetReason();
  Serial.print("[CAM] "); Serial.print(RAW_W); Serial.print("x");
  Serial.print(RAW_H); Serial.println(CAP_QVGA ? " QVGA 전체(4:3)" : " QQVGA 전체(4:3)");

  settle(CAM_SETTLE_MS);                    // ★v3 웜 리셋 시 HM0360 안정화 대기

  if (!cameraInit())                        // ★v3 데드엔드 제거 — 재시도 후 리셋
    selfReset("카메라 초기화 실패");

  /* 관문 1: 아레나 선점 (WiFi 이전 — 연속 힙 블록 확보) */
  Serial.print("[관문1] 아레나 선점 추론... ");
  bool warm = false;
  for (uint8_t i = 0; i < CAM_TRIES && !warm; i++) {
    wd.kick();
    warm = (infer_once() >= 0);
    if (!warm) settle(1000);
  }
  if (!warm) selfReset("관문1 실패");       // ★v3 데드엔드 제거
  Serial.print("성공 ("); Serial.print(g_infer_ms); Serial.println("ms)");

  /* 관문 2: WiFi + NTP + 브로커 */
  connectWiFi();
  makeNodeId();
  syncTime(10);
  connectBroker();

  /* 관문 3: 공존 검증 */
  Serial.print("[관문3] WiFi 공존 추론... ");
  Serial.println(infer_once() >= 0 ? "성공 — 공존 확인" : "실패 — 공존 불가");

  Serial.print("Node: ");  Serial.println(nodeId);
  Serial.print("Topic: "); Serial.println(topic);
  Serial.print("탐지 "); Serial.print(DETECT_MS / 1000);
  Serial.print("s 단발 / 버킷 "); Serial.print(PUBLISH_MIN);
  Serial.print("분 / 회전 "); Serial.println(CAM_ROTATE_180);

  lastPubFallback = millis();
  lastNtp = millis();
}

void loop() {
  wd.kick();                                // 매 루프 생존 신고
  mqtt.poll();

  unsigned long now = millis();
  long sec = PUBLISH_MIN * 60L;

  /* v3: 시각 재동기 — 확보 전 10분 간격, 확보 후 6시간 간격 */
  if (WiFi.status() == WL_CONNECTED &&
      now - lastNtp >= (timeOK ? NTP_RESYNC_MS : NTP_RETRY_MS)) {
    lastNtp = now;
    syncTime(3);
  }

  if (timeOK) {
    long bucket = (nowEpoch() / sec) * sec;
    if (curBucket < 0) curBucket = bucket;
    if (bucket > curBucket) {               // 버킷 경계 → 발행
      publishBucket(curBucket);
      resetBucket();
      curBucket = bucket;
    } else if (bucket < curBucket) {        // v3: 재동기로 시계 후퇴 → 중복 발행 방지
      curBucket = bucket;
    }
  } else {
    if (now - lastPubFallback >= (unsigned long)PUBLISH_MIN * 60000UL) {
      lastPubFallback = now;
      publishBucket(0);
      resetBucket();
    }
  }

  if (now - lastDetect >= DETECT_MS) {
    lastDetect = now;
    takeSample();
    Serial.print("sample n="); Serial.print(s_n);
    Serial.print(" last="); Serial.print(occLast);
    Serial.print(" ("); Serial.print(g_infer_ms); Serial.println("ms)");
  }

  delay(20);
}
