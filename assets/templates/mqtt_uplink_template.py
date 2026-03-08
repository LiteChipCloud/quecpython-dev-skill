import utime
import ujson
from umqtt import MQTTClient


class MqttUplink(object):
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = None
        self.connected = False
        self.retries = 0

    def connect(self):
        try:
            self.client = MQTTClient(
                self.cfg["client_id"],
                self.cfg["server"],
                self.cfg["port"],
                self.cfg.get("user"),
                self.cfg.get("password"),
                self.cfg.get("keepalive", 60),
            )
            self.client.connect()
            self.connected = True
            self.retries = 0
            print("[MQTT] connected")
            return True
        except Exception as e:
            self.connected = False
            print("[MQTT] connect error: %s" % e)
            return False

    def publish_json(self, topic, payload):
        if not self.connected:
            return False
        try:
            data = ujson.dumps(payload)
            self.client.publish(topic, data)
            return True
        except Exception as e:
            print("[MQTT] publish error: %s" % e)
            self.connected = False
            return False

    def loop(self):
        backoff_s = 3
        while True:
            if not self.connected:
                ok = self.connect()
                if not ok:
                    self.retries += 1
                    utime.sleep(backoff_s)
                    if backoff_s < 30:
                        backoff_s += 3
                    continue
                backoff_s = 3

            payload = {
                "ts": utime.time(),
                "status": "ok",
            }
            if not self.publish_json(self.cfg["topic_up"], payload):
                utime.sleep(2)
                continue

            utime.sleep(self.cfg.get("report_interval_s", 10))


def main():
    cfg = {
        "server": "mqtt.example.com",
        "port": 1883,
        "client_id": "device_001",
        "topic_up": "device/001/up",
        "report_interval_s": 10,
    }
    app = MqttUplink(cfg)
    app.loop()


if __name__ == "__main__":
    main()
