import utime
from machine import UART


class UartModbusClient(object):
    def __init__(self, uart_id=UART.UART2, baudrate=9600):
        self.uart = UART(uart_id, baudrate, 8, 0, 1, 0)

    def close(self):
        try:
            self.uart.close()
        except Exception:
            pass

    def read_frame(self, timeout_ms=800):
        start = utime.ticks_ms()
        buf = b""
        while utime.ticks_diff(utime.ticks_ms(), start) < timeout_ms:
            n = self.uart.any()
            if n > 0:
                data = self.uart.read(n)
                if data:
                    buf += data
                    # Replace with protocol-specific frame length/checksum logic.
                    if len(buf) >= 7:
                        return buf
            utime.sleep_ms(20)
        return None

    def write_frame(self, frame_bytes):
        try:
            return self.uart.write(frame_bytes)
        except Exception as e:
            print("[UART] write error: %s" % e)
            return 0


def main():
    client = UartModbusClient(uart_id=UART.UART2, baudrate=9600)
    try:
        # Example frame only, replace with your real modbus payload.
        req = b"\x01\x03\x00\x00\x00\x02\xc4\x0b"
        client.write_frame(req)
        resp = client.read_frame(1000)
        if resp is None:
            print("[MODBUS] timeout")
        else:
            print("[MODBUS] resp len=%d" % len(resp))
    finally:
        client.close()


if __name__ == "__main__":
    main()
