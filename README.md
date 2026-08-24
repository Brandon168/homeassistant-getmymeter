# GetMyMeter for Home Assistant

GetMyMeter is an unofficial, read-only Home Assistant integration for the H2O Analytics water-meter portal. It is designed for Home Assistant 2026.8.3 and newer releases that preserve the public APIs used by this project. Version 0.1.0 is the first publication-quality release target.

The integration makes only HTTPS GET requests to the fixed origin `https://h2o-analytics.appspot.com`, and it does not change portal data. The portal interface and its token header are undocumented and may change without notice.

## Install with HACS

1. Open HACS → Integrations.
2. Select the menu → Custom repositories.
3. Add `https://github.com/Brandon168/homeassistant-getmymeter` with type **Integration**.
4. Install **GetMyMeter** and restart Home Assistant.
5. Open Settings → Devices & services → Add integration → GetMyMeter.

See the official [HACS documentation](https://www.hacs.xyz/docs/faq/custom_repositories/) and Home Assistant's [integration setup documentation](https://www.home-assistant.io/integrations/).

## Manual installation

Download a release from this repository, copy only its `custom_components/getmymeter/` directory into the `custom_components/` directory of your Home Assistant configuration, and restart Home Assistant. Do not copy test files, development files, archives, browser captures, or local configuration files.

Home Assistant's [custom integration guidance](https://developers.home-assistant.io/docs/creating_integration_manifest/) explains the directory layout. Do not edit `.storage` files by hand.

## Configure safely

The form asks for a company ID, account identifier, channel, and the sensitive `h2o-token` value. It does not accept the portal username or password. The company and channel defaults are only suggestions; use the values shown by your own portal session.

To find the values without saving or sharing a browser capture:

1. Sign in to your own GetMyMeter portal in a private browser window.
2. Open the browser's Developer Tools → Network panel. Enable the option that preserves the network log only if you understand that it retains private data locally.
3. Filter requests for `ami_data`, then open the request made when the meter data is displayed.
4. In the request URL query, manually read the `cid` (company), `l` (account), and `c` (channel) values. Enter them directly into the Home Assistant form.
5. In request headers, manually read the value of the `h2o-token` header. Paste that value directly into the masked Home Assistant token field.
6. Clear the Network panel and close Developer Tools when finished.

Never use **Save all as HAR**, **Copy as cURL**, a screenshot, a console dump, or an issue attachment for this process. Do not save, commit, upload, email, or share the token, cookies, authorization headers, full request URL, or portal response. A token is not a password for the portal and is sensitive configuration data even though Home Assistant masks it in the form.

The fixed endpoint is `https://h2o-analytics.appspot.com/ami_data`. The token is sent only in the `h2o-token` request header. Requests have an explicit timeout and redirects disabled. Login pages and other HTML responses are rejected without retaining their body.

## Runtime behavior

- The integration polls about every six hours.
- Daily data is the primary live source. The daily sensor and cumulative meter remain usable if raw or monthly history is temporarily unavailable.
- Four read-only water sensors are provided: latest raw/hourly usage, latest daily usage, cumulative meter reading, and latest monthly usage.
- Every live bucket is retried on a later refresh. A daily authentication failure requests reauthentication; a non-authentication raw or monthly failure is isolated and does not make daily data unavailable.
- Values are reported in gallons and include only the bucket key and source timestamp as state attributes.
- The portal may be several hours behind the Home Assistant refresh time. `sample_timestamp` is the portal timestamp in UTC; the entity last-updated time is the Home Assistant refresh time.

## Long-term statistics and backfill

After Home Assistant starts, a per-entry history worker replays the complete returned `r`, `d`, and `m` payloads. It repeats at the polling cadence and has no completion flag or destructive migration. Home Assistant Recorder's external-statistics upsert behavior makes restarts and corrections idempotent.

The worker creates three separate external statistics IDs:

- `getmymeter:meter_<identity-hash>_raw`
- `getmymeter:meter_<identity-hash>_daily`
- `getmymeter:meter_<identity-hash>_monthly`

The identity hash is the lowercase hexadecimal SHA-256 digest of the exact company, account, and channel strings joined with one U+001F unit-separator character. The token and Home Assistant config-entry UUID are never inputs. The daily series is the canonical GetMyMeter water source for the Energy dashboard; raw, daily, and monthly series must not be combined because their periods overlap.

Each row uses usage as `state` and the portal cumulative meter reading as `sum`, with `mean_type=NONE`, `has_sum=true`, source `getmymeter`, volume unit class, and gallons. A missing cumulative value is reconstructed deterministically from the sorted series and is reported in diagnostics. A source cumulative decrease is preserved and counted rather than silently clamped.

Timestamps are normalized in UTC at the top of the hour. A raw `xx:59:59` boundary marker is moved to the following hour before flooring. Daily rows use the UTC day start and monthly rows use the UTC month start. The current incomplete raw hour, day, or month is not imported. Rows that canonicalize to the same hour use the latest source timestamp; a later correction at that same canonical start updates the existing Recorder row instead of creating an overlapping series.

Recorder import is queued through Home Assistant's public [`async_add_external_statistics`](https://developers.home-assistant.io/docs/core/entity/sensor/#long-term-statistics) API. It is safe to replay the same payload and it does not manufacture an hourly entity from history.

## Dashboard

Home Assistant supports water sources in its Energy dashboard and exposes the Energy water cards for reuse on ordinary dashboards.[1][2] The synthetic [water dashboard example](examples/water-dashboard.yaml) shows the built-in `energy-date-selection`, `energy-water-graph`, `energy-sources-table`, and `statistics-graph` card types. The statistics graph card accepts external statistic IDs, which lets the detailed charts use the imported GetMyMeter series directly.[3] Configure the daily external statistic as a water source in Settings → Dashboards → Energy, then replace the synthetic placeholders in the example with the actual statistic/entity IDs from your installation. Do not add the raw and monthly series to the same Energy source.

See the official [Energy dashboard documentation](https://www.home-assistant.io/docs/energy/), [statistics graph card documentation](https://www.home-assistant.io/dashboards/statistics-graph/), and [Lovelace dashboard documentation](https://www.home-assistant.io/dashboards/).

## Reauthentication and reconfiguration

Tokens can expire. Use the Home Assistant reauthentication prompt for this entry and paste only a newly observed `h2o-token` header value. The replacement is validated with a read-only daily request before the entry is updated. The reconfigure flow can change the company, account, or channel, but it requires a current token and creates a new stable identity hash; old Recorder statistics are not deleted.

If the portal is down, the integration reports a connection error and retries during the next refresh. It does not retry by following redirects or by sending credentials to another host.

## Limitations and privacy

- This project depends on an undocumented portal endpoint and header. Vendor-side changes can break setup or history imports.
- The integration is read-only and does not support billing, account, session, or portal mutations.
- History imports depend on the portal returning complete bucket payloads and on Recorder being enabled. A missing optional bucket is visible in diagnostics and is retried.
- The raw/hourly series is historical statistics only; the latest raw value is exposed as a current sensor. Raw, daily, and monthly values are different period observations.
- Diagnostics contain only redacted configuration, counts, timestamps, fixed transport policy, and aggregate replay status. They do not contain tokens, account identifiers, raw responses, headers, or usage values.

For an issue, first download the redacted GetMyMeter diagnostics from Home Assistant. Before posting anything, remove tokens, account/company/channel identifiers, cookies, authorization headers, full URLs, addresses, meter identifiers, timestamps that identify a household, screenshots, and raw portal responses. Never attach a browser capture or a copied request. Use the repository's [issue tracker](https://github.com/Brandon168/homeassistant-getmymeter/issues).

For security reports, follow [SECURITY.md](SECURITY.md) rather than opening a public issue.

## Development

The test suite uses synthetic inline payloads and the `pytest-homeassistant-custom-component` harness; it does not require a portal session. The exact target is Home Assistant 2026.8.3. Run the commands in `.github/workflows/validate.yml` before a release.

## Official references

- [Home Assistant integration manifest](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [Config entries and config flows](https://developers.home-assistant.io/docs/config_entries_config_flow_handler/)
- [Diagnostics](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/diagnostics/)
- [HACS custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/)
- [Energy dashboard](https://www.home-assistant.io/docs/energy/)

## Sources

[1] [Energy cards - Home Assistant](https://www.home-assistant.io/dashboards/energy/)

[2] [Integrating your water usage - Home Assistant](https://www.home-assistant.io/docs/energy/water/)

[3] [Statistics graph card - Home Assistant](https://www.home-assistant.io/dashboards/statistics-graph/)
