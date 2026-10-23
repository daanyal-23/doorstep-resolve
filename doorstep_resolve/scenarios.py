"""
Synthetic test scenarios for Doorstep Resolve.

Each scenario produces realistic domain inputs covering key real-world edge cases:
1. Replacement meets the deadline
2. Replacement arrives too late
3. Replacement stock unavailable
4. Return/replacement window expired
5. Expedited option meets deadline when standard shipping cannot
"""

from datetime import datetime, time
from typing import NamedTuple, List
from .models import Order, Policy, InventoryItem, ShippingEstimate


class ScenarioData(NamedTuple):
    name: str
    description: str
    order: Order
    policy: Policy
    inventory: List[InventoryItem]
    shipping_estimates: List[ShippingEstimate]
    customer_deadline: datetime
    current_time: datetime


def scenario_replacement_meets_deadline() -> ScenarioData:
    """Scenario 1: Replacement in stock and standard transit meets customer's deadline."""
    current_time = datetime(2026, 10, 20, 10, 0, 0)
    delivered_at = datetime(2026, 10, 15, 14, 0, 0)
    deadline = datetime(2026, 10, 22, 18, 0, 0)

    order = Order(
        order_id="ORD-1001",
        item_id="SKU-HEADPHONES-PRO",
        item_name="Noise Cancelling Wireless Headphones",
        price=199.99,
        delivered_at=delivered_at,
    )
    policy = Policy(return_window_days=30, replacement_allowed=True)
    inventory = [
        InventoryItem(
            item_id="SKU-HEADPHONES-PRO",
            sku="SKU-HP-BLK",
            warehouse_id="WH-EAST-1",
            quantity=12,
        )
    ]
    shipping_estimates = [
        ShippingEstimate(
            warehouse_id="WH-EAST-1",
            carrier="FastTrack Logistics",
            method_name="Standard Ground",
            cutoff_time=time(17, 0),
            transit_hours=24,
            shipping_cost=0.0,
        )
    ]
    return ScenarioData(
        name="replacement_meets_deadline",
        description="Replacement is in stock and standard transit delivers well before customer deadline.",
        order=order,
        policy=policy,
        inventory=inventory,
        shipping_estimates=shipping_estimates,
        customer_deadline=deadline,
        current_time=current_time,
    )


def scenario_replacement_arrives_too_late() -> ScenarioData:
    """Scenario 2: Replacement is in stock, but misses deadline due to transit duration & cutoff."""
    # Current time is 17:30 (past the 16:00 cutoff), pushing dispatch to next day
    current_time = datetime(2026, 10, 20, 17, 30, 0)
    delivered_at = datetime(2026, 10, 16, 12, 0, 0)
    # Customer urgently needs it by Oct 22 at 12:00
    deadline = datetime(2026, 10, 22, 12, 0, 0)

    order = Order(
        order_id="ORD-1002",
        item_id="SKU-CHARGER-100W",
        item_name="100W USB-C GaN Charger",
        price=49.99,
        delivered_at=delivered_at,
    )
    policy = Policy(return_window_days=30, replacement_allowed=True)
    inventory = [
        InventoryItem(
            item_id="SKU-CHARGER-100W",
            sku="SKU-CHG-100W",
            warehouse_id="WH-WEST-1",
            quantity=8,
        )
    ]
    shipping_estimates = [
        ShippingEstimate(
            warehouse_id="WH-WEST-1",
            carrier="Apex Freight",
            method_name="Standard Ground",
            cutoff_time=time(16, 0),
            transit_hours=48,
            shipping_cost=0.0,
        )
    ]
    return ScenarioData(
        name="replacement_arrives_too_late",
        description="Standard delivery cannot satisfy tight deadline due to missed daily cutoff and 48h transit.",
        order=order,
        policy=policy,
        inventory=inventory,
        shipping_estimates=shipping_estimates,
        customer_deadline=deadline,
        current_time=current_time,
    )


def scenario_replacement_stock_unavailable() -> ScenarioData:
    """Scenario 3: Return window is active, but replacement inventory is 0 across all warehouses."""
    current_time = datetime(2026, 10, 20, 11, 0, 0)
    delivered_at = datetime(2026, 10, 18, 10, 0, 0)
    deadline = datetime(2026, 10, 24, 18, 0, 0)

    order = Order(
        order_id="ORD-1003",
        item_id="SKU-JACKET-LTD",
        item_name="Limited Edition Winter Jacket",
        price=249.00,
        delivered_at=delivered_at,
    )
    policy = Policy(return_window_days=30, replacement_allowed=True)
    inventory = [
        InventoryItem(
            item_id="SKU-JACKET-LTD",
            sku="SKU-JKT-M-BLUE",
            warehouse_id="WH-CENTRAL-1",
            quantity=0,
        ),
        InventoryItem(
            item_id="SKU-JACKET-LTD",
            sku="SKU-JKT-M-BLUE",
            warehouse_id="WH-EAST-1",
            quantity=0,
        ),
    ]
    shipping_estimates = [
        ShippingEstimate(
            warehouse_id="WH-CENTRAL-1",
            carrier="Apex Freight",
            method_name="Standard Ground",
            cutoff_time=time(17, 0),
            transit_hours=24,
            shipping_cost=0.0,
        )
    ]
    return ScenarioData(
        name="replacement_stock_unavailable",
        description="Stock is depleted across all fulfillment centers, making replacement promise impossible.",
        order=order,
        policy=policy,
        inventory=inventory,
        shipping_estimates=shipping_estimates,
        customer_deadline=deadline,
        current_time=current_time,
    )


def scenario_window_expired() -> ScenarioData:
    """Scenario 4: Replacement requested after the return/replacement window has elapsed."""
    current_time = datetime(2026, 10, 20, 11, 0, 0)
    # Delivered 40 days ago (30-day window expired 10 days ago)
    delivered_at = datetime(2026, 9, 10, 14, 0, 0)
    deadline = datetime(2026, 10, 23, 12, 0, 0)

    order = Order(
        order_id="ORD-1004",
        item_id="SKU-ESPRESSO-DELUXE",
        item_name="Deluxe Compact Espresso Machine",
        price=320.00,
        delivered_at=delivered_at,
    )
    policy = Policy(return_window_days=30, replacement_allowed=True)
    inventory = [
        InventoryItem(
            item_id="SKU-ESPRESSO-DELUXE",
            sku="SKU-ESP-SS",
            warehouse_id="WH-EAST-1",
            quantity=5,
        )
    ]
    shipping_estimates = [
        ShippingEstimate(
            warehouse_id="WH-EAST-1",
            carrier="FastTrack Logistics",
            method_name="Standard Ground",
            cutoff_time=time(17, 0),
            transit_hours=24,
            shipping_cost=0.0,
        )
    ]
    return ScenarioData(
        name="window_expired",
        description="Order delivered 40 days ago exceeds 30-day policy window, disqualifying replacement.",
        order=order,
        policy=policy,
        inventory=inventory,
        shipping_estimates=shipping_estimates,
        customer_deadline=deadline,
        current_time=current_time,
    )


def scenario_expedited_meets_deadline_when_standard_cannot() -> ScenarioData:
    """Scenario 5: Standard shipping misses deadline, but expedited air delivery fulfills customer's need."""
    current_time = datetime(2026, 10, 20, 13, 0, 0)
    delivered_at = datetime(2026, 10, 17, 9, 0, 0)
    # Customer deadline is Oct 21 at 17:00
    deadline = datetime(2026, 10, 21, 17, 0, 0)

    order = Order(
        order_id="ORD-1005",
        item_id="SKU-MONITOR-PULSE",
        item_name="Continuous Health Pulse Monitor",
        price=145.00,
        delivered_at=delivered_at,
    )
    policy = Policy(return_window_days=30, replacement_allowed=True)
    inventory = [
        InventoryItem(
            item_id="SKU-MONITOR-PULSE",
            sku="SKU-MON-WHT",
            warehouse_id="WH-NORTH-1",
            quantity=10,
        )
    ]
    shipping_estimates = [
        ShippingEstimate(
            warehouse_id="WH-NORTH-1",
            carrier="GroundLogistics",
            method_name="Standard Ground",
            cutoff_time=time(15, 0),
            transit_hours=48,  # Arrives Oct 22 at 15:00 (too late)
            shipping_cost=0.0,
        ),
        ShippingEstimate(
            warehouse_id="WH-NORTH-1",
            carrier="SwiftExpress",
            method_name="Expedited Air",
            cutoff_time=time(15, 0),
            transit_hours=12,  # Arrives Oct 21 at 03:00 (meets deadline!)
            shipping_cost=14.99,
        ),
    ]
    return ScenarioData(
        name="expedited_alternative_meets_deadline",
        description="Standard shipping arrives after deadline, but expedited air delivers in time and is ranked #1.",
        order=order,
        policy=policy,
        inventory=inventory,
        shipping_estimates=shipping_estimates,
        customer_deadline=deadline,
        current_time=current_time,
    )
