#!/usr/bin/env python3
"""Record a tagged vacuum's route from a fixed camera or a local video."""
import argparse
import csv
from datetime import datetime, timezone
from math import atan2, degrees, isfinite
from pathlib import Path

from route_trace import svg_route


def create_tag(cv, dictionary, tag_id, path):
    marker = cv.aruco.generateImageMarker(dictionary, tag_id, 480)
    marker = cv.copyMakeBorder(marker, 60, 60, 60, 60, cv.BORDER_CONSTANT, value=255)
    ok, image = cv.imencode(".png", marker)
    if not ok:
        raise ValueError("could not encode the marker")
    with path.open("xb") as file:
        file.write(image.tobytes())


def capture_route(cv, detector, args):
    live = args.camera is not None
    capture = cv.VideoCapture(args.camera if live else str(args.video))
    segments = []
    segment = []
    frame_number = 0
    try:
        if not capture.isOpened():
            raise ValueError("could not open the camera or video")
        fps = capture.get(cv.CAP_PROP_FPS)
        if not live and (not isfinite(fps) or fps <= 0):
            raise ValueError("video has no usable frame rate")
        args.output.mkdir()
        with (args.output / "route.csv").open("x", newline="", encoding="utf-8", buffering=1) as file:
            writer = csv.writer(file)
            writer.writerow(("segment", "frame", "received_at_utc", "video_elapsed_s", "x_px", "y_px",
                             "tag_heading_deg"))
            try:
                while True:
                    ok, frame = capture.read()
                    if not ok:
                        if live:
                            print("Camera stopped delivering frames.")
                        break

                    received = datetime.now(timezone.utc).isoformat() if live else ""
                    corners, ids, _ = detector.detectMarkers(cv.cvtColor(frame, cv.COLOR_BGR2GRAY))
                    matching = [] if ids is None else [i for i, marker in enumerate(ids.flat) if marker == args.tag_id]
                    if len(matching) == 1:
                        points = corners[matching[0]][0]
                        x, y = (round(float(value), 2) for value in points.mean(axis=0))
                        top = (points[0] + points[1]) / 2
                        bottom = (points[2] + points[3]) / 2
                        dx, dy = top - bottom
                        heading = round(degrees(atan2(float(dy), float(dx))) % 360, 2) % 360
                        if not segment:
                            segments.append(segment)
                        segment.append((x, y, 0))
                        elapsed = "" if live else round(frame_number / fps, 4)
                        writer.writerow((len(segments), frame_number, received, elapsed, x, y, heading))
                    else:
                        segment = []
                    frame_number += 1
            except KeyboardInterrupt:
                pass
    finally:
        capture.release()

    if not segments:
        raise ValueError("no tag detections. Check the tag ID, lighting, and camera placement.")
    with (args.output / "route.svg").open("xb") as file:
        svg_route(segments, title="Vacuum route in camera pixels").write(file, encoding="utf-8")
    count = sum(len(segment) for segment in segments)
    print(f"Saved {count} positions in {len(segments)} segment(s) to {args.output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag-id", type=int, default=0, help="AprilTag 36h11 ID, 0 to 586")
    subparsers = parser.add_subparsers(dest="action", required=True)

    tag = subparsers.add_parser("tag", help="generate a printable AprilTag")
    tag.add_argument("output", type=Path, help="new PNG file")

    track = subparsers.add_parser("track", help="capture the tag route")
    source = track.add_mutually_exclusive_group(required=True)
    source.add_argument("--camera", type=int, help="OpenCV camera index, typically 0")
    source.add_argument("--video", type=Path, help="existing local video")
    track.add_argument("output", type=Path, help="new directory for CSV and SVG")

    args = parser.parse_args()
    if not 0 <= args.tag_id < 587:
        parser.error("--tag-id must be between 0 and 586")
    try:
        import cv2 as cv
    except ImportError:
        parser.exit(1, "Install opencv-contrib-python-headless in the route virtual environment.\n")

    dictionary = cv.aruco.getPredefinedDictionary(cv.aruco.DICT_APRILTAG_36h11)
    try:
        if args.action == "tag":
            create_tag(cv, dictionary, args.tag_id, args.output)
        else:
            capture_route(cv, cv.aruco.ArucoDetector(dictionary), args)
    except (OSError, ValueError, cv.error) as error:
        parser.exit(1, f"camera route: {error}\n")


if __name__ == "__main__":
    main()
