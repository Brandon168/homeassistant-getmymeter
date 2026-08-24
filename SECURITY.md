# Security policy

## Scope

GetMyMeter is an unofficial, read-only Home Assistant integration. It sends the sensitive `h2o-token` request header only to the fixed HTTPS origin documented in the README. It does not implement portal mutations.

## Reporting a vulnerability

Please do not open a public issue for a suspected credential, token, redirect, URL-boundary, or privacy vulnerability. Use the private security-reporting mechanism provided by the repository owner at:

https://github.com/Brandon168/homeassistant-getmymeter/security

If that mechanism is unavailable, contact the maintainer through the repository profile before disclosing technical details. Include a minimal reproduction that contains no token, cookie, account identifier, browser capture, raw response, or personal data.

## Safe reports

- Never send a live token, password, cookie, authorization header, or copied request.
- Never attach a HAR, screenshot, console dump, database, diagnostics file containing unreviewed data, or raw portal response.
- Use synthetic identifiers and payloads wherever possible.
- State the Home Assistant version, integration version, and the smallest non-sensitive reproduction.

Security fixes are released under the version shown in `manifest.json` and summarized in `CHANGELOG.md`.
