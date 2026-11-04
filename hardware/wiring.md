# Wiring: first test (breadboard + jumper wires)

Everything sits on one breadboard with jumper wires. No soldering is needed beyond the header
pins that come with the modules.

## Parts

| Part | Notes |
|---|---|
| ESP32 dev board (ESP32-WROOM DevKit) | Choose "ESP32 Dev Module" in the Arduino IDE |
| MMA7361 accelerometer breakout | Analog X/Y/Z outputs |
| GY-MAX30102 pulse oximeter | I2C |
| 3.7 V LiPo, ~500 mAh, with protection circuit, JST-PH 2.0 | e.g. a "502535" or "503035" cell |
| TP4056 USB-C charger module **with protection** (6 pins: IN+, IN-, B+, B-, OUT+, OUT-) | Charges the LiPo |
| Small slide switch | Battery on/off (optional but strongly recommended) |
| Breadboard, jumper wires | |

## Pin table

| From | To ESP32 | Why this pin |
|---|---|---|
| MMA7361 **X** | GPIO 34 | ADC1 (ADC2 pins stop working when Wi-Fi is on) |
| MMA7361 **Y** | GPIO 35 | ADC1 |
| MMA7361 **Z** | GPIO 32 | ADC1 |
| MMA7361 **SL** (sleep) | GPIO 25 | Firmware drives it HIGH (awake). You can tie it to 3V3 instead. |
| MMA7361 **GS** (g-select) | GPIO 26 | Firmware drives it LOW = ±1.5 g (see `ACCEL_RANGE_6G` in `config.h`) |
| MMA7361 **3V3** (or VCC) | 3V3 | Power the sensor at 3.3 V so its outputs stay inside the ESP32 ADC range |
| MMA7361 **GND** | GND | |
| MMA7361 0G, ST | not connected | |
| MAX30102 **VIN** | 3V3 | |
| MAX30102 **SDA** | GPIO 21 | Default I2C pins |
| MAX30102 **SCL** | GPIO 22 | |
| MAX30102 **GND** | GND | |
| MAX30102 INT | not connected | |

```
                ┌──────────── ESP32 DevKit ────────────┐
   MMA7361      │                                      │     GY-MAX30102
   X  ──────────┤ GPIO34                        GPIO21 ├──────── SDA
   Y  ──────────┤ GPIO35                        GPIO22 ├──────── SCL
   Z  ──────────┤ GPIO32                           3V3 ├──┬───── VIN
   SL ──────────┤ GPIO25                           GND ├──┼──┬── GND
   GS ──────────┤ GPIO26                               │  │  │
   3V3 ─────────┤ 3V3 ─────────────────────────────────┼──┘  │
   GND ─────────┤ GND ─────────────────────────────────┼─────┘
                │                                      │
                │ 5V/VIN ◄── switch ◄── TP4056 OUT+    │   LiPo + ──► TP4056 B+
                │ GND    ◄────────────── TP4056 OUT-   │   LiPo - ──► TP4056 B-
                │ GPIO2 = on-board LED, GPIO0 = BOOT   │   charge through the TP4056's USB-C
                └──────────────────────────────────────┘
```

## Battery

1. LiPo red (+) → TP4056 **B+**, black (−) → **B−**. Check the polarity of the JST plug before
   connecting. Cheap cells and modules sometimes swap the colours.
2. TP4056 **OUT+** → slide switch → ESP32 **5V/VIN** pin. TP4056 **OUT−** → ESP32 **GND**.
3. Charge by plugging USB-C into the **TP4056**. The red LED means charging, blue/green means full.
4. **Turn the switch off while the ESP32's own USB cable is plugged in** (uploading code, USB serial).
   This keeps two power sources from fighting.

> **Heads-up on low battery:** the 5V/VIN pin feeds the board's 3.3 V regulator (usually an
> AMS1117), which needs about 1 V of headroom. A full LiPo (4.2 V) works fine. Once it drops
> below about 3.7 V, the ESP32 may reset during Wi-Fi bursts, so recharge then. If that becomes a
> problem, add a common **MT3608 boost module set to 5.0 V** between TP4056 OUT+ and the switch.

Battery voltage reporting is optional: add two 100 kΩ resistors as a divider from LiPo + to
GPIO 33 and GND, then set `PIN_BATTERY 33` in `config.h`.

## Wearing it

- The MAX30102's window must touch the skin on the **inside of the wrist**, held snug by the
  velcro band. Light leaking in or loose contact gives "no contact" or invalid readings.
- The accelerometer can sit at any angle: tilt exercises measure angle from wherever the start
  position is. Do keep it **firmly attached**, because a wobbling sensor adds false motion.
- The LED is on GPIO 2. Many "ESP32 DevKit V1" boards have a blue LED there, but some
  (e.g. DevKitC) have no user LED. In that case the dashboard is the only alert display.

## First power-up checklist

1. Open the Serial Monitor at **115200** baud with line ending "Newline". You should see a
   `{"type":"hello",...}` line.
2. If you see `MMA7361 not responding`, check X/Y/Z, 3V3, GND and SL. The error lists the
   millivolts it read. Each axis should be about 800-2500 mV.
3. If you see `MAX30102 not found`, check that SDA is on 21, SCL on 22, and VIN/GND are connected.
4. Lay the band flat, face up, and **hold BOOT for 2 s** to calibrate. Calibration is saved and
   only needs redoing if you change the range setting.
5. Type `{"cmd":"start","exercise":"bicep_curl","target":5}`, hold your arm still until you see
   `"ready"`, then do curls. Each rep prints a `"rep"` line.
