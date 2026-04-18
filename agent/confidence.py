def score_confidence(steps, status):
    if status != "success":
        return "low"

    if "escalate" in steps:
        return "low"

    if any(step.startswith("retry:") for step in steps):
        return "medium"

    return "high"
