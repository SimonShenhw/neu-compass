"""Capture every cb_desc paragraph from the already verified course block."""

from schemas.course_description_evidence import CourseDescriptionEvidence


def extract_description_evidence(block) -> CourseDescriptionEvidence:
    paragraphs = [" ".join(item.get_text(" ", strip=True).split()) for item in block.select("p.cb_desc")]
    return CourseDescriptionEvidence.from_paragraphs([text for text in paragraphs if text])
