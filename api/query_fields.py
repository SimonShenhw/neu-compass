"""Log a student's question by keyed hash and length, never by its text.

`query_log` keeps the text (export still needs both privacy switches); the operational log is a second
copy that gets read, pasted and shipped, so it holds only `<name>_hash` and `<name>_len`. The hash is an
HMAC-SHA256 under a key derived from `SESSION_SECRET`, so a short, guessable question cannot be confirmed
by hashing guesses. Someone who can read the log and also send questions can still ask the guess and look
for the same hash, so log access needs the same care as `query_log`. Whoever holds the key can hash a
`query_log.query` value and find its log lines; `query_log.written` gives the row id without the key.
Without a secret (local development, tests) a random per-process key is used: the hashes still repeat
within one process but cannot be matched against `query_log`.

中文：日志里只记学生问题的带密钥哈希和长度，不记原文。`query_log` 仍存原文（导出照旧要两个隐私开关）；
运行日志是会被翻看、粘贴、转发的第二份副本，所以只留 `<name>_hash`、`<name>_len`。哈希是 HMAC-SHA256，
密钥从 `SESSION_SECRET` 派生，拿猜的句子算哈希对不上。但能看日志、又能提问的人，可以把猜的句子问一遍，
再找相同的哈希，所以日志的访问要和 `query_log` 一样管住。有密钥的人可以对 `query_log.query` 算哈希，
找到对应的日志行；`query_log.written` 不用密钥也给出行号。没有配置密钥时（本地开发、测试）用每个进程随机的
密钥：同一进程里哈希仍然一致，但对不上 `query_log`。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from config import settings

HASH_CHARS = 16
_LABEL = b"neu-compass/log-query-hash/v1"
_PROCESS_KEY = secrets.token_bytes(32)


def _key() -> bytes:
    secret = settings.session_secret
    if not secret:
        return _PROCESS_KEY
    # A label-derived subkey: the session-token signer never sees this key, and this never signs tokens.
    # os.environ turns a stray byte into a surrogate; surrogatepass encodes any surrogate, so such a secret still
    # works and every valid secret gives the same bytes as before.
    # 中文：用标签派生的子密钥：会话令牌的签名不用它，它也不签令牌。环境变量里的坏字节会变成代理字符；
    # surrogatepass 能编码任何代理字符，所以这样的密钥也不会让请求失败，正常密钥的结果不变。
    return hmac.new(secret.encode("utf-8", "surrogatepass"), _LABEL, hashlib.sha256).digest()


def query_fields(text: str, name: str = "query") -> dict[str, object]:
    """`{name}_hash` (16 hex characters) and `{name}_len` (characters). Never raises on odd text or secrets.

    中文：返回 `{name}_hash`（16 位十六进制）和 `{name}_len`（字符数）；遇到奇怪的文字或密钥也不抛异常。
    """
    data = text.encode("utf-8", "surrogatepass")
    return {f"{name}_hash": hmac.new(_key(), data, hashlib.sha256).hexdigest()[:HASH_CHARS], f"{name}_len": len(text)}


__all__ = ["HASH_CHARS", "query_fields"]
