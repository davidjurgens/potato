"""Each deploy provider's install hint names an extra that installs what it needs.

`potato deploy` refuses a provider whose modules are missing and prints
``pip install 'potato-annotation[<install_extra>]'``. The huggingface provider
inherited the base ``deploy`` extra, which is paramiko only, so following the
hint left huggingface_hub missing and the refusal unchanged.
"""

import os
import re
from unittest import mock

import pytest

from potato.deploy.providers.base import available_providers, get_provider

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Import name -> distribution name, where they differ.
DISTRIBUTION = {"openstack": "openstacksdk"}


def _extras():
    """extras_require as setup.py declares it, read without installing."""
    captured = {}
    import setuptools

    with mock.patch.object(setuptools, "setup", lambda **kw: captured.update(kw)):
        source = open(os.path.join(ROOT, "setup.py"), encoding="utf-8").read()
        cwd = os.getcwd()
        os.chdir(ROOT)
        try:
            path = os.path.join(ROOT, "setup.py")
            exec(compile(source, path, "exec"), {"__name__": "__main__", "__file__": path})
        finally:
            os.chdir(cwd)
    return captured["extras_require"]


def _names(requirements):
    return {re.split(r"[<>=!~\[; ]", r, 1)[0].lower().replace("_", "-")
            for r in requirements}


@pytest.mark.parametrize("name", [n for n in available_providers()
                                  if get_provider(n).requires])
def test_the_install_hint_installs_every_required_module(name):
    provider = get_provider(name)
    extras = _extras()
    assert provider.install_extra in extras, provider.install_extra
    installed = _names(extras[provider.install_extra])
    for module in provider.requires:
        dist = DISTRIBUTION.get(module, module).lower().replace("_", "-")
        assert dist in installed, (
            f"{name}: pip install 'potato-annotation[{provider.install_extra}]' "
            f"does not install {dist}")
