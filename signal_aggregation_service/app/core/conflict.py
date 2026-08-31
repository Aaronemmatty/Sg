"""
ConflictResolutionEngine: takes the ConflictReport (net score, agreement, weights) plus
the individual votes and decides the final action, applying the BUY/SELL thresholds, and
determines `contributors` — the strategies whose own vote agrees with the final action and
clears a minimum individual confidence bar (matching the brief's example: mean_reversion's
SELL is excluded from `contributors` when the final signal is BUY).
"""
from __future__ import annotations

from app.config import Settings
from app.models.domain import ConflictReport, SignalAction, SignalVote


class ConflictResolutionEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    def decide(self, report: ConflictReport) -> SignalAction:
        if report.net_score >= self.settings.BUY_THRESHOLD:
            return SignalAction.BUY
        if report.net_score <= self.settings.SELL_THRESHOLD:
            return SignalAction.SELL
        return SignalAction.HOLD

    def contributors(self, votes: list[SignalVote], final_signal: SignalAction) -> list[str]:
        if final_signal == SignalAction.HOLD:
            # For a HOLD outcome, "contributors" are the strategies that were actually
            # voting HOLD (i.e. agreeing with the consensus), not an empty list — this
            # keeps the field meaningful for operators inspecting a no-trade decision.
            return [
                v.strategy for v in votes
                if v.raw_action == SignalAction.HOLD
                and v.confidence >= self.settings.MIN_INDIVIDUAL_CONFIDENCE_FOR_CONTRIBUTOR
            ]

        return [
            v.strategy for v in votes
            if v.raw_action == final_signal
            and v.confidence >= self.settings.MIN_INDIVIDUAL_CONFIDENCE_FOR_CONTRIBUTOR
        ]
