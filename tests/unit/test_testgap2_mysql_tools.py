"""
`potato deploy pull` on a MySQL study.

SFTP and `docker cp` copy the output directory, which holds no annotator on
MySQL. The pull now goes through the admin archive, which writes them out of
the database. The archive itself is tested against a real MySQL server in
tests/server/test_testgap2_mysql.py.
"""

import os
from unittest.mock import patch

import pytest

from potato.deploy.providers.base import ProviderError
from potato.deploy.providers.digitalocean import DigitalOceanProvider
from potato.deploy.providers.local import LocalProvider
from potato.deploy.state import DeploymentRecord
from tests.helpers.test_utils import create_test_directory

MYSQL = "database: {type: mysql, host: db, database: d, username: u, password: p}\n"


def _record(name, database):
    d = create_test_directory(name)
    path = os.path.join(d, "config.yaml")
    with open(path, "w") as f:
        f.write("annotation_task_name: t\n" + (MYSQL if database else ""))
    return DeploymentRecord(name="t", provider="x", url="https://example.test",
                            provider_ref={"container": "c"},
                            spec={"config_path": path})


@pytest.mark.parametrize("provider_cls", [DigitalOceanProvider, LocalProvider])
def test_a_mysql_study_is_pulled_through_the_archive(provider_cls):
    record = _record(f"tg2_pull_{provider_cls.__name__}", database=True)
    provider = provider_cls(token="t", console=lambda *_: None)
    with patch("potato.deploy.providers.vm_base.https_fallback",
               return_value="archive") as fallback, \
            patch.object(provider_cls, "_session", create=True,
                         side_effect=AssertionError("used SFTP")):
        assert provider.pull(record, "dest") == "archive"
    assert fallback.called


@pytest.mark.parametrize("provider_cls", [DigitalOceanProvider, LocalProvider])
def test_without_the_archive_a_mysql_pull_says_why(provider_cls):
    record = _record(f"tg2_pull_none_{provider_cls.__name__}", database=True)
    provider = provider_cls(token="t", console=lambda *_: None)
    with patch("potato.deploy.providers.vm_base.https_fallback", return_value=None):
        with pytest.raises(ProviderError, match="mysqldump"):
            provider.pull(record, "dest")


def test_a_file_study_still_uses_sftp():
    record = _record("tg2_pull_files", database=False)
    provider = DigitalOceanProvider(token="t", console=lambda *_: None)
    with patch.object(DigitalOceanProvider, "_session",
                      side_effect=ProviderError("sftp attempted")), \
            patch("potato.deploy.providers.vm_base.https_fallback", return_value=None):
        with pytest.raises(ProviderError, match="sftp attempted"):
            provider.pull(record, "dest")
