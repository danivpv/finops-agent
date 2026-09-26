"""Fixed economics rates and SQL dimension expressions. No environment variables."""

from __future__ import annotations

PROFIT_RATE = 0.10
COR_MIN_POINTS = 4.0
COR_MAX_POINTS = 80.0

DEFAULT_SCOPE = "AWS#Compute"
DEFAULT_COMMITMENT_PER_HOUR = 16.0
DEFAULT_TERM_MONTHS = 12
DEFAULT_PAYMENT_OPTION = "no_upfront"

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
