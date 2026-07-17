"""
Crowd-provider registry and singleton.

The singleton lives in this module (NOT in flask_server) so it is immune to
the `__main__` vs `potato.flask_server` module-namespace split that affects
globals assigned in flask_server (see get_prolific_study there).

Resolution order for init_crowd_provider(config) — legacy configs must keep
running byte-identical, so only an explicit `crowdsourcing.provider` selects
the new provider classes:

1. `crowdsourcing.provider` set        -> that provider, fed its sub-block
2. `login.type` url_direct / prolific  -> LegacyUrlDirectProvider (historical
   dual Prolific+MTurk behavior, driven by login.url_argument)
3. otherwise                           -> no provider (standard login)
"""

import logging

from potato.crowdsourcing.providers.clickworker import ClickworkerProvider
from potato.crowdsourcing.providers.connect import ConnectProvider
from potato.crowdsourcing.providers.expert import ExpertInviteProvider
from potato.crowdsourcing.providers.generic import GenericProvider
from potato.crowdsourcing.providers.legacy import LegacyUrlDirectProvider
from potato.crowdsourcing.providers.microworkers import MicroworkersProvider
from potato.crowdsourcing.providers.mturk import MTurkProvider
from potato.crowdsourcing.providers.prolific import ProlificProvider
from potato.crowdsourcing.providers.sona import SonaProvider

logger = logging.getLogger(__name__)

_PROVIDER_CLASSES = {}
_provider_instance = None


def register_provider(cls):
    """Register a CrowdProvider subclass under its ``name``."""
    _PROVIDER_CLASSES[cls.name] = cls
    return cls


def get_supported_providers():
    return sorted(_PROVIDER_CLASSES.keys())


for _cls in (GenericProvider, ProlificProvider, MTurkProvider, LegacyUrlDirectProvider,
             ConnectProvider, SonaProvider, MicroworkersProvider, ClickworkerProvider,
             ExpertInviteProvider):
    register_provider(_cls)


def init_crowd_provider(config):
    """Resolve and instantiate the provider for this deployment (or None)."""
    global _provider_instance

    crowd_config = config.get('crowdsourcing', {}) or {}
    provider_name = crowd_config.get('provider')

    if provider_name:
        cls = _PROVIDER_CLASSES.get(provider_name)
        if cls is None:
            logger.error(
                "Unknown crowdsourcing provider '%s' (supported: %s)",
                provider_name, ', '.join(get_supported_providers()))
            _provider_instance = None
            return None
        provider_config = crowd_config.get(provider_name, {}) or {}
        _provider_instance = cls(provider_config, config)
        logger.info("Initialized crowdsourcing provider: %s", provider_name)
    else:
        login_type = (config.get('login', {}) or {}).get('type', 'standard')
        if login_type in ('url_direct', 'prolific'):
            _provider_instance = LegacyUrlDirectProvider({}, config)
            logger.debug("Using legacy url_direct crowd provider (login.type: %s)", login_type)
        else:
            _provider_instance = None
            return None

    try:
        _provider_instance.init_api()
    except Exception as e:
        logger.warning("Crowd provider API init failed: %s", e)
    return _provider_instance


def get_crowd_provider():
    """The active provider instance, or None when not a crowd deployment."""
    return _provider_instance


def clear_crowd_provider():
    """Reset the singleton (for tests)."""
    global _provider_instance
    _provider_instance = None
