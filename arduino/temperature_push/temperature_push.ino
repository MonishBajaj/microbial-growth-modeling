/*
  UNO R4 WiFi: read a DS18B20 and POST Celsius to the dashboard.

  Every POST_EVERY_MS the sketch sends:
    POST https://SERVER_HOST/api/arduino/ingest
    Authorization: Bearer PUSH_TOKEN
    {"celsius": <float>, "device_id": DEVICE_ID}
  Flask stores that in arduino_push.py. The dashboard does not open a
  connection back to the board.

  WIFI_SSID, WIFI_PASSWORD, and SERVER_HOST in this file are lab values.
  Change them before you share the sketch. SERVER_HOST must match the current
  public_base_url.txt or the deployed host. It has no https:// prefix.

  UNO R4 WiFi — push Celsius to the microbial growth dashboard.

  The board POSTs JSON to your Flask ingest URL. That URL stays the same when
  you use a tunnel or a deployed host (set SERVER_HOST below once).

  Libraries (Library Manager):
    - OneWire
    - DallasTemperature
    - ArduinoHttpClient

  DS18B20 data pin: 2 (4.7k pull-up to 3.3V/5V).
*/

#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <ArduinoHttpClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ---- edit these ----
const char WIFI_SSID[] = "iPhone";
const char WIFI_PASSWORD[] = "00000000";

// Hostname only — no https:// and no path.
// Examples:
//   "xxxx.trycloudflare.com"     (Cloudflare quick tunnel)
//   "your-app.onrender.com"      (deployed)
//   "172.20.10.2"                (same LAN only; may change)
// Filled from the current Cloudflare quick tunnel (scripts/start_push_tunnel.sh).
// If you restart the tunnel, update this host to the new *.trycloudflare.com name
// shown in public_base_url.txt / the dashboard Arduino Push panel.
const char SERVER_HOST[] = "huntington-wednesday-more-indication.trycloudflare.com";
const int SERVER_PORT = 443;          // 443 for HTTPS tunnels/deploy; 5000 for plain LAN
const bool SERVER_USE_TLS = true;     // false for http://LAN-IP:5000
const char INGEST_PATH[] = "/api/arduino/ingest";
const char PUSH_TOKEN[] = "microbial-lab-token";
const char DEVICE_ID[] = "uno-r4-1";

const int ONE_WIRE_PIN = 2;
const unsigned long POST_EVERY_MS = 3000;
// --------------------

OneWire oneWire(ONE_WIRE_PIN);
DallasTemperature sensors(&oneWire);

WiFiSSLClient tlsClient;
WiFiClient plainClient;
HttpClient* http = nullptr;

unsigned long lastPostMs = 0;
unsigned long lastWifiTryMs = 0;

void ensureHttpClient() {
  if (http != nullptr) {
    return;
  }
  if (SERVER_USE_TLS) {
    http = new HttpClient(tlsClient, SERVER_HOST, SERVER_PORT);
  } else {
    http = new HttpClient(plainClient, SERVER_HOST, SERVER_PORT);
  }
}

bool connectWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }
  if (millis() - lastWifiTryMs < 15000 && lastWifiTryMs != 0) {
    return false;
  }
  lastWifiTryMs = millis();
  Serial.println("WIFI_CONNECTING");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  return false;
}

bool postCelsius(float celsius) {
  ensureHttpClient();
  String body = String("{\"celsius\":") + String(celsius, 2) +
                ",\"device_id\":\"" + DEVICE_ID + "\"}";

  http->beginRequest();
  http->post(INGEST_PATH);
  http->sendHeader("Content-Type", "application/json");
  http->sendHeader("Authorization", String("Bearer ") + PUSH_TOKEN);
  http->sendHeader("Content-Length", body.length());
  http->beginBody();
  http->print(body);
  http->endRequest();

  int status = http->responseStatusCode();
  String response = http->responseBody();
  Serial.print("HTTP ");
  Serial.print(status);
  Serial.print(" ");
  Serial.println(response);

  http->stop();
  return status >= 200 && status < 300;
}

void setup() {
  Serial.begin(9600);
  sensors.begin();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  lastWifiTryMs = millis();
  Serial.println("PUSH_SKETCH_BOOT");
  Serial.print("Target host: ");
  Serial.println(SERVER_HOST);
}

void loop() {
  if (!connectWifi()) {
    delay(500);
    return;
  }

  if (millis() - lastWifiTryMs > 0 && WiFi.status() == WL_CONNECTED) {
    static bool printed = false;
    if (!printed) {
      Serial.print("WIFI_OK ");
      Serial.println(WiFi.localIP());
      printed = true;
    }
  }

  if (millis() - lastPostMs < POST_EVERY_MS) {
    return;
  }
  lastPostMs = millis();

  sensors.requestTemperatures();
  float celsius = sensors.getTempCByIndex(0);
  if (celsius < -100.0) {
    Serial.println("SENSOR_FAIL");
    return;
  }

  Serial.print("TEMP ");
  Serial.println(celsius, 2);
  if (!postCelsius(celsius)) {
    Serial.println("POST_FAIL");
  } else {
    Serial.println("POST_OK");
  }
}
