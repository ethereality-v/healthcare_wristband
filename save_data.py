
import serial
import json
import os
from datetime import datetime

# ESP32 connection settings
SERIAL_PORT = "COM3"       # Change to your ESP32 port
BAUD_RATE = 115200

# JSON database
DATABASE_FILE = "health_data.json"


def load_database():
    """Load existing data or create a new database."""

    if os.path.exists(DATABASE_FILE):
        with open(DATABASE_FILE, "r") as file:
            return json.load(file)

    return {
        "readings": []
    }


def save_reading(sensor_data):
    """Add a sensor reading to the JSON database."""

    database = load_database()

    reading = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "heart_rate": sensor_data.get("heart_rate"),
        "spo2": sensor_data.get("spo2"),
        "reps": sensor_data.get("reps")
    }

    database["readings"].append(reading)

    with open(DATABASE_FILE, "w") as file:
        json.dump(database, file, indent=4)

    print("Data saved:", reading)


def main():

    database = load_database()

    print("Connecting to ESP32...")

    try:
        esp32 = serial.Serial(
            SERIAL_PORT,
            BAUD_RATE,
            timeout=2
        )

        print("Connected! Receiving sensor data...")
        print("Press Ctrl+C to stop.\n")

        while True:

            # Read data sent by ESP32
            line = esp32.readline().decode(
                "utf-8", errors="ignore"
            ).strip()

            if not line:
                continue

            try:
                # Convert JSON text into Python dictionary
                sensor_data = json.loads(line)

                # Save the reading
                save_reading(sensor_data)

            except json.JSONDecodeError:
                print("Invalid data received:", line)

    except serial.SerialException as error:
        print("Serial connection error:", error)

    except KeyboardInterrupt:
        print("\nData collection stopped.")

    finally:
        if "esp32" in locals() and esp32.is_open:
            esp32.close()


if __name__ == "__main__":
    main()
