#include "status_led.h"

void StatusLed::begin(int pin) {
    pin_ = pin;
    if (pin_ >= 0) {
        pinMode(pin_, OUTPUT);
        digitalWrite(pin_, LOW);
    }
}

void StatusLed::flash(uint8_t times) {
    flashesLeft_ = times;
    flashOn_ = false;
    flashChangeMs_ = 0;
}

void StatusLed::update(uint32_t now) {
    if (pin_ < 0) return;
    bool on = false;

    if (mode_ == Mode::Alert) {
        on = (now / 100) % 2 == 0;  // 5 Hz flashing: hard to miss
    } else if (flashesLeft_ > 0) {
        if (now - flashChangeMs_ >= 120) {
            flashChangeMs_ = now;
            flashOn_ = !flashOn_;
            if (!flashOn_) flashesLeft_--;
        }
        on = flashOn_;
    } else {
        switch (mode_) {
            case Mode::Idle:         on = (now % 3000) < 60; break;
            case Mode::WaitingStill: on = true; break;
            case Mode::Active:       on = false; break;
            default: break;
        }
    }
    digitalWrite(pin_, on ? HIGH : LOW);
}
