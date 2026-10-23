"""
Demo runner for Doorstep Resolve.

Executes all 5 synthetic scenarios and prints the ranked resolution options,
estimated arrival times, deadline checks, and audit evidence.
"""

import json
from doorstep_resolve.resolver import resolve_replacement
from doorstep_resolve.scenarios import (
    scenario_replacement_meets_deadline,
    scenario_replacement_arrives_too_late,
    scenario_replacement_stock_unavailable,
    scenario_window_expired,
    scenario_expedited_meets_deadline_when_standard_cannot,
)


def run_demo():
    scenarios = [
        scenario_replacement_meets_deadline(),
        scenario_replacement_arrives_too_late(),
        scenario_replacement_stock_unavailable(),
        scenario_window_expired(),
        scenario_expedited_meets_deadline_when_standard_cannot(),
    ]

    print("=" * 80)
    print("DOORSTEP RESOLVE - PROOF OF CONCEPT DEMONSTRATION")
    print("=" * 80)

    for i, s in enumerate(scenarios, start=1):
        print(f"\n--- Scenario {i}: {s.name.replace('_', ' ').title()} ---")
        print(f"Description      : {s.description}")
        print(f"Order ID         : {s.order.order_id} ({s.order.item_name})")
        print(f"Delivered At     : {s.order.delivered_at.isoformat()}")
        print(f"Current Time     : {s.current_time.isoformat()}")
        print(f"Customer Deadline: {s.customer_deadline.isoformat()}")

        options = resolve_replacement(
            order=s.order,
            policy=s.policy,
            inventory=s.inventory,
            shipping_estimates=s.shipping_estimates,
            customer_deadline=s.customer_deadline,
            current_time=s.current_time,
        )

        print(f"\nRanked Resolution Options ({len(options)} total):")
        for opt in options:
            status = "MEETS DEADLINE" if opt.meets_deadline else "MISSES DEADLINE"
            eligibility = "ELIGIBLE" if opt.eligible else "INELIGIBLE"
            arrival = opt.estimated_arrival.isoformat() if opt.estimated_arrival else "N/A"

            print(f"  [Rank {opt.rank}] Action: {opt.action_type} | {eligibility} | {status}")
            print(f"          Estimated Arrival : {arrival}")
            print(f"          Shipping Method   : {opt.shipping_method or 'N/A'} (Cost: ${opt.cost:.2f})")
            print(f"          Decision Evidence :")
            for ev in opt.evidence:
                print(f"            - {ev}")

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
