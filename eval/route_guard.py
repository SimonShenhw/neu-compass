"""Process audit hook with a serial, context-owned activation window; no external I/O.
中文：钩子只注册一次；按合成世界作用域启停，跨 TestClient 线程保护并计数。
"""

from __future__ import annotations

import importlib.abc
import os
import sys
from pathlib import Path

_ACTIVE = None
_INSTALLED = False
_MODELS = {"torch", "transformers", "FlagEmbedding", "sentence_transformers", "google", "openvino", "onnxruntime"}


class OfflineViolation(RuntimeError):
    pass


def _audit(event, args):
    guard = _ACTIVE
    if guard is None:
        return
    if event == "sqlite3.connect" and args[0] != ":memory:":
        guard.deny("database_attempts")
    if event in {"socket.connect", "socket.getaddrinfo"}:
        guard.deny("network_attempts")
    if event in {"subprocess.Popen", "os.system"}:
        guard.deny("process_attempts")
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.truncate"}:
        guard.deny("file_attempts")
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes, os.PathLike)):
            target = Path(os.fsdecode(path)).resolve()
            if target.name == ".env" or target.name.startswith(".env."):
                guard.deny("file_attempts")
            if target.suffix.lower() in {".onnx", ".safetensors", ".pt", ".pth", ".bin", ".faiss"}:
                guard.deny("file_attempts")
            if target.is_relative_to(guard.data_dir):
                guard.deny("file_attempts")
        if (mode and any(char in mode for char in "wax+")) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            guard.deny("file_attempts")


class _ModelBlock(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if _ACTIVE is not None and fullname.split(".")[0] in _MODELS:
            _ACTIVE.deny("model_attempts")


class OfflineGuard:
    def __init__(self, data_dir):
        self.data_dir = data_dir.resolve()
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
