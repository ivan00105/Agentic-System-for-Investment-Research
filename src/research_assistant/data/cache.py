"""A small disk cache shared by every data provider: one body file and one metadata file per key."""
import contextlib
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

LOG = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def get(self, key: str, max_age: timedelta | None) -> tuple[bytes, datetime] | None:
        """The cached body and when it was first retrieved, or None. `max_age=None` never expires."""
        body_path, meta_path = self._paths(key)
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
            retrieved_at = datetime.fromisoformat(meta["retrieved_at"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        # A hash mismatch means a torn or concurrent write: treat it as a miss.
        if meta.get("key") != key or meta.get("sha256") != hashlib.sha256(body).hexdigest():
            return None
        if max_age is not None and datetime.now(timezone.utc) - retrieved_at > max_age:
            return None
        return body, retrieved_at

    def put(self, key: str, body: bytes, retrieved_at: datetime):
        body_path, meta_path = self._paths(key)
        meta = {"key": key, "retrieved_at": retrieved_at.isoformat(), "sha256": hashlib.sha256(body).hexdigest()}
        # Body first, then metadata; each replaced atomically so readers never see half a file.
        for path, data in ((body_path, body), (meta_path, json.dumps(meta).encode())):
            temporary = path.parent / f"{path.name}.{uuid4().hex}.tmp"
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(data)
                os.replace(temporary, path)
            except OSError as exc:
                # The data was fetched fine, so a cache problem must not fail the caller.
                LOG.warning("Cache write failed for %s: %s", key, exc)
                # Best-effort cleanup. Linux raises NotADirectoryError (not FileNotFoundError) when the
                # cache folder is a file, so missing_ok alone is not enough.
                with contextlib.suppress(OSError):
                    temporary.unlink()
                return

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = hashlib.sha256(key.encode()).hexdigest()
        return self.root / f"{digest}.body", self.root / f"{digest}.json"
