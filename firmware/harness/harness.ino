// AMETA S20 Lite payload harness -- Seeed XIAO ESP32-C3 + micro servo on D10.
// Talks to a ground-station XIAO (firmware/ground) over ESP-NOW, because the drone's Wi-Fi is 5 GHz-only.
// Radio in:  "AMH1 <seq> <COMMAND>"   -> radio out "AMH1R <seq> <reply>"   (same seq retried = same reply, no re-run)
// Heartbeat: "AMH1H <state>" once a second. Commands also work over USB serial (115200) for bench tests.
//
// Commands -> reply
//   PING            -> PONG <state>
//   ARM             -> ARMED          (expires after ARM_TIMEOUT_MS if no RELEASE follows)
//   DISARM          -> DISARMED
//   RELEASE         -> RELEASED | REFUSED not-armed
//   CLOSE           -> CLOSED         (latch back to hold position; also disarms)
//   ANGLE <0-180>   -> ANGLE <n> | REFUSED armed   (bench tuning only, while disarmed)
//   SETHOLD <n>     -> HOLD n saved        (latch-closed angle, kept across power-off; disarmed only)
//   SETRELEASE <n>  -> RELEASE_ANGLE n saved
//   ANGLES          -> ANGLES hold <h> release <r> now <current>
//   SIGNAL          -> measured servo pulse on the pin (self-test)
// Safety: boots DISARMED with latch CLOSED; never releases on its own (no release on radio loss).

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <ESP32Servo.h>
#include "driver/gpio.h"
#include <Preferences.h>

const int SERVO_PIN = D10;           // next to 3V3 + GND: servo black-red-white lines up with GND-3V3-D10
int HOLD_ANGLE = 0;                  // latch closed  -- tunable: SETHOLD n  (saved in flash)
int RELEASE_ANGLE = 90;              // latch open    -- tunable: SETRELEASE n (saved in flash)
Preferences prefs;
const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
const uint8_t CHANNEL = 1;           // must match firmware/ground
const uint32_t ARM_TIMEOUT_MS = 10000;
const uint32_t HELLO_MS = 1000;

Servo latch;
bool armed = false;
uint32_t armedAt = 0, lastHello = 0;
bool released = false;

const char* stateName() { return released ? "released" : (armed ? "armed" : "disarmed"); }

int currentAngle = HOLD_ANGLE;

// Move in small steps instead of one jump: the servo's start-up current spike is much smaller, which
// helps avoid brown-out resets on a small battery (especially without a capacitor). ~0.25 s for 90 deg.
void moveServo(int target) {
  target = constrain(target, 0, 180);
  int step = target > currentAngle ? 2 : -2;
  while (abs(target - currentAngle) > 2) {
    currentAngle += step;
    latch.write(currentAngle);
    delay(5);
  }
  currentAngle = target;
  latch.write(currentAngle);
}

String handle(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  if (cmd == "PING") return String("PONG ") + stateName();
  if (cmd == "ARM") { armed = true; armedAt = millis(); return "ARMED"; }
  if (cmd == "DISARM") { armed = false; return "DISARMED"; }
  if (cmd == "RELEASE") {
    if (!armed) return released ? "RELEASED" : "REFUSED not-armed";
    moveServo(RELEASE_ANGLE);
    armed = false; released = true;
    return "RELEASED";
  }
  if (cmd == "CLOSE") { moveServo(HOLD_ANGLE); armed = false; released = false; return "CLOSED"; }
  if (cmd.startsWith("ANGLE ")) {
    if (armed) return "REFUSED armed";
    int a = constrain(cmd.substring(6).toInt(), 0, 180);
    moveServo(a);
    return String("ANGLE ") + a;
  }
  if (cmd.startsWith("SETHOLD ") || cmd.startsWith("SETRELEASE ")) {
    if (armed) return "REFUSED armed";
    bool hold = cmd.startsWith("SETHOLD ");
    int a = constrain(cmd.substring(hold ? 8 : 11).toInt(), 0, 180);
    if (hold) HOLD_ANGLE = a; else RELEASE_ANGLE = a;
    prefs.putInt(hold ? "hold" : "release", a);
    return String(hold ? "HOLD " : "RELEASE_ANGLE ") + a + " saved";
  }
  if (cmd == "ANGLES") return String("ANGLES hold ") + HOLD_ANGLE + " release " + RELEASE_ANGLE + " now " + currentAngle;
  if (cmd == "SIGNAL") {
    // Self-test: read back the PWM on the servo pin itself (checks the chip/pin, not the wire).
    gpio_input_enable((gpio_num_t)SERVO_PIN);
    unsigned long hi = pulseIn(SERVO_PIN, HIGH, 60000);
    unsigned long lo = pulseIn(SERVO_PIN, LOW, 60000);
    if (!hi) return "SIGNAL none (no pulses on pin)";
    return String("SIGNAL pulse ") + hi + " us, period " + (hi + lo) + " us (expect 500-2400 us / ~20000 us)";
  }
  return "ERR unknown";
}

// ---- ESP-NOW link --------------------------------------------------------------------------
volatile bool rxPending = false;
char rxBuf[128];
long lastSeq = -1;
String lastReply = "";

void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (rxPending || len < 6 || memcmp(data, "AMH1 ", 5) != 0) return;
  len = min(len, (int)sizeof(rxBuf) - 1);
  memcpy(rxBuf, data, len);
  rxBuf[len] = 0;
  rxPending = true;                     // handled in loop(), not in the radio callback
}

void radioSend(const String& msg) {
  esp_err_t e = esp_now_send(BCAST, (const uint8_t*)msg.c_str(), msg.length());
  static uint32_t lastErr = 0;
  if (e != ESP_OK && millis() - lastErr > 5000) { lastErr = millis(); Serial.printf("radio send error %d\n", e); }
}

void handleRadio() {
  if (!rxPending) return;
  String line = String(rxBuf + 5);      // "<seq> <COMMAND>"
  rxPending = false;
  int sp = line.indexOf(' ');
  if (sp < 0) return;
  long seq = line.substring(0, sp).toInt();
  String reply = (seq == lastSeq) ? lastReply : handle(line.substring(sp + 1));   // retry -> same answer
  lastSeq = seq;
  lastReply = reply;
  radioSend("AMH1R " + String(seq) + " " + reply);
  Serial.printf("radio %s -> %s\n", line.c_str(), reply.c_str());
}

void setup() {
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);     // never stall on log output when USB is connected but nobody is reading
  prefs.begin("harness", false);
  HOLD_ANGLE = prefs.getInt("hold", HOLD_ANGLE);
  RELEASE_ANGLE = prefs.getInt("release", RELEASE_ANGLE);
  currentAngle = HOLD_ANGLE;
  latch.setPeriodHertz(50);
  latch.attach(SERVO_PIN, 500, 2400);
  latch.write(HOLD_ANGLE);                 // boot: closed + disarmed
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_protocol(WIFI_IF_STA, WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N | WIFI_PROTOCOL_LR);  // normal + long-range (both ends match)
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  if (esp_now_init() != ESP_OK) Serial.println("ERR espnow init");
  esp_now_register_recv_cb(onRecv);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = CHANNEL;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  Serial.println("harness ready (disarmed). Commands: PING ARM DISARM RELEASE CLOSE ANGLE n SETHOLD n SETRELEASE n ANGLES SIGNAL");
}

void loop() {
  if (armed && millis() - armedAt > ARM_TIMEOUT_MS) { armed = false; Serial.println("arm expired"); }

  handleRadio();
  if (millis() - lastHello > HELLO_MS) {
    lastHello = millis();
    radioSend(String("AMH1H ") + stateName());
  }

  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line == "WHO") { Serial.println("HARNESS"); return; }
    Serial.println(handle(line));
  }
  delay(2);
}
