// Messages to/from the laptop: newline-delimited JSON over USB serial, Bluetooth SPP and (optionally) Wi-Fi UDP.
// Commands are accepted from each transport. See docs/protocol.md.
#pragma once

#include <Arduino.h>
#include <BluetoothSerial.h>

class BandLink {
public:
    void begin();

    // Call every loop: keeps Wi-Fi connected
    void maintain();

    // Send one JSON object (without trailing newline)
    void send(const char* json);
    void sendBluetooth(const char* json);

    // printf-style helper; message must be a complete JSON object
    void sendf(const char* fmt, ...) __attribute__((format(printf, 2, 3)));
    void sendBluetoothf(const char* fmt, ...) __attribute__((format(printf, 2, 3)));

    // Returns true and fills `out` when a full command line has arrived
    bool poll(char* out, size_t outSize);

    bool wifiConnected() const;
    bool bluetoothConnected();
    const char* deviceId() const { return deviceId_; }

private:
    char serialBuf_[256];
    size_t serialLen_ = 0;
    char bluetoothBuf_[256];
    size_t bluetoothLen_ = 0;
    char deviceId_[20] = "wristband";
    BluetoothSerial bluetooth_;
    bool bluetoothStarted_ = false;
    uint32_t lastWifiAttemptMs_ = 0;
    bool udpStarted_ = false;
};
