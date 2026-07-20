"""Gemini 2.5 Flash client wrapper (google.genai SDK).

Migrated from `google.generativeai` (deprecated) per PLAN v2.3 §3.5.

从 `google.generativeai`(已废弃)迁移而来,依据 PLAN v2.3 §3.5。

Schema-stripping is still required:
The new SDK has its own bug — when you pass a Pydantic class as
`response_schema`, the SDK serializes it to a protobuf payload that
includes `additional_properties` (snake_case), and Gemini's API rejects
that field with INVALID_ARGUMENT. We sidestep this by going through a
dict path: `pydantic_to_gemini_schema(model)` returns a stripped dict
that the SDK ships verbatim (no re-serialization), so we control the
exact wire format. The strip list is the same as for the old SDK
(both surfaces reject OpenAPI-3-incompatible JSON-Schema-2020 keywords),
which is why the helper survives the migration.

仍然需要做 schema 剥离:
新 SDK 有自己的 bug —— 当你把一个 Pydantic 类作为 `response_schema`
传入时,SDK 会把它序列化成一个包含 `additional_properties`(下划线
命名)的 protobuf payload,而 Gemini 的 API 会以 INVALID_ARGUMENT 拒绝
这个字段。我们绕开这个问题的方式是走一条 dict 路径:
`pydantic_to_gemini_schema(model)` 返回一个剥离过的 dict,SDK 会原样
发送(不再重新序列化),这样我们就能完全掌控实际发出的格式。剥离
列表与旧 SDK 用的相同(新旧两个接口都会拒绝与 OpenAPI-3 不兼容的
JSON-Schema-2020 关键字),这正是这个辅助函数能在迁移后继续存活的
原因。

Design choice: generate_structured() accepts an explicit `client` parameter
so tests can pass a fake without monkey-patching globals. The default factory
_build_default_client() reads settings.gemini_api_key.

设计选择:generate_structured() 接受一个显式的 `client` 参数,这样测试
可以直接传入一个假实现,而不需要 monkey-patch 全局对象。默认的工厂
函数 _build_default_client() 读取 settings.gemini_api_key。

Cost discipline (PLAN §8 budget): caller is responsible for managing prompt
length + retries. This wrapper does NOT auto-retry on quota errors — Gemini
quota retries cost real money. Caller logs + decides.

成本纪律(PLAN §8 预算):调用方负责管理 prompt 长度和重试。这个包装类
不会在配额错误上自动重试 —— Gemini 的配额重试是真金白银的开销。由
调用方记录日志并自行决定。
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.2  # low for extraction; high for creative tasks
# 中文:提取任务用低温;创造性任务用高温。
DEFAULT_MAX_OUTPUT_TOKENS = 16384  # Week 7 §3.2: 8192 truncated CS 5800 mid-JSON
# 中文:第 7 周 §3.2:8192 曾把 CS 5800 截断在 JSON 中间。


class GeminiError(Exception):
    """Wrapped error from Gemini API call or response parsing.

    中文:包装 Gemini API 调用或响应解析过程中的错误。
    """


class _ModelsLike(Protocol):
    """Subset of google.genai client.models we need.

    中文:我们需要用到的 google.genai client.models 子集。
    """

    def generate_content(
        self,
        *,
        model: str,
        contents: Any,
        config: Any | None = ...,
    ) -> Any: ...

    def generate_content_stream(
        self,
        *,
        model: str,
        contents: Any,
        config: Any | None = ...,
    ) -> Any: ...


class _ClientLike(Protocol):
    models: _ModelsLike


# Hard ceiling on any single Gemini HTTP round-trip (milliseconds — the SDK's
# HttpOptions unit). Without it a hung call holds the request slot forever;
# /chat streams stay well under this, and extraction calls that exceed it are
# better surfaced as GeminiError than waited on.
# 中文:对单次 Gemini HTTP 往返的硬性上限(单位毫秒 —— SDK 的 HttpOptions
# 用的单位)。没有它,一次卡住的调用会永远占着请求名额;/chat 的流式
# 输出远低于这个值,而超出它的抽取调用最好是被抛出 GeminiError,而不是
# 被一直等下去。
DEFAULT_HTTP_TIMEOUT_MS = 120_000


@lru_cache(maxsize=4)
def _build_client_with_timeout(timeout_ms: int) -> _ClientLike:
    """Lazy: import SDK + build Client on first use; one cached client per
    distinct timeout (the SDK sets timeout at client construction, not per
    call). maxsize=4 — in practice two values exist: the 120s default and
    the short rescue budget.

    中文:懒加载:首次使用时才 import SDK 并构建 Client;每个不同的
    timeout 值缓存一个 client(SDK 在构造 client 时设置超时,而不是
    按次调用设置)。maxsize=4 —— 实践中只会出现两个值:120 秒的默认值
    和 rescue 用的短预算。
    """
    from google import genai  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    from config import settings  # noqa: PLC0415

    return genai.Client(  # type: ignore[return-value]
        api_key=settings.gemini_api_key,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )


def _build_default_client() -> _ClientLike:
    return _build_client_with_timeout(DEFAULT_HTTP_TIMEOUT_MS)


# Schema keywords Gemini's Schema proto doesn't accept. Pydantic v2's
# model_json_schema() emits these for Field(min_length=...) / Field(pattern=...)
# / nested-model $refs / etc — passing them through trips
# `Unknown name "<key>": Cannot find field` from the API (or its protobuf layer).
# Both google.generativeai (old) and google.genai (new) reject the same set
# at the wire level, so the strip list survives the SDK migration.
# 中文:Gemini 的 Schema proto 不接受这些 schema 关键字。Pydantic v2 的
# model_json_schema() 会为 Field(min_length=...) / Field(pattern=...) /
# 嵌套模型的 $ref 等生成这些关键字 —— 直接透传会触发 API(或其 protobuf
# 层)报错 `Unknown name "<key>": Cannot find field`。google.generativeai
# (旧)和 google.genai(新)在协议层拒绝的是同一批关键字,所以这份剥离
# 列表能在 SDK 迁移后继续沿用。
_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset({
    "minLength", "maxLength", "pattern",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "additionalProperties", "propertyNames", "patternProperties",
    "uniqueItems", "contains", "minContains", "maxContains",
    "$schema", "$id", "title",  # title harmless but cleaner to drop at top level
    # 中文:title 本身无害,但在顶层丢弃更干净。
    "const", "default",  # Gemini Schema doesn't model these
    # 中文:Gemini 的 Schema 模型不支持这两个概念。
})


def _resolve_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Inline Pydantic's $ref pointers using its $defs table.

    Pydantic v2 emits `{"$ref": "#/$defs/Name"}` for nested-model references.
    Gemini's Schema proto has no $ref concept; it requires fully-inlined trees.
    Cycles aren't expected for the schemas we send (Course / Alias / Coop are
    DAGs); we don't guard against them here.

    中文:用 $defs 表把 Pydantic 的 $ref 指针内联展开。
    Pydantic v2 为嵌套模型引用生成 `{"$ref": "#/$defs/Name"}`。Gemini 的
    Schema proto 没有 $ref 概念,要求完全内联的树。我们发送的 schema
    (Course / Alias / Coop 都是 DAG)预期不会出现环,这里没有做防护。
    """
    if isinstance(node, dict):
        if "$ref" in node and len(node) == 1:
            ref_name = node["$ref"].split("/")[-1]
            return _resolve_refs(defs.get(ref_name, {}), defs)
        return {k: _resolve_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_resolve_refs(x, defs) for x in node]
    return node


def _strip_unsupported(node: Any, *, in_properties_map: bool = False) -> Any:
    """Drop schema keywords Gemini doesn't accept; collapse Pydantic-style
    union encodings into Gemini's `nullable` form.

    Three Pydantic patterns we normalize:
      - `Optional[T]` → `{anyOf: [{type:T}, {type:"null"}]}` → `{type:T, nullable:True}`
      - JSON-Schema-2020 nullable → `{type:["foo","null"]}` → `{type:"foo", nullable:True}`
      - Multiple non-null variants in `anyOf` → first one (lossy; our schemas
        don't actually use sum types beyond Optional, so this branch is
        defensive rather than load-bearing).

    Context-aware: when `in_properties_map=True`, dict keys are property
    NAMES (e.g. a Textbook model has a property literally called `title`),
    not schema keywords — so the keyword blacklist is suppressed at that
    level. Without this, stripping `title` as metadata also nuked the
    `title` data field, leaving `required: ["title"]` dangling and Gemini
    complaining `property is not defined`.

    After the per-node strip, we also prune `required` entries that no
    longer have a corresponding `properties` key (defense in depth).

    中文:丢弃 Gemini 不接受的 schema 关键字;把 Pydantic 风格的联合类型
    编码折叠成 Gemini 的 `nullable` 形式。
    我们规范化的三种 Pydantic 模式:
      - `Optional[T]` → `{anyOf: [{type:T}, {type:"null"}]}` →
        `{type:T, nullable:True}`
      - JSON-Schema-2020 的 nullable → `{type:["foo","null"]}` →
        `{type:"foo", nullable:True}`
      - `anyOf` 里有多个非 null 变体 → 取第一个(有损;我们的 schema
        除 Optional 外实际不用 sum type,所以这个分支是防御性的,而非
        承重的)。

    有上下文感知:当 `in_properties_map=True` 时,dict 的键是属性名
    (比如 Textbook 模型可能就有一个叫 `title` 的属性),而不是 schema
    关键字 —— 所以这一层会暂停关键字黑名单。没有这个判断,把 `title`
    当元数据剥离时也会连带干掉 `title` 这个数据字段,留下悬空的
    `required: ["title"]`,Gemini 会报错 `property is not defined`。

    对每个节点做完剥离后,我们还会修剪掉那些不再有对应 `properties`
    键的 `required` 条目(纵深防御)。
    """
    if isinstance(node, dict):
        # Collapse `anyOf` BEFORE generic recursion. Both old and new Gemini
        # Schema surfaces reject `anyOf` outright.
        # 中文:在通用递归之前先折叠 `anyOf`。新旧两个 Gemini Schema 接口
        # 都会直接拒绝 `anyOf`。
        if "anyOf" in node and not in_properties_map:
            variants = node["anyOf"]
            non_null = [
                v for v in variants
                if not (isinstance(v, dict) and v.get("type") == "null")
            ]
            has_null = len(non_null) < len(variants)
            if non_null:
                base = _strip_unsupported(non_null[0])
                if not isinstance(base, dict):
                    base = {"type": "string"}
                if has_null:
                    base["nullable"] = True
                if "description" in node and "description" not in base:
                    base["description"] = node["description"]
                return base
            return {"type": "string", "nullable": True}

        cleaned: dict[str, Any] = {}
        for k, v in node.items():
            # Inside a properties map, k is a property name — don't blacklist.
            # 中文:身处 properties 映射内部时,k 是属性名 —— 不做黑名单过滤。
            if not in_properties_map and k in _GEMINI_UNSUPPORTED_SCHEMA_KEYS:
                continue
            if not in_properties_map and k == "type" and isinstance(v, list):
                non_null_types = [t for t in v if t != "null"]
                cleaned["type"] = non_null_types[0] if non_null_types else "string"
                if "null" in v:
                    cleaned["nullable"] = True
                continue
            cleaned[k] = _strip_unsupported(
                v, in_properties_map=(k == "properties" and not in_properties_map),
            )

        # Prune dangling `required` entries (defense: should be moot now that
        # properties keys aren't blacklisted, but a Pydantic schema with
        # exclude_*-style trickery could still produce this gap).
        # 中文:修剪悬空的 `required` 条目(防御性的:既然属性名已经不再
        # 被拉黑,理论上不该再出现这个缺口,但用了 exclude_* 之类技巧的
        # Pydantic schema 仍可能产生这种情况)。
        if "required" in cleaned and "properties" in cleaned:
            valid = set(cleaned["properties"].keys())
            cleaned["required"] = [r for r in cleaned["required"] if r in valid]
            if not cleaned["required"]:
                del cleaned["required"]

        return cleaned
    if isinstance(node, list):
        return [_strip_unsupported(x) for x in node]
    return node


def pydantic_to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Convert a Pydantic model class into a dict the Gemini SDK accepts as
    `response_schema`.

    Why not pass the Pydantic class directly: both old and new SDKs
    re-serialize Pydantic schemas in ways the API rejects (old SDK chokes
    on `minLength`/`pattern`/etc inside its Schema proto; new SDK emits
    `additional_properties` (snake_case) at the protobuf layer that the
    API rejects with INVALID_ARGUMENT). Going through a stripped dict
    bypasses both bugs.

    The returned dict still validates the LLM's reply via
    `schema.model_validate_json` downstream, so the constraints we strip
    here from the prompt schema are still enforced when we PARSE the response.

    中文:把一个 Pydantic 模型类转换成 Gemini SDK 能接受的 `response_schema`
    dict。
    为什么不直接传 Pydantic 类:新旧两个 SDK 都会以 API 拒绝的方式重新
    序列化 Pydantic schema(旧 SDK 在其 Schema proto 内部处理
    `minLength`/`pattern` 等时会出问题;新 SDK 会在 protobuf 层生成
    `additional_properties`(下划线命名),API 会以 INVALID_ARGUMENT
    拒绝)。走一个剥离过的 dict 能绕开这两个 bug。
    返回的 dict 不影响下游通过 `schema.model_validate_json` 校验 LLM 的
    回复 —— 我们在这里从 prompt schema 中剥离的约束,在我们解析响应时
    依然会被强制执行。
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    inlined = _resolve_refs(raw, defs)
    return _strip_unsupported(inlined)


def _build_config(
    *,
    temperature: float,
    max_output_tokens: int,
    response_schema: dict[str, Any] | None = None,
    thinking_budget: int | None = None,
) -> Any:
    """Construct GenerateContentConfig with our defaults.

    When response_schema is set, also forces JSON mime so Gemini emits
    structured output validating the schema. Schema must be the
    pre-stripped dict (cf. pydantic_to_gemini_schema), not a Pydantic class.

    thinking_budget: gemini-2.5-flash "thinks" by default, which multiplies
    latency+cost. Mechanical tasks (batch extraction/expansion) set 0;
    None keeps the model default (good for judgment calls like the
    ADR-0019 rescue verdict).

    中文:用我们的默认值构造 GenerateContentConfig。
    设置了 response_schema 时,同时强制 JSON mime,让 Gemini 输出满足
    schema 校验的结构化结果。schema 必须是预先剥离过的 dict(参见
    pydantic_to_gemini_schema),而不是 Pydantic 类。
    thinking_budget:gemini-2.5-flash 默认会"思考",这会成倍增加延迟和
    成本。机械性任务(批量抽取/扩写)设为 0;None 则保留模型默认值
    (适合像 ADR-0019 rescue 判断这样需要判断力的场景)。
    """
    from google.genai import types  # noqa: PLC0415

    kwargs: dict[str, Any] = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if response_schema is not None:
        kwargs["response_mime_type"] = "application/json"
        kwargs["response_schema"] = response_schema
    if thinking_budget is not None:
        kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_budget=thinking_budget
        )
    return types.GenerateContentConfig(**kwargs)


def generate_structured(
    prompt: str,
    *,
    schema: type[T],
    client: _ClientLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    thinking_budget: int | None = None,
) -> T:
    """Call Gemini, parse JSON response, validate against `schema`.

    Caller may inject `client` for testing. Otherwise uses cached default
    (lazy SDK import + config from settings.gemini_api_key).

    Raises GeminiError on:
      - API call failure (network / quota / auth)
      - Response not valid JSON
      - JSON not matching `schema`

    中文:调用 Gemini,解析 JSON 响应,并按 `schema` 校验。
    调用方可以注入 `client` 用于测试;否则使用缓存的默认值(懒加载 SDK
    + 来自 settings.gemini_api_key 的配置)。
    以下情况会抛出 GeminiError:
      - API 调用失败(网络 / 配额 / 鉴权)
      - 响应不是合法 JSON
      - JSON 不满足 `schema`
    """
    if client is None:
        client = _build_default_client()

    response_schema = pydantic_to_gemini_schema(schema)
    config = _build_config(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
        thinking_budget=thinking_budget,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        raise GeminiError(f"Gemini API call failed: {type(e).__name__}: {e}") from e

    response_text = _extract_text(response)
    try:
        return schema.model_validate_json(response_text)
    except Exception as e:
        raise GeminiError(
            f"Response failed schema validation against {schema.__name__}: "
            f"{type(e).__name__}: {e}\nResponse text: {response_text[:500]}"
        ) from e


def generate_text(
    prompt: str,
    *,
    client: _ClientLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    timeout_ms: int | None = None,
) -> str:
    """Plain text response (no JSON schema). Use for prompts that don't need
    structured output — e.g., quick summary or paraphrase tasks.

    timeout_ms: per-call HTTP budget override. Latency-sensitive callers
    (the HyDE rescue sits INSIDE a /search request) must not inherit the
    120s default — a hung Gemini call would pin a threadpool worker and
    the user for two minutes.

    中文:返回纯文本响应(没有 JSON schema)。用于不需要结构化输出的
    prompt —— 比如快速摘要或改写任务。
    timeout_ms:按次调用覆盖 HTTP 预算。对延迟敏感的调用方(HyDE 的
    rescue 就运行在一个 /search 请求内部)不能继承 120 秒的默认值 ——
    一次卡住的 Gemini 调用会把一个线程池 worker 和用户一起拖住两分钟。
    """
    if client is None:
        client = (
            _build_client_with_timeout(timeout_ms)
            if timeout_ms is not None
            else _build_default_client()
        )

    config = _build_config(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        raise GeminiError(f"Gemini API call failed: {type(e).__name__}: {e}") from e

    return _extract_text(response)


def generate_text_stream(
    prompt: str,
    *,
    client: _ClientLike | None = None,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> Iterator[str]:
    """Yield text chunks as Gemini produces them.

    Used by /chat for token-by-token UI streaming (Streamlit st.write_stream).
    Caller must consume the iterator promptly — Gemini disconnects idle
    streams after a few seconds.

    GeminiError surfaces if the SDK raises during stream init OR if the
    response never produces text (safety block, empty completion). Per-chunk
    errors mid-stream propagate as GeminiError too — the partial output up
    to that point is what the caller already received.

    中文:随 Gemini 产出逐块 yield 文本。
    供 /chat 用于逐 token 的 UI 流式展示(Streamlit st.write_stream)。
    调用方必须及时消费这个迭代器 —— Gemini 会在闲置几秒后断开流。
    如果 SDK 在流初始化时抛错,或响应从未产出任何文本(安全拦截、空
    completion),都会抛出 GeminiError。流中途逐块出现的错误也会作为
    GeminiError 向外传播 —— 调用方在那之前已经收到的部分输出不受影响。
    """
    if client is None:
        client = _build_default_client()

    config = _build_config(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )

    try:
        stream = client.models.generate_content_stream(
            model=model_name,
            contents=prompt,
            config=config,
        )
    except Exception as e:
        raise GeminiError(
            f"Gemini stream init failed: {type(e).__name__}: {e}"
        ) from e

    saw_any_text = False
    try:
        for chunk in stream:
            text = getattr(chunk, "text", None)
            if text:
                saw_any_text = True
                yield str(text)
    except Exception as e:
        raise GeminiError(
            f"Gemini stream interrupted: {type(e).__name__}: {e}"
        ) from e

    if not saw_any_text:
        raise GeminiError(
            "Gemini stream produced no text chunks (safety block or empty completion)"
        )


def _extract_text(response: Any) -> str:
    """Pull the text out of a Gemini response. response.text is a property
    that auto-concatenates parts; falls back to candidates path if empty.

    中文:从 Gemini 响应中取出文本。response.text 是一个会自动拼接各
    part 的属性;为空时回退到 candidates 路径。
    """
    text = getattr(response, "text", None)
    if text:
        return str(text)

    # Fallback: dig through candidates path (defensive — covers safety-blocked
    # responses where .text returns None but parts may still have content).
    # 中文:回退方案:深入 candidates 路径查找(防御性的 —— 覆盖被安全
    # 拦截的响应:.text 返回 None,但 parts 里可能仍有内容)。
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        parts = getattr(getattr(candidate, "content", None), "parts", None) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if part_text:
                return str(part_text)

    raise GeminiError(
        "Gemini response had no text content. "
        f"Possible safety block or empty completion. Response: {response!r}"
    )


__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "DEFAULT_MODEL",
    "DEFAULT_TEMPERATURE",
    "GeminiError",
    "generate_structured",
    "generate_text",
    "generate_text_stream",
    "pydantic_to_gemini_schema",
]
