"""
Prolific REST API client (v2 — current API model, verified July 2026).

Differences from the legacy wrapper in server_utils/prolific_apis.py:
- Study creation uses the CURRENT study model: a ``completion_codes`` array
  (code/code_type/actor/actions) — the legacy ``completion_code`` /
  ``failed_attention_code`` fields no longer exist — and ``filters`` /
  ``filter_set_id`` instead of the removed ``eligibility_requirements``.
- Covers the full lifecycle: draft/publish/stop, place scaling, submission
  review (approve/reject/screen-out), bonuses, cost preview, participant
  groups (qualification sync), and test participants.

API notes (from docs.prolific.com/api-reference):
- Auth: ``Authorization: Token <token>``; tokens are created in workspace
  settings and carry full permission.
- ``total_available_places`` can only increase.
- Most study fields are immutable after publish.
- REJECT transitions require a ``message`` of >= 100 chars and a
  ``rejection_category``.
"""

import logging

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.prolific.com/api/v1"


class ProlificAPIError(Exception):
    """Raised when the Prolific API returns an error response."""

    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class ProlificClient:
    """Thin, complete client for the current Prolific REST API."""

    def __init__(self, token, base_url=API_BASE, timeout=30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.headers = {'Authorization': f'Token {token}'}

    # --- plumbing -------------------------------------------------------------

    def _request(self, method, path, json_body=None, params=None):
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(
                method, url, headers=self.headers, json=json_body,
                params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise ProlificAPIError(f"Request to {path} failed: {e}") from e
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {'raw': response.text[:500]}
            raise ProlificAPIError(
                f"{method} {path} -> {response.status_code}: {payload}",
                status_code=response.status_code, payload=payload)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def _get(self, path, params=None):
        return self._request('GET', path, params=params)

    def _post(self, path, json_body=None):
        return self._request('POST', path, json_body=json_body)

    def _patch(self, path, json_body=None):
        return self._request('PATCH', path, json_body=json_body)

    def _delete(self, path):
        return self._request('DELETE', path)

    # --- account / workspaces -------------------------------------------------

    def who_am_i(self):
        return self._get('/users/me/')

    def list_workspaces(self):
        return self._get('/workspaces/')

    def workspace_balance(self, workspace_id):
        return self._get(f'/workspaces/{workspace_id}/balance/')

    def list_projects(self, workspace_id):
        return self._get(f'/workspaces/{workspace_id}/projects/')

    # --- studies --------------------------------------------------------------

    def list_studies(self, state=None):
        params = {'state': state} if state else None
        return self._get('/studies/', params=params)

    def get_study(self, study_id):
        return self._get(f'/studies/{study_id}/')

    def create_study(self, spec):
        """Create a draft study.

        ``spec`` must follow the CURRENT model. Minimum required fields:
        name, description, external_study_url, prolific_id_option,
        completion_codes, total_available_places, estimated_completion_time,
        reward. Example completion_codes entry:

            {"code": "C1ABC", "code_type": "COMPLETED",
             "actor": "participant",
             "actions": [{"action": "AUTOMATICALLY_APPROVE"}]}
        """
        for legacy_field in ('completion_code', 'failed_attention_code',
                             'eligibility_requirements', 'completion_option'):
            if legacy_field in spec:
                raise ValueError(
                    f"'{legacy_field}' is a retired Prolific study field; use "
                    "completion_codes / filters (see the Prolific API reference)")
        return self._post('/studies/', spec)

    def update_study(self, study_id, patch):
        return self._patch(f'/studies/{study_id}/', patch)

    def delete_study(self, study_id):
        return self._delete(f'/studies/{study_id}/')

    def _transition_study(self, study_id, action, **extra):
        body = {'action': action}
        body.update(extra)
        return self._post(f'/studies/{study_id}/transition/', body)

    def publish_study(self, study_id):
        return self._transition_study(study_id, 'PUBLISH')

    def pause_study(self, study_id):
        return self._transition_study(study_id, 'PAUSE')

    def start_study(self, study_id):
        return self._transition_study(study_id, 'START')

    def stop_study(self, study_id):
        return self._transition_study(study_id, 'STOP')

    def increase_places(self, study_id, total_available_places):
        """Set total_available_places (Prolific only allows increases)."""
        current = self.get_study(study_id)
        existing = current.get('total_available_places', 0)
        if total_available_places <= existing:
            logger.info("Places already at %s (requested %s); skipping",
                        existing, total_available_places)
            return current
        return self._patch(f'/studies/{study_id}/',
                           {'total_available_places': total_available_places})

    def study_cost(self, study_id):
        return self._get(f'/studies/{study_id}/cost/')

    def calculate_cost(self, reward, total_available_places):
        return self._post('/study-cost-calculator/',
                          {'reward': reward,
                           'total_available_places': total_available_places})

    # --- submissions ----------------------------------------------------------

    def list_submissions(self, study_id=None):
        params = {'study': study_id} if study_id else None
        return self._get('/submissions/', params=params)

    def get_submission(self, submission_id):
        return self._get(f'/submissions/{submission_id}/')

    def _transition_submission(self, submission_id, action, **extra):
        body = {'action': action}
        body.update(extra)
        return self._post(f'/submissions/{submission_id}/transition/', body)

    def approve_submission(self, submission_id):
        return self._transition_submission(submission_id, 'APPROVE')

    def reject_submission(self, submission_id, message, rejection_category):
        """Reject: message must be >= 100 chars; category from Prolific's enum
        (TOO_QUICKLY, FAILED_CHECK, LOW_EFFORT, NO_CODE, OTHER, ...)."""
        if not message or len(message) < 100:
            raise ValueError("Prolific requires a rejection message of at least 100 characters")
        return self._transition_submission(
            submission_id, 'REJECT',
            message=message, rejection_category=rejection_category)

    def complete_submission(self, submission_id, completion_code, **code_data):
        """Trigger a researcher-actor completion code for a submission."""
        extra = {'completion_code': completion_code}
        if code_data:
            extra['completion_code_data'] = code_data
        return self._transition_submission(submission_id, 'COMPLETE', **extra)

    def bulk_approve(self, study_id, submission_ids):
        return self._post('/submissions/bulk-approve/',
                          {'study_id': study_id, 'submission_ids': list(submission_ids)})

    def screen_out_submissions(self, study_id, submission_ids,
                               increase_places=False):
        """Paid screen-out for ACTIVE submissions (fixed screen-out feature)."""
        return self._post(
            f'/studies/{study_id}/screen-out-submissions/',
            {'submission_ids': list(submission_ids),
             'increase_places': bool(increase_places)})

    # --- bonuses --------------------------------------------------------------

    def set_up_bonuses(self, study_id, bonuses):
        """Create a bulk bonus payment.

        ``bonuses``: list of (participant_id, amount) pairs; amounts are in
        the study's currency (e.g. 1.50). Returns the bulk payment object —
        pass its id to pay_bonuses() to dispatch.
        """
        csv_bonuses = "\n".join(f"{pid},{amount}" for pid, amount in bonuses)
        return self._post('/submissions/bonus-payments/',
                          {'study_id': study_id, 'csv_bonuses': csv_bonuses})

    def pay_bonuses(self, bulk_payment_id):
        return self._post(f'/bulk-bonus-payments/{bulk_payment_id}/pay/')

    # --- participant groups (qualification sync) ------------------------------

    def list_participant_groups(self, workspace_id=None, project_id=None):
        params = {}
        if workspace_id:
            params['workspace_id'] = workspace_id
        if project_id:
            params['project_id'] = project_id
        return self._get('/participant-groups/', params=params or None)

    def create_participant_group(self, project_id, name, description=""):
        return self._post('/participant-groups/',
                          {'project_id': project_id, 'name': name,
                           'description': description})

    def delete_participant_group(self, group_id):
        return self._delete(f'/participant-groups/{group_id}/')

    def list_group_participants(self, group_id):
        return self._get(f'/participant-groups/{group_id}/participants/')

    def add_to_group(self, group_id, participant_ids):
        return self._post(f'/participant-groups/{group_id}/participants/',
                          {'participant_ids': list(participant_ids)})

    def remove_from_group(self, group_id, participant_ids):
        return self._request(
            'DELETE', f'/participant-groups/{group_id}/participants/',
            json_body={'participant_ids': list(participant_ids)})

    # --- filters / testing ----------------------------------------------------

    def list_filters(self):
        return self._get('/filters/')

    def eligibility_count(self, filters):
        return self._post('/eligibility-count/', {'filters': filters})

    def create_test_participant(self):
        """Create a test participant (no-credit testing flow)."""
        return self._post('/researchers/participants/')

    def make_test_study(self, study_id):
        return self._post(f'/studies/{study_id}/test-study')

    # --- webhooks (hooks) -----------------------------------------------------

    def list_hook_event_types(self):
        return self._get('/hooks/event-types/')

    def create_hook_secret(self, workspace_id):
        """One active secret per workspace; used to sign deliveries."""
        return self._post('/hooks/secrets/', {'workspace_id': workspace_id})

    def list_hook_secrets(self, workspace_id):
        return self._get('/hooks/secrets/', params={'workspace_id': workspace_id})

    def list_hook_subscriptions(self, workspace_id):
        return self._get('/hooks/subscriptions/', params={'workspace_id': workspace_id})

    def create_hook_subscription(self, workspace_id, event_type, target_url):
        """Create a subscription; Prolific then confirms against target_url
        (which must be public HTTPS)."""
        return self._post('/hooks/subscriptions/',
                          {'workspace_id': workspace_id,
                           'event_type': event_type,
                           'target_url': target_url})

    def delete_hook_subscription(self, subscription_id):
        return self._delete(f'/hooks/subscriptions/{subscription_id}/')

    def hook_subscription_events(self, subscription_id):
        """Delivery log for a subscription (debugging failed deliveries)."""
        return self._get(f'/hooks/subscriptions/{subscription_id}/events/')
