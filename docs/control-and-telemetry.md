# Control and LAN telemetry

## Onboarding and cloud control

Pair the G8000 Max over 2.4 GHz Wi-Fi using Tuya Smart, then link the app account to a Tuya Smart Home cloud project. Bluetooth discovery and the setup hotspot were observed during onboarding. Linux-only provisioning was attempted and remained unverified.

From the project root, use `scripts/vacuumctl.py` with the private cloud configuration described in the [README](../README.md#1-set-up). Cloud status, start, and return-to-dock were verified on hardware. For a movement test, start capture first, bound the run, send the vacuum home, and check the final reported state.

## Local Wi-Fi status

`scripts/lan_capture.py` uses authenticated Tuya LAN 3.4. The first run can retrieve the local key through the cloud project. A cached key allows subsequent LAN collection over local Wi-Fi. The collector records status replies and unsolicited updates in receipt order. Import the JSONL with `scripts/telemetry_db.py` and query `lan_frames`.

Observed status fields include battery, cleaning state, elapsed cleaning time, reported area, fault, and cleaning-record ID. The verified coordinate stream uses device MQTT and is documented in [Route capture and decoding](route-capture.md).

Keep configuration and LAN keys under `~/.config/smart-vacuum/` with restrictive permissions. Raw captures, databases, generated maps, and device identifiers stay private.
