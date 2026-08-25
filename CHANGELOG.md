# Changelog

All notable changes to this integration are recorded here.

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
