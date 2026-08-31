"""
ConfidenceEngine: turns weighted votes into a net directional score, an agreement ratio
(how concentrated the voting weight is on the winning side), and a final confidence value
that combines both — so a narrow 51/49 split doesn't get reported with the same confidence
as a 90/10 landslide, even if the raw net score happens to be similar.
"""
from __future__ import annotations

from app.config import Settings
from app.models.domain import ConflictReport, SignalVote, WeightSet


class ConfidenceEngine:
    def __init__(self, settings: Settings):
        self.settings = settings

    def compute(self, votes: list[SignalVote], weights: WeightSet) -> ConflictReport:
        buy_weight = 0.0
        sell_weight = 0.0
        hold_weight = 0.0
        net_score = 0.0

        for vote in votes:
            w = weights.effective_weights.get(vote.strategy, 0.0)
            net_score += w * vote.signed_strength
            if vote.direction > 0:
                buy_weight += w
            elif vote.direction < 0:
                sell_weight += w
            else:
                hold_weight += w

        directional_weight = buy_weight + sell_weight
        if directional_weight > 0:
            agreement_ratio = max(buy_weight, sell_weight) / directional_weight
        else:
            # Everyone voted HOLD / nobody reported a direction.
            agreement_ratio = 0.0

        return ConflictReport(
            net_score=round(net_score, 4),
            agreement_ratio=round(agreement_ratio, 4),
            voting_strategies=len(votes),
            buy_weight=round(buy_weight, 4),
            sell_weight=round(sell_weight, 4),
            hold_weight=round(hold_weight, 4),
        )

    def final_confidence(self, report: ConflictReport) -> float:
        """
        base = |net_score|, already in [0,1] since weights sum to 1 and individual
        confidences are in [0,1]. Dampened by agreement: full agreement (1.0) keeps the
        base confidence; minimum agreement (0.5, i.e. a dead-even directional split)
        multiplies it down to AGREEMENT_DAMPENING_FLOOR.
        """
        base = min(1.0, abs(report.net_score))
        floor = self.settings.AGREEMENT_DAMPENING_FLOOR
        # agreement_ratio is in [0.5, 1.0] whenever there's any directional split at all
        # (since it's max(buy,sell)/(buy+sell)); map that range onto [floor, 1.0].
        if report.agreement_ratio <= 0.5:
            dampening = floor
        else:
            span = (report.agreement_ratio - 0.5) / 0.5  # 0..1
            dampening = floor + span * (1.0 - floor)

        confidence = base * dampening

        if report.voting_strategies < self.settings.MIN_STRATEGIES_REQUIRED:
            confidence *= 0.5  # not a hard veto, but a meaningful penalty for thin consensus

        return round(min(1.0, max(0.0, confidence)), 4)
