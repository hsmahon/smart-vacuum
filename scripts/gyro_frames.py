"""Decode the Tuya gyro panel's map records inside a binary MQTT envelope."""
from zlib import crc32


def split_records(wire):
    if len(wire) < 25 or wire[:2] != b"\x55\xaa":
        raise ValueError("invalid gyro MQTT header")
    end = len(wire) - 4
    if int.from_bytes(wire[6:8], "big") != end - 8:
        raise ValueError("incorrect MQTT payload length")
    if crc32(wire[:end]) != int.from_bytes(wire[end:], "big"):
        raise ValueError("gyro MQTT CRC mismatch")
    position = 8
    records = []
    while position < end:
        if end - position < 13:
            raise ValueError("truncated gyro map header")
        length = int.from_bytes(wire[position + 11:position + 13], "big")
        stop = position + 13 + length
        if stop > end:
            raise ValueError("truncated gyro map record")
        records.append(wire[position:stop])
        position = stop
    return records
