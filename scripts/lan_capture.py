"""Capture authenticated incoming Tuya LAN 3.4 application frames from the linked vacuum."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import tinytuya
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from vacuumctl import Vacuum


class Recorder(tinytuya.Device):
    def _receive(self):
        msg = super()._receive()
        # Commands 3-5 establish the session key. They carry no telemetry.
        if msg.cmd in (3, 4, 5):
            return msg
        if not msg.crc_good:
            raise ValueError("Invalid LAN message authentication")
        payload = msg.payload
        if payload:
            payload = unpad(AES.new(self.local_key, AES.MODE_ECB).decrypt(payload), 16)
        row = {"received_at": datetime.now(timezone.utc).isoformat(), "command": msg.cmd,
               "sequence": msg.seqno, "return_code": msg.retcode, "payload_hex": payload.hex()}
        self.output.write(json.dumps(row) + "\n")
        return msg


def local_credentials(key_file):
    if key_file and key_file.exists():
        saved = json.loads(key_file.read_text())
        return saved["device_id"], saved["local_key"]
    robot = Vacuum()
    device_id = robot.prefix.rsplit("/", 1)[1]
    key = robot.request("/v1.0/devices/" + device_id)["local_key"]
    if key_file:
        with key_file.open("x") as out:
            json.dump({"device_id": device_id, "local_key": key}, out)
    return device_id, key


def capture(address, duration, output, key_file):
    device_id, key = local_credentials(key_file)
    device = Recorder(device_id, address, key, version=3.4, persist=True,
                      connection_timeout=1, connection_retry_limit=1)
    with output.open("x", buffering=1) as stream:
        device.output = stream
        try:
            first = device.status()
            if not first or "dps" not in first:
                raise RuntimeError("Authenticated LAN status unavailable")
            print("LAN authenticated; capturing", flush=True)
            end = time.monotonic() + duration
            next_poll = time.monotonic() + 3
            while time.monotonic() < end:
                if time.monotonic() >= next_poll:
                    result = device.status()
                    if not result or "Error" in result:
                        raise RuntimeError("LAN status poll failed")
                    next_poll += 3
                else:
                    result = device.receive()
                    if isinstance(result, dict) and "Error" in result:
                        raise RuntimeError("LAN receive failed: " + str(result.get("Err")))
        finally:
            device.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new JSONL file")
    parser.add_argument("--address", required=True)
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--key-file", type=Path,
                        help="reuse a private local credential file; create from linked account on first use")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    os.umask(0o077)
    capture(args.address, args.seconds, args.output, args.key_file)
