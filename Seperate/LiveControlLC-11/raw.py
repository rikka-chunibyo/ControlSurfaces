import serial
import time

ser = serial.Serial(
    port='COM5',
    baudrate=9600,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=0.01
)

ser.write(b'\x43\x00\x00\x00')
time.sleep(0.1)
ser.reset_input_buffer()

print("Raw capture running. Press buttons, then Ctrl+C to stop.")

try:
    while True:
        if ser.in_waiting > 0:
            raw = ser.read(ser.in_waiting)
            # Show both the exact bytes (hex) and the ascii repr side by side
            print(f"HEX: {raw.hex(' ')}")
            print(f"REPR: {raw!r}")
            print("-" * 40)
        time.sleep(0.01)
except KeyboardInterrupt:
    ser.close()
