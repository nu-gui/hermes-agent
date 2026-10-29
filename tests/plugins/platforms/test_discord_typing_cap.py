"""Ghost-typing regression tests: persistent typing loops must self-expire.

Field incident 2026-10-29: a turn interrupted between ``send_typing`` and
``stop_typing`` leaked a 12-second POST loop that kept the Discord
"Rocco is typing..." indicator alive indefinitely.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Hermetic import: stub the Discord SDK + ruamel so the adapter module imports
# without real installs (the code paths under test never touch them).
import sys
import types


from unittest.mock import MagicMock as _AutoAttr


def _stub_pkg(name: str) -> types.ModuleType:
    """PEP 562 stub: any attribute access auto-resolves to a MagicMock."""
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    mod.__path__ = []  # mark as package so submodule imports resolve
    mod.__getattr__ = lambda attr: _AutoAttr()  # auto-attribute (instance, not class)
    sys.modules[name] = mod
    if "." in name:
        parent, _, child = name.rpartition(".")
        setattr(_stub_pkg(parent), child, mod)
    return mod


for _name in (
    "discord", "discord.http", "discord.ext", "discord.ext.tasks",
    "discord.ui", "discord.app_commands", "discord.utils",
    "ruamel", "ruamel.yaml", "ruamel.yaml.error", "ruamel.yaml.main",
    "ruamel.yaml.constructor", "ruamel.yaml.representer", "ruamel.yaml.resolver",
    "ruamel.yaml.scanner", "ruamel.yaml.parser", "ruamel.yaml.composer",
    "ruamel.yaml.emitter", "ruamel.yaml.serializer", "ruamel.yaml.loader",
    "ruamel.yaml.dumper", "ruamel.yaml.comments", "ruamel.yaml.scalarstring",
):
    _stub_pkg(_name)

from plugins.platforms.discord.adapter import DiscordAdapter


def _make_adapter() -> DiscordAdapter:
    """Bare adapter with a fake HTTP client — no Discord connection needed."""
    adapter = DiscordAdapter.__new__(DiscordAdapter)
    adapter._typing_tasks = {}
    adapter._client = cast(Any, MagicMock())
    adapter._client.http = MagicMock()
    adapter._client.http.request = AsyncMock(return_value=None)
    return adapter


@pytest.mark.asyncio
async def test_typing_loop_self_expires_after_cap():
    """A leaked loop (stop_typing never called) must end on its own."""
    adapter = _make_adapter()
    with patch.object(DiscordAdapter, "MAX_TYPING_SECONDS", 0.05):
        await adapter.send_typing("chan-1")
        task = adapter._typing_tasks["chan-1"]
        await asyncio.wait_for(task, timeout=5)
    assert "chan-1" not in adapter._typing_tasks


@pytest.mark.asyncio
async def test_stop_typing_still_cancels_cleanly():
    """The normal path still cancels immediately, well under the cap."""
    adapter = _make_adapter()
    await adapter.send_typing("chan-2")
    assert "chan-2" in adapter._typing_tasks
    await adapter.stop_typing("chan-2")
    assert "chan-2" not in adapter._typing_tasks
    assert adapter._typing_tasks == {}


@pytest.mark.asyncio
async def test_second_send_typing_is_idempotent():
    """Duplicate sends keep one loop, as before."""
    adapter = _make_adapter()
    with patch.object(DiscordAdapter, "MAX_TYPING_SECONDS", 30):
        await adapter.send_typing("chan-3")
        first = adapter._typing_tasks["chan-3"]
        await adapter.send_typing("chan-3")
        assert adapter._typing_tasks["chan-3"] is first
    await adapter.stop_typing("chan-3")
