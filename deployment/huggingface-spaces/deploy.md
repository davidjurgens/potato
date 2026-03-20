# Deploying Potato on HuggingFace Spaces

This guide walks you through deploying Potato as a HuggingFace Space using Docker.

## Prerequisites

- A [HuggingFace account](https://huggingface.co/join)
- Your Potato config YAML and data files

## Quick Start

### 1. Create a New Space

1. Go to [huggingface.co/new-space](https://huggingface.co/new-space)
2. Choose a name for your Space
3. Select **Docker** as the SDK
4. Set visibility (Public or Private)
5. Click "Create Space"

### 2. Clone and Set Up

```bash
git clone https://huggingface.co/spaces/YOUR_USERNAME/YOUR_SPACE
cd YOUR_SPACE
```

### 3. Copy Potato Files

Copy the deployment files into your Space:

```bash
# Copy Dockerfile and entrypoint
cp path/to/potato/deployment/huggingface-spaces/Dockerfile .
cp path/to/potato/deployment/huggingface-spaces/entrypoint.sh .
cp path/to/potato/deployment/huggingface-spaces/README.md .

# Copy your Potato project files
cp -r path/to/potato/potato/ ./potato/
cp path/to/potato/requirements.txt .
cp path/to/potato/setup.py .

# Copy your annotation config and data
cp your-config.yaml ./config.yaml
cp -r your-data/ ./data/
```

### 4. Configure Environment Variables

In your Space settings (Settings tab), add:

| Variable | Required | Description |
|----------|----------|-------------|
| `POTATO_CONFIG` | Yes | Path to your config YAML (default: `config.yaml`) |
| `HF_TOKEN` | No | For CommitScheduler backup |
| `OAUTH_CLIENT_ID` | Auto | Set automatically by HF Spaces when `hf_oauth: true` |
| `OAUTH_CLIENT_SECRET` | Auto | Set automatically by HF Spaces when `hf_oauth: true` |

### 5. Push and Deploy

```bash
git add .
git commit -m "Initial Potato deployment"
git push
```

Your Space will build and deploy automatically.

## Configuration for Spaces

### Example Config

See `spaces_config_example.yaml` for a complete example. Key settings:

```yaml
# Bind to all interfaces (required for Docker)
server:
  host: "0.0.0.0"

# Use HuggingFace OAuth for authentication
authentication:
  type: oauth
  providers:
    huggingface:
      client_id: "${OAUTH_CLIENT_ID}"
      client_secret: "${OAUTH_CLIENT_SECRET}"

# Store output locally (backed up via CommitScheduler)
output_annotation_dir: "annotation_output"
```

### HuggingFace OAuth

When you set `hf_oauth: true` in the Space README front matter, HuggingFace automatically provides OAuth credentials. Configure Potato to use them:

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

### CommitScheduler Backup

Automatically back up annotations to a HuggingFace dataset:

```yaml
huggingface_backup:
  enabled: true
  repo_id: "your-org/annotation-backup"
  token: "${HF_TOKEN}"
  schedule_minutes: 5
  private: true
```

## Resource Requirements

| Setting | Minimum | Recommended |
|---------|---------|-------------|
| CPU | 2 cores | 4 cores |
| RAM | 2 GB | 4 GB |
| Disk | 1 GB | 5 GB |

For larger annotation projects, consider upgrading your Space hardware.

## Troubleshooting

**Space crashes on startup**
- Check the logs in the Space's "Logs" tab
- Verify your config file path matches `POTATO_CONFIG`
- Ensure data files are included in the repository

**OAuth login not working**
- Verify `hf_oauth: true` is in the README front matter
- Check that HF OAuth provider is configured in your Potato config
- Review OAuth scopes match what your config expects

**Data not persisting**
- Spaces have ephemeral storage — use CommitScheduler for persistence
- Or export annotations regularly via the admin API

**Build timeout**
- Large data files slow down builds; consider using `git lfs` for data
- Or load data from an external source at runtime
