"""Record status changes pushed by the linked robot. Run until interrupted."""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import paho.mqtt.client as mqtt

from vacuumctl import Vacuum


def listen(out, on_ready=None):
    robot = Vacuum()
    device_id = robot.prefix.rsplit("/", 1)[1]
    owner = robot.request("/v1.0/devices/" + device_id)["uid"]
    config = robot.request("/v1.0/open-hub/access/config", {
        "uid": owner, "link_id": str(uuid.uuid4()), "link_type": "mqtt",
        "topics": "device", "msg_encrypted_version": "1.0",
    })
    url = urlsplit(config["url"])
    if url.scheme != "ssl":
        raise ValueError("Expected TLS MQTT endpoint")
    client = mqtt.Client(client_id=config["client_id"])
    client.username_pw_set(config["username"], config["password"])
    client.tls_set()
    key = config["password"][8:24].encode()

    def connected(client, userdata, flags, rc):
        if rc:
            raise ConnectionError(f"MQTT connection refused ({rc})")
        for topic in config["source_topic"].values():
            client.subscribe(topic)

    def received(client, userdata, msg):
        envelope = json.loads(msg.payload)
        cipher = AES.new(key, AES.MODE_ECB)
        raw = unpad(cipher.decrypt(base64.b64decode(envelope["data"])), 16)
        data = json.loads(raw)
        if data.get("devId") == device_id:
            record = {"received_at": datetime.now(timezone.utc).isoformat(),
                      "broker_time": envelope.get("t"), "protocol": envelope.get("protocol"),
                      "data": data}
            out.write(json.dumps(record) + "\n")

    def subscribed(client, userdata, mid, granted_qos):
        if on_ready and granted_qos and all(qos < 128 for qos in granted_qos):
            on_ready()

    client.on_subscribe = subscribed
    client.on_connect = connected
    client.on_message = received
    client.connect(url.hostname, url.port)
    expires = time.monotonic() + max(1, int(config["expire_time"]) - 60)
    try:
        while time.monotonic() < expires:
            if client.loop(timeout=1) != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError("MQTT session disconnected")
    finally:
        client.disconnect()


if __name__ == "__main__":
    os.umask(0o077)
    with (Path(__file__).resolve().parents[1] / "movement-events.jsonl").open("a", buffering=1) as out:
        while True:
            listen(out)
