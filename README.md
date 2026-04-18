# Autonomous Support Agent

## Problem

Build an autonomous support agent that can process customer tickets at scale, resolve common cases using tools, and safely escalate failures without stopping the overall system.

## Architecture

- `main.py`: Entry point for single-command execution.
- `agent/`: Orchestration modules (`demo_runner`, `dead_letter_queue`, `confidence`).
- `tools/`: Domain tools (`get_customer`, `get_order`, `get_product`, actions, retry utilities).
- `utils/`: Shared infrastructure helpers (`json_store`).
- `data/`: Input datasets (`tickets.json`, customers, products, orders).
- `logs/`: Runtime outputs (`audit_log.json`, `dead_letter.json`, `agent.log`).

## Features

- Concurrent ticket processing with isolated per-ticket failure handling.
- Reusable retry logic with exponential backoff for tool calls.
- Dead letter queue for failed tickets (`ticket_id`, `error`).
- Confidence scoring in audit logs:
  - `high`: all tool calls succeeded
  - `medium`: retries/fallback behavior occurred
  - `low`: escalation or error
- Structured run summary output at the end of execution.

## Run

```bash
python main.py
```

## Outputs

- `logs/audit_log.json`: Per-ticket steps, decision, confidence, and error.
- `logs/dead_letter.json`: Failed tickets captured for later reprocessing.
- `logs/agent.log`: Execution logs.
