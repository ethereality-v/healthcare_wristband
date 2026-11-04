// Copy this file to secrets.h (same folder) and fill it in to use Wi-Fi.
// secrets.h is listed in .gitignore, so your password stays on your computer.
#pragma once

#define WIFI_ENABLED  1
#define WIFI_SSID     "your-network-name"
#define WIFI_PASSWORD "your-password"

// IP address of the laptop running `python -m wristband run --udp`
// (Windows: run `ipconfig` and use the IPv4 address of your Wi-Fi adapter)
#define HOST_IP       "192.168.1.100"
#define HOST_PORT     5005
#define BAND_PORT     5006
