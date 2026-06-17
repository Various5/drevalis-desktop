"""Unit tests for the ComfyUI/RunPod base-URL SSRF guard.

``_assert_safe_base_url`` rejects non-http(s) schemes and link-local /
cloud-metadata literal IPs while ALLOWING loopback + RFC1918 (the normal
local/LAN/RunPod ComfyUI case).
"""

from __future__ import annotations

import pytest

from drevalis.services.comfyui._monolith import _assert_safe_base_url


class TestAssertSafeBaseUrl:
    def test_loopback_allowed(self) -> None:
        _assert_safe_base_url("http://127.0.0.1:8188")
        _assert_safe_base_url("http://localhost:8188")

    def test_private_lan_allowed(self) -> None:
        _assert_safe_base_url("http://192.168.1.50:8188")
        _assert_safe_base_url("http://10.0.0.5:8188")

    def test_public_host_allowed(self) -> None:
        _assert_safe_base_url("https://pod-abc.runpod.io")

    def test_metadata_ip_rejected(self) -> None:
        with pytest.raises(ValueError):
            _assert_safe_base_url("http://169.254.169.254/latest/meta-data/")

    def test_non_http_scheme_rejected(self) -> None:
        with pytest.raises(ValueError):
            _assert_safe_base_url("file:///etc/passwd")
        with pytest.raises(ValueError):
            _assert_safe_base_url("gopher://127.0.0.1:8188")
