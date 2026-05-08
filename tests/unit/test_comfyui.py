"""Tests for ComfyUI workflow injection and server pool."""

from __future__ import annotations

import asyncio
import copy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from drevalis.schemas.comfyui import NodeInput, WorkflowInputMapping
from drevalis.services.comfyui import ComfyUIPool, ComfyUIService

# ── Sample workflow for injection tests ───────────────────────────────────────

SAMPLE_WORKFLOW: dict = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler_ancestral",
            "scheduler": "normal",
            "denoise": 1.0,
            "text": "placeholder positive prompt",
        },
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": 512,
            "height": 512,
            "batch_size": 1,
        },
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "placeholder negative prompt",
        },
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "Drevalis",
        },
    },
}


# ── Workflow injection tests ──────────────────────────────────────────────────


class TestInjectParams:
    """Test ComfyUIService.inject_params (static method)."""

    def test_inject_params_positive_prompt(
        self, sample_workflow_mapping: WorkflowInputMapping
    ) -> None:
        result = ComfyUIService.inject_params(
            workflow=SAMPLE_WORKFLOW,
            mappings=sample_workflow_mapping,
            prompt="a beautiful sunset over mountains",
            negative_prompt="ugly, blurry",
            width=1080,
            height=1920,
            seed=42,
        )

        # Positive prompt injected into node 3's text field
        assert result["3"]["inputs"]["text"] == "a beautiful sunset over mountains"

    def test_inject_params_all_fields(self, sample_workflow_mapping: WorkflowInputMapping) -> None:
        result = ComfyUIService.inject_params(
            workflow=SAMPLE_WORKFLOW,
            mappings=sample_workflow_mapping,
            prompt="test prompt",
            negative_prompt="bad quality",
            width=720,
            height=1280,
            seed=12345,
        )

        # All fields injected correctly
        assert result["3"]["inputs"]["text"] == "test prompt"
        assert result["3"]["inputs"]["seed"] == 12345
        assert result["7"]["inputs"]["text"] == "bad quality"
        assert result["5"]["inputs"]["width"] == 720
        assert result["5"]["inputs"]["height"] == 1280

    def test_inject_params_optional_fields_skipped(self) -> None:
        """Mappings that reference unknown sf_field values should be skipped."""
        mappings = WorkflowInputMapping(
            mappings=[
                NodeInput(
                    sf_field="visual_prompt",
                    node_id="3",
                    field_name="text",
                ),
                NodeInput(
                    sf_field="unknown_field",
                    node_id="99",
                    field_name="whatever",
                ),
            ],
            output_node_id="9",
            output_field_name="images",
        )

        result = ComfyUIService.inject_params(
            workflow=SAMPLE_WORKFLOW,
            mappings=mappings,
            prompt="actual prompt",
            negative_prompt="",
            width=1080,
            height=1920,
            seed=1,
        )

        # The known mapping should be applied
        assert result["3"]["inputs"]["text"] == "actual prompt"

        # The unknown field mapping should not cause an error and node 99
        # should not appear (since it wasn't in the original)
        assert "99" not in result

    def test_inject_params_preserves_other_nodes(
        self, sample_workflow_mapping: WorkflowInputMapping
    ) -> None:
        result = ComfyUIService.inject_params(
            workflow=SAMPLE_WORKFLOW,
            mappings=sample_workflow_mapping,
            prompt="new prompt",
            negative_prompt="new negative",
            width=1080,
            height=1920,
            seed=99,
        )

        # SaveImage node (9) should be untouched
        assert result["9"]["class_type"] == "SaveImage"
        assert result["9"]["inputs"]["filename_prefix"] == "Drevalis"

        # KSampler's non-injected fields should be preserved
        assert result["3"]["inputs"]["steps"] == 20
        assert result["3"]["inputs"]["cfg"] == 7.0

    def test_inject_params_does_not_mutate_original(
        self, sample_workflow_mapping: WorkflowInputMapping
    ) -> None:
        original = copy.deepcopy(SAMPLE_WORKFLOW)
        ComfyUIService.inject_params(
            workflow=SAMPLE_WORKFLOW,
            mappings=sample_workflow_mapping,
            prompt="injected",
            negative_prompt="bad",
            width=1080,
            height=1920,
            seed=42,
        )

        # Original workflow should not be changed
        assert original == SAMPLE_WORKFLOW

    def test_inject_params_missing_node_graceful(self) -> None:
        """Mapping pointing to a non-existent node should not raise."""
        mappings = WorkflowInputMapping(
            mappings=[
                NodeInput(
                    sf_field="visual_prompt",
                    node_id="999",
                    field_name="text",
                ),
            ],
            output_node_id="9",
            output_field_name="images",
        )

        # Should not raise -- missing node is logged and skipped
        result = ComfyUIService.inject_params(
            workflow=SAMPLE_WORKFLOW,
            mappings=mappings,
            prompt="test",
            negative_prompt="",
            width=1080,
            height=1920,
            seed=1,
        )

        # Node 999 should not appear
        assert "999" not in result


# ── ComfyUIPool tests ─────────────────────────────────────────────────────────


class TestComfyUIPool:
    """Test ComfyUIPool registration, acquisition, concurrency."""

    def test_pool_register_and_acquire(self, mock_comfyui_client: AsyncMock) -> None:
        pool = ComfyUIPool()
        server_id = uuid4()

        pool.register_server(server_id, mock_comfyui_client, max_concurrent=2)

        assert server_id in pool._servers
        client, semaphore = pool._servers[server_id]
        assert client is mock_comfyui_client
        # Semaphore should have capacity of 2
        assert semaphore._value == 2

    async def test_pool_acquire_releases_semaphore(self, mock_comfyui_client: AsyncMock) -> None:
        pool = ComfyUIPool()
        server_id = uuid4()
        pool.register_server(server_id, mock_comfyui_client, max_concurrent=2)

        _, sem = pool._servers[server_id]
        assert sem._value == 2

        async with pool.acquire(server_id) as (sid, client):
            assert sid == server_id
            assert client is mock_comfyui_client
            # Inside the context manager, one slot should be taken
            assert sem._value == 1

        # After exiting, semaphore should be fully released
        assert sem._value == 2

    async def test_pool_concurrency_limit(self, mock_comfyui_client: AsyncMock) -> None:
        """Semaphore should block when all slots are in use."""
        pool = ComfyUIPool()
        server_id = uuid4()
        pool.register_server(server_id, mock_comfyui_client, max_concurrent=1)

        acquired = asyncio.Event()
        blocking = asyncio.Event()

        async def hold_lock():
            async with pool.acquire(server_id):
                acquired.set()
                # Hold the lock until signaled
                await blocking.wait()

        # Start a task that holds the single slot
        task = asyncio.create_task(hold_lock())
        await acquired.wait()

        # Try to acquire -- should block since max_concurrent=1
        timed_out = False

        async def try_acquire():
            nonlocal timed_out
            try:
                async with asyncio.timeout(0.1):
                    async with pool.acquire(server_id):
                        pass
            except TimeoutError:
                timed_out = True

        await try_acquire()
        assert timed_out, "Second acquire should have timed out"

        # Release the first lock
        blocking.set()
        await task

    async def test_pool_round_robin_selection(self) -> None:
        """When server_id is None, the pool round-robins across servers.

        The previous least-loaded selector was replaced because it
        couldn't observe slot usage from inside an asyncio.gather()
        fan-out — the load picture was always stale at decision time.
        Round-robin gives the same end-state utilisation under burst
        load and is observable.
        """
        pool = ComfyUIPool()
        server_a = uuid4()
        server_b = uuid4()

        client_a = AsyncMock()
        client_a.base_url = "http://server-a:8188"
        client_b = AsyncMock()
        client_b.base_url = "http://server-b:8188"

        pool.register_server(server_a, client_a, max_concurrent=2)
        pool.register_server(server_b, client_b, max_concurrent=2)

        chosen: list = []
        async with pool.acquire() as (sid1, _c1):
            chosen.append(sid1)
        async with pool.acquire() as (sid2, _c2):
            chosen.append(sid2)

        # Two distinct round-robin picks back-to-back must hit both
        # registered servers exactly once.
        assert set(chosen) == {server_a, server_b}

    async def test_pool_total_capacity(self) -> None:
        """total_capacity sums max_concurrent across all registered servers."""
        pool = ComfyUIPool()

        # Empty pool returns the fallback constant rather than zero so
        # callers don't divide by zero in scene-gen sizing.
        assert pool.total_capacity() > 0

        a, b = uuid4(), uuid4()
        pool.register_server(a, AsyncMock(), max_concurrent=4)
        pool.register_server(b, AsyncMock(), max_concurrent=8)
        assert pool.total_capacity() == 12

        pool.unregister_server(a)
        assert pool.total_capacity() == 8

    async def test_pool_acquire_specific_server(self, mock_comfyui_client: AsyncMock) -> None:
        pool = ComfyUIPool()
        server_id = uuid4()
        pool.register_server(server_id, mock_comfyui_client, max_concurrent=5)

        async with pool.acquire(server_id) as (sid, client):
            assert sid == server_id
            assert client is mock_comfyui_client

    async def test_pool_acquire_unknown_server_raises(self) -> None:
        pool = ComfyUIPool()
        pool.register_server(uuid4(), AsyncMock(), max_concurrent=1)

        with pytest.raises(KeyError, match="not registered"):
            async with pool.acquire(uuid4()):
                pass

    async def test_pool_acquire_empty_pool_raises(self) -> None:
        pool = ComfyUIPool()

        with pytest.raises(RuntimeError, match="No ComfyUI servers"):
            async with pool.acquire():
                pass

    def test_pool_unregister_server(self, mock_comfyui_client: AsyncMock) -> None:
        pool = ComfyUIPool()
        server_id = uuid4()
        pool.register_server(server_id, mock_comfyui_client, max_concurrent=1)

        assert server_id in pool._servers
        pool.unregister_server(server_id)
        assert server_id not in pool._servers

    async def test_pool_close_all(self) -> None:
        pool = ComfyUIPool()
        client1 = AsyncMock()
        client2 = AsyncMock()
        pool.register_server(uuid4(), client1, max_concurrent=1)
        pool.register_server(uuid4(), client2, max_concurrent=1)

        await pool.close_all()
        client1.close.assert_awaited_once()
        client2.close.assert_awaited_once()
        assert len(pool._servers) == 0
