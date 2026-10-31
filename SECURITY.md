# Security Policy

DentalVoice Studio is a portfolio simulator for fictional dental clinics. It runs on synthetic
data only and is not intended to process real patient information.

## Supported versions

Only the `main` branch is maintained.

## Reporting a vulnerability

Please report security issues privately through GitHub: open the repository's **Security** tab
and choose **Report a vulnerability**. Do not open a public issue for a vulnerability, and do not
include real personal data in any report.

You can expect an acknowledgement within a week. Fixes are made on a branch, verified with the
test suite, and merged through a pull request.

## Scope

The threat model, controls and known limits are in
[`docs/security/threat-model.md`](docs/security/threat-model.md). Missing production features
listed there as residual risks (for example, a shared rate-limit store or TLS inside the app)
are known and documented rather than vulnerabilities.
