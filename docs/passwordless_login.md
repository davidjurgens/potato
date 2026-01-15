# Passwordless Login

Potato supports passwordless authentication for low-stakes annotation tasks where security is less critical than ease of access. This mode allows annotators to log in with just a username, without requiring a password.

## Overview

Passwordless login is useful when:

- Running quick annotation studies with volunteers
- Conducting internal team annotation sessions
- Testing annotation configurations
- Working with crowdsourcing platforms that handle authentication externally
- Running classroom exercises or demos

## Configuration

Enable passwordless login by setting `require_password: false` in your configuration:

```yaml
# Enable passwordless login
require_password: false

# Optional: Specify authentication method
authentication:
  method: in_memory  # Default
```

## Authentication Methods

Potato supports three authentication backends, all of which work with passwordless mode:

### In-Memory (Default)

Users are stored in memory only. Data is lost when the server restarts.

```yaml
require_password: false
authentication:
  method: in_memory
```

### Database

Users are persisted to a database. Set the connection string via environment variable:

```bash
export POTATO_DB_CONNECTION="sqlite:///users.db"
```

```yaml
require_password: false
authentication:
  method: database
```

### Clerk SSO

Integration with Clerk for enterprise single sign-on. Requires API keys:

```bash
export CLERK_API_KEY="your_api_key"
export CLERK_FRONTEND_API="your_frontend_api"
```

```yaml
authentication:
  method: clerk
```

## How It Works

### With Passwordless Enabled

1. User visits the login page
2. User enters only their username
3. System creates or authenticates the user without password verification
4. User proceeds to annotation

### User Registration

In passwordless mode:
- New users are automatically registered on first login
- Only the username is required
- Additional user data (if configured) is still collected

### Security Considerations

Passwordless mode provides minimal security:

- **No identity verification**: Anyone can claim any username
- **Session hijacking**: Sessions can be easily impersonated
- **No audit trail integrity**: User actions cannot be cryptographically verified

**Recommended uses:**
- Internal team annotation
- Classroom exercises
- Quick prototyping
- Platforms with external authentication (Prolific, MTurk)

**Not recommended for:**
- Sensitive data annotation
- Medical or legal annotation tasks
- Tasks requiring verified annotator identity
- Long-running studies with incentives

## User Configuration File

Even in passwordless mode, you can pre-register users with a configuration file:

```yaml
authentication:
  user_config_path: users.jsonl
```

**users.jsonl:**
```json
{"username": "annotator1"}
{"username": "annotator2"}
{"username": "admin", "role": "admin"}
```

## API Reference

### UserAuthenticator

```python
from potato.authentication import UserAuthenticator

# Check if passwordless mode is enabled
authenticator = UserAuthenticator.get_instance()
if not authenticator.require_password:
    print("Passwordless mode enabled")

# Authenticate user (password ignored in passwordless mode)
success = UserAuthenticator.authenticate("username", None)
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `require_password` | boolean | true | When false, enables passwordless login |
| `authentication.method` | string | "in_memory" | Backend: "in_memory", "database", or "clerk" |
| `authentication.user_config_path` | string | auto | Path to user configuration file |

## Migration

### From Password-Required to Passwordless

1. Update configuration:
   ```yaml
   require_password: false
   ```

2. Existing users can still log in with or without their password

### From Passwordless to Password-Required

1. Update configuration:
   ```yaml
   require_password: true
   ```

2. Existing passwordless users will need to register with a password

## Troubleshooting

### Users Can't Log In

Check that:
1. `require_password: false` is set in the configuration
2. The authentication backend is properly initialized
3. There are no conflicting authentication settings

### User Data Not Persisting

If using `in_memory` backend:
- User data is lost on server restart
- Switch to `database` backend for persistence

### Duplicate Username Errors

If a user tries to register with an existing username:
- In passwordless mode, they are simply logged in as that user
- This is by design for ease of use
- For stricter control, pre-register allowed usernames

## Complete Example

```yaml
annotation_task_name: "Quick Annotation Task"

# Enable passwordless login for easy access
require_password: false

# Use database backend to persist users
authentication:
  method: database

# Task configuration
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

## Related Documentation

- [User and Collaboration](user_and_collaboration.md) - User management features
- [Crowdsourcing](crowdsourcing.md) - Integration with crowdsourcing platforms
- [Configuration](configuration.md) - Full configuration reference
