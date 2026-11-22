"""Export actual captured robot positions for one gyro record as a standalone HTML page."""
import argparse
import html
import math
from pathlib import Path
import duckdb


THEME_STYLE = """<style>
.route-header { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
.route-header h1 { margin: 0; text-decoration: underline; }
.route-header label { white-space: nowrap; padding: .35rem .5rem; cursor: pointer; }
:root[data-theme="dark"] { color-scheme: dark; background: #16181b; color: #eee; }
[data-theme="dark"] body { color: #eee; }
[data-theme="dark"] svg { background: #202327; border-color: #717780; }
[data-theme="dark"] .axes { fill: #ddd; }
[data-theme="dark"] .axes line { stroke: #abb1ba; }
[data-theme="dark"] .axes .grid line { stroke: #474c53; }
[data-theme="dark"] #axis-arrow path { fill: #abb1ba; }
[data-theme="dark"] circle { fill: #eee; }
[data-theme="dark"] circle.going-home { fill: #78baff; }
[data-theme="dark"] circle.active, [data-theme="dark"] svg rect { fill: #ff9658; }
[data-theme="dark"] svg polyline { stroke: #a6adb7; }
[data-theme="dark"] svg polyline[stroke="#175b9a"] { stroke: #78baff; }
[data-theme="dark"] ol, [data-theme="dark"] li { border-color: #717780; }
[data-theme="dark"] li.active summary { outline-color: #ff9658; }
</style>"""

THEME_CONTROL = '<label><input id="route-dark-mode" type="checkbox"> Dark mode</label>'

THEME_SCRIPT = """<script>
(() => {
    const toggle = document.getElementById("route-dark-mode");
    const key = "vacuum-route-theme";
    let savedTheme;
    try { savedTheme = localStorage.getItem(key); } catch {}
    toggle.checked = savedTheme ? savedTheme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const applyTheme = () => {
        document.documentElement.dataset.theme = toggle.checked ? "dark" : "light";
    };
    applyTheme();
    toggle.addEventListener("change", () => {
        applyTheme();
        try { localStorage.setItem(key, document.documentElement.dataset.theme); } catch {}
    });
})();
</script>"""


def render(database, capture, record, output, going_home_from=None):
    with duckdb.connect(str(database), read_only=True) as db:
        positions = db.execute("""
            SELECT x_from_dock, y_from_dock, x, y,
                   strftime(received_at AT TIME ZONE 'UTC', '%Y-%m-%d %H:%M:%S.%f') AS received_utc,
                   source_offset, record_index, point_index
            FROM gyro_positions
            WHERE capture_name = ? AND record_hex = ?
            ORDER BY source_offset, record_index, point_index
        """, [capture, record]).fetchall()
    if not positions or any(x is None or y is None for x, y, *_ in positions):
        raise ValueError("This record needs robot positions and one consistent dock location")

    xs, ys = zip(*[(x, y) for x, y, *_ in positions])
    span = max(max(0, *xs) - min(0, *xs), max(0, *ys) - min(0, *ys))
    target = max(1, span / 8)
    magnitude = 10 ** math.floor(math.log10(target))
    step = next(unit * magnitude for unit in (1, 2, 5, 10) if unit * magnitude >= target)
    x_ticks = range((min(0, *xs) // step) * step, max(0, *xs) + step, step)
    y_ticks = range((min(0, *ys) // step) * step, max(0, *ys) + step, step)
    padding = step * .6
    left, right = x_ticks[0] - padding, x_ticks[-1] + padding
    top, bottom = -y_ticks[-1] - padding, -y_ticks[0] + padding
    width, height = right - left, bottom - top
    grid = []
    for x in x_ticks:
        if x:
            grid.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{bottom}"/>'
                        f'<text x="{x}" y="{step * .26}" text-anchor="middle">{x}</text>')
    for y in y_ticks:
        if y:
            grid.append(f'<line x1="{left}" y1="{-y}" x2="{right}" y2="{-y}"/>'
                        f'<text x="{-step * .12}" y="{-y}" text-anchor="end" '
                        f'dominant-baseline="central">{y}</text>')
    if going_home_from is not None and not 1 <= going_home_from <= len(positions) + 1:
        raise ValueError("Going home boundary must be a report number or one past the last report")
    split = len(positions) if going_home_from is None else going_home_from - 1
    cleaning_points = " ".join(f"{x},{-y}" for x, y, *_ in positions[:split])
    home_points = " ".join(f"{x},{-y}" for x, y, *_ in positions[split:])
    home_divider = '<li class="phase-divider">Going home</li>'
    if not home_points:
        home_divider = '<li class="phase-divider">Going home · No position reports captured</li>'
    dots = []
    rows = []
    for number, (x, y, raw_x, raw_y, received, offset, frame, index) in enumerate(positions, 1):
        timestamp = f"{received} UTC" if received else "Unknown"
        details = html.escape(
            f"Report {number} · Received {timestamp} · Dock-relative ({x}, {y}) · "
            f"Raw ({raw_x}, {raw_y}) · Byte offset {offset} · Record index {frame} · Point index {index}"
        )
        phase_class = ' class="going-home"' if number > split else ""
        if number == going_home_from:
            rows.append(home_divider)
        dots.append(f'<circle{phase_class} id="dot-{number}" cx="{x}" cy="{-y}" r=".34" data-report="{number}">'
                    f'<title>{details}</title></circle>')
        fields = [
            ("Received", timestamp),
            ("Dock-relative X, Y", f"({x}, {y})"),
            ("Raw X, Y", f"({raw_x}, {raw_y})"),
            ("Source byte offset", offset),
            ("Record index", frame),
            ("Point index", index),
        ]
        if going_home_from is not None:
            fields.append(("Phase", "Going home" if number > split else "Cleaning"))
        telemetry_fields = "".join(
            f"<dt>{label}</dt><dd>{html.escape(str(value))}</dd>" for label, value in fields
        )
        rows.append(f'<li id="report-{number}" value="{number}"><details>'
                    f'<summary data-report="{number}">({x}, {y}) · <small>{timestamp}</small></summary>'
                    f'<dl>{telemetry_fields}</dl></details></li>')

    if going_home_from == len(positions) + 1:
        rows.append(home_divider)

    output.write_text(f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vacuum Route {int(record, 16)}</title>
<style>
body {{ box-sizing: border-box; margin: 0; padding: clamp(.65rem, 2vw, 1.25rem); height: 100dvh; font: 1rem/1.4 system-ui, sans-serif;
        display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: .65rem; }}
body > p {{ margin: 0; }}
main {{ display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-height: 0; grid-template-columns: minmax(0, 1fr) minmax(19rem, 28rem); gap: .6rem 1.25rem; }}
main section {{ display: grid; grid-row: span 3; grid-template-rows: subgrid; min-width: 0; }}
main h2, main p {{ margin: 0; }}
main h2 {{ font-size: 1.15rem; }}
main p {{ font-size: .875rem; }}
.map-frame {{ container-type: size; min-height: 0; }}
svg {{ display: block; width: min(100%, calc(100cqh * {width} / {height})); height: auto; aspect-ratio: {width} / {height}; border: 1px solid #aaa; box-sizing: border-box; }}
.axes {{ pointer-events: none; font-family: sans-serif; fill: #444; }}
.axes line {{ stroke: #555; vector-effect: non-scaling-stroke; }}
.axes .grid line {{ stroke: #ddd; }}
circle {{ cursor: pointer; }}
circle.going-home {{ fill: #175b9a; }}
circle.active {{ fill: #c40; r: .65; }}
ol {{ contain: size; min-height: 0; box-sizing: border-box; margin: 0; overflow: auto;
      padding: .25rem .65rem .25rem 2.9rem; border: 1px solid #aaa; }}
li {{ padding: .2rem 0; }}
li::marker {{ font-size: .85rem; font-variant-numeric: tabular-nums; }}
li + li {{ border-top: 1px solid #ddd; }}
li.phase-divider {{ list-style: none; margin-left: -2.5rem; border-top: 2px solid #555;
                    font-weight: bold; }}
li summary {{ padding: .55rem .4rem; cursor: pointer; border-radius: .2rem; }}
li summary:hover, li details[open] summary {{ background: color-mix(in srgb, currentColor 8%, transparent); }}
li dl {{ display: grid; grid-template-columns: max-content minmax(0, 1fr);
         gap: .3rem .8rem; margin: .5rem .4rem .65rem; padding-left: .65rem;
         border-inline-start: 2px solid #888; font-size: .875rem; }}
li dt {{ font-weight: 600; }}
li dd {{ margin: 0; overflow-wrap: anywhere; }}
li small {{ font-variant-numeric: tabular-nums; }}
li.active summary {{ outline: 2px solid #c40; outline-offset: -2px; }}
@media (max-width: 760px) {{
  main {{ grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 3fr) auto auto minmax(0, 2fr) auto; }}
  .map-frame {{ display: grid; place-items: center; }}
  .route-header h1 {{ font-size: 1.4rem; }}
  li dl {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); }}
}}
</style>
{THEME_STYLE}
<header class="route-header"><h1>Vacuum Route {int(record, 16)}</h1>{THEME_CONTROL}</header>
{THEME_SCRIPT}
<p>{len(positions)} reports in capture order. Coordinates are in grid units. Lines connect successive reports and may span gaps.</p>
<main>
  <section aria-labelledby="map-heading">
    <h2 id="map-heading">Route map</h2>
    <div class="map-frame">
    <svg aria-label="Top-down route from reported positions" viewBox="{left} {top} {width} {height}" preserveAspectRatio="xMidYMid meet">
      <g class="axes" aria-hidden="true" font-size="{step * .18}">
        <defs>
          <marker id="axis-arrow" viewBox="0 0 8 8" refX="8" refY="4"
                  markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0 0 L8 4 L0 8 Z" fill="#555"/>
          </marker>
        </defs>
        <g class="grid">{''.join(grid)}</g>
        <line x1="{left}" y1="0" x2="{right}" y2="0" marker-end="url(#axis-arrow)"/>
        <line x1="0" y1="{bottom}" x2="0" y2="{top}" marker-end="url(#axis-arrow)"/>
        <text x="{right - step * .15}" y="{-step * .15}" text-anchor="end">X</text>
        <text x="{step * .15}" y="{top + step * .23}">Y</text>
        <text x="{-step * .15}" y="{step * .26}" text-anchor="end">0</text>
      </g>
      <polyline points="{cleaning_points}" fill="none" stroke="#777" stroke-width=".25"/>
      <polyline points="{home_points}" fill="none" stroke="#175b9a" stroke-width=".25"/>
      <rect x="-.6" y="-.6" width="1.2" height="1.2" fill="#c40"><title>Dock</title></rect>
      <g>{''.join(dots)}</g>
    </svg>
    </div>
    <p id="telemetry">Hover over a dot or select a report to see its telemetry. The orange square marks the dock.</p>
  </section>
  <section aria-labelledby="run-heading">
    <h2 id="run-heading">Full run</h2>
    <ol>{''.join(rows)}</ol>
    <p>Select a report to expand its telemetry and locate it on the map.</p>
  </section>
</main>
<script>
const telemetry = document.getElementById("telemetry");
let activeDot, activeRow;
function showReport(number, revealRow) {{
    activeDot?.classList.remove("active");
    activeRow?.classList.remove("active");
    activeDot = document.getElementById("dot-" + number);
    activeRow = document.getElementById("report-" + number);
    activeDot.classList.add("active");
    activeRow.classList.add("active");
    telemetry.textContent = activeDot.querySelector("title").textContent;
    if (revealRow) activeRow.scrollIntoView({{block: "nearest", inline: "nearest"}});
}}
document.querySelector("svg").addEventListener("pointerover", event => {{
    if (event.target.dataset.report) showReport(event.target.dataset.report, false);
}});
document.querySelector("svg").addEventListener("click", event => {{
    if (event.target.dataset.report) showReport(event.target.dataset.report, true);
}});
const reports = document.querySelector("ol");
for (const type of ["click", "focusin"]) {{
    reports.addEventListener(type, event => {{
        const summary = event.target.closest("summary[data-report]");
        if (summary) showReport(summary.dataset.report, false);
    }});
}}
</script>
</html>""", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture")
    parser.add_argument("record_hex")
    parser.add_argument("output", type=Path)
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "telemetry.duckdb")
    parser.add_argument("--going-home-from", type=int,
                        help="first verified return report (one past the last if none were captured)")
    args = parser.parse_args()
    render(args.database, args.capture, args.record_hex, args.output, args.going_home_from)
