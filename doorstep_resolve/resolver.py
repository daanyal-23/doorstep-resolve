"""
Core decision engine for Doorstep Resolve.

Evaluates replacement eligibility, shipping cutoffs, and transit times
against customer deadlines to produce ranked resolution options with evidence.
"""

from datetime import datetime, timedelta, time
from typing import List, Optional, Dict, Any, Set, Tuple

from .models import Order, Policy, InventoryItem, ShippingEstimate, ResolutionOption


def _validate_datetime_inputs(
    order: Order,
    customer_deadline: datetime,
    current_time: datetime,
) -> None:
    """
    Validates datetime types and ensures consistent timezone awareness across all inputs.
    Raises TypeError if any value is not a datetime.
    Raises ValueError if there is a mix of timezone-aware and timezone-naive datetimes.
    """
    for name, val in [
        ("order.delivered_at", order.delivered_at),
        ("customer_deadline", customer_deadline),
        ("current_time", current_time),
    ]:
        if not isinstance(val, datetime):
            raise TypeError(f"Expected datetime for '{name}', got {type(val).__name__}")

    aware_states = {
        "order.delivered_at": (
            order.delivered_at.tzinfo is not None
            and order.delivered_at.tzinfo.utcoffset(order.delivered_at) is not None
        ),
        "customer_deadline": (
            customer_deadline.tzinfo is not None
            and customer_deadline.tzinfo.utcoffset(customer_deadline) is not None
        ),
        "current_time": (
            current_time.tzinfo is not None
            and current_time.tzinfo.utcoffset(current_time) is not None
        ),
    }

    num_aware = sum(aware_states.values())
    if num_aware not in (0, 3):
        details = ", ".join(f"{k} (aware={v})" for k, v in aware_states.items())
        raise ValueError(
            f"Inconsistent datetime timezone awareness: {details}. "
            "All datetime inputs must either be all timezone-aware or all timezone-naive."
        )


def evaluate_order_policy(
    delivered_at: datetime,
    return_window_days: int = 30,
    replacement_allowed: bool = True,
    current_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Deterministically evaluates replacement policy based on order delivery date,
    policy return window, replacement allowance, and evaluation current_time.
    """
    window_expiry = delivered_at + timedelta(days=return_window_days)

    if current_time is not None:
        if current_time.tzinfo is not None and delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=current_time.tzinfo)
            window_expiry = window_expiry.replace(tzinfo=current_time.tzinfo)
        elif current_time.tzinfo is None and delivered_at.tzinfo is not None:
            delivered_at = delivered_at.replace(tzinfo=None)
            window_expiry = window_expiry.replace(tzinfo=None)
        is_within_window = current_time <= window_expiry
    else:
        now_dt = datetime.now(delivered_at.tzinfo) if delivered_at.tzinfo else datetime.now()
        is_within_window = now_dt <= window_expiry

    if not replacement_allowed:
        return {
            "return_window_days": return_window_days,
            "replacement_allowed": False,
            "allows_replacement": False,
            "is_eligible": False,
            "status": "POLICY_DISALLOWED",
            "badge_label": "Policy Blocked",
            "reason": "Policy disallows replacements for this order.",
            "window_expiry": window_expiry.isoformat(),
            "is_within_window": is_within_window,
        }
    elif not is_within_window:
        return {
            "return_window_days": return_window_days,
            "replacement_allowed": True,
            "allows_replacement": False,
            "is_eligible": False,
            "status": "WINDOW_EXPIRED",
            "badge_label": "Replacement Window Expired",
            "reason": f"Replacement window of {return_window_days} days expired on {window_expiry.strftime('%Y-%m-%d')}.",
            "window_expiry": window_expiry.isoformat(),
            "is_within_window": False,
        }
    else:
        return {
            "return_window_days": return_window_days,
            "replacement_allowed": True,
            "allows_replacement": True,
            "is_eligible": True,
            "status": "ELIGIBLE",
            "badge_label": "Replacements Eligible",
            "reason": f"Order is within active {return_window_days}-day replacement window.",
            "window_expiry": window_expiry.isoformat(),
            "is_within_window": True,
        }


def resolve_replacement(
    order: Order,
    policy: Policy,
    inventory: List[InventoryItem],
    shipping_estimates: List[ShippingEstimate],
    customer_deadline: datetime,
    current_time: datetime,
) -> List[ResolutionOption]:
    """
    Evaluates replacement options for an order based on policy, inventory,
    transit constraints, and customer deadline.

    Returns a ranked list of ResolutionOptions, each containing eligibility,
    arrival estimate, deadline compatibility, and decision evidence.

    Limitation & Timezone Policy:
    ShippingEstimate does not currently specify an explicit warehouse timezone.
    The resolver adheres to the explicit policy that cutoff_time is evaluated
    in the coordinate space of current_time. Warehouse-specific timezones should
    be modeled in future iterations.
    """
    _validate_datetime_inputs(order, customer_deadline, current_time)

    options: List[ResolutionOption] = []

    # 1. Pre-delivery timing validation
    if current_time < order.delivered_at:
        options.append(
            ResolutionOption(
                option_id="INVALID_PRE_DELIVERY_TIMING",
                action_type="INVALID_PRE_DELIVERY_TIMING",
                eligible=False,
                meets_deadline=False,
                evidence=[
                    f"Current time ({current_time.isoformat()}) precedes order delivery time ({order.delivered_at.isoformat()}).",
                    "Replacement requests cannot be evaluated before an order has been delivered.",
                ],
            )
        )
        _assign_ranks(options)
        return options

    # 2. Policy Validation
    window_expiry = order.delivered_at + timedelta(days=policy.return_window_days)
    is_within_window = current_time <= window_expiry

    if not policy.replacement_allowed:
        options.append(
            ResolutionOption(
                option_id="POLICY_REPLACEMENT_DISALLOWED",
                action_type="REPLACEMENT_DISALLOWED",
                eligible=False,
                meets_deadline=False,
                reason="Policy disallows replacements for this order.",
                evidence=[
                    f"Policy disallows replacements for order '{order.order_id}'.",
                    "Only alternative resolutions (e.g. standard refund) may be considered.",
                ],
            )
        )
        _assign_ranks(options)
        return options

    if not is_within_window:
        overdue_duration = current_time - window_expiry
        options.append(
            ResolutionOption(
                option_id="POLICY_WINDOW_EXPIRED",
                action_type="REPLACEMENT_WINDOW_EXPIRED",
                eligible=False,
                meets_deadline=False,
                reason="Return and replacement policy window expired.",
                evidence=[
                    f"Delivered on {order.delivered_at.isoformat()}.",
                    f"Return/replacement policy is {policy.return_window_days} days.",
                    f"Policy window expired on {window_expiry.isoformat()}.",
                    f"Current evaluation time {current_time.isoformat()} is overdue by {overdue_duration}.",
                    "Replacement request denied due to expired policy window.",
                ],
            )
        )
        _assign_ranks(options)
        return options

    # 3. Inventory Availability Check (Aggregated per warehouse)
    matching_inventory = [
        inv for inv in inventory if inv.item_id == order.item_id and inv.quantity > 0
    ]

    if not matching_inventory:
        total_qty = sum(inv.quantity for inv in inventory if inv.item_id == order.item_id)
        options.append(
            ResolutionOption(
                option_id="INVENTORY_UNAVAILABLE",
                action_type="REPLACEMENT_OUT_OF_STOCK",
                eligible=False,
                meets_deadline=False,
                reason="Replacement item is out of stock across all fulfillment locations.",
                evidence=[
                    f"Order delivered on {order.delivered_at.isoformat()} (policy window active until {window_expiry.isoformat()}).",
                    f"Item '{order.item_id}' ({order.item_name}) has {total_qty} units available across all fulfillment locations.",
                    "No replacement stock is currently available to fulfill this order. Cannot meet deadline.",
                ],
            )
        )
        _assign_ranks(options)
        return options

    # Aggregate stock by warehouse to prevent duplicate resolution options
    warehouse_stock: Dict[str, Dict[str, Any]] = {}
    for inv in matching_inventory:
        if inv.warehouse_id not in warehouse_stock:
            warehouse_stock[inv.warehouse_id] = {
                "total_quantity": 0,
                "skus": set(),
            }
        warehouse_stock[inv.warehouse_id]["total_quantity"] += inv.quantity
        warehouse_stock[inv.warehouse_id]["skus"].add(inv.sku)

    # 4. Fulfillment & Shipping Options Evaluation
    seen_option_ids: Dict[str, int] = {}
    for warehouse_id, stock_info in warehouse_stock.items():
        total_qty = stock_info["total_quantity"]
        skus_str = ", ".join(sorted(stock_info["skus"]))

        applicable_shipping = [
            ship for ship in shipping_estimates if ship.warehouse_id == warehouse_id
        ]

        if not applicable_shipping:
            unroutable_id = f"NO_CARRIER_ROUTE_{warehouse_id}"
            options.append(
                ResolutionOption(
                    option_id=unroutable_id,
                    action_type="REPLACEMENT_UNROUTABLE",
                    eligible=False,
                    meets_deadline=False,
                    warehouse_id=warehouse_id,
                    reason=f"No active shipping routes or carriers available from warehouse '{warehouse_id}'.",
                    evidence=[
                        f"Stock available ({total_qty} units) at warehouse '{warehouse_id}'.",
                        f"No active shipping routes or carriers available from warehouse '{warehouse_id}'.",
                        "Cannot meet customer deadline due to lack of carrier route.",
                    ],
                )
            )
            continue

        # Deduplicate shipping estimates for this warehouse if identical route definition exists
        unique_shipping: List[ShippingEstimate] = []
        seen_routes: Set[Tuple[str, str, time, int, float]] = set()
        for ship in applicable_shipping:
            route_key = (ship.carrier, ship.method_name, ship.cutoff_time, ship.transit_hours, ship.shipping_cost)
            if route_key not in seen_routes:
                seen_routes.add(route_key)
                unique_shipping.append(ship)

        for ship in unique_shipping:
            # Determine dispatch datetime based on cutoff
            same_day_cutoff_met = current_time.time() <= ship.cutoff_time
            if same_day_cutoff_met:
                dispatch_date = current_time.date()
                cutoff_status = f"same-day dispatch (before cutoff {ship.cutoff_time.strftime('%H:%M')})"
            else:
                dispatch_date = current_time.date() + timedelta(days=1)
                cutoff_status = f"next-day dispatch (past daily cutoff {ship.cutoff_time.strftime('%H:%M')})"

            dispatch_time = datetime.combine(
                dispatch_date, ship.cutoff_time, tzinfo=current_time.tzinfo
            )
            estimated_arrival = dispatch_time + timedelta(hours=ship.transit_hours)
            meets_deadline = estimated_arrival <= customer_deadline

            # Build transparent evidence chain
            evidence = [
                f"Policy window check: Valid (expires {window_expiry.isoformat()}).",
                f"Inventory verified: {total_qty} units available at warehouse '{warehouse_id}' (SKU: {skus_str}).",
                f"Dispatch timing: Current time {current_time.strftime('%H:%M')} -> {cutoff_status}. Dispatch scheduled for {dispatch_time.isoformat()}.",
                f"Transit calculation: Carrier '{ship.carrier}' ({ship.method_name}) transit duration is {ship.transit_hours} hours.",
                f"Estimated arrival: {estimated_arrival.isoformat()}.",
            ]

            if meets_deadline:
                margin = customer_deadline - estimated_arrival
                evidence.append(
                    f"Deadline evaluation: Arrives {margin} ahead of deadline ({customer_deadline.isoformat()}). Promise safe."
                )
            else:
                lateness = estimated_arrival - customer_deadline
                evidence.append(
                    f"Deadline evaluation: Arrives {lateness} after customer deadline ({customer_deadline.isoformat()}). Fails deadline constraint."
                )

            action_type = (
                "REPLACEMENT_EXPEDITED"
                if "expedited" in ship.method_name.lower() or "next-day" in ship.method_name.lower() or "express" in ship.method_name.lower()
                else "REPLACEMENT_STANDARD"
            )

            # Generate unique option ID
            base_option_id = f"REPLACE_{warehouse_id}_{ship.method_name.replace(' ', '_').upper()}"
            if base_option_id not in seen_option_ids:
                seen_option_ids[base_option_id] = 1
                opt_id = base_option_id
            else:
                seen_option_ids[base_option_id] += 1
                opt_id = f"{base_option_id}_{seen_option_ids[base_option_id]}"

            options.append(
                ResolutionOption(
                    option_id=opt_id,
                    action_type=action_type,
                    eligible=True,
                    meets_deadline=meets_deadline,
                    estimated_arrival=estimated_arrival,
                    dispatch_time=dispatch_time,
                    warehouse_id=warehouse_id,
                    carrier=ship.carrier,
                    shipping_method=ship.method_name,
                    shipping_speed=ship.method_name,
                    cost=ship.shipping_cost,
                    reason=f"{ship.carrier} {ship.method_name} - {'Meets customer deadline' if meets_deadline else 'Arrives after customer deadline'}",
                    evidence=evidence,
                )
            )

    # 5. Rank the options
    _assign_ranks(options)
    return options


def _assign_ranks(options: List[ResolutionOption]) -> None:
    """
    Ranks options according to priority:
    1. Eligible & meets deadline (sorted by earliest arrival, then lowest shipping cost)
    2. Eligible & does not meet deadline (sorted by earliest arrival, then lowest shipping cost)
    3. Ineligible options

    Uses deterministic datetime comparisons without host-OS timestamp conversions.
    """
    def sort_key(opt: ResolutionOption):
        if opt.eligible and opt.meets_deadline:
            tier = 0
        elif opt.eligible and not opt.meets_deadline:
            tier = 1
        else:
            tier = 2

        # 0 if arrival is present (evaluated first), 1 if None (placed last)
        has_no_arrival = 1 if opt.estimated_arrival is None else 0
        # If has_no_arrival == 1, a dummy value is used. Python only compares index 2
        # if index 1 (has_no_arrival) is identical.
        arrival_val = opt.estimated_arrival if opt.estimated_arrival is not None else 0
        return (tier, has_no_arrival, arrival_val, opt.cost)

    options.sort(key=sort_key)
    current_rank = 1
    for opt in options:
        if opt.eligible:
            opt.rank = current_rank
            current_rank += 1
        else:
            opt.rank = 0

