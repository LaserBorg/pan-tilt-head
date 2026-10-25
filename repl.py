"""Interactive CircuitPython REPL bridge over a serial port.

Usage:  python cp_repl.py [COM4] [115200]

Type Python at the prompt and press Enter.  Lines are sent to the board.
Serial output is echoed back as it arrives.
Ctrl-]  or  :quit   exits the bridge WITHOUT resetting the board.
:reset  sends Ctrl-D (soft reload).
:break  sends Ctrl-C twice (interrupt running code).
"""
import sys, threading, time
import serial

port = sys.argv[1] if len(sys.argv) > 1 else "COM4"
baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

ser = serial.Serial(port, baud, timeout=0.05)
time.sleep(0.2)
ser.reset_input_buffer()


def reader():
    while True:
        try:
            data = ser.read(4096)
        except Exception:
            return
        if data:
            sys.stdout.write(data.decode("utf-8", "replace"))
            sys.stdout.flush()


threading.Thread(target=reader, daemon=True).start()

# Interrupt whatever is running and land on a fresh prompt
ser.write(b"\x03\x03\r\n")
time.sleep(0.6)

try:
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        cmd = line.rstrip("\r\n")
        if cmd in (":quit", ":q"):
            break
        if cmd == ":reset":
            ser.write(b"\x04")
        elif cmd == ":break":
            ser.write(b"\x03\x03")
        elif cmd == ":help":
            print("  :reset  soft reload (Ctrl-D)   :break  interrupt (Ctrl-C)")
            print("  :quit   close bridge            (any other line goes to the board)")
        else:
            ser.write(cmd.encode("utf-8") + b"\r\n")
        time.sleep(0.15)
finally:
    ser.close()
    print("\n[bridge closed - board left running]")