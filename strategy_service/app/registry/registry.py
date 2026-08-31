"""
Strategy Registry — single source of truth for all loaded strategies.

Responsibilities:
  - Register / deregister strategy classes
  - Track version hash per strategy file
  - Provide lookup by name, type, status
  - Thread-safe (asyncio.Lock)
"""
from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Optional, Type

from app.core.logging import get_logger
from app.sdk.base import StrategyBase
from app.sdk.types import StrategyMetadata, StrategyStatus, StrategyType

log = get_logger(__name__)


class StrategyRegistration:
    """One entry in the registry per unique strategy name."""

    def __init__(
        self,
        cls: Type[StrategyBase],
        source_path: Optional[Path] = None,
        file_hash: str = "",
        is_builtin: bool = False,
    ) -> None:
        self.cls = cls
        self.metadata: StrategyMetadata = cls.METADATA
        self.source_path = source_path
        self.file_hash = file_hash
        self.is_builtin = is_builtin
        self.status: StrategyStatus = StrategyStatus.REGISTERED
        self.load_error: Optional[str] = None

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "version":     self.version,
            "type":        self.metadata.strategy_type.value,
            "author":      self.metadata.author,
            "description": self.metadata.description,
            "timeframes":  self.metadata.timeframes,
            "symbols":     self.metadata.symbols,
            "min_bars":    self.metadata.min_bars_required,
            "parameters":  self.metadata.parameters,
            "tags":        self.metadata.tags,
            "is_builtin":  self.is_builtin,
            "file_hash":   self.file_hash,
            "source_path": str(self.source_path) if self.source_path else None,
            "status":      self.status.value,
            "load_error":  self.load_error,
        }


class StrategyRegistry:
    """
    Central registry. Singleton — get via get_registry().
    """

    def __init__(self) -> None:
        self._strategies: dict[str, StrategyRegistration] = {}
        self._lock = asyncio.Lock()

    # ── Registration ──────────────────────────────────────────────────────────

    async def register(
        self,
        cls: Type[StrategyBase],
        source_path: Optional[Path] = None,
        file_hash: str = "",
        is_builtin: bool = False,
    ) -> StrategyRegistration:
        async with self._lock:
            name = cls.METADATA.name
            existing = self._strategies.get(name)

            if existing and existing.file_hash == file_hash and file_hash:
                log.debug("strategy_unchanged", name=name, hash=file_hash[:8])
                return existing

            reg = StrategyRegistration(
                cls=cls,
                source_path=source_path,
                file_hash=file_hash,
                is_builtin=is_builtin,
            )
            self._strategies[name] = reg
            action = "reloaded" if existing else "registered"
            log.info(f"strategy_{action}", name=name, version=cls.METADATA.version,
                     hash=file_hash[:8] if file_hash else "builtin")
            return reg

    async def deregister(self, name: str) -> bool:
        async with self._lock:
            if name in self._strategies:
                del self._strategies[name]
                log.info("strategy_deregistered", name=name)
                return True
            return False

    # ── Queries ───────────────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[StrategyRegistration]:
        return self._strategies.get(name)

    def get_all(self) -> list[StrategyRegistration]:
        return list(self._strategies.values())

    def get_by_type(self, strategy_type: StrategyType) -> list[StrategyRegistration]:
        return [r for r in self._strategies.values()
                if r.metadata.strategy_type == strategy_type]

    def instantiate(self, name: str) -> StrategyBase:
        reg = self.get(name)
        if not reg:
            raise KeyError(f"Strategy '{name}' not registered.")
        return reg.cls()

    @property
    def count(self) -> int:
        return len(self._strategies)

    def names(self) -> list[str]:
        return list(self._strategies.keys())


# ── Strategy Loader ───────────────────────────────────────────────────────────

class StrategyLoader:
    """
    Loads strategy classes from Python files.

    Builtin strategies: imported normally via importlib.
    User strategies:    loaded from filesystem paths via importlib.util.spec_from_file_location
    """

    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    async def load_builtins(self) -> int:
        """Discover and register all built-in strategy classes."""
        from app.strategies.builtin.trend.ema_crossover import EMACrossoverStrategy
        from app.strategies.builtin.momentum.rsi_momentum import RSIMomentumStrategy
        from app.strategies.builtin.mean_reversion.bollinger_reversion import BollingerReversionStrategy
        from app.strategies.builtin.breakout.donchian_breakout import DonchianBreakoutStrategy
        from app.strategies.builtin.ml.ml_signal import MLSignalStrategy

        builtins = [
            EMACrossoverStrategy,
            RSIMomentumStrategy,
            BollingerReversionStrategy,
            DonchianBreakoutStrategy,
            MLSignalStrategy,
        ]

        count = 0
        for cls in builtins:
            await self._registry.register(cls, is_builtin=True)
            count += 1

        log.info("builtin_strategies_loaded", count=count)
        return count

    async def load_file(self, path: Path) -> Optional[StrategyRegistration]:
        """Load a single user strategy file. Returns registration or None on error."""
        from app.core.config import get_settings
        settings = get_settings()

        if not path.exists() or not path.suffix == ".py":
            log.warning("invalid_strategy_file", path=str(path))
            return None

        if path.stat().st_size > settings.MAX_STRATEGY_FILE_SIZE:
            log.warning("strategy_file_too_large", path=str(path),
                        size=path.stat().st_size)
            return None

        file_hash = _hash_file(path)

        try:
            cls = _import_strategy_class(path)
            if cls is None:
                log.warning("no_strategy_class_found", path=str(path))
                return None

            reg = await self._registry.register(
                cls, source_path=path, file_hash=file_hash, is_builtin=False
            )
            return reg

        except Exception as exc:
            log.error("strategy_load_error", path=str(path), error=str(exc))
            return None

    async def load_directory(self, directory: Path) -> int:
        """Scan a directory and load all .py files as strategies."""
        if not directory.exists():
            log.warning("strategy_dir_not_found", path=str(directory))
            return 0

        count = 0
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            reg = await self.load_file(path)
            if reg:
                count += 1

        log.info("user_strategies_loaded", directory=str(directory), count=count)
        return count


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _import_strategy_class(path: Path) -> Optional[Type[StrategyBase]]:
    """Dynamically import a strategy class from a file path."""
    module_name = f"user_strategy_{path.stem}_{id(path)}"

    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[attr-defined]

    # Find the first concrete StrategyBase subclass defined in this module
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(obj, StrategyBase)
            and obj is not StrategyBase
            and obj.__module__ == module_name
            and hasattr(obj, "METADATA")
        ):
            return obj

    return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_registry: Optional[StrategyRegistry] = None
_loader: Optional[StrategyLoader] = None


def get_registry() -> StrategyRegistry:
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry


def get_loader() -> StrategyLoader:
    global _loader
    if _loader is None:
        _loader = StrategyLoader(get_registry())
    return _loader
