"""The keyed hash behind `api.query_fields`, without reading settings.

`query_fields` (K) logs a question as an HMAC-SHA256 under a key derived from `SESSION_SECRET`. The query_log
retention (batch T) stores the same hash in place of a row's expired text, so a log line and its row still match.
Both use this module, which needs no settings, so a process without the full app configuration can import it too.

中文：`api.query_fields` 背后的带密钥哈希，不读取设置。K 把问题记成 HMAC-SHA256，密钥从 `SESSION_SECRET` 派生；
query_log 的到期清理（T 批）把同一个哈希存进到期行、替换原文，所以日志行和这一行仍然对得上。两边都用这个模块，
它不需要设置，没有完整应用配置的进程也能导入。
"""

from __future__ import annotations

import hashlib
import hmac

HASH_CHARS = 16
_LABEL = b"neu-compass/log-query-hash/v1"


def derive_key(secret: str) -> bytes:
    """The hash key for a non-empty `SESSION_SECRET`.

    A label-derived subkey: the session-token signer never sees this key, and this never signs tokens.
    os.environ turns a stray byte into a surrogate; surrogatepass encodes any surrogate, so such a secret still
    works and every valid secret gives the same bytes as before.
    中文：用标签派生的子密钥：会话令牌的签名不用它，它也不签令牌。环境变量里的坏字节会变成代理字符；
    surrogatepass 能编码任何代理字符，所以这样的密钥也不会让请求失败，正常密钥的结果不变。
    """
    return hmac.new(secret.encode("utf-8", "surrogatepass"), _LABEL, hashlib.sha256).digest()


def keyed_hash(text: str, key: bytes) -> str:
    """16 hex characters; never raises on odd text. 中文：16 位十六进制；遇到奇怪的文字也不抛异常。"""
    return hmac.new(key, text.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()[:HASH_CHARS]


__all__ = ["HASH_CHARS", "derive_key", "keyed_hash"]
