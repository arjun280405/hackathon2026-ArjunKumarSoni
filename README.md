# 🚀 Autonomous Support Resolution Agent (Agentic AI Hackathon 2026)
Demo Video Link: https://drive.google.com/file/d/1wEXhywqomlYzfcqoBi-N3SXO5ib-pjbC/view?usp=sharing
## 🧠 Problem Statement

Customer support systems are overloaded with repetitive queries (refunds, product issues, FAQs), yet most still rely on human intervention.

This project builds an **autonomous AI agent** that:

* Understands support tickets
* Takes real actions using tools
* Resolves issues end-to-end without human involvement

---

## ⚡ What Makes This Different

> ❌ Not a chatbot
> ✅ A real **agent that acts**

* Performs **multi-step reasoning**
* Uses **tool chaining (3+ calls per ticket)**
* Executes **real actions (refund, reply, escalate)**
* Handles failures like a production system

---

## 🏗️ Architecture Overview

```
Tickets → Agent (Decision Engine)
              ↓
     Tool Layer (Customer / Order / Product / KB)
              ↓
     Action Layer (Refund / Reply / Escalate)
              ↓
     Logging Layer (Audit Logs + Dead Letter Queue)
```

---

## 🔧 Tech Stack

* **Python**
* **Streamlit** (UI Dashboard)
* **Async / Concurrency**
* **JSON-based Mock APIs**

---

## 🚀 Key Features

### 🤖 Agentic Intelligence

* Multi-step decision making (not single LLM call)
* Dynamic reasoning based on ticket context
* Minimum **3+ tool calls per resolution**

### 🛠️ Tool Integration

* `get_customer()`
* `get_order()` / fallback to customer orders
* `get_product()`
* `check_refund_eligibility()`
* `issue_refund()`
* `send_reply()`
* `escalate()`

---

### ⚙️ Autonomous Actions

* Refund processing (with eligibility check)
* Customer response generation
* Smart escalation with context

---

### 🔁 Production Readiness

* ✅ Retry logic with backoff
* ✅ Failure handling (timeouts, invalid data)
* ✅ Dead Letter Queue for failed tickets
* ✅ Concurrency (parallel ticket processing)

---

### 📊 Explainability & Logging

* Full **audit trail per ticket**
* Logs include:

  * tool calls
  * decisions
  * confidence score
  * error handling

Example:

```json
{
  "ticket_id": "TKT-001",
  "steps": [
    "get_customer",
    "get_order",
    "get_product",
    "classify:refund",
    "check_refund",
    "issue_refund",
    "send_reply"
  ],
  "decision": "refund_issued",
  "confidence": "high"
}
```

---

### 🖥️ UI Dashboard

* Upload tickets.json
* Run agent in one click
* Live processing view
* Results + audit logs visualization

---

## ▶️ How to Run

### 1. Clone Repo

```bash
git clone https://github.com/your-username/hackathon2026-yourname.git
cd hackathon2026-yourname
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Run Agent (CLI)

```bash
python main.py
```

### 4. Run UI Dashboard

```bash
streamlit run ui_app.py
```

---

## 📁 Project Structure

```
hackathon2026/
├── main.py
├── ui_app.py
├── agent/
├── tools/
├── utils/
├── data/
├── logs/
│   ├── audit_log.json
│   ├── dead_letter.json
```

---

## ⚠️ Failure Modes & Handling

| Scenario         | Handling           |
| ---------------- | ------------------ |
| Tool timeout     | Retry + escalate   |
| Invalid customer | Escalate           |
| Refund failure   | Retry → fallback   |
| Missing order_id | Fetch latest order |

---

## 🎥 Demo

* Run the agent on 20 tickets
* Show refund, escalation, and logging
* Display audit logs for transparency

---

## 🏆 Why This Solution Stands Out

* Real **agentic architecture (not rule-based script)**
* Handles **uncertainty and failures**
* Fully **explainable decisions**
* Designed like a **production system**

---

## 🚀 Future Improvements

* LLM-based semantic classification
* Vector search for knowledge base
* Real API integrations
* Deployment with Docker

---

## 👨‍💻 Author

Hackathon 2026 Submission

---

> “Not just AI that talks — AI that acts.”
