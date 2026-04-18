import logging
import threading
from pathlib import Path

from utils.json_store import load_json, save_json


class DeadLetterQueue:
    def __init__(self, file_path):
        self.file_path = Path(file_path)
        self._lock = threading.Lock()
        self._entries = self._load_entries()

    def _load_entries(self):
        try:
            data = load_json(self.file_path, default=[])
            if isinstance(data, list):
                return data
            return []
        except Exception:
            logging.exception("Failed to load dead letter queue file %s", self.file_path)
            return []

    def add(self, ticket_id, error):
        with self._lock:
            self._entries.append(
                {
                    "ticket_id": ticket_id,
                    "error": str(error),
                }
            )

    def persist(self):
        try:
            with self._lock:
                save_json(self.file_path, self._entries)
        except Exception:
            logging.exception("Failed to persist dead letter queue to %s", self.file_path)
