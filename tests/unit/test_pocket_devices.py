"""Unit tests for device classification and the per-user device tracker."""

import json
import os
import threading

import pytest

from potato.pocket.devices import (
    DESKTOP,
    MOBILE,
    TABLET,
    DeviceTracker,
    classify_user_agent,
    clear_device_tracker,
    is_touch_device,
)
from tests.helpers.test_utils import create_test_directory

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
          "Mobile/15E148 Safari/604.1")
ANDROID_PHONE = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")
ANDROID_TABLET = ("Mozilla/5.0 (Linux; Android 13; SM-X710) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
IPAD_LEGACY = ("Mozilla/5.0 (iPad; CPU OS 12_5 like Mac OS X) "
               "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/12.1.2 "
               "Mobile/15E148 Safari/604.1")
IPAD_DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
                   "Safari/605.1.15")  # iPadOS 13+ masquerades as desktop
DESKTOP_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 "
                  "Safari/537.36")
DESKTOP_FIREFOX = ("Mozilla/5.0 (X11; Linux x86_64; rv:126.0) "
                   "Gecko/20100101 Firefox/126.0")
WINDOWS_PHONE = ("Mozilla/5.0 (Windows Phone 10.0; Android 6.0.1; NOKIA; "
                 "Lumia 635) AppleWebKit/537.36")
PYTHON_REQUESTS = "python-requests/2.32.0"


class TestClassification:
    @pytest.mark.parametrize("ua,expected", [
        (IPHONE, MOBILE),
        (ANDROID_PHONE, MOBILE),
        (WINDOWS_PHONE, MOBILE),
        (ANDROID_TABLET, TABLET),
        (IPAD_LEGACY, TABLET),
        (DESKTOP_CHROME, DESKTOP),
        (DESKTOP_FIREFOX, DESKTOP),
        # iPadOS 13+ lies; server-side classification must NOT guess touch
        # (the client-side coarse-pointer check covers it).
        (IPAD_DESKTOP_UA, DESKTOP),
        # API clients and degenerate UAs are desktop — the no-op class.
        (PYTHON_REQUESTS, DESKTOP),
        ("", DESKTOP),
        (None, DESKTOP),
    ])
    def test_classify(self, ua, expected):
        assert classify_user_agent(ua) == expected

    def test_is_touch_device(self):
        assert is_touch_device(IPHONE)
        assert is_touch_device(ANDROID_TABLET)
        assert not is_touch_device(DESKTOP_CHROME)
        assert not is_touch_device(PYTHON_REQUESTS)


class TestTracker:
    def make_tracker(self, name):
        return DeviceTracker(create_test_directory(name))

    def test_record_and_stats(self):
        tracker = self.make_tracker("devices_basic")
        tracker.record("ana", IPHONE, "annotate")
        tracker.record("ana", IPHONE, "pocket")
        tracker.record("ben", DESKTOP_CHROME, "annotate")
        stats = tracker.stats()
        assert stats["summary"] == {"n_users_seen": 2, "n_touch_users": 1}
        ana = [r for r in stats["users"] if r["username"] == "ana"][0]
        assert ana["mobile_visits"] == 2
        assert ana["pocket_visits"] == 1
        assert ana["used_touch_device"] is True
        assert ana["last_device"] == MOBILE
        ben = [r for r in stats["users"] if r["username"] == "ben"][0]
        assert ben["used_touch_device"] is False
        assert ben["desktop_visits"] == 1

    def test_persists_and_reloads(self):
        test_dir = create_test_directory("devices_persist")
        tracker = DeviceTracker(test_dir)
        tracker.record("ana", ANDROID_TABLET, "annotate")
        path = os.path.join(test_dir, "pocket", "device_visits.json")
        assert os.path.exists(path)
        with open(path) as f:
            assert json.load(f)["ana"]["visits"][TABLET] == 1
        reborn = DeviceTracker(test_dir)
        assert reborn.stats()["users"][0]["tablet_visits"] == 1

    def test_client_hint_marks_touch(self):
        tracker = self.make_tracker("devices_hint")
        # An iPad with a desktop UA looks like desktop server-side...
        tracker.record("cara", IPAD_DESKTOP_UA, "annotate")
        assert tracker.stats()["summary"]["n_touch_users"] == 0
        # ...until the client-side coarse-pointer hint arrives.
        tracker.record_client_hint("cara", TABLET)
        stats = tracker.stats()
        assert stats["summary"]["n_touch_users"] == 1
        assert stats["users"][0]["last_device"] == TABLET

    def test_client_hint_ignores_bogus_values(self):
        tracker = self.make_tracker("devices_hint_bogus")
        tracker.record("dave", DESKTOP_CHROME, "annotate")
        tracker.record_client_hint("dave", "desktop")
        tracker.record_client_hint("dave", "<script>")
        tracker.record_client_hint("nobody", TABLET)  # unknown user: no-op
        stats = tracker.stats()
        assert stats["summary"]["n_touch_users"] == 0
        assert len(stats["users"]) == 1

    def test_no_output_dir_is_memory_only(self):
        tracker = DeviceTracker(None)
        tracker.record("eve", IPHONE, "annotate")
        assert tracker.stats()["summary"]["n_touch_users"] == 1

    def test_concurrent_records(self):
        tracker = self.make_tracker("devices_threads")

        def hammer(name):
            for _ in range(25):
                tracker.record(name, IPHONE, "annotate")

        threads = [threading.Thread(target=hammer, args=(f"u{i}",))
                   for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stats = tracker.stats()
        assert stats["summary"]["n_users_seen"] == 4
        assert all(r["mobile_visits"] == 25 for r in stats["users"])

    def test_singleton_clear(self):
        clear_device_tracker()  # must not raise, before or after use
