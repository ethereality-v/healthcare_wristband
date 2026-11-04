// Messages to/from the laptop: newline-delimited JSON over USB serial and (optionally) Wi-Fi UDP.
// Every message goes out on both; commands are accepted from either. See docs/protocol.md.
#pragma once

#include <Arduino.h>

class BandLink {
public:
    void begin();

    // Call every loop: keeps Wi-Fi connected
    void maintain();

    // Send one JSON object (without trailing newline)
    void send(const char* json);

    // printf-style helper; message must be a complete JSON object
    void sendf(const char* fmt, ...) __attribute__((format(printf, 2, 3)));

    // Returns true and fills `out` when a full command line has arrived
    bool poll(char* out, size_t outSize);

    bool wifiConnected() const;
    const char* deviceId() const { return deviceId_; }

private:
    char serialBuf_[256];
    size_t serialLen_ = 0;
    char deviceId_[20] = "wristband";
    uint32_t lastWifiAttemptMs_ = 0;
    bool udpStarted_ = false;
};
