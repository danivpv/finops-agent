"""Deterministic synthetic billing and pricing dataset generator.

Writes the two input Parquet files that `scripts/precompute_data.py` reads:
1. `data/parquet/pricing_options_filtered.parquet`
2. `data/parquet/candidate_dataset.parquet`

Uses a fixed seed and synthetic 12-digit AWS account identifiers (`100000202601`
through `100000202612`) so the schema, hourly time series, and commitment
economics math are reproducible with zero real customer data.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OUT_DIR = _REPO_ROOT / "data" / "parquet"
_USAGE_PARQUET = _OUT_DIR / "candidate_dataset.parquet"
_PRICING_PARQUET = _OUT_DIR / "pricing_options_filtered.parquet"

# 11 full months (2025-07 through 2026-05) plus a partial month (2026-06 through Jun 18).
_START_TS = "2025-07-01 00:00:00"
_END_TS = "2026-06-18 17:00:00"


def generate_pricing(con: duckdb.DuckDBPyConnection) -> None:
    """Write synthetic Savings Plan pricing rows for compute workloads."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    if _PRICING_PARQUET.exists():
        _PRICING_PARQUET.unlink()

    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE catalog_items AS
        SELECT * FROM (VALUES
            -- Compute Savings Plan eligible workloads (od_rate, sp12_rate, sp36_rate)
            ('plk-ec2-use1-m6i-xl',   'AmazonEC2',  'USE1-BoxUsage:m6i.xlarge',          'm6i.xlarge',     'AWS#Compute',                                       '100000202601', 0.1920, 0.1400, 0.1050, 26.0, 'Hrs'),
            ('plk-ec2-use1-c6i-2xl',  'AmazonEC2',  'USE1-BoxUsage:c6i.2xlarge',         'c6i.2xlarge',    'AWS#Compute',                                       '100000202602', 0.3400, 0.2550, 0.1900, 14.5, 'Hrs'),
            ('plk-ec2-use2-m7g-xl',   'AmazonEC2',  'USE2-BoxUsage:m7g.xlarge',          'm7g.xlarge',     'AWS#Compute-EC2#us-east-2#m7g#RunInstances#shared', '100000202603', 0.1632, 0.1190, 0.0890, 22.0, 'Hrs'),
            ('plk-ec2-usw2-r6i-lg',   'AmazonEC2',  'USW2-BoxUsage:r6i.large',           'r6i.large',      'AWS#Compute',                                       '100000202604', 0.1260, 0.0950, 0.0720, 19.0, 'Hrs'),
            ('plk-ec2-euc1-m6i-xl',   'AmazonEC2',  'EUC1-BoxUsage:m6i.xlarge',          'm6i.xlarge',     'AWS#Compute-EC2#eu-central-1#m6i#RunInstances#shared','100000202605', 0.2300, 0.1720, 0.1280, 16.0, 'Hrs'),
            ('plk-ec2-euw1-t4g-lg',   'AmazonEC2',  'EUW1-BoxUsage:t4g.large',           't4g.large',      'AWS#Compute',                                       '100000202606', 0.0752, 0.0560, 0.0410, 28.0, 'Hrs'),
            ('plk-ecs-use1-vcpu',     'AmazonECS',  'USE1-Fargate-vCPU-Hours:perCPU',    'perCPU',         'AWS#Compute',                                       '100000202607', 0.04048,0.0315, 0.0245, 95.0, 'Hrs'),
            ('plk-ecs-euc1-vcpu',     'AmazonECS',  'EUC1-Fargate-vCPU-Hours:perCPU',    'perCPU',         'AWS#Compute',                                       '100000202608', 0.04656,0.0368, 0.0285, 58.0, 'Hrs'),
            ('plk-lambda-use1-gbsec', 'AWSLambda',  'USE1-Lambda-GB-Second',             NULL,             'AWS#Compute',                                       '100000202609', 0.00001667, 0.0000138, 0.0000115, 85000.0, 'GB-Seconds'),
            -- Non-compute / storage / database workloads (not covered by Compute Savings Plan)
            ('plk-rds-use1-r6g-2xl',  'AmazonRDS',  'USE1-InstanceUsage:db.r6g.2xlarge', 'db.r6g.2xlarge', 'AWS#Database',                                      '100000202601', 0.9600, 0.0,    0.0,    12.5, 'Hrs'),
            ('plk-rds-euc1-m6g-xl',   'AmazonRDS',  'EUC1-InstanceUsage:db.m6g.xlarge',  'db.m6g.xlarge',  'AWS#Database',                                      '100000202605', 0.4120, 0.0,    0.0,    15.0, 'Hrs'),
            ('plk-ddb-use1-wcu',      'AmazonDynamoDB', 'USE1-WriteRequestUnits',        NULL,             NULL,                                                '100000202610', 0.00000125, 0.0,0.0,    4200000.0, 'WriteRequestUnits'),
            ('plk-s3-use1-storage',   'AmazonS3',   'USE1-TimedStorage-ByteHrs',         'GP3-Storage',    NULL,                                                '100000202611', 0.0230, 0.0,    0.0,    145.0, 'GB-Mo'),
            ('plk-cw-use1-logs',      'AmazonCloudWatch', 'USE1-DataProcessing-Bytes',   'MetricStreamUsage', NULL,                                             '100000202612', 0.5000, 0.0,    0.0,    7.2,  'GB'),
            ('plk-ec-use1-r6g-lg',    'AmazonElastiCache', 'USE1-NodeUsage:cache.r6g.large', 'cache.r6g.large', NULL,                                           '100000202602', 0.1660, 0.0,    0.0,    18.0, 'Hrs'),
            ('plk-sqs-use1-reqs',     'AWSQueueService', 'USE1-Requests-Tier1',          NULL,             NULL,                                                '100000202607', 0.0000004, 0.0, 0.0,    5600000.0, 'Requests'),
            ('plk-vpc-use1-nat',      'AmazonVPC',  'USE1-NatGateway-Hours',             NULL,             NULL,                                                '100000202603', 0.0450, 0.0,    0.0,    48.0, 'Hrs'),
            ('plk-apigw-use1-reqs',   'AmazonApiGateway', 'USE1-ApiGatewayRequest',      NULL,             NULL,                                                '100000202609', 0.0000035, 0.0, 0.0,    520000.0, 'Requests'),
            ('plk-kin-use2-shard',    'AmazonKinesis', 'USE2-ShardHour',                 NULL,             NULL,                                                '100000202604', 0.0150, 0.0,    0.0,    96.0, 'Hrs')
        ) AS t(
            price_list_key, product_code, usage_type, instance_type,
            commitment_key, account_id, od_rate, sp12_rate, sp36_rate,
            base_qty, unit
        )
        """
    )

    con.execute(
        f"""
        COPY (
            SELECT
                price_list_key,
                'compute_savings_plan' AS instrument_type,
                CAST(12 AS BIGINT) AS term_months,
                'no_upfront' AS payment_option,
                CAST(sp12_rate AS DOUBLE) AS rate,
                unit,
                'USD' AS currency,
                'standard' AS offering_class
            FROM catalog_items
            WHERE sp12_rate > 0
            UNION ALL
            SELECT
                price_list_key,
                'compute_savings_plan' AS instrument_type,
                CAST(36 AS BIGINT) AS term_months,
                'no_upfront' AS payment_option,
                CAST(sp36_rate AS DOUBLE) AS rate,
                unit,
                'USD' AS currency,
                'standard' AS offering_class
            FROM catalog_items
            WHERE sp36_rate > 0
        ) TO '{_PRICING_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    size_kb = _PRICING_PARQUET.stat().st_size / 1024
    print(f"Created {_PRICING_PARQUET} ({size_kb:.1f} KB)")


def generate_usage(con: duckdb.DuckDBPyConnection) -> None:
    """Write deterministic hourly usage rows across 12 billing periods."""
    if _USAGE_PARQUET.exists():
        _USAGE_PARQUET.unlink()

    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE hours AS
        SELECT
            ts AS timestamp,
            strftime(ts, '%Y-%m') AS billing_period,
            EXTRACT(EPOCH FROM (ts - TIMESTAMP '{_START_TS}')) / 3600.0 AS hour_idx,
            EXTRACT(HOUR FROM ts) AS hr_of_day,
            EXTRACT(ISODOW FROM ts) AS day_of_week
        FROM generate_series(
            TIMESTAMP '{_START_TS}',
            TIMESTAMP '{_END_TS}',
            INTERVAL 1 HOUR
        ) AS g(ts)
        """
    )

    # Deterministic diurnal + weekend wave + steady growth + hash jitter so that
    # hourly eligible compute spend averages ~$21/hr and dips below $16/hr during
    # weekend off-peak troughs (~10% of hours), exercising both protection and waste.
    con.execute(
        f"""
        COPY (
            WITH raw AS (
                SELECT
                    h.timestamp,
                    h.billing_period,
                    c.product_code,
                    c.usage_type,
                    c.instance_type,
                    c.price_list_key,
                    c.commitment_key,
                    c.account_id,
                    c.od_rate,
                    c.sp12_rate,
                    c.base_qty
                    * (1.0 + 0.012 * (h.hour_idx / 730.0))
                    * CASE
                        WHEN h.day_of_week IN (6, 7) AND h.hr_of_day BETWEEN 0 AND 7 THEN 0.56
                        WHEN h.day_of_week IN (6, 7) THEN 0.78
                        WHEN h.hr_of_day BETWEEN 13 AND 21 THEN 1.18
                        WHEN h.hr_of_day BETWEEN 1 AND 6 THEN 0.74
                        ELSE 1.00
                      END
                    * (0.92 + 0.16 * (( abs(hash(c.price_list_key || CAST(h.hour_idx AS VARCHAR))) % 1000 ) / 1000.0))
                    AS usage_amount
                FROM hours h
                CROSS JOIN catalog_items c
            )
            SELECT
                timestamp,
                billing_period,
                product_code,
                usage_type,
                instance_type,
                CAST(usage_amount AS DOUBLE) AS usage_amount,
                CAST(usage_amount * od_rate AS DOUBLE) AS on_demand_cost,
                CAST(
                    CASE
                        WHEN sp12_rate > 0 THEN usage_amount * (0.35 * sp12_rate + 0.65 * od_rate)
                        ELSE usage_amount * od_rate * 0.96
                    END AS DOUBLE
                ) AS amortized_cost,
                price_list_key,
                commitment_key,
                account_id,
                CASE WHEN commitment_key IS NOT NULL THEN 'SavingsPlan' ELSE 'OnDemand' END AS commitment,
                'Usage' AS cost_type,
                CAST(0.0 AS DOUBLE) AS baseline_covered,
                CAST(0.0 AS DOUBLE) AS baseline_max
            FROM raw
        ) TO '{_USAGE_PARQUET.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    size_mb = _USAGE_PARQUET.stat().st_size / (1024 * 1024)
    print(f"Created {_USAGE_PARQUET} ({size_mb:.2f} MB)")


def main() -> None:
    con = duckdb.connect(":memory:")
    generate_pricing(con)
    generate_usage(con)
    con.close()
    print("Synthetic dataset generation complete!")


if __name__ == "__main__":
    main()
