# HuggingFace Spaces Deployment

Deploy Potato as a [HuggingFace Space](https://huggingface.co/docs/hub/spaces) for easy cloud hosting with built-in OAuth authentication.

## Overview

HuggingFace Spaces provides free hosting for Docker-based applications. Potato includes a ready-to-use Dockerfile and configuration templates for Spaces deployment.

### Features

- One-click deployment via Docker SDK
- Built-in HuggingFace OAuth authentication
- Optional CommitScheduler for automatic annotation backup
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
  type: oauth
  providers:
    huggingface:
      client_id: "${OAUTH_CLIENT_ID}"
      client_secret: "${OAUTH_CLIENT_SECRET}"
  auto_register: true
  user_identity_field: email
```

The `OAUTH_CLIENT_ID` and `OAUTH_CLIENT_SECRET` environment variables are automatically set by HuggingFace Spaces.

### How It Works

1. User clicks "Sign in with HuggingFace" on the login page
2. Redirected to HuggingFace for authentication
3. After approval, redirected back to Potato with user identity
4. User is automatically registered and can start annotating

## CommitScheduler Backup

Automatically back up annotations to a HuggingFace dataset repository:

```yaml
huggingface_backup:
  enabled: true
  repo_id: "your-org/annotation-backup"
  token: "${HF_TOKEN}"
  schedule_minutes: 5
  private: true
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `false` | Enable automatic backup |
| `repo_id` | string | *required* | HuggingFace repo for backups |
| `token` | string | `$HF_TOKEN` | API token with write access |
| `schedule_minutes` | int | `5` | Backup interval in minutes |
| `private` | bool | `true` | Create private backup repo |

### Requirements

```bash
pip install huggingface_hub>=0.20.0
```

The CommitScheduler runs as a background thread and automatically commits changed files at the configured interval.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `POTATO_CONFIG` | Path to Potato config YAML |
| `HF_TOKEN` | HuggingFace API token (for CommitScheduler) |
| `OAUTH_CLIENT_ID` | OAuth client ID (auto-set by HF Spaces) |
| `OAUTH_CLIENT_SECRET` | OAuth client secret (auto-set by HF Spaces) |
| `PORT` | Server port (default: 7860) |
| `GUNICORN_WORKERS` | Number of worker processes (default: 2) |
| `GUNICORN_THREADS` | Threads per worker (default: 4) |

## Limitations

- **Ephemeral storage**: Files are lost when the Space restarts. Use CommitScheduler for persistence.
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

### 2. CommitScheduler Backup (Automatic)

If `commit_scheduler` is configured, raw annotation files are automatically pushed to your Space's repository on a regular interval. These are the raw JSON files, not structured datasets.

### 3. Download Raw Files

Access annotation files directly via the HuggingFace Spaces file browser in your repository, or clone the repo locally.

See [HuggingFace Hub Export](huggingface_export.md) for detailed export options and format documentation.

## Related Documentation

- [HuggingFace Hub Export](huggingface_export.md) - Export annotations to HuggingFace datasets
- [SSO & OAuth Authentication](sso_authentication.md) - OAuth configuration details
- [Webhooks](webhooks.md) - Event notifications for external integrations
