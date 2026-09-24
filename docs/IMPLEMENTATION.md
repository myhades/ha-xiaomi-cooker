# Local implementation validation

Date: 2026-09-24. Base: v0.2.0 (`1f219b6`). Local version: 0.4.0 (unreleased).

- One integration with separate legacy and CMC301 backends; serialized device I/O.
- CMC301: 13 bundled recipes, validated parameter editing, atomic named-recipe action,
  device feedback, settings with readback, independent stop and panel recipe save.
- normal3: start/stop RPCs, existing entity identifiers and work-status enums
  retained; temperature-history prefix/AA parsing and cache handling fixed.
  Eleven current official templates, isolated from other legacy models, now back
  duration/taste selectors and a next-cook auto keep-warm switch.
- Configuration accepts token BOM/whitespace and surfaces absent device information.
- Initial implementation was offline. Subsequent user-authorized bounded hardware
  acceptance is recorded in [the hardware report](HARDWARE_VALIDATION.zh-CN.md).
  No Home Assistant deployment or GitHub Release publication was performed.

Validation: **196 tests passed in each environment** on WSL Ubuntu: Python
3.14.7 / Home Assistant 2026.8.0 and 2026.9.3,
with python-miio 0.5.12 and construct 2.10.68. Tests use real HA classes and
fake transports, with real device discovery/send blocked. Ruff check, formatting
check and `git diff --check` passed. Dependency deprecation warnings remain in
python-miio and Home Assistant; no integration test failed.

HA runtime data now belongs to typed config entries. Actions live in services.py,
register during integration setup, and resolve loaded entries at invocation time.
The supported minimum is HA 2026.8.0. Device targeting uses config_entry_id and
the public composite-split lookup without pre-2026.8 compatibility branches. Additional lifecycle
and service-target tests cover unload, reload, first-refresh failure, duplicate
targets, and rejection before any device start. Identity-preserving reconfiguration,
allowlisted offline diagnostics, translated command/validation errors and backend/codec
Protocol contracts are implemented and tested. Static contract checking passed. See the
[modernization audit](HA_MODERNIZATION.zh-CN.md).

Coverage includes all official template checksums, parameter limits, preserved
heating program bytes, RPC shape, partial property failures, time units, history
markers, settings read-modify-write/readback, start timeout without retry, remote
permission checks, independent stop, duplicate button presses, separate device
drafts, service preflight, shared polling/command lock, config connection errors,
normal3 start/stop payloads, old entity IDs and old status enums. Real-device
fixtures also cover scheduled/instant starts, target duration, taste feedback,
late-arriving temperature history and clearing it when stopping.

Both backends share selector/draft lifecycle management. Next-cook auto keep-warm
availability requires coordinator availability and a capable selected recipe.
Tests cover all bundled recipe capability gates, offline/recovery, reset after
start, fresh coordinator state, preserved legacy failure behavior, and preserving
a new selection made during an in-flight start (including the same recipe key).

Both models now use a duration selector with 5/10-minute spacing and preserved
endpoints/defaults, including a single option for fixed durations. Menu changes
publish options and default selection together. Tests cover registry migration
from the old beta duration number, new normal3 menu feedback, and unchanged
platforms/templates on other legacy models. A separate offline comparison with
the supplied official JS module 10445 matched **37 parameter combinations byte
for byte**, using the official class's setters and CRC encoder.

CMC301 and normal3 expose localized stage name/description enums for running rice
menus 1/2, using their official plugins' temperature-history AA marker count. Empty,
malformed, marker-only and out-of-range histories yield unknown; non-running or
unsupported recipes never retain a previous rice phase. Running rice history
uses a 30-second refresh interval. normal3 keeps existing entity IDs and raw stage
codes, but replaces the generic python-miio stage mapping and its misspelled or
truncated English strings with the shared five-phase enum and full translations.
Automations matching the old English states must migrate to the enum keys; raw
stage codes are separate feedback, not aliases for history phase indices. Other
legacy models retain their original stage text. Malformed stage parsing is
isolated from main feedback. Tests cover phase cache expiry, failures, context
changes and independence from generic stage codes. Phase transitions are covered
by synthetic tests, not a full hardware phase trace; no additional cooking was
started for this change.

CMC301 recipe action 2.6 immediate/scheduled starts, parameter feedback and stop
were verified on firmware 1.1.3. Panel recipe action 2.5 accepted a 130-minute
congee recipe and reported mode 5, recipe 3 and duration 130 while remaining idle.
The user confirmed that the panel automatically selected the custom slot and
displayed 2:10, blinking and waiting for start. A subsequent user-authorized full
28-minute quick-rice cycle started successfully with auto keep-warm enabled; the
user then confirmed automatic entry into keep-warm. Completion with auto
keep-warm disabled and actual HA deployment remain unverified. Raw status 3 is not interpreted
as heater on/off. Empty active history is retried after 30 seconds and history
is re-read on status/recipe/fault changes; outside running rice, existing samples
retain a 120-second interval.
The old normal3 Refan/Sweet rice checksum inconsistencies are resolved by using
fresh model-specific official templates. Several other normal3 program bodies
also differ from the old repository templates; they are kept as returned by the
official service. These updated recipes and parameter controls still need normal3
hardware/HA acceptance. Other old models retain their original templates. See
[CMC301 limits](CMC301.zh-CN.md) and [normal3 sources/limits](NORMAL3.zh-CN.md).
