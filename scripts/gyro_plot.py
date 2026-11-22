"""Export actual captured robot positions for one gyro record as a standalone HTML page."""
import argparse
import html
from pathlib import Path
import duckdb


def render(database, capture, record, output):
    with duckdb.connect(str(database), read_only=True) as db:
        positions = db.execute("""
            SELECT x_from_dock, y_from_dock FROM gyro_positions
            WHERE capture_name = ? AND record_hex = ?
            ORDER BY source_offset, record_index, point_index
        """, [capture, record]).fetchall()
    if not positions or any(x is None or y is None for x, y in positions):
        raise ValueError("This record needs robot positions and one consistent dock location")
    xs, ys = zip(*positions)
    left, top = min(0, *xs) - 4, -max(0, *ys) - 4
    width, height = max(0, *xs) + 4 - left, -min(0, *ys) + 4 - top
    points = " ".join(f"{x},{-y}" for x, y in positions)
    dots = "".join(f'<circle cx="{x}" cy="{-y}" r=".34"><title>({x}, {y})</title></circle>'
                   for x, y in positions)
    output.write_text(f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Vacuum route {html.escape(record)}</title>
<style>body{{max-width:48rem;margin:auto;padding:1rem;font:1rem/1.5 system-ui;color:#183544}}
svg{{display:block;width:100%;height:62vh;background:#f4f8fa}}p{{max-width:62ch}}</style>
<h1>Vacuum route {int(record, 16)}</h1><p>{len(positions)} position reports, in arrival order.
The orange square marks the reported dock at (0, 0). Distances are in map grid units.</p>
<svg role="img" aria-label="Top-down route from measured robot positions" viewBox="{left} {top} {width} {height}">
<polyline points="{points}" fill="none" stroke="#07736c" stroke-width=".25"/>
<g fill="#173948">{dots}</g><rect x="-.6" y="-.6" width="1.2" height="1.2" fill="#d65500"><title>Dock</title></rect>
</svg><p>Dots are measured positions. Lines connect successive reports. Travel between reports and the return to dock may be missing.</p></html>""")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture")
    parser.add_argument("record_hex")
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "telemetry.duckdb")
    args = parser.parse_args()
    render(args.database, args.capture, args.record_hex, args.output)
