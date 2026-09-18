# Partial MQTT telemetry reporting

## Diagnosis and scope

Prepared against `branko-lazarevic/esysunhome` main, revision
`8aef3706f` (manifest 2.2.3). The inspected installed-source fork,
`binaryzer0/esysunhome` at `be8e7d6`, has manifest 2.1.11.
Apply this change to upstream 2.2.3, not directly over the stale fork.

The parser retained complete segments before a truncated segment, then filled
absent measurements with defaults. The coordinator already merges incoming
fields into its last-good cache, but synthesized zeros and Regular Mode
incorrectly overwrote that cache. The select independently started at Regular
Mode before receiving telemetry. Neither behavior proves a physical mode change.

This follows the presence-guard approach from doctordarko's
[PR #25](https://github.com/branko-lazarevic/esysunhome/pull/25), extending it to
status-only packets, dependencies within a domain, and three-phase normalization.
It also incorporates the diagnostics preload/type-only-import approach from
[PR #26](https://github.com/branko-lazarevic/esysunhome/pull/26), without swallowing
import errors. Both PR heads were inspected directly, and neither was merged in
the inspected upstream main.

## Reporting behavior

- Empty, truncated-before-first-segment, and unknown-register-only messages
  produce no entity update. Complete recognized segments before a truncated
  segment remain usable.
- Missing measurements are omitted, preserving previously received values in
  the coordinator. Before the first valid reading, an entity remains unknown.
  Actual reported zero values remain valid, including SOC and operating mode 0.
- PV sums require all inputs defined for the device, or a directly reported PV
  total. A lone phase cannot become a three-phase grid total. Battery magnitude
  can update independently, but directional power requires battery status too.
- Three-phase flow normalization requires PV, grid, battery direction, and load
  from the same packet. It cannot create absent sources from defaults.
- Only `systemRunMode` can derive a mode name. `systemRunStatus` alone cannot
  change operating mode. The select starts unknown and retains its last known
  option on a missing-mode update, while still publishing availability changes.
- Truncation logs use DEBUG, with actual payload length, available segment bytes,
  parsed segment header fields, and at most the first 64 payload bytes in hex.
  The outer MQTT header (which contains a user ID) is not included in that dump.
- Diagnostics loads in the executor, uses the correctly named coordinator only
  for type checking, and exports the current `TelemetryData` container correctly.

No mode/setpoint write path, automation, polling interval, or deployment was
changed. Poll-interval configuration is deferred to a separate change. Many
optional sensors are explicitly disabled by default in source; that is separate
from parsing. Issue #17 describes config-entry disabling, a different condition.

Without an actual affected-device capture, the reason for the malformed segment
length cannot be established. Upstream already detects protocol parameters from
device info; the byte dump can help distinguish truncation from layout mismatch.
An HM6 model name alone does not establish the installation's phase count.

## Verification

From the repository root, using Python 3.14:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.test.txt aiomqtt aiohttp
.venv/bin/python -m pytest -q
```

The regression tests use synthetic binary packets and real parser, coordinator,
and HA entity code without connecting to the inverter. They cover two valid
segments followed by a segment claiming 1642 bytes with only 202 available, every
byte truncation boundary, status-only packets, missing dependencies, true zeros,
mode retention and genuine mode transitions, diagnostics preload/export, and
existing three-phase behavior. The original three-phase fixtures now explicitly
provide zero-valued second-PV and AC-PV inputs instead of treating their absence
as zero.

Local verification used Home Assistant 2026.9.2,
pytest-homeassistant-custom-component 0.13.365, pytest 9.0.3, and Python 3.14.4.
The owner's exact HA 2026.9.0 instance and physical HM6 were not accessed.

After installing the patched upstream integration and restarting HA, keep the
owner's battery-commanding automations disabled. Observe multiple normal poll
cycles: no warning-level truncation spam, no temporary Regular Mode reversions,
and no power zero spikes. Enable integration debug logging temporarily if packet
layout evidence is needed. Verify diagnostics downloads and startup logs.
Hold-last-good deliberately does not impose a new per-sensor expiry policy;
connection availability continues to follow the existing coordinator behavior.
