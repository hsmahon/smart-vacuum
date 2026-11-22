"""Capture Tuya MCU map frames from a binary stream (passive serial or file)."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import sys


def map_payload(frame):
    if (len(frame) < 13 or frame[:3] != b'\x55\xaa\x03'
            or int.from_bytes(frame[4:6], "big") + 7 != len(frame)
            or sum(frame[:-1]) % 256 != frame[-1]):
        raise ValueError("invalid MCU frame")
    layouts = {0x28: ">BBB", 0x3c: ">HHB"}
    if frame[3] not in layouts:
        raise ValueError("unknown map command")
    record_id, offset = struct.unpack_from(">HI", frame, 6)
    layout = layouts[frame[3]]
    data = frame[12:-1]
    if len(data) % struct.calcsize(layout):
        raise ValueError("partial map point")
    return record_id, offset, list(struct.iter_unpack(layout, data))


def frames(stream):
    buffer = bytearray()
    while chunk := stream.read1(4096):
        buffer.extend(chunk)
        while len(buffer) >= 6:
            start = buffer.find(b'\x55\xaa\x03')
            if start < 0:
                del buffer[:-2]
                break
            del buffer[:start]
            if len(buffer) < 6:
                break
            size = int.from_bytes(buffer[4:6], "big") + 7
            if buffer[3] not in (0x28, 0x3c) or not 13 <= size <= 269:
                del buffer[0]
                continue
            if len(buffer) < size:
                break
            frame = bytes(buffer[:size])
            if sum(frame[:-1]) % 256 != frame[-1]:
                del buffer[0]
                continue
            yield frame
            del buffer[:size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="new JSONL capture, typically under route-captures/")
    parser.add_argument("--input", type=Path, help="configured receive-only serial device or binary replay; default stdin")
    args = parser.parse_args()
    os.umask(0o077)
    with (args.input.open("rb") if args.input else sys.stdin.buffer) as stream, args.output.open("x", buffering=1) as out:
        for frame in frames(stream):
            now = datetime.now(timezone.utc)
            out.write(json.dumps({"received_at": now.isoformat(), "format": "tuya_mcu_map",
                                  "frame_hex": frame.hex()}) + "\n")


if __name__ == "__main__":
    main()
