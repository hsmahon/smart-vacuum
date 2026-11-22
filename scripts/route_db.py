"""Store original Sweeper SDK packets and tentative decoded points in DuckDB."""
import hashlib
import json
from pathlib import Path
from datetime import datetime

from gyro_frames import split_records
from robot_map_stream import map_payload
from route_trace import LIVE_HEADER_BYTES, decode_hex, decode_points


SCHEMA = """
CREATE TABLE IF NOT EXISTS route_packets (
    packet_id VARCHAR PRIMARY KEY,
    capture_name VARCHAR NOT NULL,
    source_offset BIGINT NOT NULL,
    received_at TIMESTAMPTZ,
    record_hex VARCHAR,
    frame BLOB,
    raw VARCHAR NOT NULL,
    decode_error VARCHAR
);
CREATE TABLE IF NOT EXISTS route_points (
    packet_id VARCHAR REFERENCES route_packets(packet_id),
    point_index INTEGER,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    point_type INTEGER NOT NULL,
    PRIMARY KEY (packet_id, point_index)
);
CREATE VIEW IF NOT EXISTS route_steps AS
WITH steps AS (
    SELECT r.capture_name, r.source_offset, r.received_at, r.record_hex,
           p.point_index, p.x, p.y, p.point_type,
           p.x - lag(p.x) OVER packet AS dx,
           p.y - lag(p.y) OVER packet AS dy
    FROM route_points p JOIN route_packets r USING (packet_id)
    WINDOW packet AS (PARTITION BY p.packet_id ORDER BY p.point_index)
)
SELECT *, sqrt(dx * dx + dy * dy) AS step_grid_units,
       CASE WHEN dx <> 0 OR dy <> 0 THEN degrees(atan2(dy, dx)) END AS direction_deg
FROM steps;
""" + (Path(__file__).resolve().parents[1] / "robot_motion.sql").read_text()


def read_packets(log, capture_name, offset):
    log.seek(offset)
    packets = []
    points = []
    while len(packets) < 500 and (line := log.readline()):
        if not line.endswith(b"\n"):
            break
        start = offset
        offset = log.tell()
        if not line.strip():
            continue

        raw = line.decode("utf-8", errors="replace").rstrip("\r\n")
        packet_id = hashlib.sha256(f"{capture_name}\0{start}\0".encode() + line).hexdigest()
        timestamp = record = frame = error = None
        try:
            row = json.loads(raw)
            gyro = "payload_hex" in row
            frame = (decode_hex(row["payload_hex"], "gyro MQTT envelope") if gyro
                     else decode_hex(row["frame_hex"], "SDK frame"))
            timestamp = datetime.fromisoformat(row["received_at"])
            if timestamp.utcoffset() is None:
                timestamp = None
                raise ValueError("packet receipt time needs a time zone")
            if gyro:
                for index, part in enumerate(split_records(frame)):
                    part_id = f"{packet_id}-{index}"
                    record = part[:2].hex()
                    try:
                        decoded = decode_points(part[13:], "gyro map")
                    except ValueError as exc:
                        packets.append((part_id, capture_name, start, timestamp, record,
                                        part, raw, str(exc)))
                        continue
                    packets.append((part_id, capture_name, start, timestamp, record, part, raw, None))
                    points.extend((part_id, n, x, y, kind)
                                  for n, (x, y, kind) in enumerate(decoded))
                continue
            if row.get("format") == "tuya_mcu_map":
                map_id, _, decoded = map_payload(frame)
                record = f"{map_id:04x}"
            else:
                if len(frame) < LIVE_HEADER_BYTES:
                    raise ValueError("incomplete live frame header")
                record = frame[:4].hex()
                decoded = decode_points(frame[LIVE_HEADER_BYTES:], "SDK frame")
            points.extend((packet_id, index, x, y, kind) for index, (x, y, kind) in enumerate(decoded))
        except (ValueError, TypeError, KeyError) as exc:
            error = str(exc)
        packets.append((packet_id, capture_name, start, timestamp, record, frame, raw, error))
        if len(packets) == 500:
            break
    return packets, points, offset


def sync_routes(database, capture, offset, connect):
    with capture.open("rb") as log:
        while True:
            packets, points, next_offset = read_packets(log, capture.name, offset)
            if not packets:
                return next_offset
            with connect(str(database)) as connection:
                connection.begin()
                connection.execute(SCHEMA)
                connection.executemany(
                    "INSERT INTO route_packets VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
                    packets,
                )
                if points:
                    connection.executemany(
                        "INSERT INTO route_points VALUES (?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", points
                    )
                connection.commit()
            offset = next_offset
            if len(packets) < 500:
                return offset
