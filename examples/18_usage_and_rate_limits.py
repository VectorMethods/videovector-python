"""Inspect current usage and rate-limit status for integration guardrails."""

from __future__ import annotations

from _common import api_client


def main() -> None:
    with api_client() as client:
        usage = client.usage.get_current()
        rate_limits = client.rate_limits.get_status()
        metric_types = client.usage.get_metric_types()

        print("usage period", usage.period_start, usage.period_end)
        print("usage totals", usage.totals)
        print("rate limit categories", rate_limits.categories)
        print("available metric types", [metric.type for metric in metric_types])


if __name__ == "__main__":
    main()
