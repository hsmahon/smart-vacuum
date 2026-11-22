CREATE OR REPLACE VIEW coverage_changes AS
WITH samples_with_previous AS (
    SELECT recorded_at, state, cleaning_m2,
           lag(state) OVER w AS previous_state,
           lag(cleaning_m2) OVER w AS previous_area
    FROM telemetry
    WINDOW w AS (ORDER BY recorded_at)
), changes AS (
    SELECT *,
           CASE WHEN state IS DISTINCT FROM previous_state OR cleaning_m2 < previous_area
                     OR previous_area IS NULL THEN true ELSE false END AS baseline
    FROM samples_with_previous
    WHERE state IS DISTINCT FROM previous_state OR cleaning_m2 IS DISTINCT FROM previous_area
), timed AS (
    SELECT *, lag(recorded_at) OVER (ORDER BY recorded_at) AS previous_change_at
    FROM changes
)
SELECT recorded_at, state, cleaning_m2,
       round(cleaning_m2 - previous_area, 2) AS added_m2,
       round(epoch(recorded_at - previous_change_at), 1) AS seconds_since_change
FROM timed
WHERE NOT baseline AND cleaning_m2 > previous_area
  AND state IN ('smart_clean','cleaning','spot_clean','wall_clean','mop_clean');
