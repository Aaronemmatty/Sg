from __future__ import annotations

import asyncio

from app.config import Settings
from app.evaluator import RiskEvaluator
from app.logging_setup import get_logger
from app.models import RiskStatus, TradeIntent
from app.redis_bus import RedisBus
from app.repository import Database

log = get_logger(module="consumer")


class IntentConsumer:
    def __init__(self, redis_bus: RedisBus, evaluator: RiskEvaluator, db: Database, settings: Settings) -> None:
        self._redis = redis_bus
        self._evaluator = evaluator
        self._db = db
        self._settings = settings
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="intent_consumer")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        log.info("intent_consumer_started", pattern=self._settings.redis_intents_pattern)
        while not self._stopping:
            try:
                async for raw in self._redis.subscribe_pattern(self._settings.redis_intents_pattern):
                    await self._handle_message(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.error("intent_consumer_error", error=str(exc))
                await asyncio.sleep(1.0)

    async def _handle_message(self, raw: dict) -> None:
        raw = {k: v for k, v in raw.items() if k != "_channel"}
        try:
            intent = TradeIntent.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            log.warning("invalid_intent_payload", error=str(exc), raw=raw)
            return

        # Only evaluate intents the orchestrator marked ELIGIBLE; orchestrator
        # REJECTED/HOLD intents never reach risk evaluation by contract, but
        # we guard defensively in case of upstream changes.
        if intent.status.value != "ELIGIBLE":
            log.debug("intent_skipped_not_eligible", intent_id=str(intent.intent_id), status=intent.status.value)
            return

        decision = await self._evaluator.evaluate(intent)

        await self._db.insert_risk_decision(decision)

        for name, check in decision.checks.items():
            if not check.passed:
                await self._db.insert_audit_log(
                    decision.intent_id,
                    "CHECK_FAIL",
                    {"check": name, "detail": check.detail, "value": check.value, "threshold": check.threshold},
                )

        if decision.status == RiskStatus.RISK_REJECTED:
            channel = f"{self._settings.redis_risk_rejected_prefix}{decision.symbol}"
        else:
            # Both RISK_APPROVED and RISK_HOLD publish to risk_approved channel
            # with `status` field distinguishing them, so execution_engine can
            # decide whether HOLD intents are queued for re-evaluation rather
            # than treating channel name as the only signal.
            channel = f"{self._settings.redis_risk_approved_prefix}{decision.symbol}"

        await self._redis.publish_json(channel, decision.to_redis_payload())
        await self._redis.publish_json(
            self._settings.redis_risk_events_channel,
            {"event": "risk_decision", "intent_id": str(decision.intent_id), "status": decision.status.value},
        )
