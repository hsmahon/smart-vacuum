# Working on smart-vacuum

- Use Python 3.10+ and the dependencies in `requirements.txt`. Run entry points from the project root.
- Keep cloud credentials and LAN keys in `~/.config/smart-vacuum/` with restrictive permissions. Keep device IDs, account details, raw captures, databases, and actual floor plans out of Git, logs shared publicly, and issue attachments. Use synthetic packets and placeholder identifiers for examples.
- `scripts/vacuumctl.py` handles cloud control. `scripts/gyro_channel.py` records MQTT map envelopes. `scripts/gyro_frames.py` checks framing and CRC. `scripts/route_db.py` imports the raw envelope and decoded points. `gyro_positions` is the query surface for actual position reports. The separate `scripts/lan_capture.py` records authenticated LAN status.
- Preserve receipt time, capture order, map IDs, raw bytes, and decode errors. Preserve compatibility with existing MCU and SDK JSONL captures. When deriving motion, use robot-position points and document packet gaps, calibration and units. A steering acknowledgement confirms receipt rather than movement.
- Verify parsing and DuckDB imports with synthetic data before testing against a real device. Check that replaying a capture does not duplicate rows. For an authorized movement test, keep it bounded, send the vacuum home afterward, and verify the final reported state.
- Before publishing, inspect the staged file list and scan staged content for secrets and private telemetry. Generated route artifacts and owner-specific investigation notes stay local.
