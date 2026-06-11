# ADR-0023: NAS 镜像瘦身 (9GB→2.6GB) + 中英混合查询适配结论

## 状态

Accepted - 2026-06-11

## 一、镜像瘦身

**约束**:不碰 uv.lock(PC dev venv 的解析结果一个字节不变)。

**方案**(全部在 Dockerfile 层):
1. `uv sync --frozen ... --no-install-package <name>` 排除 NAS 运行时
   永不执行的包:CUDA torch + triton + 15 个 nvidia-cu12 包(~6GB 安装体积,
   FlagEmbedding/optimum 连带拉入)、playwright、pymupdf、ragas、deepeval、
   datasets、pyarrow
2. 在 optimum-intel 之前 `uv pip install torch --index-url .../whl/cpu`
   (~200MB):optimum-intel 无条件 import torch、tokenizer 打包 pt 张量
   都需要它 — CPU 轮子完全够用,且先装好后 optimum 的 torch 依赖已满足,
   CUDA 轮子不会再进镜像

**实测**:9GB → **2.59GB (-71%)**;api healthy,RSS 3.4GB(持平);
test_set v0.3.1 全量 eval 数字与瘦身前一致(行为零漂移)。
部署/重启从分钟级拉包降到秒级层复用。

## 二、中英混合(code-switched)查询适配 — 测了,结论是"已覆盖"

用户观察:真实使用习惯是中英混合("有没有 workload 轻一点的 ML 课"),
而 ADR-0020 的优化看起来只针对纯中文。**先测量再适配**:
`scripts/augment_test_set_mixed.py` 生成 12 条 code_switched 查询
(Gemini,中文句架+英文术语,强制双语校验)→ test_set v0.3.1 (n=116)。

| 类别 | R@5 |
|---|---:|
| boundary(纯中/重中) | 1.000 |
| **code_switched(中英混合)** | **0.917** |
| simple(课程号) | 0.908 |
| medium(英文改写) | 0.644 |

混合查询是**第二强类别** — 因为它天然吃到双通道:英文术语命中原文+扩展
字段的 BM25,中文片段命中 zh 关键词的 CJK bigram,bge-m3 对 code-switch
的嵌入本身也稳。唯一 miss(q108 "有没有讲 behavior analysis 的课")返回
的是 CAEP 系的行为分析课程 — weak-label 假阴性(同主题异课),非真错。

**决定:不为混合查询增加专门机制**。现有管线(CJK bigram + 双语扩展字段 +
缩写 union + cjk 门控特征按字符占比自动适配)已覆盖;真正的短板仍是
medium(英文语义改写,0.644),那是 embedder/doc-expansion 质量问题,
与 code-switching 无关。

## 整体终态 (test_set v0.3.1 n=116, live)

R@5 **0.7989** / MRR **0.7434** / 误拒 0 / p50 852ms / 镜像 2.59GB。
