"""
Kite Connect (KiteTicker) live WebSocket feed.

Architecture:
  - KiteTicker runs in a background thread (kiteconnect library is sync)
  - Ticks are pushed onto an asyncio.Queue bridging thread → async
  - The async consumer loop validates → aggregates → publishes
  - Auto-reconnect handled by KiteTicker with exponential backoff
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional

from kiteconnect import KiteTicker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import (
    add_subscription,
    cache_tick,
    get_subscriptions,
    publish_tick,
    set_feed_status,
)
from app.core.types import Tick
from app.feeds.base import BaseFeed
from app.validators.tick import TickValidator

settings = get_settings()
log = get_logger(__name__)


class KiteFeed(BaseFeed):
    """
    Production KiteTicker feed for NSE equities.

    Usage:
        feed = KiteFeed(on_tick=aggregator.process_tick)
        await feed.start()
        await feed.subscribe({"NSE:RELIANCE": 738561, ...})
        # ... later ...
        await feed.stop()
    """

    def __init__(self, on_tick) -> None:
        super().__init__(on_tick)
        self._ticker: Optional[KiteTicker] = None
        self._queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=50_000)
        self._validator = TickValidator()
        self._consumer_task: Optional[asyncio.Task] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._token_to_symbol: dict[int, str] = {}
        self._stats = {
            "ticks_received": 0,
            "ticks_rejected": 0,
            "ticks_processed": 0,
            "reconnects": 0,
        }
        self._pubsub_task: Optional[asyncio.Task] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()

        import redis.asyncio as redis_lib
        access_token = settings.KITE_ACCESS_TOKEN
        try:
            r_b2 = redis_lib.from_url("redis://127.0.0.1:6379/2")
            cached_token = await r_b2.get("sg:kite:access_token")
            if cached_token:
                access_token = cached_token.decode() if isinstance(cached_token, bytes) else str(cached_token)
            await r_b2.aclose()
        except Exception as e:
            log.warning("kite_feed_redis_token_check_failed", error=str(e))

        self._ticker = KiteTicker(
            api_key=settings.KITE_API_KEY,
            access_token=access_token,
        )

        # Wire callbacks
        self._ticker.on_ticks = self._on_ticks_sync
        self._ticker.on_connect = self._on_connect_sync
        self._ticker.on_close = self._on_close_sync
        self._ticker.on_error = self._on_error_sync
        self._ticker.on_reconnect = self._on_reconnect_sync
        self._ticker.on_noreconnect = self._on_noreconnect_sync

        # Start KiteTicker in its own thread
        thread = threading.Thread(
            target=self._ticker.connect,
            kwargs={
                "threaded": True,
                "disable_ssl_verification": False,
            },
            daemon=True,
            name="kite-ticker",
        )
        thread.start()

        # Start async consumer and pubsub subscriber
        self._consumer_task = asyncio.create_task(
            self._consume_queue(), name="tick-consumer"
        )
        self._pubsub_task = asyncio.create_task(
            self._listen_token_refreshed(), name="token-refreshed-listener"
        )
        log.info("kite_feed_started", mode="live")
        await set_feed_status("connecting")

    async def stop(self) -> None:
        self._running = False
        if self._ticker:
            try:
                self._ticker.stop()
            except Exception as e:
                log.warning("kite_ticker_stop_error", error=str(e))
        if self._consumer_task:
            self._consumer_task.cancel()
        if self._pubsub_task:
            self._pubsub_task.cancel()
        log.info("kite_feed_stopped", stats=self._stats)
        await set_feed_status("stopped")

    async def update_access_token(self, new_token: str) -> None:
        """Update KiteTicker access token and force reconnect."""
        if self._ticker:
            log.info("updating_kite_feed_access_token_and_reconnecting")
            self._ticker.set_access_token(new_token)
            try:
                self._ticker.reconnect()
            except Exception as e:
                log.warning("kite_feed_reconnect_failed", error=str(e))

    async def _listen_token_refreshed(self) -> None:
        """Listen for sg:kite:token_refreshed Redis pubsub notifications."""
        import redis.asyncio as redis_lib
        try:
            r = redis_lib.from_url("redis://127.0.0.1:6379/2")
            pubsub = r.pubsub()
            await pubsub.subscribe("sg:kite:token_refreshed")
            log.info("subscribed_to_kite_token_refreshed_pubsub")
            async for message in pubsub.listen():
                if not self._running:
                    break
                if message and message.get("type") == "message":
                    raw_tok = await r.get("sg:kite:access_token")
                    if raw_tok:
                        tok_str = raw_tok.decode() if isinstance(raw_tok, bytes) else str(raw_tok)
                        await self.update_access_token(tok_str)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.error("token_refreshed_listener_error", error=str(exc))

    # ── Subscription management ───────────────────────────────────────────────

    async def subscribe(self, symbol_token_map: dict[str, int]) -> None:
        """
        symbol_token_map: {"NSE:RELIANCE": 738561, ...}
        """
        if not self._ticker:
            raise RuntimeError("Feed not started. Call start() first.")

        tokens = list(symbol_token_map.values())
        if not tokens:
            return

        # Store mapping for tick lookup
        self._token_to_symbol.update({v: k for k, v in symbol_token_map.items()})

        # Kite: subscribe in FULL mode (gives bid/ask, OI, etc.)
        if self._ticker and getattr(self._ticker, "ws", None) and self._ticker.is_connected():
            try:
                self._ticker.subscribe(tokens)
                self._ticker.set_mode(self._ticker.MODE_FULL, tokens)
            except Exception as exc:
                log.warning("ticker_subscribe_call_failed", error=str(exc))
        else:
            log.info("ticker_not_yet_connected_queued_in_redis", count=len(tokens))

        # Persist subscription registry to Redis
        for symbol, token in symbol_token_map.items():
            await add_subscription(symbol, token)

        log.info("subscribed", count=len(tokens), sample=list(symbol_token_map.keys())[:5])

    async def unsubscribe(self, tokens: list[int]) -> None:
        if self._ticker:
            self._ticker.unsubscribe(tokens)
        for token in tokens:
            self._token_to_symbol.pop(token, None)

    async def resubscribe_from_redis(self) -> None:
        """Restore subscriptions from Redis after a reconnect."""
        subs = await get_subscriptions()
        if subs:
            await self.subscribe(subs)
            log.info("resubscribed_from_redis", count=len(subs))

    # ── KiteTicker sync callbacks (called from ticker thread) ─────────────────

    def _on_ticks_sync(self, ws, ticks: list[dict]) -> None:
        """Bridge: ticker thread → asyncio queue."""
        if not self._loop:
            return
        for raw in ticks:
            tick = self._parse_raw(raw)
            if tick:
                try:
                    self._loop.call_soon_threadsafe(self._queue.put_nowait, tick)
                except asyncio.QueueFull:
                    log.warning("tick_queue_full", symbol=tick.symbol)

    def _on_connect_sync(self, ws, response) -> None:
        log.info("kite_ws_connected")
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                set_feed_status("connected"), self._loop
            )
            asyncio.run_coroutine_threadsafe(
                self.resubscribe_from_redis(), self._loop
            )

    def _on_close_sync(self, ws, code, reason) -> None:
        log.warning("kite_ws_closed", code=code, reason=reason)
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                set_feed_status("disconnected", {"code": code, "reason": reason}),
                self._loop,
            )

    def _on_error_sync(self, ws, code, reason) -> None:
        log.error("kite_ws_error", code=code, reason=reason)

    def _on_reconnect_sync(self, ws, attempts_count) -> None:
        self._stats["reconnects"] += 1
        log.warning("kite_ws_reconnecting", attempt=attempts_count)

    def _on_noreconnect_sync(self, ws) -> None:
        log.critical("kite_ws_no_reconnect_giving_up")
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                set_feed_status("failed"), self._loop
            )

    # ── Async tick consumer ───────────────────────────────────────────────────

    async def _consume_queue(self) -> None:
        log.info("tick_consumer_started")
        while self._running:
            try:
                tick = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            self._stats["ticks_received"] += 1

            # Validate
            result = self._validator.validate(tick)
            if not result.valid:
                self._stats["ticks_rejected"] += 1
                continue

            # Publish to Redis (fire-and-forget)
            tick_dict = {
                "symbol": tick.symbol,
                "exchange": tick.exchange,
                "last_price": tick.last_price,
                "volume": tick.volume,
                "timestamp_ns": tick.timestamp_ns,
                "open": tick.open,
                "high": tick.high,
                "low": tick.low,
                "bid": tick.bid,
                "ask": tick.ask,
            }
            asyncio.create_task(cache_tick(tick.symbol, tick_dict))
            asyncio.create_task(publish_tick(tick_dict))

            # Forward to aggregator
            try:
                await self.on_tick(tick)
                self._stats["ticks_processed"] += 1
            except Exception as exc:
                log.error("tick_processing_error", symbol=tick.symbol, error=str(exc))

    # ── Raw tick parser ───────────────────────────────────────────────────────

    def _parse_raw(self, raw: dict) -> Tick | None:
        try:
            token = raw["instrument_token"]
            symbol = self._token_to_symbol.get(token)
            if not symbol:
                return None

            exchange = symbol.split(":")[0]

            return Tick(
                instrument_token=token,
                symbol=symbol,
                exchange=exchange,
                last_price=float(raw.get("last_price", 0)),
                volume=int(raw.get("volume", raw.get("volume_traded", 0))),
                timestamp_ns=int(raw.get("exchange_timestamp",
                                         time.time()) * 1e9
                                  if isinstance(raw.get("exchange_timestamp"), float)
                                  else time.time_ns()),
                open=raw.get("ohlc", {}).get("open"),
                high=raw.get("ohlc", {}).get("high"),
                low=raw.get("ohlc", {}).get("low"),
                close=raw.get("ohlc", {}).get("close"),
                bid=raw.get("depth", {}).get("buy", [{}])[0].get("price"),
                ask=raw.get("depth", {}).get("sell", [{}])[0].get("price"),
                bid_qty=raw.get("depth", {}).get("buy", [{}])[0].get("quantity"),
                ask_qty=raw.get("depth", {}).get("sell", [{}])[0].get("quantity"),
                average_price=raw.get("average_traded_price"),
                last_traded_qty=raw.get("last_traded_quantity"),
                buy_quantity=raw.get("total_buy_quantity"),
                sell_quantity=raw.get("total_sell_quantity"),
            )
        except Exception as exc:
            log.error("tick_parse_error", error=str(exc), raw=str(raw)[:200])
            return None

    @property
    def stats(self) -> dict:
        return {**self._stats, "queue_depth": self._queue.qsize()}
