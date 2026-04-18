import threading


_PRINT_LOCK = threading.Lock()


def send_reply(ticket_id, message):
    with _PRINT_LOCK:
        print(f"[Reply Sent] Ticket {ticket_id}: {message}")


def issue_refund(order_id, amount):
    with _PRINT_LOCK:
        print(f"[Refund Issued] Order {order_id}: ${amount}")


def escalate(ticket_id, summary, priority="high"):
    with _PRINT_LOCK:
        print(f"[Escalated] Ticket {ticket_id} | Priority: {priority}")
        print("Summary:", summary)