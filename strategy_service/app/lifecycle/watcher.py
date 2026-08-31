"""
Hot-reload watcher — monitors user strategy directory for file changes.

Uses watchfiles (fast Rust-backed watcher) to detect:
  - New .py files → load and register
  - Modified .py files → reload and re-register (triggers lifecycle restart)
  - Deleted .py files → deregister

The lifecycle manager will automatically restart running instances
that use a reloaded strategy.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.registry.registry import get_loader, get_registry

settings = get_settings()
log = get_logger(__name__)


class HotReloadWatcher:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if not settings.USER_STRATEGIES_DIR.exists():
            settings.USER_STRATEGIES_DIR.mkdir(parents=True, exist_ok=True)

        self._running = True
        self._task = asyncio.create_task(self._watch(), name="hot-reload-watcher")
        log.info("hot_reload_watcher_started",
                 directory=str(settings.USER_STRATEGIES_DIR))

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("hot_reload_watcher_stopped")

    async def _watch(self) -> None:
        try:
            from watchfiles import awatch, Change
            async for changes in awatch(
                settings.USER_STRATEGIES_DIR,
                stop_event=asyncio.Event(),
            ):
                for change_type, path_str in changes:
                    path = Path(path_str)
                    if not path.suffix == ".py" or path.name.startswith("_"):
                        continue

                    if change_type in (Change.added, Change.modified):
                        log.info("strategy_file_changed",
                                 event=change_type.name, path=path.name)
                        await self._reload_file(path)

                    elif change_type == Change.deleted:
                        # Deregister by stem name convention
                        await get_registry().deregister(path.stem)
                        log.info("strategy_file_deleted", path=path.name)

        except asyncio.CancelledError:
            pass
        except ImportError:
            # watchfiles not installed — fall back to polling
            log.warning("watchfiles_not_installed_using_polling")
            await self._poll()

    async def _reload_file(self, path: Path) -> None:
        loader = get_loader()
        reg = await loader.load_file(path)
        if reg:
            log.info("strategy_hot_reloaded",
                     name=reg.name, version=reg.version, path=path.name)
            # Notify lifecycle manager to restart instances using this strategy
            from app.lifecycle.manager import get_lifecycle_manager
            manager = get_lifecycle_manager()
            for instance in manager.list_instances():
                if instance.registration.name == reg.name:
                    log.info("restarting_instance_after_reload",
                             instance_id=instance.instance_id)
                    await manager.stop(instance.instance_id)
                    await manager.start(
                        strategy_name=reg.name,
                        symbol=instance.symbol,
                        exchange=instance.exchange,
                        timeframe=instance.timeframe,
                        params=instance.params,
                        trading_mode=instance.trading_mode,
                    )

    async def _poll(self, interval_s: float = 5.0) -> None:
        """Fallback polling watcher when watchfiles is unavailable."""
        known: dict[Path, float] = {}
        while self._running:
            for path in settings.USER_STRATEGIES_DIR.glob("*.py"):
                if path.name.startswith("_"):
                    continue
                mtime = path.stat().st_mtime
                if path not in known or known[path] != mtime:
                    known[path] = mtime
                    await self._reload_file(path)
            await asyncio.sleep(interval_s)
