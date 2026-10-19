"""Process audit hook with a serial, context-owned activation window; no external I/O.
中文：钩子只注册一次；按合成世界作用域启停，跨 TestClient 线程保护并计数。
"""

from __future__ import annotations

import importlib.abc
import os
import sqlite3
import sys
import threading
from pathlib import Path

_ACTIVE = None
_INSTALLED = False
_OPENING = threading.local()  # set while guarded_connect opens a connection in this thread
_MODELS = {"torch", "transformers", "FlagEmbedding", "sentence_transformers", "google", "openvino", "onnxruntime"}
_NETWORK = {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto", "socket.sendmsg",
            "socket.gethostbyname", "socket.gethostbyaddr"}
_PROCESS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork", "os.forkpty", "os.spawn", "os.startfile"}
_FILE_CHANGE = {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.truncate", "os.chmod",
                "os.chown", "os.utime", "shutil.rmtree"}
_SQLITE_EXTENSION = {"sqlite3.enable_load_extension", "sqlite3.load_extension"}


class OfflineViolation(RuntimeError):
    pass


def deny_attach(action, *args):
    """Authorizer for every connection opened inside a world: no ATTACH/DETACH of a file.
    中文：合成世界里每个连接的授权器：不能 ATTACH/DETACH 文件。"""
    if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
        if _ACTIVE is not None:
            _ACTIVE.counters["database_attempts"] += 1
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def guarded_connect(original):
    """The only way to open SQLite inside a world: `original` (sqlite3.connect) plus deny_attach on the result.

    The audit hook refuses and counts any other new connection while a world is active (sqlite3.dbapi2.connect,
    sqlite3.Connection(...), _sqlite3.connect, a reference saved before the world), because SQLite reads an attached
    file through its own VFS, where the `open` rule cannot see it. Connections opened before the world are not covered.
    中文：合成世界里打开 SQLite 的唯一途径：原 sqlite3.connect，再给结果装上 deny_attach。其他方式新开的连接
    （dbapi2.connect、Connection(...)、_sqlite3.connect、提前保存的函数）都会被审计钩子拒绝并计数；世界之前打开的连接
    不在范围内。
    """
    def connect(*args, **kwargs):
        _OPENING.active = True
        try:
            handle = original(*args, **kwargs)
        finally:
            _OPENING.active = False
        handle.set_authorizer(deny_attach)
        return handle

    return connect


def _audit(event, args):
    guard = _ACTIVE
    if guard is None:
        return
    if event == "sqlite3.connect" and args[0] != ":memory:":
        guard.deny("database_attempts")
    if event == "sqlite3.connect/handle" and not getattr(_OPENING, "active", False):
        guard.deny("database_attempts")
    if event in _SQLITE_EXTENSION:
        guard.deny("database_attempts")
    if event in _NETWORK:
        guard.deny("network_attempts")
    if event in _PROCESS:
        guard.deny("process_attempts")
    if event in _FILE_CHANGE:
        guard.deny("file_attempts")
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes, os.PathLike)):
            target = Path(os.fsdecode(path)).resolve()
            if target.name == ".env" or target.name.startswith(".env."):
                guard.deny("file_attempts")
            if target.suffix.lower() in {".onnx", ".safetensors", ".pt", ".pth", ".bin", ".faiss"}:
                guard.deny("file_attempts")
            if any(target.is_relative_to(directory) for directory in (guard.data_dir, *guard.protected)):
                guard.deny("file_attempts")
        if (mode and any(char in mode for char in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            guard.deny("file_attempts")


class _ModelBlock(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if _ACTIVE is not None and fullname.split(".")[0] in _MODELS:
            _ACTIVE.deny("model_attempts")


class OfflineGuard:
    def __init__(self, data_dir, *, protected=()):
        self.data_dir = data_dir.resolve()
        # The configured real database and index (a file, or the index directory and everything under it).
        # 中文：配置里的真实库文件和索引（文件，或索引目录及其下所有内容）。
        self.protected = tuple(Path(path).expanduser().resolve() for path in protected)
        self.counters = {name: 0 for name in ("database_attempts", "network_attempts", "model_attempts", "file_attempts", "process_attempts")}

    def deny(self, category):
        self.counters[category] += 1
        raise OfflineViolation(f"forbidden offline action: {category}")

    def __enter__(self):
        global _ACTIVE, _INSTALLED
        if _ACTIVE is not None:
            raise RuntimeError("synthetic worlds must run serially, without nesting")
        if not _INSTALLED:
            sys.addaudithook(_audit)
            sys.meta_path.insert(0, _ModelBlock())
            _INSTALLED = True
        self.previous_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        _ACTIVE = self
        return self

    def __exit__(self, *exc):
        global _ACTIVE
        _ACTIVE = None
        sys.dont_write_bytecode = self.previous_bytecode
