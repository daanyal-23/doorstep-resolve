"""
Data models for Doorstep Resolve decision engine.
"""

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional, List


@dataclass(frozen=True)
class Order:
    order_id: str
    item_id: str
    item_name: str
    price: float
    delivered_at: datetime


@dataclass(frozen=True)
class Policy:
    return_window_days: int = 30
    replacement_allowed: bool = True


@dataclass(frozen=True)
class InventoryItem:
    item_id: str
    sku: str
    warehouse_id: str
    quantity: int


@dataclass(frozen=True)
class ShippingEstimate:
    warehouse_id: str
    carrier: str
    method_name: str
    cutoff_time: time
    transit_hours: int
    shipping_cost: float = 0.0


@dataclass
class ResolutionOption:
    option_id: str
    action_type: str  # "REPLACEMENT_EXPEDITED", "REPLACEMENT_STANDARD", "REFUND", "NO_REPLACEMENT_AVAILABLE"
    eligible: bool
    meets_deadline: bool
    estimated_arrival: Optional[datetime] = None
    dispatch_time: Optional[datetime] = None
    warehouse_id: Optional[str] = None
    shipping_method: Optional[str] = None
    cost: float = 0.0
    rank: int = 0
    evidence: List[str] = field(default_factory=list)
    carrier: Optional[str] = None
    shipping_speed: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "option_id": self.option_id,
            "action_type": self.action_type,
            "eligible": self.eligible,
            "is_eligible": self.eligible,
            "meets_deadline": self.meets_deadline,
            "estimated_arrival": self.estimated_arrival.isoformat() if self.estimated_arrival else None,
            "dispatch_time": self.dispatch_time.isoformat() if self.dispatch_time else None,
            "warehouse_id": self.warehouse_id,
            "carrier": self.carrier,
            "shipping_method": self.shipping_method,
            "shipping_speed": self.shipping_speed or self.shipping_method,
            "cost": self.cost,
            "rank": self.rank,
            "evidence": self.evidence,
            "reason": self.reason or (self.evidence[-1] if self.evidence else ""),
        }

