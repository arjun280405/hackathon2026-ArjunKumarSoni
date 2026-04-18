import json
from datetime import datetime

with open("data/orders.json") as f:
    orders = json.load(f)

def get_order(order_id):
    if not order_id:
        raise Exception("Order ID is required")

    order_id = str(order_id).strip()

    for order in orders:
        if order.get("order_id", "").strip() == order_id:
            return order

    raise Exception(f"Order not found: {order_id}")


def get_latest_order_for_customer(customer_id):
    customer_orders = [
        order for order in orders if order.get("customer_id") == customer_id
    ]

    if not customer_orders:
        raise Exception(f"No orders found for customer: {customer_id}")

    # Pick the most recent order by order_date.
    return max(
        customer_orders,
        key=lambda order: datetime.strptime(order["order_date"], "%Y-%m-%d")
    )

def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        # Accept "YYYY-MM-DD" and ISO timestamp strings.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return value


def check_refund_eligibility(
    order,
    reference_date=None,
    customer=None,
    product=None,
    ticket_text="",
):
    ticket_text = (ticket_text or "").lower()
    order_notes = (order.get("notes") or "").lower()
    customer_notes = ((customer or {}).get("notes") or "").lower()
    customer_tier = ((customer or {}).get("tier") or "").lower()
    product_notes = ((product or {}).get("notes") or "").lower()

    if order.get("refund_status") is not None:
        return {"eligible": False, "reason": "Already refunded"}

    # Damaged/defective/wrong item cases are eligible regardless of return window.
    forced_refund_keywords = [
        "damaged",
        "defect",
        "defective",
        "broken",
        "cracked",
        "wrong size",
        "wrong colour",
        "wrong color",
        "wrong item",
    ]
    if any(keyword in ticket_text for keyword in forced_refund_keywords):
        return {"eligible": True, "reason": "Defect or wrong item policy"}

    if "registered online" in order_notes and "registered online" in product_notes:
        return {"eligible": False, "reason": "Registered product is non-returnable"}

    if order.get("status") in {"processing", "shipped"}:
        return {"eligible": False, "reason": f"Order is {order.get('status')} and not return-eligible yet"}

    if not order.get("return_deadline"):
        return {"eligible": False, "reason": "Order not eligible for return yet"}

    reference_day = _to_date(reference_date) or datetime.now().date()
    return_deadline = datetime.strptime(order["return_deadline"], "%Y-%m-%d").date()

    if reference_day <= return_deadline:
        return {"eligible": True, "reason": "Within return window"}

    # VIP management exception.
    if customer_tier == "vip" and (
        "extended return" in customer_notes or "extended return" in order_notes
    ):
        return {"eligible": True, "reason": "VIP extended-return exception"}

    # Premium grace period for borderline cases.
    days_late = (reference_day - return_deadline).days
    if customer_tier == "premium" and 1 <= days_late <= 3:
        return {"eligible": True, "reason": "Premium grace-period approval"}


    return {"eligible": False, "reason": "Return window expired"}