import logging
import time


def call_with_retry(func, *args, retries=3, base_delay_seconds=0.2, on_retry=None, **kwargs):
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                raise

            delay_seconds = base_delay_seconds * (2 ** (attempt - 1))
            logging.warning(
                "Failure in %s (attempt %s/%s): %s | retrying in %.2fs",
                getattr(func, "__name__", "tool_call"),
                attempt,
                retries,
                exc,
                delay_seconds,
            )
            if on_retry is not None:
                on_retry(attempt, exc, delay_seconds)
            time.sleep(delay_seconds)

    raise last_error