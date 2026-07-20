"""OpenVINO backend for bge-m3 + bge-reranker-v2-m3 via optimum-intel.

Drop-in replacement for OnnxEmbedder / OnnxReranker that runs inference
through OpenVINO Runtime *natively* (no ONNX intermediate). Implements
the same EmbedderProtocol / score(...) surface as the PyTorch/ONNX
backends so HybridRetriever + rerank_blend_with_rejection are unchanged.

OnnxEmbedder / OnnxReranker 的直接替代品,通过 OpenVINO Runtime *原生*
运行推理(不经过 ONNX 中间表示)。实现了与 PyTorch/ONNX 后端相同的
EmbedderProtocol / score(...) 接口,因此 HybridRetriever +
rerank_blend_with_rejection 都无需改动。

Why this exists when we already have ONNX:
  The ONNX path (onnxruntime-openvino) chokes on Intel GPU compile of
  the bge-m3 model — `GatherND` with u8 indices isn't supported by the
  Intel GPU plugin's `program_builder`. The optimum-intel direct-to-IR
  export bypasses ONNX intermediate representation, so the GatherND
  surfaces with int64 indices that GPU compiles cleanly.

为什么已经有 ONNX 了还需要这个:
  ONNX 路径(onnxruntime-openvino)在 Intel GPU 编译 bge-m3 模型时会卡住——
  带 u8 索引的 `GatherND` 不被 Intel GPU 插件的 `program_builder` 支持。
  optimum-intel 的直出 IR 导出绕开了 ONNX 中间表示,这样落地的 GatherND
  用的是 int64 索引,GPU 就能干净地编译。

Latency on i5-1235U + Iris Xe 80EU (NAS), expected:
  - This backend (OpenVINO IR + Iris Xe GPU FP16): ~100-300 ms /search
  - ONNX + OpenVINO CPU EP (fallback, current):    ~7-10 s   /search
  See https://gist.github.com/ravi9/7023573645ed37a0c5e40b5b1b0af759
  + https://huggingface.co/docs/optimum-intel/openvino/inference

i5-1235U + Iris Xe 80EU(NAS)上的预期延迟:
  - 本后端(OpenVINO IR + Iris Xe GPU FP16):约 100-300 毫秒/次搜索
  - ONNX + OpenVINO CPU EP(当前的回退方案):约 7-10 秒/次搜索
  参见 https://gist.github.com/ravi9/7023573645ed37a0c5e40b5b1b0af759
  + https://huggingface.co/docs/optimum-intel/openvino/inference

Setup:
  1. PC: `uv sync --extra openvino` (adds optimum-intel[openvino])
  2. PC: `uv run python scripts/export_openvino.py` (~5 min)
  3. Transfer ./openvino/{embedder,reranker} to NAS runtime-data/openvino/
  4. NAS: set INFERENCE_BACKEND=openvino + OPENVINO_MODEL_DIR=/data/openvino

搭建步骤:
  1. PC:`uv sync --extra openvino`(添加 optimum-intel[openvino])
  2. PC:`uv run python scripts/export_openvino.py`(约 5 分钟)
  3. 把 ./openvino/{embedder,reranker} 传到 NAS 的 runtime-data/openvino/
  4. NAS:设置 INFERENCE_BACKEND=openvino + OPENVINO_MODEL_DIR=/data/openvino

Design:
  - `OvEmbedder` / `OvReranker` accept already-built model + tokenizer in
    __init__ so tests don't need optimum-intel installed.
  - `from_path()` classmethod is the production loader (lazy SDK import).
  - device + ov_config come from settings; default device="GPU" for Iris Xe.
  - CACHE_DIR points to a persistent volume so the GPU-compiled kernel cache
    survives container restarts (first boot ~60s, subsequent boots ~5s).

设计:
  - `OvEmbedder` / `OvReranker` 在 __init__ 里接受已经构建好的模型 +
    tokenizer,这样测试不需要安装 optimum-intel。
  - `from_path()` 类方法是生产环境的加载器(懒加载 SDK)。
  - device + ov_config 来自 settings;默认 device="GPU",对应 Iris Xe。
  - CACHE_DIR 指向一个持久化卷,让 GPU 编译出的内核缓存能在容器重启后
    继续存活(首次启动约 60 秒,之后启动约 5 秒)。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any

import numpy as np
import structlog

_log = structlog.get_logger("neu_compass.openvino")

EMBEDDING_DIM = 1024  # bge-m3 dense vector dimension (mirrors rag.embedder)
# 中文:bge-m3 稠密向量维度(与 rag.embedder 保持一致)。

# Single-query embedding cache size. Repeats are STRUCTURAL, not
# hypothetical: the UI's hero sample chips and follow-up chips send
# fixed query strings, so every first-time visitor and every chip click
# re-embeds the same handful of texts (~50-100ms each on Iris Xe).
# 中文:单查询 embedding 缓存的大小。重复请求是结构性的,不是假设:UI 的
# 首页示例 chip 和追问 chip 会发送固定的查询字符串,所以每个第一次访问的
# 用户、每次点击 chip,都会把同样那几段文本重新 embed 一遍(在 Iris Xe 上
# 每次约 50-100ms)。
_QUERY_CACHE_SIZE = 256


def _build_ov_config(*, cache_dir: str | None) -> dict[str, str]:
    """Return ov_config dict tuned for low-latency single-query inference.

    PERFORMANCE_HINT=LATENCY tells OpenVINO to optimize for minimum p50
    latency rather than throughput. CACHE_DIR persists compiled GPU
    kernels across restarts (first boot pays the compile cost once).

    中文:返回针对低延迟单查询推理调优的 ov_config 字典。
    PERFORMANCE_HINT=LATENCY 让 OpenVINO 优化最小 p50 延迟而非吞吐量。
    CACHE_DIR 让编译好的 GPU 内核在重启后依然存活(编译成本只在首次启动
    时付一次)。
    """
    cfg = {"PERFORMANCE_HINT": "LATENCY"}
    if cache_dir:
        cfg["CACHE_DIR"] = cache_dir
    return cfg


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    # Guard against div-by-zero for an all-zero row (stays zero, not NaN).
    # 中文:防止全零行导致除零(全零行结果保持为零,而不是变成 NaN)。
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


class OvEmbedder:
    """OpenVINO-backed embedder (bge-m3 family).

    Loads an `OVModelForFeatureExtraction` and performs CLS-token pooling
    + L2 normalization — matches FlagEmbedding's `encode(return_dense=True)`
    output bit-for-bit (within FP16 quantization noise).

    中文:基于 OpenVINO 的 embedder(bge-m3 系列)。
    加载一个 `OVModelForFeatureExtraction`,做 CLS token 池化 + L2 归一化——
    与 FlagEmbedding 的 `encode(return_dense=True)` 输出逐位一致(在 FP16
    量化噪声范围内)。
    """

    def __init__(
        self,
        *,
        model: Any,
        tokenizer: Any,
        max_length: int = 512,
    ) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.max_length = max_length
        # optimum-intel OVModel* hold ONE OpenVINO InferRequest — concurrent
        # forward passes on the same instance are NOT safe. Sync routes run
        # in FastAPI's threadpool, so serialize inference here.
        # 中文:optimum-intel 的 OVModel* 只持有一个 OpenVINO InferRequest——
        # 同一实例上并发跑前向传播是不安全的。同步路由跑在 FastAPI 线程池
        # 里,所以这里要把推理串行化。
        self._lock = threading.Lock()
        # LRU for the single-text (query) case only — document batches
        # during indexing must not evict query entries or bloat memory.
        # Guarded by the same lock as inference (dict ops are cheap).
        # 中文:LRU 缓存只用于单文本(查询)场景 —— 建索引时的文档批次
        # 不能把查询条目挤出去,也不能让内存膨胀。用与推理相同的锁保护
        # (dict 操作本身很便宜)。LRU 具体如何命中/淘汰见 encode() 里的
        # move_to_end / popitem 用法。
        self._query_cache: OrderedDict[tuple[str, bool], np.ndarray] = (
            OrderedDict()
        )

    @classmethod
    def from_path(
        cls,
        model_dir: str,
        *,
        tokenizer_id: str = "BAAI/bge-m3",
        max_length: int = 512,
        device: str = "GPU",
        cache_dir: str | None = None,
    ) -> OvEmbedder:
        """Production loader. Lazy imports so tests don't pay the cost.

        `device` accepts standard OpenVINO device strings: "GPU", "CPU",
        "AUTO:GPU,CPU", "MULTI:GPU,CPU", etc. Default "GPU" targets the
        integrated Iris Xe on the NAS.

        中文:生产环境加载器。懒加载 import,测试不需要承担这个开销。
        `device` 接受标准的 OpenVINO 设备字符串:"GPU"、"CPU"、
        "AUTO:GPU,CPU"、"MULTI:GPU,CPU" 等。默认 "GPU" 对应 NAS 上的
        集成显卡 Iris Xe。
        """
        from optimum.intel import OVModelForFeatureExtraction  # noqa: PLC0415
        from transformers import AutoTokenizer  # noqa: PLC0415

        model = OVModelForFeatureExtraction.from_pretrained(
            model_dir,
            device=device,
            ov_config=_build_ov_config(cache_dir=cache_dir),
        )
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)
        return cls(model=model, tokenizer=tokenizer, max_length=max_length)

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        # Single-text fast path: query embeddings are deterministic, and
        # the UI's fixed sample/follow-up chips guarantee verbatim repeats.
        # 中文:单文本快路径:查询的 embedding 是确定性的,而 UI 的固定
        # 示例/追问 chip 又保证了逐字重复,因此这里值得缓存。
        cache_key = (texts[0], normalize) if len(texts) == 1 else None
        if cache_key is not None:
            with self._lock:
                hit = self._query_cache.get(cache_key)
                if hit is not None:
                    # LRU touch: move this key to the "recently used" end so
                    # it survives future evictions (paired with the
                    # popitem(last=False) eviction below).
                    # 中文:LRU 触达:把这个 key 挪到"最近使用"的一端,让它
                    # 在之后的淘汰中存活(与下方 popitem(last=False) 的
                    # 淘汰逻辑配套)。
                    self._query_cache.move_to_end(cache_key)
                    return hit[np.newaxis, :].copy()

        # Tokenization INSIDE the lock on purpose: the shared HF fast
        # tokenizer (Rust) raises "Already borrowed" under concurrent
        # truncation/padding re-config — FastAPI's threadpool can run two
        # /search requests at once. Mirrors the pytorch backend's locking.
        # 中文:分词故意放在锁内:共享的 HF fast tokenizer(Rust 实现)在
        # 并发做 truncation/padding 重新配置时会抛出 "Already borrowed"——
        # FastAPI 的线程池可能同时跑两个 /search 请求。这里的加锁方式与
        # pytorch 后端保持一致。
        with self._lock:
            encoded = self._tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            outputs = self._model(**encoded)
        # last_hidden_state shape: (batch, seq_len, hidden_dim). CLS-pool [:, 0, :].
        # 中文:last_hidden_state 形状为 (batch, seq_len, hidden_dim);
        # 取 [:, 0, :] 做 CLS token 池化。
        cls_emb = outputs.last_hidden_state[:, 0, :].numpy().astype(np.float32)
        if normalize:
            cls_emb = _l2_normalize(cls_emb)

        if cache_key is not None:
            with self._lock:
                self._query_cache[cache_key] = cls_emb[0].copy()
                self._query_cache.move_to_end(cache_key)
                # LRU eviction: OrderedDict tracks insertion / move_to_end
                # order; popitem(last=False) pops from the OLDEST end once
                # the cache exceeds _QUERY_CACHE_SIZE — classic LRU cap.
                # 中文:LRU 淘汰:OrderedDict 维护插入/move_to_end 之后的
                # 顺序;缓存超过 _QUERY_CACHE_SIZE 时,popitem(last=False)
                # 从最旧的一端弹出 —— 经典的 LRU 容量上限实现。
                while len(self._query_cache) > _QUERY_CACHE_SIZE:
                    self._query_cache.popitem(last=False)
        return cls_emb


class OvReranker:
    """OpenVINO-backed cross-encoder reranker (bge-reranker-v2-m3 family).

    Mirrors `CrossEncoderReranker.score(query, candidates)`: tokenizes
    (query, candidate) pairs together and returns sigmoid scores in [0, 1].

    中文:基于 OpenVINO 的交叉编码器重排器(bge-reranker-v2-m3 系列)。
    与 `CrossEncoderReranker.score(query, candidates)` 接口一致:把
    (query, candidate) 对一起分词,返回 [0, 1] 区间的 sigmoid 分数。
    """

    def __init__(
        self,
        *,
        model: Any,
        tokenizer: Any,
        max_length: int = 512,
    ) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.max_length = max_length
        self._lock = threading.Lock()  # see OvEmbedder.__init__
        # 中文:参见 OvEmbedder.__init__ 里的说明。

    @classmethod
    def from_path(
        cls,
        model_dir: str,
        *,
        tokenizer_id: str = "BAAI/bge-reranker-v2-m3",
        max_length: int = 512,
        device: str = "GPU",
        cache_dir: str | None = None,
    ) -> OvReranker:
        # Mirrors OvEmbedder.from_path — same lazy-import / ov_config story,
        # just a different optimum-intel model class + default tokenizer.
        # 中文:与 OvEmbedder.from_path 相同的懒加载 / ov_config 套路,
        # 只是换了 optimum-intel 的模型类和默认 tokenizer。
        from optimum.intel import OVModelForSequenceClassification  # noqa: PLC0415
        from transformers import AutoTokenizer  # noqa: PLC0415

        model = OVModelForSequenceClassification.from_pretrained(
            model_dir,
            device=device,
            ov_config=_build_ov_config(cache_dir=cache_dir),
        )
        tokenizer = AutoTokenizer.from_pretrained(tokenizer_id)
        return cls(model=model, tokenizer=tokenizer, max_length=max_length)

    def score(self, query: str, candidates: list[str]) -> list[float]:
        if not candidates:
            return []

        # Tokenize inside the lock — see OvEmbedder.encode for why.
        # 中文:分词放在锁内 —— 原因见 OvEmbedder.encode。
        with self._lock:
            encoded = self._tokenizer(
                [query] * len(candidates),
                candidates,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            # Measurement hook for the max_length A/B (RERANKER_MAX_LENGTH):
            # padded seq len tells us how much of the 512 budget real pools
            # use. DEBUG level — invisible at the prod INFO default.
            # 中文:为 max_length A/B 实验(RERANKER_MAX_LENGTH)埋的测量点:
            # padding 后的序列长度告诉我们真实候选池用掉了 512 预算里的
            # 多少。DEBUG 级别 —— 生产环境默认的 INFO 级别下不可见。
            _log.debug(
                "reranker.batch",
                pairs=len(candidates),
                padded_len=int(encoded["input_ids"].shape[1]),
                max_length=self.max_length,
            )
            outputs = self._model(**encoded)
        # logits shape (batch, 1) for cross-encoder binary head.
        # 中文:logits 形状为 (batch, 1),对应交叉编码器的二分类头。
        logits = outputs.logits.squeeze(-1).numpy().astype(np.float32)
        sigmoid = 1.0 / (1.0 + np.exp(-logits))
        return [float(s) for s in sigmoid.tolist()]


def warm_up(targets: Iterable[Any]) -> None:
    """Run a single dummy inference per target so OpenVINO finishes any
    deferred device compile + warms the kernel cache. The first real
    request after this is fast.

    中文:对每个目标跑一次虚拟推理,让 OpenVINO 完成任何延迟的设备编译、
    预热内核缓存。这之后的第一个真实请求就会很快。
    """
    for t in targets:
        if hasattr(t, "encode"):
            t.encode(["warmup"])
        elif hasattr(t, "score"):
            t.score("warmup", ["warmup"])


__all__ = [
    "EMBEDDING_DIM",
    "OvEmbedder",
    "OvReranker",
    "warm_up",
]
