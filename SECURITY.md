# Security Policy

## Supported Versions

Security fixes are released for the latest published `videovector` package version.

## Reporting a Vulnerability

Do not open a public issue for suspected credential exposure, authentication bypass, data isolation, or remote execution vulnerabilities.

Report security issues by contacting Vector Methods through the private support channel listed in your customer agreement or through the security contact published on the Vector Methods website. Include:

- affected package version
- minimal reproduction details
- impact and affected API surface
- whether any credentials, customer media, or webhook secrets may be exposed

## Credential Safety

- Never commit API keys, bearer tokens, cloud provider secrets, service account JSON, webhook signing secrets, or downloaded export URLs.
- Load credentials from a secret manager or environment variables.
- Treat values returned by `client.api_keys.create`, `client.api_keys.rotate`, `client.webhooks.create`, and `client.webhooks.rotate_secret` as one-time secrets.
- Rotate credentials immediately if they are printed, logged, committed, or shared outside their intended environment.

