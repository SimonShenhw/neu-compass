"""Conservative grammar for explicit catalog prerequisite/corequisite clauses.

中文：括号保留分组；分号/and 是 AND，or 是 OR；同层混合时不猜优先级。
Unknown words, tests, approval or syntax preserve the ENTIRE clause as unparsed.
"""

from __future__ import annotations

import re

from bs4.element import Tag

from schemas.course_requisites import CatalogRequisites, RequisiteNode, RequisiteSection

ATOM = re.compile(
    r"(?P<code>[A-Z]{2,4}\s?\d{4}[A-Z]?)\b"
    r"(?:\s*\((?P<concurrent_before>may be taken concurrently)\))?"
    r"(?:\s+with a minimum grade of (?P<grade>[ABCD][+-]?|F|P|S)(?=\s|$|\)))?"
    r"(?:\s*\((?P<level>Graduate|Undergraduate)\))?"
    r"(?:\s*\((?P<concurrent>may be taken concurrently)\))?"
)


class ClauseError(ValueError):
    pass


class Parser:
    def __init__(self, text: str):
        self.text, self.position = text, 0

    def whitespace(self):
        while self.position < len(self.text) and self.text[self.position].isspace():
            self.position += 1

    def atom(self, depth):
        if depth > 10:
            raise ClauseError("input_budget")
        self.whitespace()
        if self.text[self.position:self.position + 1] == "(":
            self.position += 1
            node = self.group(depth + 1)
            self.whitespace()
            if self.text[self.position:self.position + 1] != ")":
                raise ClauseError("unbalanced_parentheses")
            self.position += 1
            return node
        match = ATOM.match(self.text, self.position)
        if not match:
            raise ClauseError("unsupported_syntax")
        self.position = match.end()
        grade = match.group("grade")
        return RequisiteNode(kind="course", course_code=match.group("code"), minimum_grade=grade,
            academic_level=match.group("level"), concurrent_allowed=bool(match.group("concurrent") or match.group("concurrent_before")))

    def group(self, depth=1):
        children, operator = [self.atom(depth)], None
        while True:
            self.whitespace()
            if self.position == len(self.text) or self.text[self.position] == ")":
                break
            match = re.match(r"(?:;|and\b|or\b)", self.text[self.position:])
            if not match:
                raise ClauseError("unsupported_syntax")
            current = "any_of" if match.group() == "or" else "all_of"
            if operator and current != operator:
                raise ClauseError("ambiguous_precedence")
            operator = current
            self.position += match.end()
            children.append(self.atom(depth))
        return children[0] if operator is None else RequisiteNode(kind=operator, children=children)


def parse_clause(text: str | None) -> RequisiteSection:
    if text is None:
        return RequisiteSection(status="not_listed")
    # Normalize formatting only; the input HTML archive remains byte-exact.
    normalized = " ".join(text.split())
    if not normalized:
        return RequisiteSection(status="unparsed", raw_text=normalized, reason="empty_clause")
    if len(normalized) > 8_000 or len(re.findall(r"\(|\)|\b[A-Z]{2,4}\s?\d{4}", normalized)) > 240:
        return RequisiteSection(status="unparsed", raw_text=normalized, reason="input_budget")
    try:
        parser = Parser(normalized)
        rule = parser.group()
        parser.whitespace()
        if parser.position != len(normalized):
            raise ClauseError("unbalanced_parentheses")
        return RequisiteSection(status="parsed", raw_text=normalized, rule=rule)
    except ValueError as exc:
        reason = str(exc) if isinstance(exc, ClauseError) else "invalid_tree"
        return RequisiteSection(status="unparsed", raw_text=normalized, reason=reason)


def parse_course_requisites(block: Tag) -> CatalogRequisites:
    clauses = {"prerequisite": [], "corequisite": []}
    malformed = set()
    for extra in block.find_all("p", class_="courseblockextra"):
        text = " ".join(extra.get_text(" ", strip=True).split())
        label = extra.find("strong")
        label_text = " ".join(label.get_text(" ", strip=True).split()) if label else ""
        name = re.fullmatch(r"(Prerequisite|Corequisite)(?:\(s\)|s)?:", label_text, re.IGNORECASE)
        if not name:
            prefix = re.match(r"(Prerequisite|Corequisite)(?:\(s\)|s)?(?=[:\s]|$)", text, re.IGNORECASE)
            if prefix:
                key = prefix.group(1).lower()
                clauses[key].append(text)
                malformed.add(key)
            continue
        if not text.startswith(label_text):
            raise ValueError("Ambiguous catalog requisite label")
        clauses[name.group(1).lower()].append(text[len(label_text):].strip())
    sections = {}
    for name, texts in clauses.items():
        if name in malformed or len(texts) > 1:
            sections[name] = RequisiteSection(status="unparsed", raw_text="\n".join(texts),
                reason="malformed_section_label" if name in malformed else "duplicate_section")
        else:
            sections[name] = parse_clause(texts[0] if texts else None)
    return CatalogRequisites(**sections)
