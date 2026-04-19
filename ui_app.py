import streamlit as st
import json
from pathlib import Path

from main import process_ticket, setup_logging
from utils.json_store import load_json

st.set_page_config(page_title="AI Agent Dashboard", layout="wide")

st.title("🤖 AI Support Agent Dashboard")

setup_logging()

if "results" not in st.session_state:
    st.session_state.results = []

col1, col2 = st.columns(2)

# Upload tickets
with col1:
    uploaded_file = st.file_uploader("📂 Upload tickets.json", type="json")

# Run button
with col2:
    run = st.button("🚀 Run Agent")

if uploaded_file and run:
    tickets = json.load(uploaded_file)

    st.info(f"Processing {len(tickets)} tickets...")

    progress = st.progress(0)

    results = []

    for i, ticket in enumerate(tickets):
        try:
            run_result = process_ticket(ticket)
            results.append({
                "Ticket": ticket["ticket_id"],
                "Status": "✅ Done" if run_result.get("status") == "success" else "❌ Failed",
                "Decision": run_result.get("decision", "unknown"),
                "Confidence": run_result.get("confidence", "unknown"),
                "Error": run_result.get("error"),
            })
        except Exception as e:
            results.append({
                "Ticket": ticket["ticket_id"],
                "Status": f"❌ {str(e)}",
                "Decision": "processing_failed",
                "Confidence": "low",
                "Error": str(e),
            })

        progress.progress((i + 1) / len(tickets))

    st.session_state.results = results

    st.success("Processing Completed!")

results = st.session_state.results

if results:
    st.subheader("📊 Ticket Results")

    status_filter = st.selectbox("Filter", ["All", "Success", "Error"])

    filtered = results
    if status_filter == "Success":
        filtered = [r for r in results if "✅" in r["Status"]]
    elif status_filter == "Error":
        filtered = [r for r in results if "❌" in r["Status"]]

    st.dataframe(filtered)

    success = sum(1 for r in results if "✅" in r["Status"])
    errors = len(results) - success

    m1, m2 = st.columns(2)
    with m1:
        st.metric("✅ Success", success)
    with m2:
        st.metric("❌ Errors", errors)

    st.subheader("📜 Audit Logs")
    audit_logs = load_json(Path("logs") / "audit_log.json", default=[])
    st.json(audit_logs)

    st.subheader("📦 Dead Letter Queue")
    dead_letter = load_json(Path("logs") / "dead_letter.json", default=[])
    st.json(dead_letter)
else:
    st.caption("Upload a tickets JSON file and click Run Agent to start processing.")