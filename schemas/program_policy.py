"""Selected policy evidence; no default college, merged rules or eligibility.

中文：只核对冻结页面、段落位置及精确方案范围；摘要仍需人工语义复核。
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.program_plan import ProgramPlan
from schemas.program_source import MAX_HTML_BYTES, SourceCapture

Authority = Literal["university", "khoury", "camd", "engineering"]
College = Literal["khoury", "camd", "engineering"]
AUTHORITY_PATHS = {
    "university": "academic-policies-procedures/",
    "khoury": "computer-information-science/academic-policies-procedures/",
    "camd": "arts-media-design/academic-policies-procedures/",
    "engineering": "engineering/academic-policies-procedures/",
}
COLLEGE_NAMES = {
    "khoury": "Khoury College of Computer Sciences",
    "camd": "College of Arts, Media and Design",
    "engineering": "College of Engineering",
}
DS_COLLEGES = {
    "computer-science": ("khoury", "Computer Science"),
    "data-design-visualization": ("camd", "Data Design and Visualization"),
    "engineering-theory-modeling": ("engineering", "Engineering Theory and Modeling"),
}


def normalized_text(value: str) -> str:
    return " ".join(value.split())


def paragraph_hash(value: str) -> str:
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


class PolicySourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority: Authority
    catalog_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    url: str
    page_title: str = Field(min_length=1, max_length=300)

    @field_validator("catalog_year")
    @classmethod
    def edition(cls, value):
        return ProgramPlan.consecutive_years(value)

    @field_validator("url")
    @classmethod
    def origin(cls, value):
        return ProgramPlan.catalog_origin(value)

    @field_validator("page_title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Policy title must not be blank")
        return value

    @model_validator(mode="after")
    def authority_and_edition(self):
        path = self.url.split("/graduate/", 1)[1]
        prefix = AUTHORITY_PATHS[self.authority]
        if not path.startswith(prefix) or path == prefix:
            raise ValueError("Policy URL must be a chapter of the declared authority")
        archived = re.search(r"/archive/(\d{4}-\d{4})/", self.url)
        if archived and archived.group(1) != self.catalog_year:
            raise ValueError("Archived policy edition mismatch")
        return self


def _policy_blocks(content: bytes, source_kind: Literal["paragraph", "list"]) -> list[tuple[str | None, str]]:
    """Separate p/outer-list indexes; nested lists stay inside their whole parent."""
    if not content or len(content) > MAX_HTML_BYTES:
        raise ValueError("Policy HTML outside size budget")
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    containers = soup.find_all(id="textcontainer")
    if len(containers) != 1:
        raise ValueError("Policy needs one unambiguous textcontainer")
    # In-body TOCs are navigation, not policy; remove before heading/text walks.
    # Keep ordinary links and `notinpdf` alone, which can contain actual rules.
    for navigation in reversed(containers[0].select("nav, footer, [role='navigation'], .onthispage")):
        navigation.decompose()
    result, heading = [], None
    tags = ["p"] if source_kind == "paragraph" else ["ul", "ol"]
    for element in containers[0].find_all(["h2", "h3", "h4", *tags]):
        if source_kind == "list" and element.find_parent(["ul", "ol"]) is not None:
            continue
        text = normalized_text(element.get_text(" ", strip=True))
        if element.name in {"h2", "h3", "h4"}:
            heading = text
        else:
            if not text or len(text) > 20_000 or len(result) >= 300:
                raise ValueError("Policy source block outside size budget")
            result.append((heading, text))
    return result


def policy_paragraphs(content: bytes) -> list[tuple[str | None, str]]:
    """Legacy zero-based p indexes are unchanged by lists or nested list items."""
    result = _policy_blocks(content, "paragraph")
    if not result:
        raise ValueError("Policy has no paragraphs")
    return result


def policy_lists(content: bytes) -> list[tuple[str | None, str]]:
    """Whole outer ul/ol blocks, including all nested exceptions; may be empty."""
    return _policy_blocks(content, "list")


def inspect_policy_html(content: bytes, request: PolicySourceRequest) -> None:
    policy_paragraphs(content)
    policy_lists(content)
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    headings = soup.find_all("h1")
    if len(headings) != 1 or normalized_text(headings[0].get_text(" ", strip=True)) != request.page_title:
        raise ValueError("Policy page identity mismatch")
    editions = set(re.findall(r"(\d{4}-\d{4})\s+Edition", soup.get_text(" ", strip=True)))
    if editions != {request.catalog_year}:
        raise ValueError("Policy page edition mismatch")


class PolicyFragment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fragment_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    source_kind: Literal["paragraph", "list"] = "paragraph"
    # Legacy field names retained: index/hash refer to the declared source kind.
    paragraph_index: int = Field(ge=0, lt=300)
    heading: str | None = Field(default=None, min_length=1, max_length=300)
    paragraph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: str = Field(min_length=1, max_length=1500)
    limitation: str = Field(min_length=1, max_length=1500)

    @field_validator("summary", "limitation", "heading")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Policy evidence text must not be blank")
        return value


class PolicyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")
    authority: Authority
    source: SourceCapture
    coverage: Literal["selected_fragments_only"] = "selected_fragments_only"
    fragments: list[PolicyFragment] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def consistent_source(self):
        PolicySourceRequest(authority=self.authority, url=self.source.url,
            catalog_year=self.source.catalog_year, page_title=self.source.page_title)
        ids = [item.fragment_id for item in self.fragments]
        positions = [(item.source_kind, item.paragraph_index) for item in self.fragments]
        if len(set(ids)) != len(ids) or len(set(positions)) != len(positions):
            raise ValueError("Duplicate policy fragment identity/position")
        return self


class PlanPolicyLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
    program_id: str = Field(min_length=1, max_length=64)
    campus: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    catalog_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    pathway: Literal["standard", "align", "bridge"]
    concentration: str | None = Field(default=None, min_length=1, max_length=100)
    plan_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    home_college: College
    policy_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("catalog_year")
    @classmethod
    def edition(cls, value):
        return ProgramPlan.consecutive_years(value)

    @field_validator("program_id", "concentration")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Link scope must not be blank")
        return value

    @field_validator("policy_ids")
    @classmethod
    def distinct_ids(cls, values):
        if len(set(values)) != len(values) or any(not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", v) for v in values):
            raise ValueError("Policy references must be distinct valid IDs")
        return values

    def scope_key(self):
        return (self.program_id, self.campus, self.catalog_year, self.pathway, self.concentration or "")


class ProgramPolicyBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal[1] = 1
    coverage: Literal["selected_fragments_only"] = "selected_fragments_only"
    review_status: Literal["source_checked"] = "source_checked"
    checked_by: str = Field(min_length=1, max_length=100)
    checked_on: date
    policies: list[PolicyEvidence] = Field(min_length=1, max_length=30)
    links: list[PlanPolicyLink] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def bounded_links(self):
        if not self.checked_by.strip():
            raise ValueError("Reviewer must not be blank")
        policies = {item.policy_id: item for item in self.policies}
        if len(policies) != len(self.policies) or len({item.source.url for item in self.policies}) != len(self.policies):
            raise ValueError("Duplicate policy identity/source")
        if (len({item.plan_id for item in self.links}) != len(self.links)
                or len({item.scope_key() for item in self.links}) != len(self.links)):
            raise ValueError("Duplicate linked plan identity/scope")
        used = set()
        for policy in self.policies:
            if self.checked_on < policy.source.captured_at.date():
                raise ValueError("Policy review cannot predate capture")
        for link in self.links:
            for policy_id in link.policy_ids:
                policy = policies.get(policy_id)
                if policy is None or policy.source.catalog_year != link.catalog_year:
                    raise ValueError("Unknown/wrong-edition policy reference")
                if policy.authority not in {"university", link.home_college}:
                    raise ValueError("Home-college evidence cannot be borrowed from another college")
                used.add(policy_id)
        if used != set(policies):
            raise ValueError("Every policy must have an explicit scoped link")
        return self


def verify_policy_source(policy: PolicyEvidence, source_dir: Path) -> dict[tuple[str, int], tuple[str | None, str]]:
    metadata = policy.source
    stem = source_dir / metadata.sha256
    html_path, sidecar_path = stem.with_suffix(".html"), stem.with_suffix(".json")
    if html_path.stat().st_size > MAX_HTML_BYTES or sidecar_path.stat().st_size > 16_000:
        raise ValueError("Policy archive outside size budget")
    content = html_path.read_bytes()
    sidecar = SourceCapture.model_validate_json(sidecar_path.read_text(encoding="utf-8"))
    if sidecar != metadata or len(content) != metadata.byte_count or hashlib.sha256(content).hexdigest() != metadata.sha256:
        raise ValueError("Policy archive metadata/content mismatch")
    inspect_policy_html(content, PolicySourceRequest(authority=policy.authority, url=metadata.url,
        catalog_year=metadata.catalog_year, page_title=metadata.page_title))
    blocks = {(kind, index): block for kind, values in
        (("paragraph", policy_paragraphs(content)), ("list", policy_lists(content)))
        for index, block in enumerate(values)}
    for fragment in policy.fragments:
        position = (fragment.source_kind, fragment.paragraph_index)
        if position not in blocks:
            raise ValueError("Policy source block position missing")
        heading, text = blocks[position]
        if heading != fragment.heading or paragraph_hash(text) != fragment.paragraph_sha256:
            raise ValueError("Policy source block heading/content mismatch")
    return blocks


def verify_home_college(plan: ProgramPlan, content: bytes) -> College:
    """This finite sample checks program-page evidence, never a course prefix."""
    soup = BeautifulSoup(content, "html.parser", from_encoding="utf-8")
    if plan.program_id == "ds-ms" and plan.pathway == "standard":
        mapping = DS_COLLEGES.get(plan.concentration)
        containers = soup.find_all(id="textcontainer")
        if mapping is None or len(containers) != 1:
            raise ValueError("No supported DS home-college evidence")
        college, concentration = mapping
        expected = f"{concentration}—{COLLEGE_NAMES[college]}"
        if [normalized_text(li.get_text(" ", strip=True)) for li in containers[0].select("li")].count(expected) != 1:
            raise ValueError("DS concentration/home-college evidence mismatch")
        return college
    college = None
    if plan.program_id == "cs-ms" and plan.pathway in {"standard", "align"}:
        college = "khoury"
    elif plan.program_id == "info-ms" and plan.pathway in {"standard", "bridge"}:
        college = "engineering"
    if college is None:
        raise ValueError("No supported home-college evidence for this scope")
    crumbs = soup.find_all(id="breadcrumb")
    if len(crumbs) != 1:
        raise ValueError("Missing/ambiguous program breadcrumb")
    path = AUTHORITY_PATHS[college].split("academic-policies-procedures/")[0]
    archive = re.search(r"/archive/(\d{4}-\d{4})/", plan.source_url)
    href = f"/archive/{archive.group(1)}/graduate/{path}" if archive else f"/graduate/{path}"
    matches = [a for a in crumbs[0].select("a") if a.get("href") == href
        and normalized_text(a.get_text(" ", strip=True)) == COLLEGE_NAMES[college]]
    if len(matches) != 1:
        raise ValueError("Program home-college breadcrumb mismatch")
    return college
