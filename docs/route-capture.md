# Route capture and decoding

Follow the [README capture workflow](../README.md#2-record-a-route) to subscribe before starting a cleaning run. Live gyro MQTT capture worked with Tuya Smart closed after a recent panel session. Availability after a power cycle or a long idle period remains unverified. Earlier cloud map-file lookups returned empty results during and after cleaning. The cleaning-record ID identifies a run but does not contain its coordinates.

## Capture and import

- `scripts/gyro_channel.py` saves receipt timestamps and original MQTT payloads as JSONL. `scripts/gyro_frames.py` checks record framing and CRC32.
- `scripts/route_db.py` stores source envelopes, frame bytes, record IDs, receipt times, source offsets, and decode errors in `route_packets`. It stores decoded coordinates and point types in `route_points`. The importer also accepts existing MCU and SDK JSONL captures.
- Replay with the same capture basename and original line bytes and offsets preserves packet identities. Verify replay by importing a synthetic capture twice and checking row counts. An incomplete final JSONL line is deferred until its newline arrives.

## Query and interpret positions

Use `gyro_positions` for live gyro position reports. Order by capture name, source offset, record index, and point index. Group plots by capture and record ID. Dock-relative coordinates depend on a consistent dock marker within that group.

Coordinates are in grid units. Calibrate against a measured floor segment before reporting distances in metres. Receipt timestamps measure arrival on the capture host. Packet gaps and batched arrivals limit estimates of elapsed movement and speed. Connected plot segments can span missing reports.

Manual steering commands were acknowledged during a live test, but the recorded path did not establish a turn. Treat a command acknowledgement as evidence of receipt and use position reports to establish motion.
