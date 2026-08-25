# GetMyMeter for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://www.hacs.xyz/docs/faq/custom_repositories/)
[![Validate](https://github.com/Brandon168/homeassistant-getmymeter/actions/workflows/validate.yml/badge.svg)](https://github.com/Brandon168/homeassistant-getmymeter/actions/workflows/validate.yml)

An unofficial, read-only Home Assistant integration for water meters available through the GetMyMeter / H2O Analytics customer portal.

## Features

- Current hourly, daily, monthly, and cumulative water usage in gallons
- Full hourly, daily, and monthly history backfilled into Home Assistant long-term statistics
- Home Assistant Energy dashboard water-source support
- Config-flow setup, reauthentication, reconfiguration, and redacted diagnostics
- Cloud polling with read-only HTTPS requests

## Installation

### HACS (recommended)

1. Open **HACS → Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add:

   ```text
   https://github.com/Brandon168/homeassistant-getmymeter
   ```

   Select **Integration** as the category.
4. Search for and install **GetMyMeter**.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration → GetMyMeter**.

### Manual installation

1. Download the latest GitHub release.
2. Copy `custom_components/getmymeter` into your Home Assistant `custom_components` directory.
3. Restart Home Assistant.
4. Add **GetMyMeter** from **Settings → Devices & services**.

## Configuration

The setup form maps directly to the portal's `/ami_data` request:

| Home Assistant field | Portal value |
|---|---|
| `cid` (company ID) | The `cid` query value, usually `138` |
| `l` (account number) | The complete `l` query value |
| `c` (meter channel) | The `c` query value, usually `1` |
| `h2o-token` request header | The complete `h2o-token` Request Headers value, including `<token>` and `</token>` |

To find these values:

1. Sign in to GetMyMeter.
2. Open your browser's **Developer Tools → Network** panel.
3. Filter for `ami_data`, then select **Daily** or **Monthly** in the portal.
4. Open the `/ami_data` request and copy `cid`, `l`, and `c` from its query string.
5. Copy the complete `h2o-token` value from **Request Headers**.
6. Enter the four values in the Home Assistant setup form.

The similarly named portal page value and browser cookie are not the API header and will be rejected.

**Optional: console helper.** Instead of digging through the Network panel, paste this snippet into the portal's browser console (**F12 → Console**) while signed in, then click **Daily** or **Monthly** in the portal. It prints the four values to copy into Home Assistant:

```js
(() => {
  const seen = new Set();
  function capture(url, token) {
    if (!url || !String(url).includes('/ami_data')) return;
    try {
      const u = new URL(url, location.href);
      const key = u.search + '|' + token;
      if (seen.has(key)) return;
      seen.add(key);
      console.log('%cGetMyMeter credentials (copy these into Home Assistant):', 'color:#2e7d32;font-weight:bold');
      console.log('  cid: ' + u.searchParams.get('cid'));
      console.log('  l:   ' + u.searchParams.get('l'));
      console.log('  c:   ' + u.searchParams.get('c'));
      console.log('  h2o-token: ' + token);
    } catch (e) {}
  }
  const origFetch = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    let token = null;
    if (init && init.headers) { try { token = new Headers(init.headers).get('h2o-token'); } catch (e) {} }
    if (String(url).includes('/ami_data')) capture(url, token);
    return origFetch.apply(this, arguments);
  };
  const o = XMLHttpRequest.prototype;
  const open = o.open, setH = o.setRequestHeader, send = o.send;
  o.open = function(m, url, ...r) { this.__url = url; this.__token = null; return open.call(this, m, url, ...r); };
  o.setRequestHeader = function(n, v) { if (String(n).toLowerCase() === 'h2o-token') this.__token = v; return setH.call(this, n, v); };
  o.send = function(...a) { capture(this.__url, this.__token); return send.apply(this, a); };
  console.log('%cGetMyMeter helper armed. Now click Daily or Monthly in the portal to capture values.', 'color:#1565c0;font-weight:bold');
})();
```

This helper only reads your own browser session's requests and prints the values locally — it does not contact any server or send your credentials anywhere. If it captures nothing, fall back to the Network-panel method above.

## Entities

| Entity | Description |
|---|---|
| Latest hourly usage | Most recent hourly usage value |
| Daily usage | Most recent complete daily total |
| Monthly usage | Most recent complete monthly total |
| Cumulative usage | Current cumulative meter reading |

All values are reported in gallons. The portal can lag behind Home Assistant's refresh time.

## Historical data

The integration imports hourly, daily, and monthly records into Home Assistant Recorder as three separate external statistics. For the Energy dashboard, use the hourly statistic as the water source:

```text
getmymeter:meter_<identity_hash>_raw
```

Keep hourly, daily, and monthly statistics separate because they represent overlapping periods.

### Why the history is re-imported

Two properties of the portal shape this design:

1. **The portal has no date-range filter.** The `/ami_data` endpoint always returns a bucket's complete series, so the integration receives the full history on every poll regardless of what it asks for.
2. **The portal is the source of truth.** Utility reads are occasionally corrected retroactively (an estimated read replaced by an actual read), so Home Assistant should converge on the portal's current values rather than freeze at the first import.

Home Assistant's statistics import is an idempotent upsert keyed on period start, so re-importing the same history updates existing rows instead of duplicating them. That makes "always re-import" correct — but re-processing thousands of rows every six hours is wasteful when only the newest period has changed.

The history worker therefore imports incrementally:

- **First run after startup** performs a full replay, backfilling the complete series.
- **Subsequent runs** import only rows newer than the last imported period, seeding the running cumulative so reconstructed sums stay continuous.
- **Every fourth run** (roughly daily at the six-hour cadence) performs a full replay again, so retroactive corrections converge within a day.

The network transfer is unchanged — the portal always sends the full series — but the per-cycle build and import work drops to just the new rows.

## Reauthentication

If the portal rejects an expired credential, Home Assistant opens a reauthentication flow. Generate a fresh `/ami_data` request and enter its complete `h2o-token` Request Headers value.

## Compatibility

- Home Assistant 2026.8.3 or newer
- HACS or manual custom-component installation
- An active GetMyMeter / H2O Analytics portal account

## Support

Open an issue with:

- Home Assistant version
- Integration version
- Redacted GetMyMeter diagnostics
- A description of the expected and actual behavior

Do not include account numbers or authentication values in issues.

## Disclaimer

This project is not affiliated with GetMyMeter, H2O Analytics, or your water utility. The portal interface is undocumented and may change without notice.

## License

[MIT](LICENSE)
