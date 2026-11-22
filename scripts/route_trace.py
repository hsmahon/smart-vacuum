#!/usr/bin/env python3
"""Convert Tuya Sweeper SDK route data to an indoor trace."""
import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET


# Tuya's hex examples encode each point as x, y, point type.
# Live frames also have a 13-byte header. Preserve the record ID as bytes.
LIVE_HEADER_BYTES = 13
HEX = re.compile(r"[0-9a-fA-F]*")


def decode_hex(value, source):
    if not isinstance(value, str) or len(value) % 2 or not HEX.fullmatch(value):
        raise ValueError(f"{source}: expected an even-length hexadecimal string")
    return bytes.fromhex(value)


def decode_points(data, source):
    if len(data) % 3:
        raise ValueError(f"{source}: point payload length {len(data)} is not divisible by 3")
    return list(zip(data[::3], data[1::3], data[2::3]))


def read_live(file):
    for index, line in enumerate(file, 1):
        if not line.strip():
            continue
        row = json.loads(line)
        source = f"live line {index}"
        frame = decode_hex(row["frame_hex"], source)
        if len(frame) < LIVE_HEADER_BYTES:
            raise ValueError(f"{source}: incomplete live frame header")
        record = frame[:4].hex()
        yield record, index, row["received_at"], decode_points(frame[LIVE_HEADER_BYTES:], source)


def read_history(file):
    page = json.load(file)
    record = str(page["subRecordId"])
    chunks = page["dataList"]
    if not isinstance(chunks, list):
        raise ValueError("history: dataList must be an array")
    if page.get("hasNext"):
        print("History page has more results. The rendered trace covers this page only.", file=sys.stderr)
    for index, chunk in enumerate(chunks, 1):
        source = f"history chunk {index}"
        yield record, index, "", decode_points(decode_hex(chunk, source), source)


def svg_route(segments, title="Vacuum route in Tuya grid units"):
    points = [point for segment in segments for point in segment]
    min_x = min(x for x, _, _ in points)
    max_x = max(x for x, _, _ in points)
    min_y = min(y for _, y, _ in points)
    max_y = max(y for _, y, _ in points)
    # Keep a minimum extent so short or stationary traces are visible.
    width = max(8, max_x - min_x) + 8
    height = max(8, max_y - min_y) + 8
    root = ET.Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg",
        "viewBox": f"{min_x - 4} {min_y - 4} {width} {height}",
        "width": "700",
        "height": "700",
    })
    ET.SubElement(root, "title").text = title
    ET.SubElement(root, "rect", {
        "x": str(min_x - 4), "y": str(min_y - 4),
        "width": str(width), "height": str(height), "fill": "#f4f7fa",
    })
    for segment in segments:
        if len(segment) > 1:
            ET.SubElement(root, "polyline", {
                "points": " ".join(f"{x},{y}" for x, y, _ in segment),
                "stroke": "#005f87", "stroke-width": "0.3", "fill": "none",
                "stroke-linejoin": "round",
            })
        for x, y, _ in segment:
            ET.SubElement(root, "circle", {"cx": str(x), "cy": str(y), "r": "0.28", "fill": "#005f87"})
    return ET.ElementTree(root)


def write_capture(batches, output_dir):
    records = defaultdict(list)
    for record, index, timestamp, points in batches:
        if points:
            records[record].append((index, timestamp, points))
    if not records:
        raise ValueError("no route points found")
    output_dir.mkdir(parents=True)
    for ordinal, (record, segments) in enumerate(records.items(), 1):
        basename = output_dir / f"route-{ordinal}"
        with basename.with_suffix(".csv").open("x", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(("record", "segment", "received_at", "x", "y", "point_type"))
            for index, timestamp, points in segments:
                writer.writerows((record, index, timestamp, x, y, kind) for x, y, kind in points)
        with basename.with_suffix(".svg").open("xb") as file:
            svg_route([points for _, _, points in segments]).write(file, encoding="utf-8")
    print(f"Exported {len(records)} route(s) to {output_dir}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("format", choices=("live", "history"))
    parser.add_argument("input", type=Path)
    parser.add_argument("output_dir", type=Path, help="new directory for CSV and SVG output")
    args = parser.parse_args()
    read = read_live if args.format == "live" else read_history
    try:
        with args.input.open(encoding="utf-8") as file:
            write_capture(read(file), args.output_dir)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"route trace: {error}\n")


if __name__ == "__main__":
    main()
