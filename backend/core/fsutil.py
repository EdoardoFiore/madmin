"""
Filesystem helpers for the configuration files MADMIN generates.

atomic_write: a reader (BIND, dhcpd, charon, nginx, wg-quick) never sees a
half-written file, and a crash mid-write leaves the previous version intact.

ConfigSnapshot: captures a set of files before a change so that a failed
validation or reload can put back exactly what was there (including "the file
did not exist"), instead of leaving the service on a config it rejected.
"""
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, os.PathLike]


def atomic_write(path: PathLike, data: Union[str, bytes], mode: Optional[int] = None) -> None:
    """
    Replace `path` with `data` atomically (temp file in the same directory,
    fsync, rename).

    Mode and ownership of an existing file are kept (e.g. bind:bind on zone
    files); `mode` overrides the mode. A new file gets `mode`, or 0644. The
    temp file is created 0600, so a secret is never readable by others, not
    even for the instant before the final chmod.
    """
    path = Path(path)
    if isinstance(data, str):
        data = data.encode("utf-8")

    try:
        st = path.stat()
    except FileNotFoundError:
        st = None

    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if mode is None:
            mode = (st.st_mode & 0o7777) if st else 0o644
        os.chmod(tmp, mode)
        if st is not None and hasattr(os, "chown"):
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except PermissionError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class ConfigSnapshot:
    """
    Content, mode and owner of a set of files at construction time.

        snap = ConfigSnapshot([CONF, DEFAULTS])
        write(...)
        if not valid:
            snap.restore()

    Files that did not exist are removed by restore(). `globs` covers files
    whose names are not known up front (zone files): every match is saved,
    and a match created after the snapshot is removed on restore.
    """

    def __init__(self, paths: Iterable[PathLike] = (), globs: Iterable[Tuple[PathLike, str]] = ()):
        self._files: Dict[Path, Optional[Tuple[bytes, os.stat_result]]] = {}
        self._globs = [(Path(d), pattern) for d, pattern in globs]
        for d, pattern in self._globs:
            paths = [*paths, *d.glob(pattern)]
        for p in paths:
            p = Path(p)
            try:
                self._files[p] = (p.read_bytes(), p.stat())
            except FileNotFoundError:
                self._files[p] = None

    def restore(self) -> None:
        for d, pattern in self._globs:
            for p in d.glob(pattern):
                if p not in self._files:
                    self._files[p] = None
        for p, saved in self._files.items():
            try:
                if saved is None:
                    p.unlink(missing_ok=True)
                    continue
                data, st = saved
                atomic_write(p, data, mode=st.st_mode & 0o7777)
            except OSError:
                logger.exception(f"Could not restore {p}")
