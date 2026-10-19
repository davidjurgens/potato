# SSO & OAuth Authentication

Potato supports single sign-on (SSO) via OAuth 2.0 and OpenID Connect (OIDC). Annotators can log in with their existing Google, GitHub, or institutional accounts instead of creating a separate password.

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Provider Setup Guides](#provider-setup-guides)
   - [Google](#google-oauth)
   - [GitHub](#github-oauth)
   - [HuggingFace](#huggingface-oauth)
   - [Generic OIDC](#generic-oidc-provider)
   - [SAML 2.0 (institutional sign-in)](#saml-20-institutional-sign-in)
4. [Configuration Reference](#configuration-reference)
5. [Mixed Mode (SSO + Local Login)](#mixed-mode)
6. [Security Considerations](#security-considerations)
7. [Troubleshooting](#troubleshooting)
8. [FAQ](#faq)

---

## Overview

**Benefits:**
- No password management for annotators
- Use institutional identity (university, company) for access control
- Restrict access by email domain or GitHub organization
- Works alongside local password login if needed

**Requirements:**
- HTTPS deployment (required by OAuth spec; `localhost` is exempted for development)
- A stable Flask secret key (for persistent sessions)
- OAuth app credentials from your chosen provider

---

## Quick Start

### Minimal Google OAuth Setup (5 minutes)

**Step 1: Create Google OAuth credentials**

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project (or select existing)
3. Click "Create Credentials" > "OAuth client ID"
4. Application type: "Web application"
5. Add authorized redirect URI: `https://your-domain.com/auth/callback/google`
   - For local development: `http://localhost:8000/auth/callback/google`
6. Copy the **Client ID** and **Client Secret**

**Step 2: Set environment variables**

```bash
export GOOGLE_CLIENT_ID="your-client-id-here.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your-client-secret-here"
export POTATO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

**Step 3: Configure Potato**

```yaml
annotation_task_name: "My Annotation Task"

authentication:
  method: "oauth"
  providers:
    google:
      client_id: ${GOOGLE_CLIENT_ID}
      client_secret: ${GOOGLE_CLIENT_SECRET}
  user_identity_field: "email"

secret_key: ${POTATO_SECRET_KEY}

# ... rest of your config (data_files, annotation_schemes, etc.)
```

**Step 4: Run**

```bash
python potato/flask_server.py start config.yaml -p 8000
```

Annotators will see a "Sign in with Google" button on the login page.

---

## Provider Setup Guides

### Google OAuth

#### Prerequisites

- A Google account
- Access to [Google Cloud Console](https://console.cloud.google.com/)

#### Step-by-Step Setup

1. **Create a Google Cloud project** (if you don't have one):
   - Go to https://console.cloud.google.com/
   - Click the project dropdown > "New Project"
   - Name it (e.g., "Potato Annotation")
   - Click "Create"

2. **Configure the OAuth consent screen**:
   - Go to "APIs & Services" > "OAuth consent screen"
   - User type: "External" (unless using Google Workspace)
   - Fill in required fields:
     - App name: Your annotation project name
     - User support email: Your email
     - Developer contact: Your email
   - Scopes: Add `email` and `profile`
   - Test users: Add your own email (for testing before publishing)
   - Click "Save and Continue" through all steps

3. **Create OAuth credentials**:
   - Go to "APIs & Services" > "Credentials"
   - Click "+ Create Credentials" > "OAuth client ID"
   - Application type: "Web application"
   - Name: "Potato" (or whatever you prefer)
   - Authorized JavaScript origins:
     - `https://your-domain.com`
     - `http://localhost:8000` (for development)
   - Authorized redirect URIs:
     - `https://your-domain.com/auth/callback/google`
     - `http://localhost:8000/auth/callback/google` (for development)
   - Click "Create"
   - **Save the Client ID and Client Secret**

4. **Set environment variables**:

   ```bash
   export GOOGLE_CLIENT_ID="123456789-abc.apps.googleusercontent.com"
   export GOOGLE_CLIENT_SECRET="GOCSPX-abc123..."
   ```

5. **Add to your Potato config**:

   ```yaml
   authentication:
     method: "oauth"
     providers:
       google:
         client_id: ${GOOGLE_CLIENT_ID}
         client_secret: ${GOOGLE_CLIENT_SECRET}
   ```

#### Optional: Restrict to a Google Workspace Domain

If you want only users from a specific organization (e.g., `umich.edu`):

```yaml
authentication:
  method: "oauth"
  providers:
    google:
      client_id: ${GOOGLE_CLIENT_ID}
      client_secret: ${GOOGLE_CLIENT_SECRET}
      allowed_domain: "umich.edu"
```

Users with non-matching email addresses will see an error message after authenticating with Google.

#### Publishing the OAuth App

While your app is in "Testing" mode, only manually-added test users can log in. To allow any Google user:

1. Go to "OAuth consent screen"
2. Click "Publish App"
3. If Google requires verification (for sensitive scopes), follow their process

For internal research teams, testing mode with explicitly listed users may be sufficient and avoids the verification process.

---

### GitHub OAuth

#### Prerequisites

- A GitHub account
- (Optional) A GitHub organization for access control

#### Step-by-Step Setup

1. **Register a new OAuth App**:
   - Go to https://github.com/settings/developers
   - Click "New OAuth App"
   - Fill in:
     - Application name: "Potato Annotation" (users see this)
     - Homepage URL: `https://your-domain.com`
     - Authorization callback URL: `https://your-domain.com/auth/callback/github`
       - For development: `http://localhost:8000/auth/callback/github`
   - Click "Register application"

2. **Get credentials**:
   - Copy the **Client ID** (shown immediately)
   - Click "Generate a new client secret"
   - **Copy the Client Secret immediately** (shown only once)

3. **Set environment variables**:

   ```bash
   export GITHUB_CLIENT_ID="Iv1.abc123..."
   export GITHUB_CLIENT_SECRET="secret123..."
   ```

4. **Add to your Potato config**:

   ```yaml
   authentication:
     method: "oauth"
     providers:
       github:
         client_id: ${GITHUB_CLIENT_ID}
         client_secret: ${GITHUB_CLIENT_SECRET}
   ```

#### Optional: Restrict to a GitHub Organization

```yaml
authentication:
  method: "oauth"
  providers:
    github:
      client_id: ${GITHUB_CLIENT_ID}
      client_secret: ${GITHUB_CLIENT_SECRET}
      allowed_org: "my-research-lab"
```

Users must be members of the specified organization to log in. Potato checks organization membership via the GitHub API after authentication.

**Note:** The user must have public membership in the org, or the OAuth app must request the `read:org` scope. Potato requests this scope automatically when `allowed_org` is configured.

---

### HuggingFace OAuth

Annotators sign in with their Hugging Face account.

#### In a Hugging Face Space

`potato deploy up config.yaml --provider huggingface --hf-oauth` sets this up
(see [Deploying to a HuggingFace Space](../deployment/deploy-huggingface.md#signing-in-with-hugging-face)).
By hand, add `hf_oauth: true` to the Space README's metadata. Hugging Face then
creates the OAuth app and gives the Space its client id, secret and scopes, so
the provider entry can be empty:

```yaml
authentication:
  method: oauth
  user_identity_field: sub
  providers:
    huggingface: {}
```

Potato builds the callback URL from the Space's public host name
(`SPACE_HOST`). On the Space's page on huggingface.co the app runs inside a
frame, where browsers can drop the sign-in's cookies, so the sign-in button
opens a new tab and annotating continues there.

#### Anywhere else

Create an OAuth application at
[huggingface.co/settings/applications](https://huggingface.co/settings/applications)
with the redirect URL `https://<your host>/auth/callback/huggingface`, then:

```yaml
authentication:
  method: oauth
  user_identity_field: sub
  providers:
    huggingface:
      client_id: ${HF_OAUTH_CLIENT_ID}
      client_secret: ${HF_OAUTH_CLIENT_SECRET}
```

Potato asks for the `openid profile` scopes. `user_identity_field: sub` keys
each annotator on their Hugging Face account id, which stays the same when they
rename themselves. A username can change, and a released one can be registered
by someone else, who would then sign in as the old annotator and see their work.
A profile has no email address unless the `email` scope is granted, and one
without an email falls back to `sub` anyway.

#### Optional: Restrict to a Hugging Face organization

```yaml
    huggingface:
      allowed_org: my-lab
```

Potato then also asks for `read-memberships` and refuses anyone whose
memberships do not include the organization. `allowed_org` is the
organization's handle (the name in its URL) or its id; its display name is not
accepted, because an organization's owners can set that to anything. In a Space, the scope must also be
listed in the README (`hf_oauth_scopes: [read-memberships]`), and
`hf_oauth_authorized_org: my-lab` makes Hugging Face refuse non-members before
they reach Potato; `--hf-oauth-org my-lab` writes both.

---

### Generic OIDC Provider

For identity providers that support OpenID Connect (most enterprise SSO systems): Okta, Azure AD, Auth0, Keycloak, etc.

#### Prerequisites

- Admin access to your identity provider
- The provider's OIDC discovery URL

#### Step-by-Step Setup

1. **Register a new application** in your identity provider:
   - Application type: "Web application" or "Server-side"
   - Grant type: "Authorization Code"
   - Redirect URI: `https://your-domain.com/auth/callback/oidc`
   - Scopes: `openid`, `email`, `profile`

2. **Find the discovery URL**:
   - Okta: `https://your-org.okta.com/.well-known/openid-configuration`
   - Azure AD: `https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration`
   - Keycloak: `https://keycloak.example.com/realms/{realm}/.well-known/openid-configuration`
   - Auth0: `https://your-domain.auth0.com/.well-known/openid-configuration`

3. **Get credentials** (Client ID and Client Secret from your provider)

4. **Set environment variables**:

   ```bash
   export OIDC_CLIENT_ID="your-client-id"
   export OIDC_CLIENT_SECRET="your-client-secret"
   ```

5. **Add to your Potato config**:

   ```yaml
   authentication:
     method: "oauth"
     providers:
       oidc:
         display_name: "University SSO"
         discovery_url: "https://sso.university.edu/.well-known/openid-configuration"
         client_id: ${OIDC_CLIENT_ID}
         client_secret: ${OIDC_CLIENT_SECRET}
         scopes:
           - openid
           - email
           - profile
   ```

#### Azure AD Example

```yaml
authentication:
  method: "oauth"
  providers:
    oidc:
      display_name: "Microsoft"
      discovery_url: "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0/.well-known/openid-configuration"
      client_id: ${AZURE_CLIENT_ID}
      client_secret: ${AZURE_CLIENT_SECRET}
      scopes:
        - openid
        - email
        - profile
```

#### Okta Example

```yaml
authentication:
  method: "oauth"
  providers:
    oidc:
      display_name: "Okta"
      discovery_url: "https://your-org.okta.com/.well-known/openid-configuration"
      client_id: ${OKTA_CLIENT_ID}
      client_secret: ${OKTA_CLIENT_SECRET}
```

---

### SAML 2.0 (institutional sign-in)

Many universities and companies offer SAML rather than OpenID Connect:
Shibboleth, ADFS, and the SAML apps in Okta and Microsoft Entra. With
`method: saml`, annotators sign in at their institution's identity provider
(IdP).

#### Prerequisites

SAML needs the `saml` extra, which builds against the system's libxmlsec1:

```bash
brew install libxmlsec1                  # macOS
sudo apt-get install libxmlsec1-dev      # Debian/Ubuntu
pip install 'potato-annotation[saml]'
```

The Docker image includes it when built with
`--build-arg POTATO_EXTRAS=saml`.

#### Configuration

```yaml
authentication:
  method: saml
  saml:
    display_name: "University sign-in"
    idp_metadata_url: https://idp.example.edu/idp/shibboleth
    sp_base_url: https://annotate.example.edu
    user_identity_attribute: urn:oid:1.3.6.1.4.1.5923.1.1.1.6   # eduPersonPrincipalName
    required_attribute:
      name: urn:oid:1.3.6.1.4.1.5923.1.1.1.1                    # eduPersonAffiliation
      values: [member, student]
secret_key: "${POTATO_SECRET_KEY}"
```

Give the IdP administrator Potato's service-provider metadata, served at
`https://<your host>/saml/metadata`. It names the entity ID
(`<sp_base_url>/saml/metadata`) and the assertion consumer service
(`<sp_base_url>/saml/acs`). They will tell you which attributes they release.

| Key | Required | Description |
|-----|----------|-------------|
| `idp_metadata_url` | One of three | The IdP's metadata (https only), fetched once, when first needed |
| `idp_metadata_file` | One of three | The same metadata saved to a file |
| `idp` | One of three | `entity_id`, `sso_url` and `x509cert` (PEM text or a file path) |
| `idp_entity_id` | No | Which entity to use when the metadata lists several |
| `sp_base_url` | Behind a proxy | The public address Potato is reached at. Behind a proxy that ends TLS, Potato sees `http` and an internal host, and the IdP's response fails the destination check |
| `sp_entity_id` | No | Default `<sp_base_url>/saml/metadata` |
| `sp_cert_file`, `sp_key_file` | No | Sign the authentication requests, if the IdP asks for that, and decrypt encrypted assertions |
| `want_assertions_encrypted` | No | Advertise the SP certificate for encryption in `/saml/metadata` and refuse unencrypted assertions. Needs `sp_cert_file` and `sp_key_file`. Without it an IdP reading the metadata does not encrypt, though an assertion the IdP encrypts anyway is still decrypted when a key is set |
| `user_identity_attribute` | Usually | Attribute that becomes the Potato username, such as eduPersonPrincipalName. Without it the NameID is used, and a transient NameID (Shibboleth's default, new on every sign-in) is refused, because the same annotator would become a new user each time |
| `required_attribute` | No | `{name, values}`: sign-in is refused unless the attribute holds one of the values |
| `claim_attributes` | No | Attributes whose values become `group:<value>` SSO claims for role mapping |
| `display_name` | No | The sign-in button's label |

#### What Potato checks

Potato starts every sign-in itself and accepts a response only when:

- the response or the assertion is signed with the certificate in the IdP's
  metadata, using a non-deprecated algorithm (Shibboleth signs the response
  by default; a response signed nowhere is refused);
- it answers the request this browser started (`InResponseTo`); a response
  the IdP sends unprompted (IdP-initiated sign-in) is refused;
- it is meant for this service provider (audience and destination) and is
  inside its validity window;
- it has not been used before.

Single logout is not supported: signing out of Potato ends the Potato
session, not the IdP session. `allow_local_login` and `auto_register` work as
they do for OAuth.

#### HTTPS is required

The IdP returns the browser to Potato with a form POST from its own site. The
cookie that ties that POST to the sign-in this browser started must be
`SameSite=None` to come along, and browsers keep such a cookie only over
HTTPS. So SAML works over plain HTTP only when the IdP is on the same site,
such as a test IdP on `localhost` with a different port. Over HTTPS the cookie
is a `__Host-` cookie, so a subdomain sharing the parent domain cannot plant
one of its own.

The record of used assertions is kept in memory by each server process and
starts empty after a restart. An assertion captured before a restart can
therefore be used once more after it, until its `NotOnOrAfter` time, which the
IdP sets (usually a few minutes after issue).

---

## Configuration Reference

### Full Configuration Options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `authentication.method` | string | `"in_memory"` | Set to `"oauth"` or `"saml"` to enable SSO |
| `authentication.providers` | dict | (required) | Provider configurations (see below) |
| `authentication.user_identity_field` | string | `"email"` | Which OAuth field becomes the Potato username: `email`, `username`, `sub`, `name` |
| `authentication.allow_local_login` | bool | `false` | Show local username/password form alongside SSO buttons. When `false`, `/register` answers 403 and local registration and password login are refused. An SSO identity never signs in with a password either way |
| `authentication.auto_register` | bool | `true` | Auto-create Potato user on first OAuth login |
| `secret_key` | string | (random) | **Must be stable for OAuth** — set via config or `POTATO_SECRET_KEY` env var |

### Provider-Specific Options

#### Google Provider

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `client_id` | string | Yes | From Google Cloud Console |
| `client_secret` | string | Yes | From Google Cloud Console |
| `allowed_domain` | string | No | Restrict to email domain (e.g., `"umich.edu"`) |

#### GitHub Provider

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `client_id` | string | Yes | From GitHub Developer Settings |
| `client_secret` | string | Yes | From GitHub Developer Settings |
| `allowed_org` | string | No | Restrict to GitHub organization members |

#### HuggingFace Provider

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `client_id` | string | Outside a Space | From huggingface.co/settings/applications; a Space supplies `OAUTH_CLIENT_ID` |
| `client_secret` | string | Outside a Space | As above; a Space supplies `OAUTH_CLIENT_SECRET` |
| `scopes` | list | No | Default: the Space's `OAUTH_SCOPES`, else `["openid", "profile"]` |
| `allowed_org` | string | No | Restrict to members of a Hugging Face organization (adds `read-memberships`) |

#### Generic OIDC Provider

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `display_name` | string | Yes | Button text shown to users (e.g., "University SSO") |
| `discovery_url` | string | Yes | OIDC discovery endpoint URL |
| `client_id` | string | Yes | From your identity provider |
| `client_secret` | string | Yes | From your identity provider |
| `scopes` | list | No | OAuth scopes (default: `["openid", "email", "profile"]`) |

### Multiple Providers

You can enable multiple providers simultaneously:

```yaml
authentication:
  method: "oauth"
  providers:
    google:
      client_id: ${GOOGLE_CLIENT_ID}
      client_secret: ${GOOGLE_CLIENT_SECRET}
    github:
      client_id: ${GITHUB_CLIENT_ID}
      client_secret: ${GITHUB_CLIENT_SECRET}
    oidc:
      display_name: "University SSO"
      discovery_url: "https://sso.university.edu/.well-known/openid-configuration"
      client_id: ${OIDC_CLIENT_ID}
      client_secret: ${OIDC_CLIENT_SECRET}
```

Each provider gets its own button on the login page. Users who log in with the same email via different providers are treated as the same Potato user (when `user_identity_field: "email"`).

### Environment Variable Substitution

Potato supports `${VAR_NAME}` syntax in YAML configs for sensitive values:

```yaml
# In config.yaml — references env vars, never stores secrets
authentication:
  providers:
    google:
      client_id: ${GOOGLE_CLIENT_ID}
      client_secret: ${GOOGLE_CLIENT_SECRET}
```

```bash
# In your shell or .env file — actual secrets
export GOOGLE_CLIENT_ID="123..."
export GOOGLE_CLIENT_SECRET="abc..."
```

**Never hardcode OAuth credentials in your config.yaml file.**

---

## Mixed Mode

You can offer both SSO and traditional login simultaneously:

```yaml
require_password: true

user_config:
  allow_all_users: true

authentication:
  method: "oauth"
  providers:
    google:
      client_id: ${GOOGLE_CLIENT_ID}
      client_secret: ${GOOGLE_CLIENT_SECRET}
  allow_local_login: true
```

This shows SSO buttons at the top of the login page with an "or" divider and the standard username/password form below.

**Use cases for mixed mode:**
- Gradual migration from password-based to SSO
- Allow both institutional (SSO) and external (password) annotators
- Development/testing with local accounts while production uses SSO

> **Note:** Local password accounts in mixed mode use per-user salted PBKDF2 hashing. Admins can reset a local (non-SSO) account's password with `potato reset-password` or the admin reset link (`POST /admin/create_reset_token`). An SSO identity has no password in Potato: its provider manages it, so a password reset for that username is refused. See [Password Management](password_management.md) for details on password security, reset flows, and user credential persistence.

---

## Security Considerations

### HTTPS Requirement

OAuth 2.0 requires HTTPS for redirect URIs in production. The only exception is `http://localhost` for local development.

For production deployment, use a reverse proxy (nginx, Caddy, Traefik) with TLS certificates:

```nginx
server {
    listen 443 ssl;
    server_name annotation.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Secret Key Persistence

You must set a stable `secret_key` when using OAuth. Without it, Potato generates a random key on each startup, which invalidates all sessions.

```yaml
# Option 1: In config.yaml (via env var)
secret_key: ${POTATO_SECRET_KEY}
```

```bash
# Option 2: Environment variable (auto-detected)
export POTATO_SECRET_KEY="your-secret-key-here"

# Generate a secure key:
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Credential Storage

- **Never commit OAuth credentials** to version control
- Use environment variables or a secrets manager
- The `${VAR}` syntax in YAML keeps secrets out of config files
- Rotate client secrets periodically

### Access Control Options

| Method | Config | Effect |
|--------|--------|--------|
| Open access | `auto_register: true` | Any OAuth-authenticated user can annotate |
| Domain lock | `allowed_domain: "umich.edu"` | Only users with matching email domain |
| Org lock | `allowed_org: "lab-name"` | Only GitHub org members |
| Pre-authorized list | `auto_register: false` + `users: [...]` | Only explicitly listed users |

---

## Troubleshooting

### "redirect_uri_mismatch" Error

**Symptom:** Google/GitHub shows "Error 400: redirect_uri_mismatch"

**Cause:** The redirect URI in your OAuth app doesn't exactly match what Potato sends.

**Fix:**
1. Check the error message for the exact URI Potato is sending
2. Add that exact URI to your OAuth app's authorized redirect URIs
3. Common issues:
   - `http` vs `https` mismatch
   - Missing or extra trailing slash
   - Port number mismatch
   - `localhost` vs `127.0.0.1`

### "Access Denied" After Authentication

**Symptom:** User authenticates with Google/GitHub but sees "Access denied" in Potato.

**Possible causes:**
- `allowed_domain` is set and user's email doesn't match
- `allowed_org` is set and user isn't a member (or has private membership)
- `auto_register: false` and user isn't in the pre-authorized list

**Fix:** Check the server logs for the specific reason. Potato logs the denial reason (domain mismatch, org check failed, etc.).

### Sessions Lost on Server Restart

**Symptom:** All users must re-authenticate after restarting the server.

**Cause:** No stable `secret_key` configured.

**Fix:** Set `secret_key` in config or `POTATO_SECRET_KEY` env var (see [Security Considerations](#security-considerations)).

### "OAuth app is in testing mode" (Google)

**Symptom:** Only manually-added test users can log in via Google.

**Fix:** Either:
1. Add all annotators as test users in Google Cloud Console, or
2. Publish the app (may require Google verification for sensitive scopes)

For internal research teams, testing mode with explicitly listed users may be sufficient.

### GitHub Organization Check Fails

**Symptom:** User is in the org but gets "not a member" error.

**Cause:** User has private organization membership.

**Fix:** Either:
1. User makes their membership public in org settings, or
2. Ensure your GitHub OAuth app has `read:org` scope (Potato requests this automatically when `allowed_org` is configured)

---

## FAQ

**Q: Can I use multiple providers at the same time?**
A: Yes. Configure multiple providers under `authentication.providers` and each gets its own login button.

**Q: What happens if a user logs in with Google and GitHub using the same email?**
A: They're treated as the same Potato user (when `user_identity_field: "email"`). Their annotations are unified under one identity.

**Q: Can I switch from password-based to OAuth without losing existing annotations?**
A: Yes, if the OAuth identity (email) matches existing usernames: annotations are keyed by username, so they carry over. Set `allow_local_login: true` during the transition so annotators who have not signed in with SSO yet can still use their passwords. Once someone signs in with SSO, that username is an SSO identity: password login and password resets no longer work for it, and they sign in through the provider from then on.

**Q: Do I need HTTPS for local development?**
A: No. OAuth providers allow `http://localhost` as a redirect URI for development. HTTPS is required only for production.

**Q: Can I use Potato's OAuth with a university SSO system?**
A: Yes, if your university supports OIDC (most do). Use the generic OIDC provider configuration with your university's discovery URL.

**Q: What data does Potato store from OAuth?**
A: Only the user identity field (email, username, or subject ID) and display name. Potato does not store OAuth tokens or passwords.

**Q: Can I require specific users AND use OAuth?**
A: Yes. Set `auto_register: false` and list authorized users in `user_config.users`. Only OAuth users whose identity matches the list can annotate.

**Q: How does this relate to the existing Clerk integration?**
A: They're separate authentication backends. Clerk is a paid service with its own dashboard. The OAuth backend lets you bring your own Google/GitHub/OIDC credentials without a third-party service.

---

## Related Documentation

- [Password Management](password_management.md) — Password security, reset flows, and database backend (for local accounts in mixed mode)
- [Passwordless Login](passwordless_login.md) — Authentication without passwords
- [Configuration Reference](../configuration/configuration.md) — Full config file documentation
- [Crowdsourcing Integration](../deployment/crowdsourcing.md) — Prolific and MTurk setup
- [Admin Dashboard](../administration/admin_dashboard.md) — Managing annotators and viewing progress
- [Debugging Guide](../tools/debugging_guide.md) — Debug flags and troubleshooting
