"""Behaviour of the duplicated helpers that SIM-01 merges (code-simplification plan, 2026-10-11): the embedding
backends' row-wise L2 normalisation, the course-code rule of program plans and requisite documents, and the canonical
UTC timestamp of the two private export schemas. Written against the copies before they were merged, so the same
expectations hold before and after.
中文：SIM-01 合并的几处重复辅助函数的行为：各嵌入后端的逐行 L2 归一化、培养方案和先修文档共用的课程代码规则、
两份私有导出 schema 的规范 UTC 时间。先对合并前的副本写好，合并前后用同一组期望。
"""

from __future__ import annotations

import numpy as np
import pytest

from rag import embedder, onnx_backend, openvino_backend
from schemas.course_requisite_document import CourseRequisiteDocument
from schemas.feedback_candidate import FeedbackCandidate
from schemas.program_plan import normalize_code
from schemas.query_log_export import QueryLogExportRow

BACKENDS = [embedder, onnx_backend, openvino_backend]
RUNTIMES = ("torch", "onnxruntime", "openvino", "FlagEmbedding", "sentence_transformers", "transformers", "optimum")


def test_each_helper_has_one_definition():
    """SIM-01: the copies are gone; every old name points at the one shared definition."""
    from rag.vectors import l2_normalize  # noqa: PLC0415
    from schemas import feedback_candidate, program_plan, query_log_export  # noqa: PLC0415
    from schemas.course import canonical_course_code  # noqa: PLC0415

    assert all(module._l2_normalize is l2_normalize for module in BACKENDS)
    assert program_plan.normalize_code is canonical_course_code
    assert query_log_export.canonical_utc_timestamp is feedback_candidate.canonical_utc_timestamp


def test_the_shared_vector_helper_loads_no_model_runtime():
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    code = f"import sys, rag.vectors; print(sorted(m for m in {RUNTIMES!r} if m in sys.modules))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize("module", BACKENDS, ids=lambda module: module.__name__)
def test_every_backend_normalises_rows_the_same_way(module):
    rows = np.array([[3.0, 4.0], [0.0, 0.0], [-1.0, 0.0]], dtype=np.float64)
    out = module._l2_normalize(rows)
    assert out.dtype == np.float32 and out.shape == (3, 2)
    assert np.array_equal(out, np.array([[0.6, 0.8], [0.0, 0.0], [-1.0, 0.0]], dtype=np.float32))
    assert rows.dtype == np.float64 and rows[0, 0] == 3.0  # The input itself is left as it was.


@pytest.mark.parametrize("module", BACKENDS, ids=lambda module: module.__name__)
def test_every_backend_handles_edge_inputs_the_same_way(module):
    empty = module._l2_normalize(np.zeros((0, 4), dtype=np.float32))
    assert empty.shape == (0, 4) and empty.dtype == np.float32
    whole = module._l2_normalize(np.array([[0, 5]]))
    assert whole.dtype == np.float32 and np.array_equal(whole, np.array([[0.0, 1.0]], dtype=np.float32))
    with pytest.raises(ValueError):  # Rows are required; numpy's AxisError is a ValueError.
        module._l2_normalize(np.array([3.0, 4.0]))


CODES = [("cs5800", "CS 5800"), ("  ds 5110 ", "DS 5110"), ("info 6105a", "INFO 6105A"), ("CS\t5800", "CS 5800"),
         ("cs 5800\n", "CS 5800")]
NOT_CODES = ["", "CS  5800", "C 5800", "ABCDE 5800", "CS 580", "CS 58000", "CS-5800", "CS 5800AB", "5800"]


@pytest.mark.parametrize(("value", "expected"), CODES)
def test_plans_and_requisite_documents_spell_codes_the_same_way(value, expected):
    assert normalize_code(value) == CourseRequisiteDocument.canonical_code(value) == expected


@pytest.mark.parametrize("value", NOT_CODES)
def test_plans_and_requisite_documents_refuse_the_same_codes(value):
    for check in (normalize_code, CourseRequisiteDocument.canonical_code):
        with pytest.raises(ValueError, match="^Invalid course code$"):
            check(value)


TIMES = ["2026-10-11T07:36:00Z", "2024-02-29T23:59:59Z", "1999-12-31T00:00:00Z"]
# Parsed (strptime ignores case and takes unpadded fields), but not written that way.
NOT_CANONICAL = ["2026-10-11T7:36:00Z", "2026-1-11T07:36:00Z", "2026-10-11t07:36:00z"]
NOT_TIMES = ["", "2026-10-11T07:36:00", "2026-10-11 07:36:00Z", "2026-02-30T00:00:00Z", "2026-10-11T07:36:00.5Z",
             "2026-10-11T07:36:00+00:00", "2026-10-11T07:36:60Z"]


@pytest.mark.parametrize("value", TIMES)
def test_both_export_schemas_take_the_same_timestamps(value):
    assert FeedbackCandidate.utc_timestamp(value) == QueryLogExportRow.utc_timestamp(value) == value


@pytest.mark.parametrize("value", NOT_CANONICAL + NOT_TIMES)
def test_both_export_schemas_refuse_the_same_timestamps(value):
    for check in (FeedbackCandidate.utc_timestamp, QueryLogExportRow.utc_timestamp):
        message = "^Canonical UTC timestamp required$" if value in NOT_CANONICAL else None
        with pytest.raises(ValueError, match=message):
            check(value)
