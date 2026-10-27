# Security Policy

## Supported Versions

Security fixes are applied to the latest release (currently 0.2.x).

## Reporting a Vulnerability

Please do **not** open a public issue containing API keys, cookies, tokens, or
other personal data.

Use GitHub's private vulnerability reporting / Security Advisories for this
repository. If that is unavailable, open a minimal issue asking for a private
contact channel without including sensitive details.

## Secret Handling

- `.env` is ignored by git. Never commit it.
- The tool reads the PC client's local cookies; it does not store passwords.
- If an API key or cookie is exposed, rotate/revoke it immediately.
- Release binaries built from this repository do not contain your `.env`;
  they read it from the executable's directory at runtime.
