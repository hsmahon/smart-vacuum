#!/usr/bin/env python3
"""Import the vacuum's append-only JSONL log into DuckDB."""
import argparse
import json
import hashlib
import os
import time
from datetime import datetime
from pathlib import Path

import duckdb

from route_db import SCHEMA as ROUTE_SCHEMA, sync_routes


ROOT = Path(__file__).resolve().parents[1]

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    recorded_at TIMESTAMPTZ PRIMARY KEY,
    status JSON,
    error VARCHAR,
    raw JSON NOT NULL
);
CREATE OR REPLACE VIEW telemetry AS
SELECT recorded_at,
       status ->> 'status' AS state,
       TRY_CAST(status ->> 'electricity_left' AS INTEGER) AS battery_pct,
       TRY_CAST(status ->> 'clean_time' AS INTEGER) AS cleaning_min,
       TRY_CAST(status ->> 'clean_area' AS DECIMAL(8, 1)) / 10 AS cleaning_m2,
       TRY_CAST(status ->> 'fault' AS BIGINT) AS fault_bitmap,
       status ->> 'mode' AS mode,
       status ->> 'suction' AS suction,
       status ->> 'cistern' AS water_setting,
       NULLIF(status ->> 'clean_record', '') AS cleaning_record,
       error
FROM samples;
"""


POSITION_SCHEMA = """
CREATE OR REPLACE VIEW vacuum_positions AS
WITH mcu_points AS (
    SELECT r.capture_name, r.record_hex, r.received_at, r.source_offset,
           p.point_index, p.point_type, p.x, p.y
    FROM route_packets r JOIN route_points p USING (packet_id)
    WHERE try_cast(r.raw AS JSON) ->> 'format' = 'tuya_mcu_map'
), docks AS (
    SELECT capture_name, record_hex, min(x) AS x, min(y) AS y
    FROM mcu_points WHERE point_type = 3
    GROUP BY capture_name, record_hex
    HAVING min(x) = max(x) AND min(y) = max(y)
)
SELECT recorded_at, 'charging_status' AS source, NULL::VARCHAR AS capture_name,
       NULL::VARCHAR AS record_hex, NULL::BIGINT AS source_offset,
       NULL::INTEGER AS point_index, 0 AS x_from_dock, 0 AS y_from_dock
FROM telemetry WHERE state IN ('charging', 'charge_done')
UNION ALL
SELECT p.received_at, 'mcu_position', p.capture_name, p.record_hex, p.source_offset,
       p.point_index, p.x - d.x, p.y - d.y
FROM mcu_points p JOIN docks d USING (capture_name, record_hex)
WHERE p.point_type = 0;
"""


def read_batch(log, offset):
    log.seek(offset)
    rows = []
    while line := log.readline():
        if not line.endswith(b"\n"):
            # The collector may still be appending the final line.
            break
        offset = log.tell()
        if not line.strip():
            continue
        raw = line.decode("utf-8").strip()
        record = json.loads(raw)
        timestamp = datetime.fromisoformat(record["timestamp"])
        if timestamp.utcoffset() is None:
            raise ValueError("Telemetry timestamp needs a time zone")
        status = record.get("status")
        rows.append((timestamp, None if status is None else json.dumps(status), record.get("error"), raw))
        if len(rows) == 500:
            break
    return rows, offset


def sync(database, source, offset):
    if not source.exists():
        with duckdb.connect(str(database)) as connection:
            connection.execute(SCHEMA + ROUTE_SCHEMA + POSITION_SCHEMA + (ROOT / "movement.sql").read_text())
        return offset
    with source.open("rb") as log:
        while True:
            rows, next_offset = read_batch(log, offset)
            if not rows and database.exists():
                return next_offset
            with duckdb.connect(str(database)) as connection:
                connection.begin()
                connection.execute(SCHEMA + ROUTE_SCHEMA + POSITION_SCHEMA + (ROOT / "movement.sql").read_text())
                if rows:
                    connection.executemany(
                        "INSERT INTO samples VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING", rows
                    )
                connection.commit()
            offset = next_offset
            if len(rows) < 500:
                return offset


def sync_push_events(database, log_path, offset):
    if not log_path.exists():
        return offset
    with log_path.open("rb") as file:
        file.seek(offset)
        rows = []
        for line in file:
            if not line.endswith(b"\n"):
                break
            record = json.loads(line)
            rows.append((hashlib.sha256(line).hexdigest(), record["received_at"], line.decode()))
            offset += len(line)
            if len(rows) == 1000:
                break
    if rows:
        with duckdb.connect(str(database)) as db:
            db.begin()
            db.execute("CREATE TABLE IF NOT EXISTS device_events "
                       "(id VARCHAR PRIMARY KEY, received_at TIMESTAMPTZ, raw JSON)")
            db.executemany("INSERT INTO device_events VALUES (?, ?, ?) ON CONFLICT DO NOTHING", rows)
            db.commit()
    return offset


def sync_lan(database, capture, offset):
    with capture.open("rb") as log:
        log.seek(offset)
        while True:
            rows = []
            for line in log:
                if not line.endswith(b"\n"):
                    break
                frame = json.loads(line)
                payload = bytes.fromhex(frame["payload_hex"])
                # Version 3.4 status pushes include a 15-byte header with variable fields.
                body = payload[15:] if payload.startswith(b"3.4") else payload
                try:
                    decoded = json.dumps(json.loads(body))
                except (ValueError, UnicodeError):
                    decoded = None
                rows.append((capture.name, offset, frame["received_at"], frame["command"],
                             frame["sequence"], frame["return_code"], payload, decoded))
                offset += len(line)
                if len(rows) == 500:
                    break
            if rows:
                with duckdb.connect(str(database)) as db:
                    db.execute("""CREATE TABLE IF NOT EXISTS lan_frames (
                        capture_name VARCHAR, source_offset BIGINT, received_at TIMESTAMPTZ,
                        command INTEGER, sequence BIGINT, return_code BIGINT, payload BLOB, data JSON,
                        PRIMARY KEY (capture_name, source_offset))""")
                    db.executemany("INSERT INTO lan_frames VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                                   "ON CONFLICT DO NOTHING", rows)
            if len(rows) < 500:
                return offset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=ROOT / "telemetry-run.jsonl")
    parser.add_argument("--database", type=Path, default=ROOT / "telemetry.duckdb")
    parser.add_argument("--follow-seconds", type=int, default=0, help="keep syncing every 15 seconds")
    parser.add_argument("--route-jsonl", type=Path, action="append", default=[],
                        help="import a Sweeper SDK capture, repeat for multiple files")
    args = parser.parse_args()
    if args.follow_seconds < 0:
        parser.error("--follow-seconds must be nonnegative")

    os.umask(0o077)
    offset = 0
    event_offset = 0
    lan_offsets = {}
    route_offsets = dict.fromkeys(args.route_jsonl, 0)
    deadline = time.monotonic() + args.follow_seconds
    while True:
        try:
            offset = sync(args.database, args.jsonl, offset)
            event_offset = sync_push_events(args.database, args.jsonl.with_name("movement-events.jsonl"), event_offset)
            for capture in (ROOT / "lan-captures").glob("*.jsonl"):
                lan_offsets[capture] = sync_lan(args.database, capture, lan_offsets.get(capture, 0))
            for capture in (ROOT / "route-captures").glob("*.jsonl"):
                route_offsets.setdefault(capture, 0)
            for capture in (ROOT / "gyro-captures").glob("*.jsonl"):
                route_offsets.setdefault(capture, 0)
            for capture, route_offset in route_offsets.items():
                if capture.is_file():
                    route_offsets[capture] = sync_routes(args.database, capture, route_offset, duckdb.connect)
        except duckdb.IOException as error:
            # A separate DuckDB reader can briefly hold a shared file lock.
            if "lock" not in str(error).lower() or time.monotonic() >= deadline:
                raise
            print(f"DuckDB busy, retrying: {error}", flush=True)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(15, remaining))


if __name__ == "__main__":
    main()
