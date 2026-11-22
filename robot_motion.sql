-- source_offset orders JSONL rows. Only the offset encoded in the MCU frame
-- establishes continuity, including packets that contain no position points.
CREATE OR REPLACE VIEW robot_motion AS
WITH packets AS (
    SELECT packet_id, capture_name, source_offset, received_at, record_hex,
           CASE WHEN decode_error IS NULL AND
                     (try_cast(raw AS JSON) ->> 'format') = 'tuya_mcu_map'
                THEN hex(frame) END AS wire
    FROM route_packets
), offsets AS (
    SELECT *, ('0x' || substr(wire, 17, 8))::BIGINT AS byte_offset,
           length(wire) // 2 - 13 AS payload_length
    FROM packets
), boundaries AS (
    SELECT *, CASE WHEN wire IS NULL OR byte_offset = 0
             OR byte_offset IS DISTINCT FROM lag(byte_offset + payload_length) OVER w
             OR record_hex IS DISTINCT FROM lag(record_hex) OVER w
             OR substr(wire, 7, 2) IS DISTINCT FROM lag(substr(wire, 7, 2)) OVER w
             THEN 1 ELSE 0 END AS boundary
    FROM offsets WINDOW w AS (PARTITION BY capture_name ORDER BY source_offset)
), segments AS (
    SELECT *, sum(boundary) OVER (PARTITION BY capture_name ORDER BY source_offset) AS segment
    FROM boundaries
), origins AS (
    SELECT s.*, p.point_index, p.point_type, p.x, p.y,
           CASE WHEN min(p.x) FILTER (WHERE point_type=3) OVER w =
                     max(p.x) FILTER (WHERE point_type=3) OVER w AND
                     min(p.y) FILTER (WHERE point_type=3) OVER w =
                     max(p.y) FILTER (WHERE point_type=3) OVER w THEN
                     min(p.x) FILTER (WHERE point_type=3) OVER w END AS dock_x,
           min(p.y) FILTER (WHERE point_type=3) OVER w AS dock_y
    FROM segments s JOIN route_points p USING (packet_id)
    WHERE wire IS NOT NULL WINDOW w AS (PARTITION BY capture_name, segment)
), steps AS (
    SELECT capture_name, segment, record_hex, source_offset, byte_offset,
           received_at, point_index, x, y, x-dock_x AS dock_dx,
           CASE WHEN dock_x IS NOT NULL THEN y-dock_y END AS dock_dy,
           x-lag(x) OVER w AS dx, y-lag(y) OVER w AS dy
    FROM origins WHERE point_type=0
    WINDOW w AS (PARTITION BY capture_name, segment ORDER BY source_offset, point_index)
)
SELECT *, sqrt(dx::DOUBLE ** 2 + dy::DOUBLE ** 2) AS step_grid_units,
       CASE WHEN dx<>0 OR dy<>0 THEN degrees(atan2(dy,dx)) END AS direction_grid_deg
FROM steps;

-- Supply the measured outbound displacement in grid units and metres.
-- handedness is +1 if a known left turn is counterclockwise in raw x,y.
CREATE OR REPLACE MACRO calibrated_robot_motion(out_x, out_y, leg_metres, handedness) AS TABLE
WITH calibration AS (
    SELECT out_x::DOUBLE AS a, out_y::DOUBLE AS b,
           a*a+b*b AS norm2
    WHERE leg_metres > 0 AND handedness IN (-1,1) AND norm2 > 0
)
SELECT m.*, (dock_dx*a+dock_dy*b)*leg_metres/norm2 AS x_metres,
       handedness*(dock_dy*a-dock_dx*b)*leg_metres/norm2 AS y_metres,
       step_grid_units*leg_metres/sqrt(norm2) AS step_metres,
       CASE WHEN dx<>0 OR dy<>0 THEN
           degrees(atan2(handedness*(dy*a-dx*b), dx*a+dy*b)) END AS travel_direction_deg
FROM robot_motion m CROSS JOIN calibration;

CREATE OR REPLACE VIEW gyro_positions AS
WITH points AS (
    SELECT capture_name, record_hex, received_at, source_offset, point_index,
           try_cast(split_part(r.packet_id, '-', 2) AS INTEGER) AS record_index,
           point_type, x, y
    FROM route_packets r JOIN route_points USING (packet_id)
    WHERE json_exists(try_cast(raw AS JSON), '$.payload_hex') AND decode_error IS NULL
), docks AS (
    SELECT capture_name, record_hex, min(x) AS dock_x, min(y) AS dock_y
    FROM points WHERE point_type = 3 GROUP BY capture_name, record_hex
    HAVING min(x) = max(x) AND min(y) = max(y)
)
SELECT p.*, dock_x, dock_y, x - dock_x AS x_from_dock, y - dock_y AS y_from_dock
FROM points p LEFT JOIN docks USING (capture_name, record_hex)
WHERE point_type = 0;
