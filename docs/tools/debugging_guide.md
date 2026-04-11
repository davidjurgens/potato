# Debugging Guide

Potato provides several command-line flags and configuration options to help with debugging and testing annotation projects. These are useful during development and troubleshooting.

## Server Configuration

You can configure server settings directly in your YAML config file instead of using CLI flags:

```yaml
server:
  port: 8000        # Port to run on (default: 8000)
  host: "0.0.0.0"   # Host to bind to (default: 0.0.0.0)
  debug: false      # Enable Flask debug mode (default: false)
```

**Note:** CLI flags take precedence over config file values. For example, `-p 9000` will override `server.port: 8000`.

## Debug Flags

### `--debug`

Launches Potato in debug mode with simplified authentication.

```bash
potato start config.yaml --debug
```

**Effects:**
- Bypasses normal login requirements
- Enables verbose logging
- Useful for quickly testing configuration changes

### `--debug-log`

Controls debug logging output for different parts of the system.

```bash
potato start config.yaml --debug --debug-log=all
```

**Options:**

| Value | Description |
|-------|-------------|
| `all` | Enable logging for both UI (frontend) and server (backend) |
| `ui` | Enable frontend JavaScript console logging only |
| `server` | Enable backend Python logging only |
| `none` | Disable all debug logging |

**Examples:**

```bash
# Debug frontend issues (JavaScript errors, UI state)
potato start config.yaml --debug --debug-log=ui

# Debug backend issues (API calls, data processing)
potato start config.yaml --debug --debug-log=server

# Full debugging (both frontend and backend)
potato start config.yaml --debug --debug-log=all

# Quiet mode - minimal output
potato start config.yaml --debug --debug-log=none
```

**How it works:**
- When `ui` logging is disabled, frontend `console.log`, `console.debug`, and `console.info` calls are suppressed
- When `server` logging is disabled, backend log messages below WARNING level are suppressed
- You can re-enable UI logging at runtime by calling `enableUIDebug()` in the browser console

### `--debug-phase`

Skip directly to a specific phase or page without going through earlier phases. This is useful for testing specific parts of an annotation workflow.

```bash
potato start config.yaml --debug --debug-phase=annotation
```

**Requires:** The `--debug` flag must also be set.

**Valid phase names:**
- `login` - Login page
- `consent` - Consent form
- `prestudy` - Pre-study survey
- `instructions` - Instructions page
- `training` - Training phase
- `annotation` - Main annotation phase
- `poststudy` - Post-study survey
- `done` - Completion page

You can also specify a specific page name if your configuration defines multiple pages within a phase.

**Examples:**

```bash
# Jump directly to annotation (most common use case)
potato start config.yaml --debug --debug-phase=annotation

# Test post-study survey
potato start config.yaml --debug --debug-phase=poststudy

# Test a specific named page
potato start config.yaml --debug --debug-phase=my_custom_survey
```

**How it works:**
- Automatically creates and logs in a user named `debug_user`
- Skips all phases before the specified phase
- The user's state is set as if they had completed all prior phases

## Combining Debug Flags

Flags can be combined for different debugging scenarios:

```bash
# Quick annotation testing with minimal noise
potato start config.yaml --debug --debug-phase=annotation --debug-log=none

# Full debugging of annotation phase
potato start config.yaml --debug --debug-phase=annotation --debug-log=all

# Debug only backend while testing post-study
potato start config.yaml --debug --debug-phase=poststudy --debug-log=server
```

## Other Useful Flags

### `--verbose` / `-v`

Enable verbose output for general operation logging.

```bash
potato start config.yaml -v
```

### `--veryVerbose`

Enable very verbose output with detailed internal state information.

```bash
potato start config.yaml --veryVerbose
```

### `--port` / `-p`

Run on a specific port (useful when running multiple instances).

```bash
potato start config.yaml -p 8080
```

## Browser Developer Tools

In addition to command-line flags, you can use browser developer tools for debugging:

1. **Console**: View JavaScript logs and errors (F12 or Cmd+Option+I)
2. **Network**: Monitor API calls between frontend and backend
3. **Elements**: Inspect the DOM and CSS styling
4. **Application**: Check session storage and cookies

### Re-enabling Console Logging

If UI logging was disabled via `--debug-log=server` or `--debug-log=none`, you can re-enable it in the browser console:

```javascript
enableUIDebug();
```

This restores `console.log`, `console.debug`, `console.info`, and `console.warn` to their original behavior.

## Common Debugging Scenarios

### Testing a New Annotation Schema

```bash
# Skip to annotation with full logging
potato start config.yaml --debug --debug-phase=annotation --debug-log=all
```

### Debugging API Issues

```bash
# Server-only logging to focus on backend
potato start config.yaml --debug --debug-log=server
```

Then use browser Network tab to inspect request/response data.

### Testing User Flow

```bash
# Start from the beginning with UI logging
potato start config.yaml --debug --debug-log=ui
```

### Performance Testing

```bash
# Minimal logging overhead
potato start config.yaml --debug --debug-phase=annotation --debug-log=none
```

## Troubleshooting

### "debug-phase requires --debug flag"

The `--debug-phase` option only works when `--debug` is also specified:

```bash
# Wrong
potato start config.yaml --debug-phase=annotation

# Correct
potato start config.yaml --debug --debug-phase=annotation
```

### Phase not found

If the specified phase doesn't exist in your configuration, check:
- The phase name is spelled correctly
- The phase is defined in your YAML config
- For custom pages, use the exact page name from your config
