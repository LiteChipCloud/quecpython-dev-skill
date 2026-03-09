import utime
import checkNet


def wait_network_ready(timeout_s):
    net = checkNet.CheckNetwork("QuecPython", "1.0")
    stagecode, subcode = net.wait_network_connected(timeout_s)
    if stagecode == 3 and subcode == 1:
        print("[NET] ready")
        return True
    print("[NET] not ready, stage=%s sub=%s" % (stagecode, subcode))
    return False


def main():
    if not wait_network_ready(60):
        return
    while True:
        utime.sleep(5)
        print("[NET] heartbeat")


if __name__ == "__main__":
    main()
