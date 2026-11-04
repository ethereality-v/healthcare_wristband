// Wristband configuration: pins, sensor settings and Wi-Fi.
// Wiring diagram and pin table: hardware/wiring.md
#pragma once

#define FIRMWARE_VERSION "1.0.0"

// ---------- MMA7361 accelerometer (analog) ----------
// X/Y/Z must be on ADC1 pins (GPIO 32-39): ADC2 stops working when Wi-Fi is on.
#define PIN_ACCEL_X      34
#define PIN_ACCEL_Y      35
#define PIN_ACCEL_Z      32
#define PIN_ACCEL_SLEEP  25   // SL: HIGH = awake (or tie to 3.3V)
#define PIN_ACCEL_GSEL   26   // GS: LOW = +/-1.5 g, HIGH = +/-6 g

// false: +/-1.5 g, 800 mV/g -> ~4x finer resolution, best for slow rehab movements (default)
// true : +/-6 g,   206 mV/g -> use if fast exercises (e.g. hard kettlebell swings) clip
#define ACCEL_RANGE_6G   false

// ---------- MAX30102 pulse oximeter (I2C) ----------
#define PIN_I2C_SDA      21
#define PIN_I2C_SCL      22
#define PULSE_LED_BRIGHTNESS 60      // 0-255; raise if readings are invalid through skin
#define PULSE_CONTACT_IR     30000   // IR level below this = sensor not touching skin

// ---------- On-board LED and BOOT button ----------
#define PIN_LED          2    // on-board blue LED on most ESP32 DevKit boards
#define PIN_BUTTON       0    // BOOT button: hold 2 s with the band flat to calibrate

// ---------- Battery (optional) ----------
// The 3.7 V LiPo can reach 4.2 V, which is too high for an ESP32 pin. To report battery level,
// add a 100k/100k divider from battery + to GPIO 33 and set PIN_BATTERY to 33.
#define PIN_BATTERY      -1
#define BATTERY_DIVIDER  2.0f

// ---------- Timing ----------
#define SERIAL_BAUD          115200
#define SAMPLE_INTERVAL_MS   20     // 50 Hz accelerometer sampling
#define STATUS_INTERVAL_MS   500    // status message rate
#define ACCEL_OVERSAMPLE     8      // ADC readings averaged per axis

// ---------- Wi-Fi (optional) ----------
// Copy secrets.example.h to secrets.h and fill in your network and laptop IP.
// secrets.h is git-ignored so passwords never get committed.
#if defined(__has_include)
#if __has_include("secrets.h")
#include "secrets.h"
#endif
#endif

#ifndef WIFI_ENABLED
#define WIFI_ENABLED 0
#endif
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif
#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif
#ifndef HOST_IP
#define HOST_IP "192.168.1.100"   // laptop running the Python app
#endif
#ifndef HOST_PORT
#define HOST_PORT 5005            // laptop listens here (UDP)
#endif
#ifndef BAND_PORT
#define BAND_PORT 5006            // band listens for commands here (UDP)
#endif
