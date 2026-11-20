#include "band_link.h"

#include <WiFi.h>
#include <WiFiUdp.h>
#include <stdarg.h>

#include "config.h"

static WiFiUDP udp;

static bool pollLine(Stream& stream, char* buffer, size_t& length, char* out, size_t outSize) {
    while (stream.available()) {
        const char c = (char)stream.read();
        if (c == '\r') continue;
        if (c == '\n') {
            if (length == 0) continue;
            buffer[length] = '\0';
            strncpy(out, buffer, outSize - 1);
            out[outSize - 1] = '\0';
            length = 0;
            return true;
        }
        if (length < 255) buffer[length++] = c;
        else length = 0;
    }
    return false;
}

void BandLink::begin() {
    Serial.begin(SERIAL_BAUD);

    // Unique name from the chip's MAC address, e.g. "wristband-3A7F"
    uint64_t mac = ESP.getEfuseMac();
    snprintf(deviceId_, sizeof(deviceId_), "wristband-%04X", (unsigned)((mac >> 32) & 0xFFFF));

    bluetoothStarted_ = bluetooth_.begin(deviceId_);
    if (!bluetoothStarted_) {
        Serial.println("{\"type\":\"error\",\"msg\":\"Bluetooth SPP failed to start\"}");
    }

#if WIFI_ENABLED
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);  // lower latency; the battery still lasts a session
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    lastWifiAttemptMs_ = millis();
#endif
}

bool BandLink::bluetoothConnected() {
    return bluetoothStarted_ && bluetooth_.hasClient();
}

bool BandLink::wifiConnected() const {
#if WIFI_ENABLED
    return WiFi.status() == WL_CONNECTED;
#else
    return false;
#endif
}

void BandLink::maintain() {
#if WIFI_ENABLED
    if (WiFi.status() == WL_CONNECTED) {
        if (!udpStarted_) {
            udp.begin(BAND_PORT);
            udpStarted_ = true;
            sendf("{\"type\":\"log\",\"msg\":\"wifi connected\",\"ip\":\"%s\"}", WiFi.localIP().toString().c_str());
        }
    } else {
        udpStarted_ = false;
        if (millis() - lastWifiAttemptMs_ > 10000) {  // retry every 10 s without blocking
            WiFi.disconnect();
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
            lastWifiAttemptMs_ = millis();
        }
    }
#endif
}

void BandLink::send(const char* json) {
    Serial.println(json);
    sendBluetooth(json);
#if WIFI_ENABLED
    if (udpStarted_) {
        udp.beginPacket(HOST_IP, HOST_PORT);
        udp.write((const uint8_t*)json, strlen(json));
        udp.write((const uint8_t*)"\n", 1);
        udp.endPacket();
    }
#endif
}

void BandLink::sendBluetooth(const char* json) {
    if (bluetoothConnected()) bluetooth_.println(json);
}

void BandLink::sendf(const char* fmt, ...) {
    char buf[512];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    send(buf);
}

void BandLink::sendBluetoothf(const char* fmt, ...) {
    char buf[512];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    sendBluetooth(buf);
}

bool BandLink::poll(char* out, size_t outSize) {
    if (outSize == 0) return false;
    if (pollLine(Serial, serialBuf_, serialLen_, out, outSize)) return true;
    if (bluetoothStarted_ && pollLine(bluetooth_, bluetoothBuf_, bluetoothLen_, out, outSize)) return true;
#if WIFI_ENABLED
    if (udpStarted_) {
        const int size = udp.parsePacket();
        if (size > 0) {
            const int n = udp.read(out, outSize - 1);
            if (n > 0) {
                out[n] = '\0';
                char* nl = strchr(out, '\n');
                if (nl) *nl = '\0';
                return out[0] != '\0';
            }
        }
    }
#endif
    return false;
}
