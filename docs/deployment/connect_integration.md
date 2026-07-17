# CloudResearch Connect Integration Guide

[Connect](https://connect.cloudresearch.com/) is CloudResearch's participant
platform and the destination they migrate MTurk Toolkit users to — making it
the most direct MTurk replacement for research studies.

## How it works

Connect's "Project Link" model matches Potato's external-URL flow:

1. Create a project on Connect and set the project link to your Potato server.
   Connect appends `participantId` (and optionally `assignmentId` and
   `projectId`) to the URL.
2. The participant annotates in Potato.
3. Completion is verified with a **fixed completion code** the participant
   pastes back into Connect, or a **completion redirect** to the URL shown in
   your Connect project's settings.

## Configuration

```yaml
login:
  type: url_direct
  url_argument: participantId

crowdsourcing:
  provider: connect
  connect:
    completion:
      code: "YOUR-CONNECT-CODE"
      # If your Connect project uses redirect-based completion instead,
      # paste the completion URL from the project settings:
      # redirect_url: "https://connect.cloudresearch.com/participant/project/<project-id>/complete"

# Recommended crowdsourcing settings
hide_navbar: true
jumping_to_id_disabled: true
assignment_strategy: random
max_annotations_per_user: 20
```

Potato captures `assignmentId` and `projectId` into each participant's
`crowd_metadata` (in `user_state.json`), so you can join annotation output
with Connect's participant reports.

## Testing locally

```bash
python potato/flask_server.py start examples/crowdsourcing/connect-example/config.yaml -p 8000
# then visit:
# http://localhost:8000/?participantId=TEST123&assignmentId=A1&projectId=P1
```

## API note

Connect exposes a REST API (`connect-api.cloudresearch.com`, API-key auth) for
projects and participant data. Potato does not call it yet; completion
verification runs entirely through codes/redirects. API-level features
(approvals, bonuses) are planned.

## Related documentation

- [Choosing a crowdsourcing platform](crowdsourcing-platforms.md)
- [Crowdsourcing setup](crowdsourcing.md)
- [Quality control](../workflow/quality_control.md)
