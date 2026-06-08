"""Crash-safe TinyDB storage: atomic whole-file writes via temp file + os.replace.

The stock ``JSONStorage`` truncates and rewrites ``db.json`` in place, so a crash
mid-write corrupts the entire database (all tables). This storage writes to a temp
file on the *same directory/volume* and atomically ``os.replace()``s it onto the
target, so a reader/observer always sees either the old or the new complete file —
never a truncated one. It keeps no long-lived file handle, which also avoids the
stale-inode problem an atomic-rename approach would otherwise hit.
"""

import json
import os
import tempfile
import time

from tinydb.storages import Storage, touch


class AtomicJSONStorage(Storage):
    """JSON storage that persists atomically (temp file + os.replace)."""

    def __init__(self, path, create_dirs=False, encoding='utf-8', **kwargs):
        super().__init__()
        self._path = path
        self._encoding = encoding
        # Remaining kwargs (indent, ensure_ascii, ...) are forwarded to json.dump,
        # matching how TinyDB passes them through to the storage.
        self._dump_kwargs = kwargs
        touch(path, create_dirs=create_dirs)

    def read(self):
        with open(self._path, 'r', encoding=self._encoding) as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                return None  # empty file -> empty database
            handle.seek(0)
            return json.load(handle)

    def write(self, data):
        directory = os.path.dirname(self._path) or '.'
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.db-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding=self._encoding) as handle:
                json.dump(data, handle, **self._dump_kwargs)
                handle.flush()
                os.fsync(handle.fileno())
            self._replace_with_retry(tmp_path, self._path)  # atomic swap
            self._fsync_dir(os.path.dirname(self._path) or '.')
        except BaseException:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _fsync_dir(directory):
        """Best-effort fsync of the directory so the rename is durable (POSIX).

        No-op on platforms (e.g. Windows) where a directory fd can't be opened.
        """
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except (OSError, AttributeError):
            pass

    @staticmethod
    def _replace_with_retry(src, dst, attempts=5, delay=0.1):
        """os.replace, retrying transient Windows locks (AV/indexer hold WinError 5/32).

        os.replace is atomic; the retry only covers the brief window where another
        process has a handle open. Re-raises the last error if all attempts fail.
        """
        for i in range(attempts):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if i == attempts - 1:
                    raise
                time.sleep(delay * (i + 1))

    def close(self):
        pass
