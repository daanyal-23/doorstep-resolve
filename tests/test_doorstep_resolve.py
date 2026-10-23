"""
Pytest test suite for Doorstep Resolve decision engine.

Validates the 5 required synthetic scenarios and mathematical invariants
without hardcoded answers tied to scenario names.
"""

from datetime import datetime, time, timedelta, timezone
import pytest

from doorstep_resolve.models import Order, Policy, InventoryItem, ShippingEstimate
from doorstep_resolve.resolver import resolve_replacement
from doorstep_resolve.scenarios import (
    scenario_replacement_meets_deadline,
    scenario_replacement_arrives_too_late,
    scenario_replacement_stock_unavailable,
    scenario_window_expired,
    scenario_expedited_meets_deadline_when_standard_cannot,
)


class TestDoorstepResolveScenarios:
    """Tests covering the five core synthetic scenarios."""

    def test_scenario_1_replacement_meets_deadline(self):
        """Scenario 1: Replacement available in stock and standard transit meets customer deadline."""
        scenario = scenario_replacement_meets_deadline()
        options = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=scenario.customer_deadline,
            current_time=scenario.current_time,
        )

        assert len(options) == 1
        best = options[0]
        assert best.rank == 1
        assert best.eligible is True
        assert best.meets_deadline is True
        assert best.action_type == "REPLACEMENT_STANDARD"
        assert best.estimated_arrival is not None
        assert best.estimated_arrival <= scenario.customer_deadline

        # Verify math derived strictly from inputs
        ship = scenario.shipping_estimates[0]
        assert ship.cutoff_time == time(17, 0)
        expected_dispatch = datetime.combine(scenario.current_time.date(), ship.cutoff_time)
        expected_arrival = expected_dispatch + timedelta(hours=ship.transit_hours)
        assert best.dispatch_time == expected_dispatch
        assert best.estimated_arrival == expected_arrival

        # Evidence should explain arrival vs deadline and 17:00 cutoff
        evidence_str = " ".join(best.evidence)
        assert "Promise safe" in evidence_str
        assert "before cutoff 17:00" in evidence_str
        assert scenario.customer_deadline.isoformat() in evidence_str

    def test_scenario_2_replacement_arrives_too_late(self):
        """Scenario 2: Replacement is in stock, but transit and cutoff cause arrival after deadline."""
        scenario = scenario_replacement_arrives_too_late()
        options = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=scenario.customer_deadline,
            current_time=scenario.current_time,
        )

        assert len(options) == 1
        best = options[0]
        assert best.eligible is True
        assert best.meets_deadline is False
        assert best.estimated_arrival is not None
        assert best.estimated_arrival > scenario.customer_deadline

        # Verify rollover to next day because current_time (17:30) > cutoff (16:00)
        ship = scenario.shipping_estimates[0]
        expected_dispatch = datetime.combine(
            scenario.current_time.date() + timedelta(days=1),
            ship.cutoff_time,
        )
        assert best.dispatch_time == expected_dispatch
        assert best.estimated_arrival == expected_dispatch + timedelta(hours=ship.transit_hours)

        # Evidence should explicitly indicate the lateness
        evidence_str = " ".join(best.evidence)
        assert "past daily cutoff" in evidence_str
        assert "Fails deadline constraint" in evidence_str

    def test_scenario_3_replacement_stock_unavailable(self):
        """Scenario 3: Return window is active, but replacement item is out of stock."""
        scenario = scenario_replacement_stock_unavailable()
        options = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=scenario.customer_deadline,
            current_time=scenario.current_time,
        )

        assert len(options) == 1
        option = options[0]
        assert option.eligible is False
        assert option.meets_deadline is False
        assert option.estimated_arrival is None
        assert option.action_type == "REPLACEMENT_OUT_OF_STOCK"

        evidence_str = " ".join(option.evidence)
        assert "0 units available" in evidence_str
        assert scenario.order.item_id in evidence_str

    def test_scenario_4_return_window_expired(self):
        """Scenario 4: Request made after policy return/replacement window expired."""
        scenario = scenario_window_expired()
        options = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=scenario.customer_deadline,
            current_time=scenario.current_time,
        )

        assert len(options) == 1
        option = options[0]
        assert option.eligible is False
        assert option.meets_deadline is False
        assert option.estimated_arrival is None
        assert option.action_type == "REPLACEMENT_WINDOW_EXPIRED"

        evidence_str = " ".join(option.evidence)
        assert "expired" in evidence_str.lower()
        assert f"{scenario.policy.return_window_days} days" in evidence_str

    def test_scenario_5_expedited_meets_deadline_when_standard_cannot(self):
        """Scenario 5: Standard shipping fails deadline, but expedited shipping meets it and ranks #1."""
        scenario = scenario_expedited_meets_deadline_when_standard_cannot()
        options = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=scenario.customer_deadline,
            current_time=scenario.current_time,
        )

        assert len(options) == 2

        # Best option should be the Expedited one that meets the deadline
        best = options[0]
        assert best.rank == 1
        assert best.action_type == "REPLACEMENT_EXPEDITED"
        assert best.eligible is True
        assert best.meets_deadline is True
        assert best.estimated_arrival is not None
        assert best.estimated_arrival <= scenario.customer_deadline
        assert best.cost == 14.99

        # Second option should be Standard which misses the deadline
        second = options[1]
        assert second.rank == 2
        assert second.action_type == "REPLACEMENT_STANDARD"
        assert second.eligible is True
        assert second.meets_deadline is False
        assert second.estimated_arrival is not None
        assert second.estimated_arrival > scenario.customer_deadline


class TestDoorstepResolveDynamicBehaviors:
    """
    Tests ensuring the decision logic is truly dynamic and derives purely
    from changes in input values, rather than hardcoded scenario data.
    """

    def test_deadline_boundary_sensitivity(self):
        """Modifying the customer deadline by +/- 1 hour flips meets_deadline dynamically."""
        scenario = scenario_replacement_meets_deadline()
        # Find exact estimated arrival under baseline parameters
        baseline_options = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=scenario.customer_deadline,
            current_time=scenario.current_time,
        )
        exact_arrival = baseline_options[0].estimated_arrival
        assert exact_arrival is not None

        # Set deadline 1 hour BEFORE arrival -> meets_deadline must be False
        early_deadline = exact_arrival - timedelta(hours=1)
        res_early = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=early_deadline,
            current_time=scenario.current_time,
        )
        assert res_early[0].meets_deadline is False

        # Set deadline 1 hour AFTER arrival -> meets_deadline must be True
        late_deadline = exact_arrival + timedelta(hours=1)
        res_late = resolve_replacement(
            order=scenario.order,
            policy=scenario.policy,
            inventory=scenario.inventory,
            shipping_estimates=scenario.shipping_estimates,
            customer_deadline=late_deadline,
            current_time=scenario.current_time,
        )
        assert res_late[0].meets_deadline is True

    def test_cutoff_sensitivity_same_day_vs_next_day(self):
        """A current time before vs after daily cutoff shifts dispatch by exactly 24 hours."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [
            ShippingEstimate("WH-1", "Carrier", "Standard", time(14, 0), transit_hours=10)
        ]
        deadline = datetime(2026, 10, 25, 12, 0)

        # Time is 13:59 (1 minute before cutoff -> same-day dispatch)
        before_cutoff_time = datetime(2026, 10, 20, 13, 59)
        opts_before = resolve_replacement(
            order, policy, inventory, shipping, deadline, before_cutoff_time
        )
        assert opts_before[0].dispatch_time == datetime(2026, 10, 20, 14, 0)
        assert opts_before[0].estimated_arrival == datetime(2026, 10, 21, 0, 0)

        # Time is 14:01 (1 minute after cutoff -> next-day dispatch)
        after_cutoff_time = datetime(2026, 10, 20, 14, 1)
        opts_after = resolve_replacement(
            order, policy, inventory, shipping, deadline, after_cutoff_time
        )
        assert opts_after[0].dispatch_time == datetime(2026, 10, 21, 14, 0)
        assert opts_after[0].estimated_arrival == datetime(2026, 10, 22, 0, 0)

        # Difference is exactly 24 hours
        diff = opts_after[0].estimated_arrival - opts_before[0].estimated_arrival
        assert diff == timedelta(hours=24)

    def test_policy_disallowed_replacements(self):
        """When policy forbids replacements completely, option is ineligible with clear evidence."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(return_window_days=30, replacement_allowed=False)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(14, 0), 10)]

        options = resolve_replacement(
            order, policy, inventory, shipping, datetime(2026, 10, 25, 12, 0), datetime(2026, 10, 16, 10, 0)
        )
        assert len(options) == 1
        assert options[0].eligible is False
        assert options[0].action_type == "REPLACEMENT_DISALLOWED"
        assert "disallows replacements" in options[0].evidence[0]


class TestRegressionAndEdgeCases:
    """Regression tests covering confirmed edge cases and boundary conditions."""

    def test_mixed_aware_and_naive_datetimes_raises_value_error(self):
        """Mixed timezone-aware and timezone-naive datetimes must raise a clear ValueError."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc))
        policy = Policy(30, True)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(14, 0), 10)]

        # Naive current_time with aware delivered_at
        with pytest.raises(ValueError, match="Inconsistent datetime timezone awareness"):
            resolve_replacement(
                order=order,
                policy=policy,
                inventory=inventory,
                shipping_estimates=shipping,
                customer_deadline=datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc),
                current_time=datetime(2026, 10, 16, 10, 0),  # naive
            )

    def test_consistently_aware_datetimes_work_correctly(self):
        """When all datetime inputs are consistently timezone-aware, resolution proceeds smoothly."""
        tz = timezone.utc
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0, tzinfo=tz))
        policy = Policy(30, True)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(14, 0), transit_hours=12)]

        current_time = datetime(2026, 10, 16, 10, 0, tzinfo=tz)
        deadline = datetime(2026, 10, 20, 12, 0, tzinfo=tz)

        options = resolve_replacement(order, policy, inventory, shipping, deadline, current_time)
        assert len(options) == 1
        best = options[0]
        assert best.eligible is True
        assert best.meets_deadline is True
        assert best.estimated_arrival == datetime(2026, 10, 17, 2, 0, tzinfo=tz)

    def test_exact_shipping_cutoff_boundary_same_day(self):
        """At exactly the cutoff time (HH:MM:00), dispatch qualifies for same-day dispatch."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(15, 0), transit_hours=24)]

        # Exactly at 15:00:00
        current_time = datetime(2026, 10, 20, 15, 0, 0)
        deadline = datetime(2026, 10, 25, 12, 0)

        options = resolve_replacement(order, policy, inventory, shipping, deadline, current_time)
        # Should be same day dispatch
        assert options[0].dispatch_time == datetime(2026, 10, 20, 15, 0)
        assert "same-day dispatch" in " ".join(options[0].evidence)

    def test_arrival_exactly_at_customer_deadline(self):
        """Estimated arrival matching the customer deadline exactly evaluates to meets_deadline=True."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(16, 0), transit_hours=24)]

        current_time = datetime(2026, 10, 20, 10, 0)
        # Dispatch Oct 20 16:00 + 24h = Oct 21 16:00
        exact_deadline = datetime(2026, 10, 21, 16, 0)

        options = resolve_replacement(order, policy, inventory, shipping, exact_deadline, current_time)
        assert options[0].meets_deadline is True
        assert options[0].estimated_arrival == exact_deadline
        assert "Promise safe" in " ".join(options[0].evidence)

    def test_exact_policy_window_expiry_boundary(self):
        """Request at the exact second the return window expires is accepted; 1 second after is rejected."""
        delivered_at = datetime(2026, 10, 1, 12, 0, 0)
        policy = Policy(return_window_days=10)
        # Window expires at 2026-10-11 12:00:00
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(16, 0), transit_hours=12)]
        deadline = datetime(2026, 10, 25, 12, 0)

        # Exact boundary: 10 days after delivery
        exact_expiry_time = delivered_at + timedelta(days=10)
        opts_exact = resolve_replacement(
            Order("O-1", "ITEM-1", "Widget", 10.0, delivered_at),
            policy, inventory, shipping, deadline, exact_expiry_time
        )
        assert opts_exact[0].eligible is True

        # 1 second past expiry
        past_expiry_time = exact_expiry_time + timedelta(seconds=1)
        opts_past = resolve_replacement(
            Order("O-1", "ITEM-1", "Widget", 10.0, delivered_at),
            policy, inventory, shipping, deadline, past_expiry_time
        )
        assert opts_past[0].eligible is False
        assert opts_past[0].action_type == "REPLACEMENT_WINDOW_EXPIRED"

    def test_multiple_inventory_records_in_same_warehouse_aggregates_stock(self):
        """Multiple inventory records for the same warehouse are aggregated into a single option."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        # 2 records in WH-1 (e.g. separate SKU batches)
        inventory = [
            InventoryItem("ITEM-1", "SKU-1-BATCH-A", "WH-1", 4),
            InventoryItem("ITEM-1", "SKU-1-BATCH-B", "WH-1", 6),
        ]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(16, 0), transit_hours=24)]
        deadline = datetime(2026, 10, 25, 12, 0)

        options = resolve_replacement(order, policy, inventory, shipping, deadline, datetime(2026, 10, 16, 10, 0))
        # Must produce exactly 1 option for WH-1, not duplicated
        assert len(options) == 1
        assert options[0].warehouse_id == "WH-1"
        assert options[0].option_id == "REPLACE_WH-1_STANDARD"
        evidence_str = " ".join(options[0].evidence)
        assert "10 units available" in evidence_str

    def test_stock_available_at_one_warehouse_but_not_another(self):
        """When warehouse A is out of stock (0 units) but warehouse B has stock, only B is fulfilled."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        inventory = [
            InventoryItem("ITEM-1", "SKU-1", "WH-EMPTY", 0),
            InventoryItem("ITEM-1", "SKU-1", "WH-STOCKED", 5),
        ]
        shipping = [
            ShippingEstimate("WH-EMPTY", "CarrierA", "Standard", time(16, 0), 24),
            ShippingEstimate("WH-STOCKED", "CarrierB", "Standard", time(16, 0), 24),
        ]
        deadline = datetime(2026, 10, 25, 12, 0)

        options = resolve_replacement(order, policy, inventory, shipping, deadline, datetime(2026, 10, 16, 10, 0))
        assert len(options) == 1
        assert options[0].warehouse_id == "WH-STOCKED"
        assert options[0].eligible is True

    def test_warehouse_with_stock_but_no_shipping_route(self):
        """A warehouse with stock but no carrier route generates REPLACEMENT_UNROUTABLE."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-ISOLATED", 10)]
        shipping = []  # No shipping estimates

        options = resolve_replacement(
            order, policy, inventory, shipping,
            datetime(2026, 10, 25, 12, 0),
            datetime(2026, 10, 16, 10, 0),
        )
        assert len(options) == 1
        assert options[0].action_type == "REPLACEMENT_UNROUTABLE"
        assert options[0].eligible is False
        assert "No active shipping routes" in " ".join(options[0].evidence)

    def test_empty_or_unrelated_inventory(self):
        """Empty inventory list or inventory containing only unrelated SKUs returns OUT_OF_STOCK."""
        order = Order("O-1", "ITEM-TARGET", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        deadline = datetime(2026, 10, 25, 12, 0)
        current_time = datetime(2026, 10, 16, 10, 0)

        # 1. Empty inventory list
        opts_empty = resolve_replacement(order, policy, [], [], deadline, current_time)
        assert opts_empty[0].action_type == "REPLACEMENT_OUT_OF_STOCK"
        assert opts_empty[0].eligible is False

        # 2. Inventory contains only other items
        unrelated = [InventoryItem("ITEM-UNRELATED", "SKU-OTHER", "WH-1", 100)]
        opts_unrelated = resolve_replacement(order, policy, unrelated, [], deadline, current_time)
        assert opts_unrelated[0].action_type == "REPLACEMENT_OUT_OF_STOCK"
        assert opts_unrelated[0].eligible is False

    def test_zero_day_return_window(self):
        """Policy with return_window_days=0 is expired immediately if current_time > delivered_at."""
        delivered_at = datetime(2026, 10, 15, 10, 0, 0)
        policy = Policy(return_window_days=0)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [ShippingEstimate("WH-1", "Carrier", "Standard", time(16, 0), 24)]
        deadline = datetime(2026, 10, 25, 12, 0)

        # 1 minute after delivery -> expired for 0-day window
        opts = resolve_replacement(
            Order("O-1", "ITEM-1", "Widget", 10.0, delivered_at),
            policy, inventory, shipping, deadline,
            delivered_at + timedelta(minutes=1),
        )
        assert opts[0].eligible is False
        assert opts[0].action_type == "REPLACEMENT_WINDOW_EXPIRED"

    def test_current_time_before_delivery_rejected(self):
        """When current_time is earlier than order delivery time, it is flagged as invalid timing."""
        delivered_at = datetime(2026, 10, 20, 12, 0, 0)
        current_time = datetime(2026, 10, 19, 12, 0, 0)  # 1 day before delivery

        options = resolve_replacement(
            order=Order("O-1", "ITEM-1", "Widget", 10.0, delivered_at),
            policy=Policy(30, True),
            inventory=[InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)],
            shipping_estimates=[ShippingEstimate("WH-1", "Carrier", "Standard", time(16, 0), 24)],
            customer_deadline=datetime(2026, 10, 25, 12, 0),
            current_time=current_time,
        )
        assert len(options) == 1
        assert options[0].eligible is False
        assert options[0].action_type == "INVALID_PRE_DELIVERY_TIMING"
        assert "precedes order delivery time" in options[0].evidence[0]

    def test_resolution_options_guaranteed_unique_ids(self):
        """Even if shipping estimates share warehouse and method name, each option receives a unique ID."""
        order = Order("O-1", "ITEM-1", "Widget", 10.0, datetime(2026, 10, 15, 10, 0))
        policy = Policy(30, True)
        inventory = [InventoryItem("ITEM-1", "SKU-1", "WH-1", 5)]
        shipping = [
            ShippingEstimate("WH-1", "Carrier A", "Standard Ground", time(14, 0), transit_hours=24),
            ShippingEstimate("WH-1", "Carrier B", "Standard Ground", time(17, 0), transit_hours=20),
        ]
        deadline = datetime(2026, 10, 25, 12, 0)
        current_time = datetime(2026, 10, 20, 10, 0)

        options = resolve_replacement(order, policy, inventory, shipping, deadline, current_time)
        assert len(options) == 2
        option_ids = [opt.option_id for opt in options]
        assert len(option_ids) == len(set(option_ids)), f"Duplicate option IDs found: {option_ids}"
        assert option_ids[0] != option_ids[1]

