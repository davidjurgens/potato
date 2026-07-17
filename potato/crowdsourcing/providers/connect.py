"""
CloudResearch Connect provider.

Connect is the platform CloudResearch migrates MTurk Toolkit users to. Its
external-study ("Project Link") model passes `participantId` (plus optional
`assignmentId` and `projectId`) to your study URL, and completion is verified
with a fixed completion code or a completion redirect configured on the
Connect project.

.. code-block:: yaml

    crowdsourcing:
      provider: connect
      connect:
        completion:
          code: "ABC123"
          # Or a redirect, using the URL shown in your Connect project's
          # completion settings:
          # redirect_url: "https://connect.cloudresearch.com/participant/project/<id>/complete"

Note: Connect's REST API (connect-api.cloudresearch.com) is not wired up yet —
its endpoint documentation requires manual verification. The URL-parameter and
completion-code flow below is the documented researcher workflow.
"""

from potato.crowdsourcing.base import CrowdProvider


class ConnectProvider(CrowdProvider):
    name = "connect"
    display_name = "Connect"

    def id_param(self):
        return self.config.get('id_param', 'participantId')

    def extract_identity(self, request_args):
        identity = super().extract_identity(request_args)
        if identity is None:
            return None
        identity.session_id = request_args.get('assignmentId')
        identity.study_id = request_args.get('projectId')
        return identity
