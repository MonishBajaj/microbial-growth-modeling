# Add an Arduino

The dashboard can read one DS18B20 temperature sensor on an Arduino UNO R4 WiFi. A board runs one sketch at a time. Pick the sketch for the path you want, paste it into the Arduino IDE, set the Wi-Fi and host lines, and upload it.

| Dashboard card | Sketch | When to use it |
|---|---|---|
| Arduino USB | `temperature_sensor.ino` | The board is plugged into the same computer that is running `python app.py`. |
| Arduino Wi-Fi | `temperature_sensor.ino` (same file) | The board and that computer are on the same Wi-Fi. No USB cable after upload. |
| Arduino Push | `temperature_push.ino` | The website is on another machine, a tunnel, or Render. The board opens the connection. |

USB and Wi-Fi are the same program. Push is a different program. Uploading one replaces the other.

The copies below use placeholders for the Wi-Fi name, the Wi-Fi password, and the server host. The files already in `arduino/` may still contain a lab network and a lab host. Replace those before you upload, and do not share a sketch that still has a real password in it.

## What to download

1. Arduino IDE 2 from [https://www.arduino.cc/en/software](https://www.arduino.cc/en/software). Install it and open it once.
2. In the IDE: Tools, Board, Boards Manager. Search for `Arduino UNO R4 Boards`. Install it. Then Tools, Board, and choose `Arduino UNO R4 WiFi`.
3. Tools, Manage Libraries. Install these by those exact names:

| Library | Needed by |
|---|---|
| OneWire | Both sketches. Talks to the DS18B20. |
| DallasTemperature | Both sketches. Turns the OneWire reading into Celsius. |
| ArduinoMDNS | USB/Wi-Fi sketch only. Announces the board on the network. |
| ArduinoHttpClient | Push sketch only. Sends the HTTP POST. |

`WiFiS3.h` and `WiFiSSLClient.h` come with the UNO R4 board package. Do not install a separate WiFi library for this board. If the IDE says those headers are missing, the selected board is not UNO R4 WiFi.

On the computer that runs the website, Python also needs the packages in `requirements.txt`. USB reading needs `pyserial`. Wi-Fi discovery needs `zeroconf`.

Push from another network needs the `cloudflared` program on that computer as well, if you use `scripts/start_push_tunnel.sh`. Install it from Cloudflare's cloudflared install page so the command `cloudflared` works in a terminal. A deployed site such as Render does not need cloudflared on the Arduino side. The board only needs to reach the public hostname.

## Wire the DS18B20

The sensor has three wires. The sketches read data on digital pin 2.

| DS18B20 pin | Usual wire color | Connect to |
|---|---|---|
| GND | black | GND on the UNO |
| VDD | red | 5V on the UNO |
| DQ (data) | yellow | digital pin 2 |

Add a 4.7 kΩ resistor between DQ and VDD (data and 5V). The chip uses that pull-up. Without it the sketch often prints `SENSOR_FAIL`.

```text
UNO 5V  ----+---- DS18B20 VDD (red)
            |
          4.7k
            |
UNO D2  ----+---- DS18B20 DQ (yellow)

UNO GND --------- DS18B20 GND (black)
```

Pin 2 here is the Arduino pin number `ONE_WIRE_PIN`. It is not a network port and not a USB port.

Use one sensor on pin 2. Both sketches call `getTempCByIndex(0)`, so they read the first sensor found on that pin.

## Which number is which port

People mix up four different "ports" in this project. Only one of them is the USB port you pick in the Arduino IDE.

| Name | Number or shape | What it is |
|---|---|---|
| Arduino data pin | `2` | The screw of the circuit. The yellow data wire. |
| USB serial port | `/dev/ttyACM0` on Linux, `COM3` on Windows, `/dev/cu.usbmodem...` on Mac | The cable, after the IDE or the dashboard opens it. The name changes when you replug the board. Speed is 9600 baud. Baud is not a port. |
| Wi-Fi listen port | `8080` | TCP port on the board. The USB/Wi-Fi sketch always listens here. The dashboard connects to it. Do not change it unless you change `WIFI_PORT` and `arduino_wifi.py` together. |
| Website port | `5000` | Flask, when you run `python app.py` on a laptop. The browser uses `http://127.0.0.1:5000`. A push board on the same LAN uses this port only if `SERVER_USE_TLS` is false. |
| HTTPS port | `443` | Used by the push sketch when the website is a Cloudflare tunnel or a host like Render. `SERVER_PORT` is 443 and `SERVER_USE_TLS` is true. |

The dashboard card Arduino USB lists USB serial ports from `GET /api/arduino/ports`. It shows USB devices (names containing `ttyACM`, `ttyUSB`, `usbmodem`, or `usbserial`, or any port that has a USB vendor id). Onboard Linux ports such as `ttyS0` are hidden. The website must be running on the machine that has the cable. A Render website cannot see the USB port on your laptop.

## Upload a sketch

1. Connect the UNO R4 WiFi with a USB data cable. A charge-only cable will not show a port.
2. Arduino IDE: Tools, Board, `Arduino UNO R4 WiFi`.
3. Tools, Port, and pick the new port. On Linux it is usually `/dev/ttyACM0`. On Windows it is the new `COM` number under Device Manager, Ports.
4. File, New. Delete the empty `setup` and `loop`. Paste one of the sketches below. File, Save.
5. Click Upload. Wait until the IDE says "Done uploading".
6. Tools, Serial Monitor. Set the baud menu at the bottom to `9600`. The monitor and the dashboard must not hold the port at the same time on the USB path. Close the monitor before you start an Arduino USB run.

If upload fails with "port busy", close the Serial Monitor and any dashboard run that is reading that port, then upload again. Opening the port resets the board. The Python USB collector waits 2 seconds after open for that reset.

## Sketch for Arduino USB and Arduino Wi-Fi

Paste this into the IDE. Change the two Wi-Fi lines. For a USB-only test you can leave the SSID as an empty string `""` and the board will only print temperatures on the cable.

```cpp
#include <OneWire.h>
#include <DallasTemperature.h>
#include <WiFiS3.h>
#include <ArduinoMDNS.h>

const char WIFI_SSID[] = "your-wifi-name";
const char WIFI_PASSWORD[] = "your-wifi-password";
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
    Serial.println("SENSOR_FAIL");
    return;
  }

  Serial.println(celsius, 2);

  if (client && client.connected()) {
    client.println(celsius, 2);
  }
}
```

The same file in the repo is `arduino/temperature_sensor/temperature_sensor.ino`.

What you should see in the Serial Monitor:

- A number such as `22.50` about once a second. That line is the whole USB protocol. A comma-separated line is allowed, and the dashboard keeps the first field. Values outside -40 C to 125 C are ignored.
- `SENSOR_FAIL` means the DS18B20 was not read. Check pin 2, ground, 5V, and the 4.7 kΩ resistor.
- `WIFI_OK temp-XXXX` and an IP address mean the board joined Wi-Fi and is listening on port 8080. The name is `temp-` plus the last two bytes of the MAC address, so two boards do not share one name.
- `WIFI_RETRY` means the password or the SSID is wrong, or the board is out of range. The UNO R4 WiFi radio is 2.4 GHz only. A 5 GHz-only network will not connect.

### Use it from the dashboard

Start the website on the computer that should read the board:

```bash
python app.py
```

Open `http://127.0.0.1:5000`, sign in, and pick a Ready model.

Arduino USB: choose that card, pick the serial port in the dropdown, then Quick connection test. Close the Serial Monitor first. A good test reports readings and an average temperature. It does not run the growth model. Short analysis collects about 6 minutes. Full analysis collects about 8 hours.

Arduino Wi-Fi: the board and the computer running Flask must be on the same network. Choose Arduino Wi-Fi. The page calls `GET /api/arduino/wifi` and lists boards that advertise `_microbial._tcp`. If the list stays empty, type the IP address printed next to `WIFI_OK` into Address and click Check. The Python default name `arduino-temp.local` is only a fallback. The sketch does not register that name.

The dashboard connects to `host:8080`, reads one Celsius line, and closes that sample into the same series the growth model uses.

## Sketch for Arduino Push

Use this when the website is not on the board's LAN. The board POSTs to the server. The server never connects back to the board.

First get a public base URL.

On the lab computer, from the `microbial_growth_modeling` directory:

```bash
./scripts/start_push_tunnel.sh
```

The script starts Flask on port 5000, starts a Cloudflare quick tunnel, and writes the `https://something.trycloudflare.com` origin into `public_base_url.txt`. It also prints the ingest URL: that origin plus `/api/arduino/ingest`.

That hostname changes every time you run the script. For a stable host, deploy the Flask app and set `PUBLIC_BASE_URL` to that origin (for example `https://your-app.onrender.com`).

On the dashboard, open the Arduino Push card. The Ingest URL and Bearer token fields are filled from `GET /api/arduino/push_status`. Copy the host only, with no `https://` and no path.

| Sketch constant | What to put |
|---|---|
| `WIFI_SSID` / `WIFI_PASSWORD` | The 2.4 GHz network the board can join. |
| `SERVER_HOST` | Host from the ingest URL. Example: `something.trycloudflare.com` or `your-app.onrender.com`. |
| `SERVER_PORT` | `443` for a tunnel or Render. `5000` only for plain `http://` to a LAN IP. |
| `SERVER_USE_TLS` | `true` with port 443. `false` with port 5000. |
| `PUSH_TOKEN` | The token shown on the Arduino Push card. Default is `microbial-lab-token` unless the server was started with `ARDUINO_PUSH_TOKEN`. |
| `DEVICE_ID` | Any short name, such as `uno-r4-1`. The dashboard can filter on it. Leave the filter blank to accept every device. |
| `INGEST_PATH` | Leave `/api/arduino/ingest`. |

```cpp
#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <ArduinoHttpClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>

const char WIFI_SSID[] = "your-wifi-name";
const char WIFI_PASSWORD[] = "your-wifi-password";

const char SERVER_HOST[] = "your-host.example.com";
const int SERVER_PORT = 443;
const bool SERVER_USE_TLS = true;
const char INGEST_PATH[] = "/api/arduino/ingest";
const char PUSH_TOKEN[] = "microbial-lab-token";
const char DEVICE_ID[] = "uno-r4-1";

const int ONE_WIRE_PIN = 2;
const unsigned long POST_EVERY_MS = 3000;

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
```

The same file in the repo is `arduino/temperature_push/temperature_push.ino`.

Upload it the same way as the other sketch. Serial Monitor at 9600 should show:

- `PUSH_SKETCH_BOOT` and `Target host: ...`
- `WIFI_OK` and the board's IP
- `TEMP 22.50`
- `HTTP 200` and `POST_OK`

`HTTP 401` means `PUSH_TOKEN` does not match the server token. `POST_FAIL` or a connection error means `SERVER_HOST` is wrong, the tunnel has stopped, or TLS and port do not match (443 with TLS, or 5000 without). `SENSOR_FAIL` is the wiring, same as the other sketch.

Then on the dashboard choose Arduino Push, click Refresh, and confirm a device and an age in seconds. Quick connection test reads the buffer for about 30 seconds. The board has to be posting during that window. Readings live in memory on the Flask process. Restarting the server clears them.

Celsius in the JSON must be between -40 and 125 or the server rejects the POST.
