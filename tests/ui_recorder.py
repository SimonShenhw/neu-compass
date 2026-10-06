"""A Streamlit stand-in that records where each element lands (shared by UI tests).

Calls on the root follow the active `with` block, like Streamlit's module functions; calls on an
expander object write into that expander. Each log entry is (kind, value, expander path).

中文：记录每个元素落在哪个折叠区里的 Streamlit 替身（UI 测试共用）。在根对象上调用时跟随
当前的 `with` 块，和 Streamlit 的模块函数一样；在折叠区对象上调用时写进那个折叠区。
每条记录是（类型，值，折叠区路径）。
"""

from __future__ import annotations


class Recorder:
    def __init__(self, shared=None, path=None, *, choice=None):
        self.shared = shared or {"log": [], "stack": [()], "state": {}, "choice": choice}
        self.path = path
        self.session_state = self.shared["state"]

    def _where(self):
        return self.path if self.path is not None else self.shared["stack"][-1]

    def _add(self, kind, value):
        self.shared["log"].append((kind, value, self._where()))

    def markdown(self, value, **kwargs):
        self._add("markdown", value)

    def caption(self, value, **kwargs):
        self._add("caption", value)

    def text(self, value):
        self._add("text", value)

    def code(self, value, **kwargs):
        self._add("code", value)

    def warning(self, value):
        self._add("warning", value)

    def selectbox(self, label, options, **kwargs):
        self._add("selectbox", label)
        assert self.shared["choice"] in options
        return self.shared["choice"]

    def button(self, label, **kwargs):
        self._add("button", label)
        return False

    def expander(self, label, **kwargs):
        self._add("expander", label)
        return Recorder(self.shared, self._where() + (label,))

    def __enter__(self):
        self.shared["stack"].append(self._where())
        return self

    def __exit__(self, *exc):
        self.shared["stack"].pop()
        return False

    @property
    def log(self):
        return self.shared["log"]

    def at(self, path=()):
        """Entries written exactly at this expander path."""
        return [entry for entry in self.log if entry[2] == tuple(path)]

    def under(self, label):
        """Entries inside the expander with this label (at any depth below it)."""
        return [entry for entry in self.log if label in entry[2]]
