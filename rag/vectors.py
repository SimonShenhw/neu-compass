"""Vector helpers shared by the embedding backends (FlagEmbedding, ONNX, OpenVINO). numpy only: importing this loads
no model runtime.
中文：几个嵌入后端共用的向量函数。只依赖 numpy，导入时不加载任何模型运行时。
"""

from __future__ import annotations

import numpy as np


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Normalize each row to unit L2 norm. Returns float32. Zero rows stay zero (not NaN).

    中文:把每一行归一化为单位 L2 范数。返回 float32。全零行保持为零(不会变成 NaN)。
    """
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)
