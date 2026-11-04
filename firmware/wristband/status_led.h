// On-board LED patterns (the only light on the materials list).
//   idle            : short blink every 3 s
//   waiting still   : solid on   ("hold your starting position")
//   exercising      : off, one quick flash per rep, three flashes when the target is reached
//   STOP alert      : fast flashing until cleared (heart rate too high / SpO2 too low)
#pragma once

#include <Arduino.h>

class StatusLed {
public:
    enum class Mode { Idle, WaitingStill, Active, Alert };

    void begin(int pin);
    void setMode(Mode m) { mode_ = m; }
    Mode mode() const { return mode_; }
    void flash(uint8_t times);  // overlay quick flashes on top of the current mode
    void update(uint32_t now);

private:
    int pin_ = -1;
    Mode mode_ = Mode::Idle;
    uint8_t flashesLeft_ = 0;
    bool flashOn_ = false;
    uint32_t flashChangeMs_ = 0;
};
