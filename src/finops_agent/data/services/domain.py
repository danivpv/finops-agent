"""Settled commitment economics domain math.

Executes over precomputed lines.parquet, retaining exact financial formulas.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import duckdb

from ..constants import (
    COR_MAX_POINTS,
    COR_MIN_POINTS,
    DEFAULT_COMMITMENT_PER_HOUR,
    DEFAULT_PAYMENT_OPTION,
    DEFAULT_SCOPE,
    DEFAULT_TERM_MONTHS,
    PROFIT_RATE,
)
from ..runtime.config import settings

LINES_PARQUET = settings.cc_data_dir / "lines.parquet"


@dataclass
class Proposal:
    scope: str = DEFAULT_SCOPE
    commitment_per_hour: float = DEFAULT_COMMITMENT_PER_HOUR
    term_months: int = DEFAULT_TERM_MONTHS
    payment_option: str = DEFAULT_PAYMENT_OPTION


DEFAULT_PROPOSAL = Proposal()


def get_connection() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    if LINES_PARQUET.exists():
        con.execute(
            f"CREATE VIEW lines AS SELECT * FROM read_parquet('{LINES_PARQUET.as_posix()}')"
        )
    return con


def _impact_relation(con: duckdb.DuckDBPyConnection, p: Proposal) -> None:
    L = float(p.commitment_per_hour)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW impact AS
        WITH ranked AS (
          SELECT timestamp, account_id, product_code, usage_type, instance_type,
                 commitment_key, on_demand_cost, line_disc_cost, discount,
                 SUM(line_disc_cost) OVER (PARTITION BY timestamp ORDER BY discount DESC
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum
          FROM lines
          WHERE term_months = {int(p.term_months)}
        )
        SELECT timestamp, account_id, product_code, usage_type, instance_type, commitment_key,
          GREATEST(0, LEAST(line_disc_cost, {L} - (cum - line_disc_cost))) AS committed_cost,
          CASE WHEN line_disc_cost > 0
               THEN GREATEST(0, LEAST(line_disc_cost, {L} - (cum - line_disc_cost))) / line_disc_cost
               ELSE 0 END * on_demand_cost AS covered_on_demand_cost
        FROM ranked
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW impact_rows AS
        SELECT timestamp, account_id, product_code, usage_type, instance_type, commitment_key,
               covered_on_demand_cost, committed_cost,
               covered_on_demand_cost - committed_cost AS gross_savings
        FROM impact
        """
    )


def _aggregate_economics(
    con: duckdb.DuckDBPyConnection, p: Proposal
) -> dict[str, float]:
    _impact_relation(con, p)
    L = float(p.commitment_per_hour)
    totals = con.execute(
        "SELECT sum(covered_on_demand_cost), sum(committed_cost), sum(gross_savings) FROM impact_rows"
    ).fetchone()
    assert totals is not None
    covered, committed, gross = totals
    waste_row = con.execute(
        f"""WITH h AS (SELECT timestamp, sum(committed_cost) used FROM impact GROUP BY 1)
        SELECT sum(GREATEST(0, {L} - used)) FROM h"""
    ).fetchone()
    waste = (waste_row[0] if waste_row else None) or 0.0
    net = (gross or 0.0) - waste
    return {
        "covered_on_demand_cost": covered or 0.0,
        "committed_cost": committed or 0.0,
        "gross_savings": gross or 0.0,
        "wasted_commitment": waste,
        "net_savings": net,
    }


def cost_of_risk(con: duckdb.DuckDBPyConnection, p: Proposal) -> dict[str, Any]:
    _impact_relation(con, p)
    L = float(p.commitment_per_hour)
    protection_row = con.execute(
        f"""WITH h AS (SELECT timestamp, sum(line_disc_cost) hr FROM lines
                   WHERE term_months = {int(p.term_months)} GROUP BY 1)
        SELECT avg(CASE WHEN hr >= {L} THEN 1.0 ELSE 0.0 END) FROM h"""
    ).fetchone()
    protection = (protection_row[0] if protection_row else None) or 0.0
    trend_row = con.execute(
        f"""WITH m AS (
          SELECT billing_period_idx, total FROM (
            SELECT row_number() OVER (ORDER BY mo) AS billing_period_idx,
                   total, cnt
            FROM (
              SELECT date_trunc('month', timestamp) mo, sum(line_disc_cost) total,
                     count(distinct timestamp) cnt
              FROM lines WHERE term_months = {int(p.term_months)} GROUP BY 1
            )
          ) WHERE cnt >= 672
        )
        SELECT regr_slope(total, billing_period_idx) * count(*) / NULLIF(avg(total),0)
        FROM m"""
    ).fetchone()
    trend = (trend_row[0] if trend_row else None) or 0.0
    under = 1.0 - protection
    downtrend = max(0.0, -trend)
    uptrend = max(0.0, trend)
    combine = (
        under * (0.6 + 0.8 * downtrend) + 0.4 * under**2 - 0.15 * uptrend * protection
    )
    combine = min(1.0, max(0.0, combine))
    points = round(COR_MIN_POINTS + (COR_MAX_POINTS - COR_MIN_POINTS) * combine, 1)
    return {
        "cost_of_risk_points": points,
        "protection": round(protection, 3),
        "trend": round(trend, 3),
        "infeasible": points >= COR_MAX_POINTS,
    }


def economics(con: duckdb.DuckDBPyConnection, p: Proposal) -> dict[str, Any]:
    agg = _aggregate_economics(con, p)
    cor = cost_of_risk(con, p)
    S = agg["net_savings"]
    profit = PROFIT_RATE * S
    reserve = (cor["cost_of_risk_points"] / 100.0) * S
    customer_savings = S - profit - reserve
    rate = (
        (customer_savings / agg["covered_on_demand_cost"])
        if agg["covered_on_demand_cost"]
        else 0.0
    )
    return {
        "proposal": asdict(p),
        **agg,
        **cor,
        "profit": profit,
        "reserve": reserve,
        "customer_savings": customer_savings,
        "customer_savings_rate": rate,
    }
