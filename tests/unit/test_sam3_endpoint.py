"""
The SAM 3 endpoint: registration, licence posture, and honest refusals.

There are no weights here and there never will be — Potato redistributes no
SAM 3 files, because the licence requires redistribution to carry the licence
and because the three graphs are ~3.5 GB. What this file checks is everything
that must be true WITHOUT the weights:

* the endpoint registers lazily, so nobody pays for it at boot;
* a config that would silently do nothing is refused at construction, with the
  licence named rather than paraphrased;
* the paths that are not implemented say so, and say what to use instead. A
  segmentation model with a mis-read tensor contract returns confident, wrong
  masks — measured at 70-148 px of centroid error when that mistake was made
  with SAM 1 — so "not implemented" is the correct state until a parity test
  against real weights exists.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from potato.ai.ai_endpoint import AIEndpointFactory


class TestRegistration:
    def test_it_is_registered_lazily(self):
        assert AIEndpointFactory.has_endpoint("sam3")

    def test_importing_potato_does_not_import_onnxruntime(self):
        """The whole point of the lazy registry.

        A guarded module-level import still loads the stack for everyone who
        happens to have it installed, which has previously added seconds to
        every start-up on machines that were never going to use it.

        Run in a SUBPROCESS. The obvious in-process version — delete every
        `potato*` entry from sys.modules and re-import — poisons every test
        that runs afterwards, because the module-level registries and config
        singletons they hold references to are replaced underneath them. It
        cost 56 unrelated failures to learn that, all of which passed in
        isolation.
        """
        code = (
            "import sys, json\n"
            "import potato.ai.ai_endpoint as e\n"
            "print(json.dumps({\n"
            "    'registered': e.AIEndpointFactory.has_endpoint('sam3'),\n"
            "    'onnxruntime': 'onnxruntime' in sys.modules,\n"
            "    'torch': 'torch' in sys.modules,\n"
            "}))\n"
        )
        result = subprocess.run([sys.executable, "-c", code],
                                capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr[:2000]
        state = json.loads(result.stdout.strip().splitlines()[-1])
        assert state["registered"], "sam3 is not registered at all"
        assert not state["onnxruntime"], "onnxruntime loaded at import time"
        assert not state["torch"], "torch loaded at import time"


class TestConstruction:
    def test_onnx_mode_without_a_model_dir_is_refused(self):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        with pytest.raises(ValueError) as raised:
            SAM3Endpoint({"mode": "onnx"})
        message = str(raised.value)
        assert "model_dir" in message
        assert "SAM License" in message, (
            "the licence has to be named where the user is choosing to use it")

    def test_server_mode_without_a_url_is_refused(self):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        with pytest.raises(ValueError) as raised:
            SAM3Endpoint({"mode": "server"})
        assert "base_url" in str(raised.value)

    def test_an_unknown_mode_names_the_two_that_work(self):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        with pytest.raises(ValueError) as raised:
            SAM3Endpoint({"mode": "magic", "model_dir": "/tmp"})
        assert "onnx" in str(raised.value) and "server" in str(raised.value)

    def test_a_trailing_slash_on_the_url_does_not_double_up(self):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        endpoint = SAM3Endpoint({"mode": "server",
                                 "base_url": "http://localhost:9000/"})
        assert endpoint.base_url == "http://localhost:9000"


class TestCapabilities:
    def test_it_declares_text_prompt_segmentation(self):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        capabilities = SAM3Endpoint(
            {"mode": "server", "base_url": "http://x"}).get_capabilities()
        assert capabilities.text_prompt_segmentation
        assert capabilities.mask_output
        assert capabilities.bounding_box_output
        assert capabilities.vision_input


class TestHonestRefusals:
    def test_the_text_query_path_refuses_rather_than_returning_nothing(self):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        endpoint = SAM3Endpoint({"mode": "server", "base_url": "http://x"})
        with pytest.raises(NotImplementedError):
            endpoint.query("find the cones")

    def test_no_phrases_means_no_call_and_no_results(self):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        endpoint = SAM3Endpoint({"mode": "server", "base_url": "http://x"})
        assert endpoint.detect(object(), []) == []

    def test_missing_graphs_name_the_files_and_the_licence(self, tmp_path):
        from potato.ai.sam3_endpoint import SAM3Endpoint

        pytest.importorskip("onnxruntime")
        endpoint = SAM3Endpoint({"mode": "onnx", "model_dir": str(tmp_path)})
        with pytest.raises(RuntimeError) as raised:
            endpoint._load_onnx()
        message = str(raised.value)
        assert "sam3_image_encoder.onnx" in message
        assert "redistributes no" in message
        assert "SAM License" in message

    def test_local_inference_points_at_what_does_work(self, tmp_path):
        """Unimplemented on purpose, and it says where to go instead."""
        from potato.ai.sam3_endpoint import SAM3Endpoint

        endpoint = SAM3Endpoint({"mode": "onnx", "model_dir": str(tmp_path)})
        with pytest.raises((NotImplementedError, RuntimeError)) as raised:
            endpoint.detect(object(), ["cone"])
        message = str(raised.value)
        assert "Grounding DINO" in message or "sam3_image_encoder" in message


class TestLicencePosture:
    def test_nothing_in_the_zoo_offers_sam3_as_a_download(self):
        from potato.model_zoo import MODELS

        spec = MODELS["sam3"]
        assert not spec.files, "Potato must not distribute SAM 3 weights"
        assert spec.licence_ack, "the licence has to be accepted explicitly"
        assert spec.runs_on == "server"

    def test_the_cli_refuses_to_fetch_it_without_acceptance(self):
        from potato.models_cli import download_model

        with pytest.raises(RuntimeError) as raised:
            download_model("sam3")
        assert "--accept-licence" in str(raised.value)
