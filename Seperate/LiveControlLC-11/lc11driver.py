import serial
import time


class LiveControlLC11:
    """
    Driver for the NewTek LiveControl LC-11 control surface.

    Protocol notes (reverse-engineered):
      - ASCII, \\r-delimited messages, 9600 8N1.
      - Wake-up sequence: 0x43 0x00 0x00 0x00
      - Joystick telemetry: "^5"/"^7" + position
      - Joystick button clicks: "^FE7" (J1), "^FF3" (J2), "^FF7" (release)
      - Dial telemetry: "~8","~9","~5","~6","~7" + position (dials 1-5)
      - Dial button clicks: "^2" + 2-hex bitmask
      - T-bar: "~4" + hex position (0-255)
      - Action row (TAKE/AUTO): "~3" + 2-hex code
      - Bus rows (EFFECTS/LIVE/PREVIEW): "~" + 4-hex word, row identified by
        the leading hex nibble (F=EFFECTS, 2=LIVE, 1=PREVIEW), button by a
        linear 12-bit inverted mask (0x0800=button1 ... 0x0002=button11).
        HARDWARE QUIRK: bus row frames are transmitted as TWO separate \\r
        terminated writes — "~FXX" then the final hex digit on its own line.
        poll_events() reassembles these before parsing.
    """

    BUS_ROW_BIT_TO_BUTTON = {
        0x0800: 1, 0x0400: 2, 0x0200: 3, 0x0100: 4,
        0x0080: 5, 0x0040: 6, 0x0020: 7, 0x0010: 8,
        0x0008: 9, 0x0004: 10, 0x0002: 11,
    }

    DIAL_CLICK_MAP = {"7F": 1, "BF": 2, "DF": 3, "EF": 4, "F7": 5}

    def __init__(self, port='COM5'):
        self.ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.01
        )
        self.buffer = ""

    def initialize_panel(self):
        """Sends the NewTek hardware wake-up signal."""
        self.ser.write(b'\x43\x00\x00\x00')
        time.sleep(0.1)
        self.ser.reset_input_buffer()

    def poll_events(self):
        """
        Reads raw bytes and splits on \\r, the frame delimiter for this protocol.

        Bus row frames ("~" + row nibble F/2/1 + 2 hex) are missing their final
        hex digit — it arrives as its own \\r-terminated line right after. We
        detect that short frame and stitch the next token onto it before parsing.
        """
        if self.ser.in_waiting > 0:
            self.buffer += self.ser.read(self.ser.in_waiting).decode('ascii', errors='ignore')

        while "\r" in self.buffer:
            idx = self.buffer.index("\r")
            message = self.buffer[:idx].strip()
            rest = self.buffer[idx + 1:]

            if not message:
                self.buffer = rest
                continue

            if len(message) == 4 and message[0] == '~' and message[1] in ('F', '2', '1'):
                if "\r" not in rest:
                    # Final digit hasn't arrived yet — wait for more bytes
                    break
                idx2 = rest.index("\r")
                extra = rest[:idx2].strip()
                self.buffer = rest[idx2 + 1:]
                message = message + extra
            else:
                self.buffer = rest

            event = self._parse_message(message)
            if event:
                yield event

    def _parse_message(self, message):
        """Decodes a single, delimiter-confirmed message into an event dict."""
        prefix = message[0]
        full_payload = message[1:]

        # --- JOYSTICK ABSOLUTE TELEMETRY ---
        if message.startswith("^5"):
            return {"type": "JOYSTICK_1", "value": message[2:]}
        elif message.startswith("^7"):
            return {"type": "JOYSTICK_2", "value": message[2:]}

        # --- JOYSTICK BUTTON CLICKS ---
        elif message.startswith("^FE7"):
            return {"type": "JOYSTICK_1_BUTTON", "state": "PRESSED"}
        elif message.startswith("^FF3"):
            return {"type": "JOYSTICK_2_BUTTON", "state": "PRESSED"}
        elif message.startswith("^FF7"):
            return {"type": "JOYSTICK_BUTTONS", "state": "RELEASED"}

        # --- ROTARY CONTINUOUS KNOBS ---
        elif message.startswith("~8"):
            return {"type": "DIAL_1", "value": message[2:]}
        elif message.startswith("~9"):
            return {"type": "DIAL_2", "value": message[2:]}
        elif message.startswith("~5"):
            return {"type": "DIAL_3", "value": message[2:]}
        elif message.startswith("~6"):
            return {"type": "DIAL_4", "value": message[2:]}
        elif message.startswith("~7"):
            return {"type": "DIAL_5", "value": message[2:]}

        # --- ROTARY DIAL CLICK EVENTS ---
        elif message.startswith("^2"):
            payload = message[2:]
            if payload == "FF":
                return {"type": "DIAL_BUTTONS", "state": "RELEASED"}
            if payload in self.DIAL_CLICK_MAP:
                return {"type": f"DIAL_{self.DIAL_CLICK_MAP[payload]}_BUTTON", "state": "PRESSED"}
            # Unrecognized dial bitmask — surfaced for future mapping, not silently dropped
            return {"type": "DIAL_BITMASK_UNKNOWN", "mask": payload}

        # --- T-BAR / TRANSITION CONTROLLER ---
        elif message.startswith("~4"):
            try:
                return {"type": "TBAR", "position": int(message[2:], 16)}
            except ValueError:
                return None

        # --- ACTION TRANSITIONS (TAKE / AUTO) ---
        elif message.startswith("~3"):
            payload = message[2:]
            if payload == "F7": return {"type": "ACTION_TAKE", "state": "PRESSED"}
            if payload == "FD": return {"type": "ACTION_AUTO", "state": "PRESSED"}
            if payload == "FF": return {"type": "ACTION_TRANSITIONS", "state": "RELEASED"}

        # --- BUS ROWS: EFFECTS / LIVE / PREVIEW ---
        elif prefix == "~":
            try:
                word_val = int(full_payload, 16)
            except ValueError:
                return None

            if full_payload in ("FFFF", "2FFF", "1FFF"):
                row_lbl = "EFFECTS" if full_payload == "FFFF" else ("LIVE" if full_payload == "2FFF" else "PREVIEW")
                return {"type": "BUS_ROW", "row": row_lbl, "state": "RELEASED"}

            row_name = None
            if full_payload.startswith("F"):   row_name = "EFFECTS"
            elif full_payload.startswith("2"): row_name = "LIVE"
            elif full_payload.startswith("1"): row_name = "PREVIEW"

            if row_name:
                inverted = (~word_val) & 0x0FFF
                button_num = self.BUS_ROW_BIT_TO_BUTTON.get(inverted)
                if button_num:
                    return {
                        "type": "BUS_ROW",
                        "row": row_name,
                        "button": button_num,
                        "state": "PRESSED"
                    }

        return {"type": "UNPARSED_DIAGNOSTIC", "raw": message}

    def close(self):
        self.ser.close()


if __name__ == "__main__":
    controller = LiveControlLC11()
    controller.initialize_panel()

    try:
        print("LC-11 Driver Online...")
        while True:
            for event in controller.poll_events():
                print(f"[EVENT LOG] {event}")
            time.sleep(0.005)
    except KeyboardInterrupt:
        print("\nClosing port connection.")
        controller.close()
