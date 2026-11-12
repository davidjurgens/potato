"""
Config-driven provider for any URL-parameter + completion-code platform.

Covers panels like Besample, Positly, User Interviews, Testable Minds, and
Cint without platform-specific code:

.. code-block:: yaml

    crowdsourcing:
      provider: generic
      generic:
        platform_label: "Besample"
        id_param: response_id
        capture_params: [study, session]
        completion:
          code: "BSMP-4432"
          redirect_url: "https://besample.app/complete?rid={worker_id}&code={code}"
          failed_code: "BSMP-FAIL"
          auto_redirect: false
"""

from potato.crowdsourcing.base import CrowdProvider


class GenericProvider(CrowdProvider):
    """Everything is inherited: the base class implements the generic flow."""

    name = "generic"
    display_name = "your crowdsourcing platform"
