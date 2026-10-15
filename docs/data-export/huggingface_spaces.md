# HuggingFace Spaces Deployment

Deploy Potato as a [HuggingFace Space](https://huggingface.co/docs/hub/spaces) for easy cloud hosting with built-in OAuth authentication.

## Overview

Potato runs as a Docker Space. Docker Spaces are not free: creating one needs a PRO account or a Team or Enterprise plan for an organization. Potato includes a Dockerfile and configuration templates for Spaces deployment, and `potato deploy up config.yaml --provider huggingface` creates the Space for you; see [Deploy to HuggingFace Spaces](../deployment/deploy-huggingface.md).

### Features

- One-click deployment via Docker SDK
- Built-in HuggingFace OAuth authentication
- Backup of annotations to a HuggingFace Dataset repo, restored when the Space restarts
- No server management required

## Quick Start

1. Create a new Space at [huggingface.co/new-space](https://huggingface.co/new-space) (select Docker SDK)
2. Copy files from `deployment/huggingface-spaces/` into your Space repository
3. Add your Potato config and data files
4. Push to deploy

See `deployment/huggingface-spaces/deploy.md` for detailed step-by-step instructions.

## HuggingFace OAuth

When deploying on Spaces with `hf_oauth: true` in the README front matter, HuggingFace automatically provides OAuth credentials.

### Configuration

```yaml
authentication:
  method: oauth
  providers:
    huggingface:
      client_id: "${OAUTH_CLIENT_ID}"
      client_secret: "${OAUTH_CLIENT_SECRET}"
  auto_register: true
  user_identity_field: email
```

The `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` environment variables are automatically set by HuggingFace Spaces.

### The HuggingFace sign-in flow

1. User clicks "Sign in with HuggingFace" on the login page
2. Redirected to HuggingFace for authentication
3. After approval, redirected back to Potato with user identity
4. User is automatically registered and can start annotating

## Backup

A Space's filesystem is wiped on every restart and rebuild, so annotations
need to live somewhere else. The `backup:` block copies the annotation output
and the project databases to a private HuggingFace **Dataset** repo (not the
Space repo) on a schedule, and copies them back into an empty Space when it
starts:

```yaml
backup:
  schedule_minutes: 5
  restore_on_boot: true
  sinks:
    - type: huggingface
      repo_id: "your-org/annotation-backup"
```

The token comes from `HF_TOKEN` (set it as a Space secret) or from a `token`
key on the sink. `potato deploy up --provider huggingface` writes this block for
you. It needs `pip install 'potato-annotation[hosting]'`, which the published
image already includes.

The older `huggingface_backup:` block (`enabled`, `repo_id`, `token`,
`schedule_minutes`, `private`) is still read as a single HuggingFace sink, but
with `restore_on_boot` off unless you set it, so a restarted Space comes back
empty. Use `backup:` for new projects. See [Backups](../deployment/deploy-backups.md)
for every option, including S3.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `POTATO_CONFIG` | Path to Potato config YAML |
| `HF_TOKEN` | HuggingFace API token with write access (for the backup Dataset) |
| `OAUTH_CLIENT_ID` | OAuth client ID (auto-set by HF Spaces) |
| `OAUTH_CLIENT_SECRET` | OAuth client secret (auto-set by HF Spaces) |
| `PORT` | Server port (default: 7860) |
| `GUNICORN_WORKERS` | Number of worker processes (default: 1). Any other value makes the entrypoint exit, because Potato's item pool and user state are per-process; `POTATO_ALLOW_MULTIWORKER=1` overrides this and loses data |
| `GUNICORN_THREADS` | Threads per worker (default: 8). Raise this, not the worker count, for more concurrency |

## Limitations

- **Ephemeral storage**: Files are lost when the Space restarts. Configure a [backup](#backup) to keep them.
- **Cold starts**: Free Spaces may sleep after inactivity. Upgraded Spaces stay running.
- **Resource limits**: Free tier has limited CPU/RAM. Upgrade for larger projects.

## Exporting Annotations

Since Spaces don't provide terminal access, there are three ways to get your annotations out:

### 1. Admin API Export (Recommended)

Use the admin API to trigger a structured export to HuggingFace Hub or other formats directly from your Space:

```bash
curl -X POST https://your-space.hf.space/admin/api/export \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_ADMIN_KEY" \
  -d '{
    "format": "huggingface",
    "output": "your-org/my-annotations",
    "options": {"private": "true"}
  }'
```

When `HF_TOKEN` is set as a Space secret, the exporter uses it automatically — no need to pass the token in the request body.

To see all available formats:

```bash
curl https://your-space.hf.space/admin/api/export/formats \
  -H "X-API-Key: YOUR_ADMIN_KEY"
```

### 2. The backup Dataset

With a [backup](#backup) configured, the raw annotation files are in the backup Dataset repo, not the Space repo. These are the raw JSON files, not structured datasets. Browse or clone them on the Hub. If you created the Space with `potato deploy`, download them with:

```bash
potato deploy pull config.yaml
```

### 3. Without a backup

Annotations written to the Space are not in its git repository, so the Space file browser does not show them. Use the admin API above while the Space is running.

See [HuggingFace Hub Export](huggingface_export.md) for detailed export options and format documentation.

## Related Documentation

- [Deploy to HuggingFace Spaces](../deployment/deploy-huggingface.md) - `potato deploy` to a Space, pricing and the concurrency cap
- [Backups](../deployment/deploy-backups.md) - The `backup:` block and its sinks
- [HuggingFace Hub Export](huggingface_export.md) - Export annotations to HuggingFace datasets
- [SSO & OAuth Authentication](../auth-users/sso_authentication.md) - OAuth configuration details
- [Webhooks](../integrations/webhooks.md) - Event notifications for external integrations
