/*
  UNO R4 WiFi temperature sketch for the microbial growth dashboard.

  USB and Wi-Fi stay independent:
  - USB: this sketch prints one Celsius value per line on Serial.
  - Wi-Fi: after it joins the same network as the dashboard computer,
    it publishes the _microbial._tcp service and serves the same line on port 8080.
    The hostname is temp- plus the last two bytes of the MAC address, so each
    board can be found without a shared name.

  Fill in WIFI_SSID and WIFI_PASSWORD. Install the OneWire,
  DallasTemperature, and ArduinoMDNS libraries, then upload.
  The DS18B20 data wire is pin 2.
*/

#include <OneWire.h>
#include <DallasTemperature.h>
#include <WiFiS3.h>
#include <ArduinoMDNS.h>

const char WIFI_SSID[] = "iPhone";
const char WIFI_PASSWORD[] = "00000000";
const uint16_t WIFI_PORT = 8080;
char wifiHost[20] = "temp";
char serviceName[32] = "temp._microbial";
const int ONE_WIRE_PIN = 2;

OneWire oneWire(ONE_WIRE_PIN);
DallasTemperature sensors(&oneWire);
WiFiServer server(WIFI_PORT);
WiFiUDP mdnsUdp;
MDNS mdns(mdnsUdp);
WiFiClient client;
bool wifiReady = false;
unsigned long lastSampleMs = 0;
unsigned long lastWifiTryMs = 0;

void setup() {
  Serial.begin(9600);
  sensors.begin();
  if (WIFI_SSID[0] != '\0') {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastWifiTryMs = millis();
  }
}

void serviceWifi() {
  if (wifiReady || WIFI_SSID[0] == '\0') {
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    if (millis() - lastWifiTryMs > 15000) {
      Serial.println("WIFI_RETRY");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      lastWifiTryMs = millis();
    }
    return;
  }

  byte mac[6];
  WiFi.macAddress(mac);
  snprintf(wifiHost, sizeof(wifiHost), "temp-%02X%02X", mac[4], mac[5]);
  snprintf(serviceName, sizeof(serviceName), "%s._microbial", wifiHost);

  server.begin();
  mdns.begin(WiFi.localIP(), wifiHost);
  mdns.addServiceRecord(serviceName, WIFI_PORT, MDNSServiceTCP);
  wifiReady = true;
  Serial.print("WIFI_OK ");
  Serial.println(wifiHost);
  Serial.println(WiFi.localIP());
}

void acceptWifiClient() {
  if (!wifiReady) {
    return;
  }
  if (!client || !client.connected()) {
    if (client) {
      client.stop();
    }
    client = server.available();
  }
}

void loop() {
  serviceWifi();
  if (wifiReady) {
    mdns.run();
  }
  acceptWifiClient();

  if (millis() - lastSampleMs < 1000) {
    return;
  }
  lastSampleMs = millis();

  sensors.requestTemperatures();
  float celsius = sensors.getTempCByIndex(0);
  if (celsius < -100.0) {
    // Keep the TCP server alive so the dashboard can still discover the board.
    Serial.println("SENSOR_FAIL");
    return;
  }

  Serial.println(celsius, 2);

  if (client && client.connected()) {
    client.println(celsius, 2);
  }
}
