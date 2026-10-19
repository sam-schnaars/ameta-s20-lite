// Ground station: XIAO ESP32-C3 on the laptop's USB. Relays text commands to the harness over ESP-NOW
// (the drone's Wi-Fi is 5 GHz, which the ESP32-C3 can't join, so the harness can't be reached via the drone).
//
// USB serial in  (from Python):  "<seq> <COMMAND>"   e.g. "17 RELEASE"      -> radio "AMH1 17 RELEASE"
// USB serial out (to Python):    "R <seq> <reply>"   from radio "AMH1R <seq> <reply>"
//                                "HELLO <state> <rssi>" from the harness's 1 Hz heartbeat "AMH1H <state>"
// "WHO" on serial -> "GROUND <mac>"

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

const uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
const uint8_t CHANNEL = 1;

void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  char buf[200];
  len = min(len, (int)sizeof(buf) - 1);
  memcpy(buf, data, len);
  buf[len] = 0;
  int rssi = info->rx_ctrl ? info->rx_ctrl->rssi : 0;
  if (strncmp(buf, "AMH1R ", 6) == 0) Serial.printf("R %s\n", buf + 6);
  else if (strncmp(buf, "AMH1H ", 6) == 0) Serial.printf("HELLO %s %d\n", buf + 6, rssi);
}

void setup() {
  Serial.begin(115200);
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
  Serial.println("ground ready");
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line == "WHO") { Serial.printf("GROUND %s\n", WiFi.macAddress().c_str()); return; }
    if (line.length() == 0) return;
    String msg = "AMH1 " + line;
    esp_now_send(BCAST, (const uint8_t*)msg.c_str(), msg.length());
  }
  delay(1);
}
