"""
Unit tests for per-annotator quota resolution on UserStateManager.
"""

from potato.user_state_management import UserStateManager


class TestQuotaResolution:
    def test_default_from_quota(self):
        usm = UserStateManager({
            "per_annotator_quota": {"default": 50},
        })
        assert usm._resolve_user_quota("alice") == 50

    def test_by_user_overrides_default(self):
        usm = UserStateManager({
            "per_annotator_quota": {
                "default": 50,
                "by_user": {"alice": 5},
            },
        })
        assert usm._resolve_user_quota("alice") == 5
        assert usm._resolve_user_quota("bob") == 50

    def test_by_role_resolves_when_user_role_set(self):
        usm = UserStateManager({
            "per_annotator_quota": {
                "default": 50,
                "by_user_role": {"expert": 20, "novice": 200},
            },
            "user_roles": {"alice": "expert", "bob": "novice"},
        })
        assert usm._resolve_user_quota("alice") == 20
        assert usm._resolve_user_quota("bob") == 200
        # Unknown user falls back to default
        assert usm._resolve_user_quota("carol") == 50

    def test_by_user_wins_over_by_role(self):
        usm = UserStateManager({
            "per_annotator_quota": {
                "default": 50,
                "by_user": {"alice": 7},
                "by_user_role": {"expert": 20},
            },
            "user_roles": {"alice": "expert"},
        })
        assert usm._resolve_user_quota("alice") == 7

    def test_empty_quota_falls_back_to_legacy(self):
        usm = UserStateManager({})
        # Default legacy max_annotations_per_user is -1
        assert usm._resolve_user_quota("alice") == -1
