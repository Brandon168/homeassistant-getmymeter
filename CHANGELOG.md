# Changelog

## 0.2.2 - 2026-10-18

- Await the coordinator refresh after a history authentication failure so recovery actually runs instead of creating an un-awaited coroutine.
- Added regression coverage for authentication failures in each history bucket and for ordinary fetch failures.
- Corrected portal wall-clock timestamps to use Home Assistant's configured timezone, including daylight-saving offsets, for sensor timestamps and historical statistics. This includes the previously committed but unpublished 0.2.1 correction.
- Updated HACS installation instructions and the badge now that GetMyMeter is in the default repository list; adding a custom repository is no longer required.

## 0.2.0

- Replaced manual `/ami_data` token setup with username/password login and automatic meter discovery.
- Added transparent relogin and one retry when a portal session expires.
- Added a one-time migration flow for existing token-only config entries.
- Session tokens and cookies are now transient and are not stored in config entries.

All notable changes to this integration are recorded here.

## 0.1.3 - 2026-08-25

- Declared the minimum supported Home Assistant version in `hacs.json` so HACS does not offer the integration to users on older releases.

## 0.1.2 - 2026-08-25

- Made history import incremental: the first run and every fourth run perform a full replay, while runs in between import only rows newer than the last imported period.
- Documented why the integration re-imports history in the README.

## 0.1.1 - 2026-08-24

- Clarified the setup, reauth, and reconfigure forms so each field names the matching `/ami_data` query or `h2o-token` request header, including the required `<token>` wrapper.
- Reworked the README as a concise HACS-first installation and configuration guide.
- Documented the hourly statistic as the Home Assistant Energy water source.

## 0.1.0 - 2026-08-24

- Initial publication-quality read-only integration.
- Added fixed-origin, timeout-bounded, redirect-free AMI requests with safe authentication-page handling.
- Added raw/hourly, daily, cumulative, and monthly current sensors.
- Added deterministic, idempotent raw/daily/monthly external-statistics replay and backfill.
- Added stable hashed config-entry, entity, and statistic identifiers.
- Added reauthentication, reconfiguration, redacted diagnostics, HACS metadata, tests, and a synthetic water dashboard example.
