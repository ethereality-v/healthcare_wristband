
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

Adafruit_MPU6050 mpu;

void setup() {

    Serial.begin(115200);

    // Initialize I2C
    Wire.begin(21, 22);

    // Initialize MPU6050
    if (!mpu.begin()) {

        Serial.println("MPU6050 not detected!");

        while (1) {
            delay(10);
        }
    }

    Serial.println("Health Band Started!");

    // Configure accelerometer
    mpu.setAccelerometerRange(
        MPU6050_RANGE_4_G
    );

    // Configure gyroscope
    mpu.setGyroRange(
        MPU6050_RANGE_500_DEG
    );

    // Configure sampling filter
    mpu.setFilterBandwidth(
        MPU6050_BAND_21_HZ
    );
}

void loop() {

    sensors_event_t a, g, temp;

    mpu.getEvent(&a, &g, &temp);

    Serial.print("Acceleration X: ");
    Serial.print(a.acceleration.x);

    Serial.print(" | Y: ");
    Serial.print(a.acceleration.y);

    Serial.print(" | Z: ");
    Serial.println(a.acceleration.z);

    delay(100);
}
