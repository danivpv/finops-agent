"""Precomputes analytical dice and extracts eligible compute lines.

Outputs:
1. lines.parquet (~30 MB): Eligible compute lines with discounts for dynamic sensitivity analysis.
2. dice.duckdb (~2 MB): Pre-aggregated 6-dimension monthly spend tables and default savings dice.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_DATA = _REPO_ROOT / "data" / "parquet"
_USAGE_PARQUET = _SRC_DATA / "candidate_dataset.parquet"
_PRICING_PARQUET = _SRC_DATA / "pricing_options_filtered.parquet"

_OUT_DIR = _REPO_ROOT / "src" / "finops_agent" / "data" / "precomputed"
_OUT_DIR.mkdir(parents=True, exist_ok=True)

_LINES_OUT = _OUT_DIR / "lines.parquet"
_DICE_OUT = _OUT_DIR / "dice.duckdb"

DIM_SQL: dict[str, str] = {
    "service": "product_code",
    "account": "account_id",
    "usage_kind": "usage_type",
    "instance_type": "COALESCE(instance_type, 'none')",
    "commitment_scope": "COALESCE(commitment_key, 'none')",
    "region": (
        "COALESCE(NULLIF(REGEXP_EXTRACT(usage_type, '^((US|EU|AP|SA|CA|ME|AF|IL)[A-Z0-9]+)-', 1), ''), 'no-prefix')"
    ),
}

_DICE_FACTS: dict[str, str] = {
    "on_demand_cost": "SUM(on_demand_cost)",
    "usage_amount": "SUM(usage_amount)",
    "amortized_cost": "SUM(amortized_cost)",
}


def precompute_lines(con: duckdb.DuckDBPyConnection) -> None:
    print("Extracting eligible compute lines to lines.parquet...")
    if _LINES_OUT.exists():
        _LINES_OUT.unlink()

    sql = f"""
    CREATE TABLE lines AS
    WITH elig AS (
      SELECT u.timestamp, u.account_id, u.product_code, u.usage_type,
             u.instance_type, u.commitment_key, u.price_list_key,
             u.on_demand_cost, u.usage_amount, p.rate AS sp_rate, p.term_months
      FROM '{_USAGE_PARQUET.as_posix()}' u
      JOIN '{_PRICING_PARQUET.as_posix()}' p
        ON u.price_list_key = p.price_list_key
       AND p.instrument_type = 'compute_savings_plan'
       AND p.payment_option = 'no_upfront'
      WHERE u.commitment_key LIKE 'AWS#Compute%'
        AND u.usage_amount > 0 AND u.on_demand_cost > 0
    )
    SELECT *,
      usage_amount * sp_rate AS line_disc_cost,
      1 - sp_rate / (on_demand_cost / usage_amount) AS discount
    FROM elig
    WHERE 1 - sp_rate / (on_demand_cost / usage_amount) BETWEEN 0 AND 0.95
    """
    con.execute(sql)
    con.execute(
        f"COPY lines TO '{_LINES_OUT.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    size_mb = _LINES_OUT.stat().st_size / (1024 * 1024)
    print(f"Created {_LINES_OUT} ({size_mb:.2f} MB)")


def precompute_dice(con: duckdb.DuckDBPyConnection) -> None:
    print("Building analytical dice tables in dice.duckdb...")
    if _DICE_OUT.exists():
        _DICE_OUT.unlink()

    dice_con = duckdb.connect(str(_DICE_OUT))
    dice_con.execute(
        f"CREATE OR REPLACE VIEW usage AS SELECT * FROM read_parquet('{_USAGE_PARQUET.as_posix()}')"
    )
    dice_con.execute(
        f"CREATE OR REPLACE VIEW lines AS SELECT * FROM read_parquet('{_LINES_OUT.as_posix()}')"
    )

    facts = ", ".join(f"{expr} AS {name}" for name, expr in _DICE_FACTS.items())
    for dim, expr in DIM_SQL.items():
        print(f"  - Precomputing dice_{dim}...")
        dice_con.execute(
            f"""
            CREATE TABLE dice_{dim} AS
            SELECT {expr} AS dim_value, billing_period, {facts}
            FROM usage
            GROUP BY 1, 2
            """
        )

    # Precompute default proposal savings dice ($16/hr, 12 mo)
    print("  - Precomputing default savings dice...")
    L = 16.0
    dice_con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW impact AS
        WITH ranked AS (
          SELECT timestamp, account_id, product_code, usage_type, instance_type,
                 commitment_key, on_demand_cost, line_disc_cost, discount,
                 SUM(line_disc_cost) OVER (PARTITION BY timestamp ORDER BY discount DESC
                     ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cum
          FROM lines
          WHERE term_months = 12
        )
        SELECT timestamp, account_id, product_code, usage_type, instance_type, commitment_key,
          GREATEST(0, LEAST(line_disc_cost, {L} - (cum - line_disc_cost))) AS committed_cost,
          CASE WHEN line_disc_cost > 0
               THEN GREATEST(0, LEAST(line_disc_cost, {L} - (cum - line_disc_cost))) / line_disc_cost
               ELSE 0 END * on_demand_cost AS covered_on_demand_cost
        FROM ranked
        """
    )
    dice_con.execute(
        """
        CREATE OR REPLACE TEMP VIEW impact_rows AS
        SELECT timestamp, account_id, product_code, usage_type, instance_type, commitment_key,
               covered_on_demand_cost, committed_cost,
               covered_on_demand_cost - committed_cost AS gross_savings
        FROM impact
        """
    )

    for dim, expr in DIM_SQL.items():
        dice_con.execute(
            f"""
            CREATE TABLE dice_{dim}_savings AS
            SELECT {expr} AS dim_value, strftime(timestamp, '%Y-%m') AS billing_period,
                   SUM(covered_on_demand_cost) AS covered_on_demand_cost,
                   SUM(committed_cost) AS committed_cost,
                   SUM(gross_savings) AS gross_savings
            FROM impact_rows
            GROUP BY 1, 2
            """
        )

    # Billing periods metadata
    periods = dice_con.execute(
        """
        SELECT billing_period, MIN(timestamp) AS first_ts, MAX(timestamp) AS last_ts
        FROM usage GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    dice_con.execute(
        """
        CREATE TABLE metadata_periods (
            billing_period VARCHAR,
            partial BOOLEAN,
            first_ts VARCHAR,
            last_ts VARCHAR
        )
        """
    )
    import calendar

    for period, first_ts, last_ts in periods:
        year, month = int(period[:4]), int(period[5:7])
        last_day = calendar.monthrange(year, month)[1]
        partial = last_ts.date().day < last_day
        dice_con.execute(
            "INSERT INTO metadata_periods VALUES (?, ?, ?, ?)",
            [period, partial, first_ts.isoformat(), last_ts.isoformat()],
        )

    dice_con.close()
    size_mb = _DICE_OUT.stat().st_size / (1024 * 1024)
    print(f"Created {_DICE_OUT} ({size_mb:.2f} MB)")


def main() -> None:
    con = duckdb.connect(":memory:")
    precompute_lines(con)
    precompute_dice(con)
    con.close()
    print("Precomputation complete!")


if __name__ == "__main__":
    main()
