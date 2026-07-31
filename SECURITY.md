# Security policy

## Supported versions

Security fixes are made on the latest version on the default branch. Older releases are not supported.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use [GitHub private security reporting](https://github.com/DurdeuVlad/trinity-pilot/security/advisories/new) and include:

- affected version and platform;
- a minimal reproduction or proof of concept;
- impact and any known mitigations.

Maintainers will acknowledge a valid report within 7 days and coordinate disclosure and a fix where practical.

## Scope and safety boundary

Trinity Pilot can operate a browser, desktop applications, and a local PowerShell terminal. Terminal execution is **not sandboxed**: commands run with the permissions of the user who launches the app and can read, modify, or delete accessible files, start processes, and access network resources. Treat task text, browser content, and model output as potentially untrusted. Do not use it with credentials, systems, or data you cannot afford to expose or change.

See [Privacy and safety](docs/PRIVACY_AND_SAFETY.md) for the data-flow and operating guidance.
