import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from tools.order_tools import (
    check_refund_eligibility,
    get_latest_order_for_customer,
    get_order,
)
from tools.customer_tools import get_customer
from tools.product_tools import get_product
from tools.action_tools import escalate, issue_refund, send_reply
from tools.retry_utils import call_with_retry
from agent.confidence import score_confidence
from agent.dead_letter_queue import DeadLetterQueue
from agent.demo_runner import (
    load_tickets,
    process_tickets_in_parallel,
    print_structured_summary,
)


LOG_FILE = Path("logs") / "agent.log"
AUDIT_LOG_FILE = Path("logs") / "audit_log.json"
DEAD_LETTER_FILE = Path("logs") / "dead_letter.json"
ORDER_ID_PATTERN = re.compile(r"\bORD-\d+\b", re.IGNORECASE)
SEPARATOR = "=" * 50
AUDIT_LOG_LOCK = threading.Lock()
OUTPUT_LOCK = threading.Lock()


def setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        ],
    )


def _read_audit_entries():
    if not AUDIT_LOG_FILE.exists():
        return []

    try:
        with open(AUDIT_LOG_FILE, encoding="utf-8") as file:
            data = json.load(file)
            if not isinstance(data, list):
                return []
            return [_normalize_audit_entry(entry) for entry in data]
    except Exception:
        # Keep processing tickets even if the audit file is corrupted.
        logging.exception("Failed to read audit log. Reinitializing audit log list.")
        return []


def _normalize_audit_entry(entry):
    if not isinstance(entry, dict):
        return {
            "ticket_id": "UNKNOWN",
            "steps": [],
            "decision": "processing_failed",
            "confidence": "low",
            "error": "Invalid audit entry format",
        }

    if {"ticket_id", "steps", "decision", "confidence", "error"}.issubset(entry.keys()):
        return {
            "ticket_id": entry.get("ticket_id", "UNKNOWN"),
            "steps": entry.get("steps", []),
            "decision": str(entry.get("decision", "processing_failed")).lower(),
            "confidence": str(entry.get("confidence", "low")).lower(),
            "error": entry.get("error"),
        }

    # Backward compatibility for old entry shape.
    inferred_decision = str(entry.get("action", "processing_failed")).lower().replace(" ", "_")
    if entry.get("status") == "failed":
        inferred_decision = "processing_failed"

    return {
        "ticket_id": entry.get("ticket_id", "UNKNOWN"),
        "steps": entry.get("steps", []),
        "decision": inferred_decision,
        "confidence": str(entry.get("confidence", "low")).lower(),
        "error": entry.get("error"),
    }


def append_audit_entry(entry):
    try:
        AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG_LOCK:
            entries = _read_audit_entries()
            entries.append(entry)
            with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as file:
                json.dump(entries, file, indent=4)
    except Exception:
        # Never block ticket processing because of audit persistence issues.
        logging.exception("Failed to append audit entry for ticket %s", entry.get("ticket_id"))


def print_ticket_header(ticket_id):
    return [f"\n{SEPARATOR}", f"🎫 Processing Ticket: {ticket_id}", SEPARATOR]


def print_step(label):
    return [f"\n🔹 {label}"]


def print_success(message):
    return [f"   ✅ {message}"]


def print_detail(icon, message):
    return [f"   {icon} {message}"]


def print_separator():
    return [SEPARATOR]


def append_output(output_lines, lines):
    output_lines.extend(lines)


def flush_output(output_lines):
    with OUTPUT_LOCK:
        for line in output_lines:
            print(line)


def safe_send_reply(ticket_id, message, output_lines=None):
    reply_line = f"[Reply Sent] Ticket {ticket_id}: {message}"
    if output_lines is None:
        with OUTPUT_LOCK:
            send_reply(ticket_id, message)
    else:
        append_output(output_lines, [reply_line])
    return reply_line


def safe_issue_refund(order_id, amount, output_lines=None):
    refund_line = f"[Refund Issued] Order {order_id}: ${amount}"
    if output_lines is None:
        with OUTPUT_LOCK:
            issue_refund(order_id, amount)
    else:
        append_output(output_lines, [refund_line])
    return refund_line


def safe_escalate(ticket_id, summary, priority="high", output_lines=None):
    escalate_lines = [
        f"[Escalated] Ticket {ticket_id} | Priority: {priority}",
        f"Summary: {summary}",
    ]
    if output_lines is None:
        with OUTPUT_LOCK:
            escalate(ticket_id, summary, priority)
    else:
        append_output(output_lines, escalate_lines)
    return escalate_lines


def _retry_step_name(func):
    return f"retry:{getattr(func, '__name__', 'tool_call')}"


def _call_tool_with_retry(ticket_id, steps, func, *args, **kwargs):
    def on_retry(attempt, exc, delay_seconds):
        steps.append(f"{_retry_step_name(func)}:{attempt}")
        logging.warning(
            "Retrying %s for ticket %s in %.2fs (attempt %s)",
            getattr(func, "__name__", "tool_call"),
            ticket_id,
            delay_seconds,
            attempt,
        )

    return call_with_retry(func, *args, retries=3, base_delay_seconds=0.2, on_retry=on_retry, **kwargs)


def _ticket_text(ticket):
    return f"{ticket.get('subject', '')} {ticket.get('body', '')}".strip()


def extract_order_id(ticket):
    if ticket.get("order_id"):
        return ticket["order_id"].strip()

    text = _ticket_text(ticket)
    match = ORDER_ID_PATTERN.search(text)
    if match:
        return match.group(0).upper()

    return None


def classify_ticket(ticket):
    text = _ticket_text(ticket).lower()

    general_phrases = [
        "return policy",
        "what is your",
        "what's your",
        "where is my order",
        "tracking",
        "what's the process",
        "not sure",
    ]
    refund_keywords = ["refund", "return", "cancel", "money back"]
    product_issue_keywords = [
        "broken",
        "damaged",
        "defect",
        "not working",
        "wrong size",
        "wrong colour",
        "wrong color",
        "cracked",
        "replacement",
    ]
    general_keywords = ["policy", "how", "process", "where is", "tracking"]

    if any(phrase in text for phrase in general_phrases):
        return "general"

    if any(keyword in text for keyword in product_issue_keywords):
        return "product_issue"
    if any(keyword in text for keyword in refund_keywords):
        return "refund"
    if any(keyword in text for keyword in general_keywords):
        return "general"

    return "unknown"


def _ticket_reference_date(ticket):
    created_at = ticket.get("created_at")
    if not created_at:
        return None
    return datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()


def _contains_any(text, keywords):
    return any(keyword in text for keyword in keywords)


def _warranty_active(order, product, reference_date):
    delivery_date = order.get("delivery_date")
    warranty_months = product.get("warranty_months", 0)

    if not delivery_date or not warranty_months or not reference_date:
        return False

    delivered_on = datetime.strptime(delivery_date, "%Y-%m-%d").date()
    days_of_warranty = warranty_months * 30
    return (reference_date - delivered_on).days <= days_of_warranty


def process_ticket(ticket):
    ticket_id = ticket.get("ticket_id", "UNKNOWN")
    logging.info("Processing ticket %s", ticket_id)
    output_lines = []
    append_output(output_lines, print_ticket_header(ticket_id))

    steps = []
    category = "unknown"
    decision = "processing_failed"
    confidence = "low"
    status = "failed"
    error_message = None

    try:
        # 1) Read ticket (already available as input)
        logging.info("Step 1: Ticket read | email=%s", ticket.get("customer_email"))

        # 2) Get customer using customer_email
        append_output(output_lines, print_step("Fetching customer..."))
        customer = _call_tool_with_retry(ticket_id, steps, get_customer, ticket["customer_email"])
        steps.append("get_customer")
        logging.info(
            "Step 2: Customer resolved | customer_id=%s",
            customer["customer_id"],
        )
        append_output(output_lines, print_success(f"Customer: {customer['name']} ({customer['email']})"))

        # 3) Get order: by order_id if present, else latest order for customer
        append_output(output_lines, print_step("Fetching order..."))
        provided_order_id = extract_order_id(ticket)
        if provided_order_id:
            order = _call_tool_with_retry(ticket_id, steps, get_order, provided_order_id)
            steps.append("get_order")
            logging.info(
                "Step 3: Order resolved from ticket | order_id=%s",
                provided_order_id,
            )
        else:
            order = _call_tool_with_retry(
                ticket_id,
                steps,
                get_latest_order_for_customer,
                customer["customer_id"],
            )
            steps.append("get_order")
            logging.info(
                "Step 3: No order_id found, using latest order | order_id=%s",
                order["order_id"],
            )
        append_output(output_lines, print_success(f"Order ID: {order['order_id']} | Amount: ${order['amount']}"))

        # 4) Validate order belongs to customer
        if order.get("customer_id") != customer.get("customer_id"):
            raise Exception(
                f"Order ownership mismatch: {order.get('order_id')} does not belong to {customer.get('customer_id')}"
            )
        logging.info("Step 4: Order ownership validated")

        # 5) Get product from order
        append_output(output_lines, print_step("Fetching product..."))
        product = _call_tool_with_retry(ticket_id, steps, get_product, order["product_id"])
        steps.append("get_product")
        logging.info(
            "Step 5: Product resolved | product_id=%s | name=%s",
            product["product_id"],
            product["name"],
        )
        append_output(output_lines, print_success(f"Product: {product['name']}"))

        # 6) Classify ticket (refund / issue / general)
        append_output(output_lines, print_step("Classifying ticket..."))
        category = classify_ticket(ticket)
        steps.append(f"classify:{category}")
        logging.info("Step 6: Classified as %s", category)
        append_output(output_lines, print_detail("🧠", f"Category: {category}"))

        # 7) Take action
        append_output(output_lines, print_step("Taking action..."))
        ticket_text = _ticket_text(ticket).lower()
        reference_date = _ticket_reference_date(ticket)

        if category == "refund":
            if (
                "premium member" in ticket_text
                and customer.get("tier", "").lower() != "premium"
            ) or "instant refund" in ticket_text:
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_escalate,
                    ticket_id,
                    f"Potential social engineering attempt on {order['order_id']}: tier claim mismatch.",
                    "high",
                    output_lines=output_lines,
                )
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    "We could not verify the requested privilege. Your request will follow standard policy review.",
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                steps.append("escalate")
                logging.info("Potential social engineering flagged")
                decision = "flagged_policy_abuse"

            elif "cancel" in ticket_text:
                if order.get("status") == "processing":
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_send_reply,
                        ticket_id,
                        f"Your order {order['order_id']} has been cancelled successfully. You will receive email confirmation shortly.",
                        output_lines=output_lines,
                    )
                    steps.append("send_reply")
                    logging.info("Cancellation confirmed")
                    decision = "order_cancelled"
                elif order.get("status") == "shipped":
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_send_reply,
                        ticket_id,
                        f"Order {order['order_id']} is already shipped and cannot be cancelled. Please request a return after delivery.",
                        output_lines=output_lines,
                    )
                    steps.append("send_reply")
                    logging.info("Cancellation denied due to shipped status")
                    decision = "cancellation_denied_shipped"
                else:
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_send_reply,
                        ticket_id,
                        f"Order {order['order_id']} is already delivered and cannot be cancelled. We can still help with a return if eligible.",
                        output_lines=output_lines,
                    )
                    steps.append("send_reply")
                    logging.info("Cancellation denied due to delivered status")
                    decision = "cancellation_denied_delivered"

            elif order.get("refund_status") == "refunded":
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    f"Refund for order {order['order_id']} is already processed. It usually reflects in 5-7 business days.",
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                logging.info("Already-refunded confirmation sent")
                decision = "refund_already_processed"

            else:
                eligibility = _call_tool_with_retry(
                    ticket_id,
                    steps,
                    check_refund_eligibility,
                    order,
                    reference_date=reference_date,
                    customer=customer,
                    product=product,
                    ticket_text=ticket_text,
                )
                logging.info(
                    "Step 7: Refund eligibility checked | eligible=%s | reason=%s",
                    eligibility["eligible"],
                    eligibility["reason"],
                )
                steps.append("check_refund")
                append_output(output_lines, print_detail("🔍", f"Eligibility: {eligibility}"))

                defect_keywords = ["broken", "defect", "defective", "not working", "cracked"]
                wants_replacement = "replacement" in ticket_text
                is_defect_case = _contains_any(ticket_text, defect_keywords)

                if is_defect_case and not eligibility["eligible"] and _warranty_active(order, product, reference_date):
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_escalate,
                        ticket_id,
                        f"Warranty claim for {order['order_id']} ({product['name']}). Defect reported and warranty appears active.",
                        "medium",
                        output_lines=output_lines,
                    )
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_send_reply,
                        ticket_id,
                        "Your item appears to be under warranty. We have escalated this to our warranty team for priority handling.",
                        output_lines=output_lines,
                    )
                    steps.append("send_reply")
                    steps.append("escalate")
                    logging.info("Warranty claim escalated")
                    decision = "escalated_warranty"
                elif wants_replacement and is_defect_case:
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_escalate,
                        ticket_id,
                        f"Customer requested replacement for {order['order_id']} ({product['name']}).",
                        "medium",
                        output_lines=output_lines,
                    )
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_send_reply,
                        ticket_id,
                        "We have escalated your replacement request to our fulfilment specialist team.",
                        output_lines=output_lines,
                    )
                    steps.append("send_reply")
                    steps.append("escalate")
                    logging.info("Replacement request escalated")
                    decision = "escalated_replacement"
                elif eligibility["eligible"]:
                    if order.get("amount", 0) > 200:
                        _call_tool_with_retry(
                            ticket_id,
                            steps,
                            safe_escalate,
                            ticket_id,
                            f"Refund requires human approval: order {order['order_id']} amount ${order['amount']}",
                            "medium",
                            output_lines=output_lines,
                        )
                        _call_tool_with_retry(
                            ticket_id,
                            steps,
                            safe_send_reply,
                            ticket_id,
                            f"Your refund request for order {order['order_id']} is approved in principle and has been sent for final review.",
                            output_lines=output_lines,
                        )
                        steps.append("send_reply")
                        steps.append("escalate")
                        logging.info("High-value refund escalated for approval")
                        decision = "refund_escalated_for_approval"
                    else:
                        _call_tool_with_retry(
                            ticket_id,
                            steps,
                            safe_issue_refund,
                            order["order_id"],
                            order["amount"],
                            output_lines=output_lines,
                        )
                        steps.append("issue_refund")
                        _call_tool_with_retry(
                            ticket_id,
                            steps,
                            safe_send_reply,
                            ticket_id,
                            f"Your refund for order {order['order_id']} has been processed.",
                            output_lines=output_lines,
                        )
                        steps.append("send_reply")
                        logging.info("Refund issued and reply sent")
                        decision = "refund_issued"
                else:
                    _call_tool_with_retry(
                        ticket_id,
                        steps,
                        safe_send_reply,
                        ticket_id,
                        (
                            f"Refund request for order {order['order_id']} was denied: {eligibility['reason']}. "
                            "If needed, we can help with warranty or exchange options."
                        ),
                        output_lines=output_lines,
                    )
                    steps.append("send_reply")
                    logging.info("Refund denied reply sent")
                    decision = "refund_denied"

        elif category == "product_issue":
            issue_keywords = ["broken", "defect", "defective", "not working", "cracked", "damaged"]
            wants_replacement = "replacement" in ticket_text
            explicit_no_refund = "not a refund" in ticket_text
            wrong_item_keywords = ["wrong size", "wrong colour", "wrong color", "wrong item"]
            eligibility = _call_tool_with_retry(
                ticket_id,
                steps,
                check_refund_eligibility,
                order,
                reference_date=reference_date,
                customer=customer,
                product=product,
                ticket_text=ticket_text,
            )
            is_damage_on_arrival = (
                ("arrived" in ticket_text or "on arrival" in ticket_text)
                and _contains_any(ticket_text, ["damaged", "cracked", "broken"])
            )

            if _contains_any(ticket_text, wrong_item_keywords):
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    f"We can arrange a free exchange for order {order['order_id']}. If you prefer, we can also process a full refund.",
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                logging.info("Wrong-item exchange options sent")
                decision = "exchange_or_refund_offered"
            elif _contains_any(ticket_text, issue_keywords) and (wants_replacement or explicit_no_refund):
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_escalate,
                    ticket_id,
                    f"Replacement requested for order {order['order_id']} ({product['name']}).",
                    "medium",
                    output_lines=output_lines,
                )
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    "Your replacement request has been sent to our specialist team for immediate handling.",
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                steps.append("escalate")
                logging.info("Replacement issue escalated")
                decision = "escalated_replacement"
            elif is_damage_on_arrival and eligibility["eligible"]:
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_issue_refund,
                    order["order_id"],
                    order["amount"],
                    output_lines=output_lines,
                )
                steps.append("issue_refund")
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    f"We are sorry your item arrived damaged. A full refund for order {order['order_id']} has been issued.",
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                logging.info("Damage-on-arrival refund issued")
                decision = "damage_refund_issued"
            elif _contains_any(ticket_text, issue_keywords) and _warranty_active(order, product, reference_date):
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_escalate,
                    ticket_id,
                    f"Warranty investigation needed for order {order['order_id']} ({product['name']}).",
                    "medium",
                    output_lines=output_lines,
                )
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    "We have escalated your case to our warranty team for a repair/replacement decision.",
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                steps.append("escalate")
                logging.info("Warranty issue escalated")
                decision = "escalated_warranty"
            else:
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    (
                        f"We are sorry about the issue with {product['name']} "
                        f"(order {order['order_id']}). Our support team will help with replacement or resolution."
                    ),
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                logging.info("Product issue reply sent")
                decision = "product_issue_reply_sent"

        elif category == "general":
            if "where is" in ticket_text or "tracking" in ticket_text:
                tracking = "Not available"
                notes_text = order.get("notes", "")
                match = re.search(r"TRK-\d+", notes_text)
                if match:
                    tracking = match.group(0)
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    f"Your order {order['order_id']} is currently {order.get('status')}. Tracking number: {tracking}.",
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                logging.info("Order tracking reply sent")
                decision = "order_status_shared"
            elif "return policy" in ticket_text or "exchange" in ticket_text or "process" in ticket_text:
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    (
                        "For most products, return window is 30 days from delivery. "
                        "High-value electronics are 15 days, accessories are 60 days. "
                        "Exchanges are available for wrong size/colour/item subject to stock."
                    ),
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                logging.info("Policy guidance reply sent")
                decision = "policy_guidance_sent"
            else:
                _call_tool_with_retry(
                    ticket_id,
                    steps,
                    safe_send_reply,
                    ticket_id,
                    (
                        "Please share your order ID and whether you need a refund, replacement, or delivery support. "
                        "We will help you right away."
                    ),
                    output_lines=output_lines,
                )
                steps.append("send_reply")
                logging.info("Clarification reply sent")
                decision = "clarification_requested"

        else:
            _call_tool_with_retry(
                ticket_id,
                steps,
                safe_escalate,
                ticket_id,
                "Unable to classify ticket intent",
                "medium",
                output_lines=output_lines,
            )
            steps.append("escalate")
            logging.info("Unknown ticket escalated")
            decision = "escalated_unknown_intent"

        status = "success"
        confidence = score_confidence(steps, status)

        append_output(output_lines, print_detail("🎯", f"Action: {decision}"))
        append_output(output_lines, print_detail("📊", f"Confidence: {confidence.upper()}"))
        append_output(output_lines, print_separator())

    except Exception as exc:
        # 8) Handle errors -> escalate
        logging.exception("Step 8: Error while processing ticket %s", ticket_id)
        append_output(output_lines, print_detail("❌", f"Error: {exc}"))
        _call_tool_with_retry(
            ticket_id,
            steps,
            safe_escalate,
            ticket_id,
            str(exc),
            "high",
            output_lines=output_lines,
        )
        steps.append("escalate")
        status = "failed"
        confidence = score_confidence(steps, status)
        append_output(output_lines, print_detail("🎯", "Action: Escalated due to error"))
        append_output(output_lines, print_detail("📊", f"Confidence: {confidence.upper()}"))
        append_output(output_lines, print_separator())
        decision = "processing_failed"
        error_message = str(exc)
    finally:
        audit_entry = {
            "ticket_id": ticket_id,
            "steps": steps,
            "decision": decision,
            "confidence": confidence,
            "error": error_message,
        }
        append_audit_entry(audit_entry)
        flush_output(output_lines)

    return {
        "ticket_id": ticket_id,
        "status": status,
        "decision": decision,
        "confidence": confidence,
        "error": error_message,
    }


def _compute_max_workers(ticket_count):
    if ticket_count <= 1:
        return 1

    cpu_count = os.cpu_count() or 1
    return min(16, ticket_count, cpu_count * 5)


def main():
    setup_logging()

    try:
        tickets = load_tickets("data/tickets.json")
    except Exception:
        logging.exception("Failed to load tickets from data/tickets.json")
        return

    dead_letter_queue = DeadLetterQueue(DEAD_LETTER_FILE)
    max_workers = _compute_max_workers(len(tickets))
    logging.info(
        "Starting concurrent ticket processing | tickets=%s | workers=%s",
        len(tickets),
        max_workers,
    )

    results = process_tickets_in_parallel(tickets, process_ticket, max_workers)

    for result in results:
        if result.get("status") != "failed":
            continue

        if result.get("unhandled_worker_error"):
            append_audit_entry(
                {
                    "ticket_id": result.get("ticket_id", "UNKNOWN"),
                    "steps": ["escalate"],
                    "decision": "processing_failed",
                    "confidence": "low",
                    "error": result.get("error", "Unknown error"),
                }
            )

        dead_letter_queue.add(
            ticket_id=result.get("ticket_id", "UNKNOWN"),
            error=result.get("error", "Unknown error"),
        )

    dead_letter_queue.persist()

    # 9) Log everything
    successful = sum(1 for item in results if item.get("status") == "success")
    failed = len(results) - successful
    logging.info(
        "Completed processing %s tickets | success=%s | failed=%s",
        len(results),
        successful,
        failed,
    )
    print_structured_summary(results)


if __name__ == "__main__":
    main()