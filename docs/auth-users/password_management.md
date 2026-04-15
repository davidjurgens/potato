# Password Management

Potato provides a comprehensive password management system with secure per-user password hashing, multiple reset flows, and persistent user storage. This guide covers password security, reset mechanisms, shared credential files, and the database authentication backend.

This documentation applies to the `in_memory` and `database` authentication methods. If you use OAuth/SSO (Google, GitHub, institutional), passwords are managed by the identity provider — see [SSO & OAuth Authentication](sso_authentication.md). In [mixed mode](sso_authentication.md#mixed-mode) (SSO + local login), the features described here apply to local password accounts.

## Overview

Potato's authentication system supports:

- **Per-user salted password hashing** using PBKDF2-SHA256 with 100,000 iterations
- **Admin-initiated password reset** via CLI command or REST API
- **Self-service password reset** via token-based reset links
- **Shared user credential files** for multi-server deployments
- **Database authentication backend** using SQLite or PostgreSQL

For passwordless authentication (no password required), see [Passwordless Login](passwordless_login.md).

## Password Security

### Per-User Salts

Every user password is hashed with a unique random salt. This means two users with the same password will have different stored hashes, preventing rainbow table attacks.

Passwords are stored in `salt$hash` format:
- **Salt**: 32-character hex string (16 random bytes)
- **Hash**: 64-character hex string (PBKDF2-SHA256, 100,000 iterations)

Verification uses `hmac.compare_digest` for constant-time comparison, preventing timing attacks.

### Backward Compatibility

Existing plaintext passwords in `user_config.json` files are automatically detected and re-hashed with per-user salts on load. No manual migration is needed.

## Password Reset

### Admin CLI Reset

Reset a user's password from the command line:

```bash
# Interactive (prompts for username and password)
potato reset-password config.yaml

# Non-interactive (prompts for password only)
potato reset-password config.yaml --username annotator1
```

The command:
1. Loads the project configuration
2. Prompts for the username (if not provided via `--username`)
3. Prompts for the new password (with confirmation)
4. Updates the password hash and saves to disk

### Admin API Reset

Reset a password programmatically via the admin REST API:

```bash
curl -X POST http://localhost:8000/admin/reset_password \
  -H "X-API-Key: YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"username": "annotator1", "new_password": "new_secure_password"}'
```

**Response (success):**
```json
{"message": "Password updated successfully"}
```

**Response (user not found):**
```json
{"error": "User not found"}
```

This endpoint requires the `admin_api_key` configured in your project (see [Admin Dashboard](../administration/admin_dashboard.md)).

### Self-Service Password Reset

Potato includes a token-based password reset flow for annotators who forget their passwords.

#### How It Works

1. The annotator visits `/forgot-password` and enters their username
2. The system generates a secure single-use reset token (valid for 24 hours)
3. The reset link is displayed on screen for the admin to copy and share with the annotator
4. The annotator opens the link (`/reset/<token>`) and sets a new password
5. The token is consumed (single-use) and the password is updated

> **Note:** Potato does not send emails. The reset link is displayed on the page after submission. In a typical workflow, an administrator generates the token and sends the link to the annotator via email or chat.

#### Generating Tokens via API

Administrators can also generate reset tokens programmatically:

```bash
curl -X POST http://localhost:8000/admin/create_reset_token \
  -H "X-API-Key: YOUR_ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"username": "annotator1"}'
```

**Response:**
```json
{
  "reset_link": "http://localhost:8000/reset/abc123...",
  "token": "abc123...",
  "expires_in_hours": 24
}
```

Optional: set a custom expiry with `"ttl_hours": 48`.

#### Login Page Link

When `require_password: true` is set, a "Forgot Password?" link appears on the login page, directing annotators to the self-service reset form.

## Shared User Credentials

By default, user credentials are stored in memory and not persisted between server restarts when using the `in_memory` authentication method. To share credentials across server restarts or between multiple server instances, configure an explicit `user_config_path`:

```yaml
authentication:
  method: in_memory
  user_config_path: /shared/path/to/user_config.jsonl
```

When `user_config_path` is explicitly set:
- New user registrations are saved to the file automatically
- Password changes are persisted immediately
- The file is in JSONL format (one JSON object per line)
- Passwords are stored as `salt$hash` (never plaintext)

**Example `user_config.jsonl`:**
```json
{"username": "annotator1", "password": "a1b2c3...salt$d4e5f6...hash"}
{"username": "annotator2", "password": "f7e8d9...salt$c0b1a2...hash"}
```

> **Note:** When using the `database` authentication method, `user_config_path` must not be set. These two persistence strategies are mutually exclusive and Potato will raise an error if both are configured.

## Database Authentication Backend

For production deployments or when you need robust user management, use the database backend with SQLite or PostgreSQL.

### SQLite (No Dependencies)

SQLite uses Python's built-in `sqlite3` module — no additional packages needed:

```yaml
authentication:
  method: database
  database_url: "sqlite:///data/auth.db"
```

The path is relative to the working directory. Potato creates the database and `users` table automatically on first start. SQLite uses WAL mode for better concurrent read performance.

### PostgreSQL

For multi-server deployments, use PostgreSQL. Requires the `psycopg2` package:

```bash
pip install psycopg2-binary
```

```yaml
authentication:
  method: database
  database_url: "postgresql://user:password@host:5432/dbname"
```

### Environment Variable

Alternatively, set the connection string via environment variable (overridden by `database_url` in config):

```bash
export POTATO_DB_CONNECTION="sqlite:///users.db"
```

```yaml
authentication:
  method: database
  # database_url not needed — uses POTATO_DB_CONNECTION
```

### Database Schema

The `users` table is created automatically:

| Column | Type | Description |
|--------|------|-------------|
| `username` | TEXT (PK) | Unique username |
| `password_hash` | TEXT | Salted PBKDF2 hash (`salt$hash` format) |
| `email` | TEXT | Optional email address |
| `created_at` | TIMESTAMP | Account creation time |
| `updated_at` | TIMESTAMP | Last password change time |

## Configuration Reference

### Complete Authentication Configuration

```yaml
# Require password for login (default: true)
require_password: true

authentication:
  # Backend: "in_memory" (default), "database", "clerk", or "oauth"
  method: in_memory

  # Path to persistent user credential file (in_memory only)
  # Mutually exclusive with method: database
  user_config_path: users.jsonl

  # Database connection URL (database method only)
  # Alternatively set POTATO_DB_CONNECTION environment variable
  database_url: "sqlite:///auth.db"
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `require_password` | boolean | `true` | Require password for login |
| `authentication.method` | string | `"in_memory"` | Backend: `in_memory`, `database`, `clerk`, `oauth` |
| `authentication.user_config_path` | string | auto-generated | Path to JSONL file for user persistence (in_memory only) |
| `authentication.database_url` | string | `sqlite:///potato_users.db` | Database connection URL (database method only) |

### Validation Rules

- `database_url` must start with `sqlite:///` or `postgresql://`
- `method: database` and `user_config_path` cannot be used together
- When `user_config_path` is set to a file that doesn't exist yet, it will be created on first user registration

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/forgot-password` | GET | None | Show forgot password form |
| `/forgot-password` | POST | None | Generate reset token for username |
| `/reset/<token>` | GET | None | Show password reset form |
| `/reset/<token>` | POST | None | Submit new password |
| `/admin/reset_password` | POST | API Key | Admin password reset |
| `/admin/create_reset_token` | POST | API Key | Generate reset token via API |

## Examples

### Basic Setup with Password Persistence

```yaml
annotation_task_name: "Annotation Task"

require_password: true

authentication:
  method: in_memory
  user_config_path: user_credentials.jsonl

data_files:
  - data/instances.json

item_properties:
  id_key: id
  text_key: text

annotation_schemes:
  - name: sentiment
    annotation_type: radio
    labels: [Positive, Negative, Neutral]
    description: "Select the sentiment"
```

### Production Setup with SQLite

```yaml
annotation_task_name: "Production Annotation"

require_password: true

authentication:
  method: database
  database_url: "sqlite:///data/users.db"

data_files:
  - data/instances.json

item_properties:
  id_key: id
  text_key: text

annotation_schemes:
  - name: label
    annotation_type: radio
    labels: [Yes, No]
    description: "Select the label"
```

## Troubleshooting

### "User not found" When Resetting Password

The user must already be registered. Check the list of registered users in your `user_config_path` file or database.

### Passwords Not Persisting After Server Restart

If using `in_memory` authentication:
- Ensure `user_config_path` is explicitly set in your config
- Without it, user data is only stored in memory

If using `database` authentication:
- Check that the `database_url` is valid and the database file/server is accessible
- Verify the `users` table was created (Potato creates it automatically on first start)

### Reset Token Expired or Invalid

Reset tokens are:
- Valid for 24 hours by default (configurable via `ttl_hours`)
- Single-use — once used, the token is consumed
- Invalidated when a new token is generated for the same user

### "database and user_config_path are mutually exclusive"

You cannot use both `method: database` and `user_config_path` together. Choose one persistence strategy:
- Use `method: in_memory` with `user_config_path` for file-based persistence
- Use `method: database` with `database_url` for database persistence

## Related Documentation

- [Users & Collaboration](user_and_collaboration.md) - User registration and access control
- [Passwordless Login](passwordless_login.md) - Authentication without passwords
- [SSO & OAuth Authentication](sso_authentication.md) - Google, GitHub, and institutional SSO
- [Admin Dashboard](../administration/admin_dashboard.md) - Admin API key configuration
- [Configuration Reference](../configuration/configuration.md) - Complete configuration options
