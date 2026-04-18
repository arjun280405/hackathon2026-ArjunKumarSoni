import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed


def load_tickets(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def process_tickets_in_parallel(tickets, process_ticket, max_workers):
    results = []

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ticket-worker") as executor:
        future_to_ticket = {
            executor.submit(process_ticket, ticket): ticket
            for ticket in tickets
        }

        for future in as_completed(future_to_ticket):
            ticket = future_to_ticket[future]
            ticket_id = ticket.get("ticket_id", "UNKNOWN")
            try:
                results.append(future.result())
            except Exception as exc:
                logging.exception("Unhandled worker error while processing ticket %s", ticket_id)
                results.append(
                    {
                        "ticket_id": ticket_id,
                        "status": "failed",
                        "decision": "processing_failed",
                        "confidence": "low",
                        "error": str(exc),
                        "unhandled_worker_error": True,
                    }
                )

    return results


def print_structured_summary(results):
    success_count = sum(1 for result in results if result.get("status") == "success")
    summary = {
        "total": len(results),
        "success": success_count,
        "failed": len(results) - success_count,
    }
    print("\nRun Summary:")
    print(json.dumps(summary, indent=4))
