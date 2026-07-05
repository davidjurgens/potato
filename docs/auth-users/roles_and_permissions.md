# Roles & Permissions (RBAC)

Potato supports **role-based access control (RBAC)**: a config-driven mapping of
roles to permissions, plus per-user and SSO-based role assignment. This
generalizes the older model (a single shared admin API key + an adjudicator
allow-list) into a coherent permission system, while remaining fully backward
compatible.

## What you get

- A small, fixed set of **permissions**.
- Built-in **roles** (`admin`, `adjudicator`, `annotator`) plus any **custom
  roles** you define.
- Role assignment by **username**, by **SSO/OAuth claim** (e.g. GitHub org), or
  via the existing quota `user_roles` map.
- The shared `admin_api_key` remains a **superuser bypass**, so existing setups
  keep working with no changes.

## Permissions

| Permission | Grants access to |
|------------|------------------|
| `view_admin_dashboard` | The `/admin` dashboard and its read APIs |
| `manage_assignment` | Assignment settings and destructive admin operations |
| `adjudicate` | The `/adjudicate` interface and adjudication APIs |
| `export_data` | Export endpoints |
| `annotate` | The annotation interface |

## Built-in roles

| Role | Permissions |
|------|-------------|
| `admin` | all of the above |
| `adjudicator` | `adjudicate`, `export_data`, `annotate` |
| `annotator` | `annotate` |

## Configuration

All fields are optional. With **no `rbac` block**, behavior is identical to
before: only the shared admin key (and the `adjudicator_users` allow-list)
confers elevated access.

```yaml
# Shared admin key still works as a superuser bypass (unchanged).
admin_api_key: "your-shared-key"

# Legacy adjudicator allow-list still works (folded into the adjudicator role).
adjudication:
  enabled: true
  adjudicator_users: ["ed@example.com"]

# Quota labels still drive per_annotator_quota (unchanged). A label only confers
# permissions if it also names a role in rbac.roles below.
user_roles:
  alice@example.com: expert
  bob@example.com: novice

rbac:
  enabled: true

  # Define or override roles -> permissions (merged over the built-in defaults).
  roles:
    lead: [view_admin_dashboard, export_data, annotate]

  # Assign roles to specific users (highest precedence).
  user_role_assignments:
    carol@example.com: admin
    dave@example.com: lead

  # Map SSO/OAuth claims to roles. Claims currently include "provider:<name>"
  # and, for GitHub, "org:<org>".
  sso_role_mapping:
    "org:my-github-org": adjudicator
```

### Role resolution

A user's roles are the union of:

1. `rbac.user_role_assignments[username]`
2. any `rbac.sso_role_mapping` entry matching the user's SSO claims
3. the legacy `adjudicator_users` list → `adjudicator`
4. `user_roles[username]` **only if** that label names a role in the permission
   map (otherwise it stays a pure quota label, e.g. `novice`/`expert`)

A user's permissions are the union of the permissions of all their roles. The
shared `admin_api_key` (and `debug: true`) bypasses all checks.

## How it's enforced

A single helper, `RBACManager.check(permission, request, session)`, backs every
guard, and one decorator, `require_permission(...)`, replaces the previously
duplicated `admin_required` decorators across the codebase. This means:

- The admin dashboard, adjudication, export, and destructive endpoints all route
  through the same permission model.
- A logged-in user with an admin-capable role reaches admin endpoints **without**
  needing the shared key.
- Requests with a valid shared key (or in debug mode) always pass.

## Backward compatibility

- No `rbac` block → unchanged behavior (shared key + `adjudicator_users` only).
- `user_roles` with non-role labels → still purely workload-quota labels.
- `adjudicator_users` → still authorizes adjudication.

## Related

- [Users & Collaboration](user_and_collaboration.md)
- [SSO & OAuth Authentication](sso_authentication.md)
- [Adjudication](../administration/adjudication.md)
- [Per-Cohort Schemas](../advanced/per_cohort_schemas.md)
- [Heterogeneous Coverage](../advanced/heterogeneous_coverage.md) (per-annotator quotas)
