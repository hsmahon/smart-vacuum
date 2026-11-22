"""Subscribe to the device-specific Tuya gyro map topic with linked-project credentials."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
import uuid

import paho.mqtt.client as mqtt

from vacuumctl import Vacuum


def capture(seconds, output):
    robot = Vacuum()
    dev = robot.prefix.rsplit("/", 1)[1]
    owner = robot.request("/v1.0/devices/" + dev)["uid"]
    config = robot.request("/v1.0/open-hub/access/config", {
        "uid": owner, "link_id": str(uuid.uuid4()), "link_type": "mqtt",
        "topics": "device", "msg_encrypted_version": "1.0",
    })
    endpoint = urlsplit(config["url"])
    if endpoint.scheme != "ssl":
        raise ValueError("TLS MQTT endpoint required")
    topic = "m/m/i/" + dev
    client = mqtt.Client(client_id=config["client_id"])
    client.username_pw_set(config["username"], config["password"])
    client.tls_set()
    acknowledged = False
    count = 0

    def connected(client, userdata, flags, rc):
        if rc:
            raise ConnectionError(f"Broker refused login ({rc})")
        print("Authenticated; requesting the gyro map topic", flush=True)
        result, _ = client.subscribe(topic)
        if result != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"Subscribe failed ({result})")

    def subscribed(client, userdata, mid, qos):
        nonlocal acknowledged
        if not qos or 128 in qos:
            raise PermissionError("Broker denied the gyro map subscription (SUBACK)")
        acknowledged = True
        print("Broker acknowledged subscription; waiting for payload", flush=True)

    def received(client, userdata, msg):
        nonlocal count
        if msg.topic == topic:
            output.write(json.dumps({
                "received_at": datetime.now(timezone.utc).isoformat(),
                "payload_hex": msg.payload.hex(),
            }) + "\n")
            count += 1

    client.on_connect = connected
    client.on_subscribe = subscribed
    client.on_message = received
    client.connect(endpoint.hostname, endpoint.port)
    try:
        start = time.monotonic()
        while time.monotonic() - start < seconds:
            rc = client.loop(timeout=1)
            if rc != mqtt.MQTT_ERR_SUCCESS:
                raise ConnectionError(f"Broker disconnected ({rc}); subscription acknowledged={acknowledged}")
            if not acknowledged and time.monotonic() - start >= 10:
                raise TimeoutError("No subscription acknowledgement")
    finally:
        client.disconnect()
    print(f"Gyro-topic MQTT payloads captured: {count}")
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("output", type=Path, nargs="?", help="new raw MQTT capture; defaults to gyro-captures/")
    parser.add_argument("--database", type=Path, default=root / "telemetry.duckdb",
                        help="DuckDB destination for completed capture")
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    if args.seconds < 10:
        parser.error("allow at least 10 seconds for subscription acknowledgement")
    os.umask(0o077)
    if args.output is None:
        directory = root / "gyro-captures"
        directory.mkdir(exist_ok=True)
        args.output = directory / datetime.now(timezone.utc).strftime("gyro-%Y%m%dT%H%M%S%fZ.jsonl")
    print(f"Recording to {args.output}", flush=True)
    with args.output.open("x", buffering=1) as out:
        try:
            count = capture(args.seconds, out)
        except KeyboardInterrupt:
            count = None
        except (OSError, RuntimeError, ValueError) as exc:
            parser.exit(1, f"{exc}. Raw capture: {args.output}\n")
    if args.output.stat().st_size:
        import duckdb
        from route_db import sync_routes
        sync_routes(args.database, args.output, 0, duckdb.connect)
        with duckdb.connect(str(args.database), read_only=True) as db:
            total, positions, errors = db.execute("""
                SELECT count(DISTINCT r.packet_id),
                       count(*) FILTER (WHERE p.point_type = 0),
                       count(DISTINCT r.packet_id) FILTER (WHERE decode_error IS NOT NULL)
                FROM route_packets r LEFT JOIN route_points p USING (packet_id)
                WHERE r.capture_name = ?
            """, [args.output.name]).fetchone()
        print(f"DuckDB: {total} map records, {positions} robot positions, {errors} decode errors")
        raise SystemExit(0 if positions and not errors else 2)
    raise SystemExit(2)
