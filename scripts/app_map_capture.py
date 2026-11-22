#!/usr/bin/env python3
"""Extract map snapshots and optional path masks from a Tuya screen recording."""
import argparse
import csv
from pathlib import Path

import cv2
import numpy as np


def rectangle(value):
    try:
        x, y, width, height = map(int, value.split(","))
        if min(x, y) >= 0 and min(width, height) > 0:
            return x, y, width, height
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("use x,y,width,height in pixels")


def color(value):
    value = value.removeprefix("#")
    if len(value) == 6:
        try:
            return np.array(list(bytes.fromhex(value))[::-1], dtype=np.int16)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError("use a six-digit RGB hex color")


def save_image(path, image):
    if not cv2.imwrite(str(path), image):
        raise OSError(f"could not write {path}")


def extract(args):
    video = cv2.VideoCapture(str(args.video))
    try:
        fps = video.get(cv2.CAP_PROP_FPS)
        if not video.isOpened() or not np.isfinite(fps) or fps <= 0:
            raise ValueError("could not open video with a usable frame rate")
        x, y, width, height = args.crop
        args.output.mkdir()
        with (args.output / "frames.csv").open("x", newline="", encoding="utf-8") as stream:
            manifest = csv.writer(stream)
            manifest.writerow(("frame", "elapsed_seconds", "snapshot", "mask"))
            previous = None
            frame_number = 0
            next_frame = 0
            while video.grab():
                if frame_number >= next_frame:
                    ok, image = video.retrieve()
                    if not ok:
                        raise ValueError(f"could not decode frame {frame_number}")
                    if x + width > image.shape[1] or y + height > image.shape[0]:
                        raise ValueError(f"crop exceeds video bounds at frame {frame_number}")
                    crop = image[y:y + height, x:x + width]
                    if previous is None or not np.array_equal(crop, previous):
                        name = f"map-{frame_number:07}.png"
                        save_image(args.output / name, crop)
                        mask_name = ""
                        if args.path_color is not None:
                            delta = np.abs(crop.astype(np.int16) - args.path_color)
                            mask = np.all(delta <= args.tolerance, axis=2).astype(np.uint8) * 255
                            mask_name = f"mask-{frame_number:07}.png"
                            save_image(args.output / mask_name, mask)
                        manifest.writerow((frame_number, f"{frame_number / fps:.3f}", name, mask_name))
                        previous = crop.copy()
                    next_frame = frame_number + max(1, round(fps * args.interval))
                frame_number += 1
            if previous is None:
                raise ValueError("video contained no decodable map snapshots")
    finally:
        video.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path, help="new directory for snapshots and index")
    parser.add_argument("--crop", type=rectangle, required=True)
    parser.add_argument("--interval", type=float, default=3, help="seconds between video samples")
    parser.add_argument("--path-color", type=color, help="optional hex color of the displayed route line")
    parser.add_argument("--tolerance", type=int, default=24, help="allowed difference per color channel")
    args = parser.parse_args()
    if not np.isfinite(args.interval) or args.interval <= 0 or not 0 <= args.tolerance <= 255:
        parser.error("use a positive finite interval and a tolerance between 0 and 255")
    try:
        extract(args)
    except (OSError, ValueError, cv2.error) as error:
        parser.exit(1, f"app map capture: {error}\n")


if __name__ == "__main__":
    main()
