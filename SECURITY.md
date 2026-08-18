# Security Policy

## Supported versions

Potato ships from a single line of releases on `master`; there are no
maintenance branches. Fixes go into the next release, so the supported version
is whatever is currently latest.

| Version | Supported |
| ------- | --------------------- |
| 2.7.x   | :white_check_mark: |
| 2.0 – 2.6 | Upgrade to 2.7.x |
| 1.x     | :x: |

## Reporting a vulnerability

**Do not open a public issue for a security problem.** Use GitHub's private
vulnerability reporting, which is enabled on this repository:

> [Report a vulnerability](https://github.com/davidjurgens/potato/security/advisories/new)

That opens a private advisory visible only to you and the maintainers. If you
would rather not use GitHub, email jurgens@umich.edu.

Please include the Potato version, the config that triggers the problem (with
credentials removed), and what an attacker gets out of it. A proof of concept
helps; a working exploit is not required.

Expect an acknowledgement within a week. We will tell you when a fix is
released and credit you in the advisory unless you ask us not to.

## What is in scope

Potato is software you host yourself, so the boundary matters:

- **In scope**: anything that lets one annotator read or change another's
  annotations; anything that lets a non-admin reach an admin route or the admin
  API key; path traversal out of `task_dir`; XSS through instance text, span
  labels, or a config field; authentication and session handling; SSRF through
  the remote data sources; unsafe deserialization of a file Potato reads.
- **Out of scope**: anything requiring an admin key you already hold, since an
  admin can already change the configuration and read every annotation. Also
  out of scope: running Potato on a public interface without a reverse proxy or
  TLS, and vulnerabilities in your own custom layout HTML or JavaScript.

Two behaviours are deliberate and documented rather than defects. The
`--load-binary-meta` flag on the ConvoKit importer unpickles a downloaded file,
which executes arbitrary code — it is off by default and
[documented as dangerous](docs/integrations/convokit.md). Debug mode
(`debug: true`) bypasses admin authentication on purpose, and is
[documented as a development-only setting](docs/tools/debugging_guide.md).

## Hardening a deployment

- Set `admin_api_key` explicitly rather than relying on the generated
  `admin_api_key.txt`, and keep that file out of version control.
- Put Potato behind a reverse proxy that terminates TLS. See
  [Reverse Proxy / URL Prefix](docs/deployment/reverse-proxy.md).
- Use `require_password: true` for anything beyond a local pilot; passwordless
  login accepts any username without verification.
- Keep `debug: false` outside development.
