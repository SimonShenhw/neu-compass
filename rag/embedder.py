"""bge-m3 embedder wrapper.

bge-m3 is multilingual + multi-granularity, suitable for the中英 mixed query
mix we expect from NEU students. Output: 1024-dim dense vectors,
L2-normalized so FAISS IndexFlatIP behaves as cosine similarity.

bge-m3 是多语言 + 多粒度模型,适合 NEU 学生预期会用到的中英混合查询。
输出:1024 维稠密向量,已做 L2 归一化,所以 FAISS IndexFlatIP 的内积
等价于余弦相似度。

The model is ~2.3GB on first download. Tests should NOT trigger this —
inject a FakeEmbedder via the EmbedderProtocol instead. BGEM3Embedder
itself loads the model lazily (first .encode() call) so importing this
module is cheap.

模型首次下载约 2.3GB。测试不应该触发这个下载 —— 应该通过
EmbedderProtocol 注入一个 FakeEmbedder。BGEM3Embedder 自身懒加载模型
(第一次调用 .encode() 时才加载),所以 import 这个模块本身很便宜。
"""

from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

EMBEDDING_DIM = 1024  # bge-m3 dense vector dimension
# 中文:bge-m3 稠密向量维度。


class EmbedderProtocol(Protocol):
    """Minimal interface for any embedder. Tests pass a fake; production
    uses BGEM3Embedder. Output shape: (len(texts), EMBEDDING_DIM) float32.

    中文:任意 embedder 的最小接口。测试传入一个假实现;生产环境用
    BGEM3Embedder。输出形状:(len(texts), EMBEDDING_DIM) float32。
    """

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray: ...


class BGEM3Embedder:
    """BAAI/bge-m3 with FlagEmbedding. Lazy load on first encode().

    Set device='cpu' to skip GPU. On 5090 + cu128, batch=32 should embed
    ~1k chunks in a few seconds. Caller controls batch_size to balance
    throughput vs VRAM (max_length=8192 means a batch of 32 is ~10GB).

    `compile_mode` is a Week 9 Day 2 hook: when set (e.g. "default",
    "reduce-overhead"), the inner XLMRoberta backbone is wrapped via
    torch.compile after load. Best-effort — if FlagEmbedding's internal
    structure changes, the wrap silently no-ops with a warning so the
    embedder still works.

    中文:基于 FlagEmbedding 的 BAAI/bge-m3。首次调用 encode() 时懒加载。
    设 device='cpu' 可以跳过 GPU。在 5090 + cu128 上,batch=32 应该能在
    几秒内 embed 约 1k 个 chunk。调用方通过 batch_size 平衡吞吐量与显存
    占用(max_length=8192 意味着 batch=32 约占 10GB 显存)。
    `compile_mode` 是第 9 周 Day 2 的挂钩:设置后(如 "default"、
    "reduce-overhead"),加载完成会用 torch.compile 包住内部的
    XLMRoberta 主干网络。这是尽力而为的 —— 如果 FlagEmbedding 的内部
    结构发生变化,包装会静默地变成空操作并打一条警告,embedder 依然
    能正常工作。
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        *,
        device: str = "cuda",
        use_fp16: bool = True,
        batch_size: int = 32,
        max_length: int = 8192,
        compile_mode: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.use_fp16 = use_fp16
        self.batch_size = batch_size
        self.max_length = max_length
        self.compile_mode = compile_mode
        self._model: object | None = None
        # Sync routes run in FastAPI's threadpool; serialize lazy load +
        # forward pass (FlagEmbedding makes no thread-safety promise).
        # 中文:同步路由跑在 FastAPI 线程池里;把懒加载 + 前向传播串行化
        # (FlagEmbedding 不承诺线程安全)。
        self._lock = threading.Lock()

    def _load(self) -> object:
        """First-call model download + load. Triggers ~2.3GB download.

        中文:首次调用时下载 + 加载模型。会触发约 2.3GB 的下载。
        """
        if self._model is not None:
            return self._model

        # Lazy import: don't drag FlagEmbedding + torch into every test that
        # only needs the fake.
        # 中文:懒加载 import:不要让每个只需要假实现的测试都被迫拖入
        # FlagEmbedding + torch。
        from FlagEmbedding import BGEM3FlagModel  # noqa: PLC0415

        self._model = BGEM3FlagModel(
            self.model_name,
            use_fp16=self.use_fp16,
            devices=[self.device] if self.device else None,
        )

        if self.compile_mode:
            _try_compile_inner_backbone(self._model, mode=self.compile_mode)

        return self._model

    def encode(self, texts: list[str], *, normalize: bool = True) -> np.ndarray:
        if not texts:
            return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)

        with self._lock:
            model = self._load()
            # FlagEmbedding's BGEM3FlagModel.encode returns dict; we want dense.
            # 中文:FlagEmbedding 的 BGEM3FlagModel.encode 返回一个 dict;
            # 我们只要稠密(dense)那部分。
            out = model.encode(  # type: ignore[attr-defined]
                texts,
                batch_size=self.batch_size,
                max_length=self.max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
        vecs = np.asarray(out["dense_vecs"], dtype=np.float32)

        if normalize:
            vecs = _l2_normalize(vecs)
        return vecs


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Normalize each row to unit L2 norm. Returns float32. Zero rows stay zero.

    中文:把每一行归一化为单位 L2 范数。返回 float32。全零行保持为零。
    """
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


def _try_compile_inner_backbone(flag_model: object, *, mode: str) -> None:
    """Wrap FlagEmbedding's inner XLMRoberta backbone with torch.compile.

    FlagEmbedding 1.x layout: BGEM3FlagModel.model is the BGE wrapper, and
    `.model.model` is the actual transformers backbone (an nn.Module). We
    can torch.compile the backbone in place — FlagEmbedding's encode() will
    call the compiled forward path automatically.

    Best-effort: any failure (FlagEmbedding internal restructure, torch.compile
    not supported on the device, OOM during compile) downgrades to a warning
    and leaves the un-compiled model in place. The embedder still works,
    just at PyTorch baseline speed.

    The `inner is None` early return is deliberately placed BEFORE the
    `import torch` so callers that ship without GPU / without torch (rare
    but possible) — and unit tests with a stub flag_model — don't pay the
    ~2s torch lazy-import cost just to learn the wrap is unreachable.

    中文:用 torch.compile 包装 FlagEmbedding 内部的 XLMRoberta 主干网络。
    FlagEmbedding 1.x 的结构:BGEM3FlagModel.model 是 BGE 的包装层,
    `.model.model` 才是真正的 transformers 主干(一个 nn.Module)。我们
    可以原地对这个主干做 torch.compile —— FlagEmbedding 的 encode() 会
    自动调用编译后的前向路径。
    尽力而为:任何失败(FlagEmbedding 内部结构变化、设备不支持
    torch.compile、编译时 OOM)都会降级为一条警告,保留未编译的模型。
    embedder 仍然能工作,只是回到 PyTorch 基线速度。
    `inner is None` 的提前返回故意放在 `import torch` 之前,这样不带
    GPU / 不装 torch 的调用方(少见但可能存在)—— 以及用 stub flag_model
    的单元测试 —— 不用为了发现"包装根本走不通"而付出约 2 秒的 torch
    懒加载开销。
    """
    inner = getattr(flag_model, "model", None)
    backbone = getattr(inner, "model", None) if inner is not None else None
    if backbone is None:
        # 中文:找不到预期路径下的主干网络,打警告后直接放弃编译。
        print(
            "warning: BGEM3Embedder compile_mode set but FlagEmbedding's "
            "inner backbone not found at .model.model — skipping compile"
        )
        return

    try:
        import torch  # noqa: PLC0415

        if not isinstance(backbone, torch.nn.Module):
            # 中文:主干不是 torch.nn.Module,同样放弃编译。
            print(
                "warning: BGEM3Embedder inner backbone is not a torch.nn.Module — "
                "skipping compile"
            )
            return
        compiled = torch.compile(backbone, mode=mode)
        inner.model = compiled
    except Exception as e:  # noqa: BLE001 — best-effort wrap
        # 中文:尽力而为的包装;编译失败只打警告,不影响 embedder 可用性。
        print(f"warning: torch.compile failed for BGEM3Embedder: {e}")


__all__ = ["EMBEDDING_DIM", "BGEM3Embedder", "EmbedderProtocol"]
