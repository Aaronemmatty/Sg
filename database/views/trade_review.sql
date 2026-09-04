-- ==============================================================================
-- View: trade_review
-- Description: Read-only consolidation view for trade auditing and post-trade review.
--              Joins pm_trade_ledger (portfolio accounting), exec_orders (execution
--              engine state), risk_decisions (pre-trade risk checks), and signals
--              (strategy indicators & triggers).
--
-- Safety: Completely read-only. Safe to re-run, modify, or DROP anytime.
-- Usage: SELECT * FROM trade_review WHERE symbol = 'NSE:RELIANCE';
--
-- CAVEAT & ATTRIBUTION WARNING:
-- The `signals` columns (strategy_name, signal_metadata, signal_reason, etc.)
-- are attached via a best-effort LATERAL time-proximity match on
-- (symbol, most recent signal at or before trade_time) — NOT a guaranteed
-- ID-based join.
--
-- Why: In the current event pipeline, signal_aggregation_service drops the
-- originating signal's metadata/identity, and execution_orchestrator_service
-- mints a new random correlation_id rather than propagating the upstream signal ID.
--
-- Limitation: If two strategies ever evaluate or trade the same symbol concurrently,
-- this signal attribution can be ambiguous or misattributed to whichever strategy
-- emitted the latest bar signal. For high-stakes manual trade reconstruction,
-- always cross-check the `signals` table directly using timestamp ranges and symbol.
-- ==============================================================================

CREATE OR REPLACE VIEW trade_review AS
SELECT
    -- Fill details from pm_trade_ledger
    ptl.event_id AS ledger_event_id,
    ptl.order_id,
    ptl.symbol,
    ptl.action,
    ptl.filled_quantity,
    ptl.avg_fill_price_inr,
    ptl.slippage_bps,
    ptl.realized_pnl_inr,
    ptl.emitted_at AS trade_time,
    ptl.recorded_at,

    -- Order & Execution details from exec_orders
    eo.state AS order_state,
    eo.execution_style,
    eo.risk_band,
    eo.market_regime,
    eo.intended_price_inr,

    -- Risk evaluation details from risk_decisions
    rd.id AS risk_decision_id,
    rd.status AS risk_status,
    rd.risk_score,
    rd.risk_band AS evaluated_risk_band,
    rd.var_inr,
    rd.var_percent_of_portfolio,
    rd.checks AS risk_checks,
    rd.rejection_reasons AS risk_rejection_reasons,
    rd.evaluated_at AS risk_evaluated_at,

    -- Originating signal details from signals (best-effort LATERAL time match)
    sig.id AS signal_id,
    sig.strategy_id,
    st.name AS strategy_name,
    st.version AS strategy_version,
    sig.signal_type,
    sig.strength AS signal_strength,
    sig.timeframe AS signal_timeframe,
    sig.metadata AS signal_metadata,
    sig.reason AS signal_reason,
    sig.created_at AS signal_time

FROM pm_trade_ledger ptl
LEFT JOIN exec_orders eo 
    ON ptl.order_id = eo.order_id
LEFT JOIN risk_decisions rd 
    ON eo.intent_id = rd.intent_id
LEFT JOIN LATERAL (
    SELECT s.*
    FROM signals s
    WHERE s.symbol = ptl.symbol
      AND s.created_at <= ptl.emitted_at
    ORDER BY s.created_at DESC
    LIMIT 1
) sig ON TRUE
LEFT JOIN strategies st
    ON sig.strategy_id = st.id;
