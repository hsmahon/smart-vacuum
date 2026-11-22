#!/usr/bin/env python3
"""Control the linked Tikom G8000 Max using Tuya's Western America API."""
import argparse
import json
from pathlib import Path
import time

from tuya_cloud import ENDPOINTS, request

CONFIG = Path.home() / ".config/smart-vacuum/cloud.json"


class Vacuum:
    def __init__(self):
        credentials = json.loads(CONFIG.read_text())
        self.base = ENDPOINTS[credentials.get("region", "western-america")]
        self.access = credentials["access"]
        self.secret = credentials["secret"]
        self.token = ""
        self.token = self.request("/v1.0/token?grant_type=1")["access_token"]
        self.prefix = "/v1.0/iot-03/devices/" + credentials["device_id"]

    def request(self, path, payload=None):
        return request(self.base, self.access, self.secret, path, payload, self.token)

    def status(self):
        return {dp["code"]: dp["value"] for dp in self.request(self.prefix + "/status")}

    def command(self, action):
        code, value = ("power_go", True) if action == "start" else ("mode", "chargego")
        ok = self.request(self.prefix + "/commands", {"commands": [{"code": code, "value": value}]})
        if ok is not True:
            raise RuntimeError("Tuya did not acknowledge command")
        wanted = {"smart_clean", "cleaning", "wall_clean", "spot_clean"} if action == "start" else {
            "goto_charge", "charging", "charge_done"
        }
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            state = self.status()
            if state.get("status") in wanted:
                return state
            time.sleep(1)
        raise RuntimeError("Command acknowledged, expected state not observed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "home", "status"))
    args = parser.parse_args()
    robot = Vacuum()
    print(json.dumps(robot.status() if args.action == "status" else robot.command(args.action)))
