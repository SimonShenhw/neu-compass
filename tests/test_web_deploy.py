"""R7: the web front end's deployment as the repository has it. docker-compose.yml's web service, the API's
WEB_ORIGINS, the tunnel's dependency, both images' build contexts, deploy.ps1's probes and CI's check of the image
agree with each other. Reads files only.
中文：仓库里的新前端部署：compose 的 web 服务、API 的 WEB_ORIGINS、隧道的依赖、两个镜像的构建上下文、deploy.ps1
的探测和 CI 对镜像的核对彼此一致。只读文件。"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DEPLOY = (ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def service(name: str) -> str:
    """One service's block of docker-compose.yml, up to the next service."""
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \S|\Z)", COMPOSE, re.M | re.S)
    assert match, name
    return match.group(1)


def value(block: str, key: str) -> str:
    match = re.search(rf"^\s+{key}: (.+)$", block, re.M)
    assert match, key
    return match.group(1).strip()


def test_the_site_shared_links_name_is_one_the_api_takes() -> None:
    """The site a build's links name serves that build, so the API must take it: CORS, the cookie's writes and Google's
    way back. The API the build calls is production's."""
    web = service("web")
    share = value(web, "VITE_PUBLIC_BASE_URL")
    origins = json.loads(value(service("api"), "WEB_ORIGINS").strip("'"))
    assert share == "https://beta.neu-compass.me" and origins == [share]
    assert value(web, "VITE_API_BASE_URL") == "https://api.neu-compass.me"


def test_the_tunnel_waits_for_the_api_only() -> None:
    """Decision 5 of the R7 plan: a front end that is not healthy keeps neither the tunnel nor the other one down."""
    block = re.search(r"depends_on:\n((?: {6,}.*\n?)+)", service("cloudflared"))
    assert block
    assert re.findall(r"^ {6}(\S+):$", block.group(1), re.M) == ["api"]
    assert not re.search(r"^ {6}web:$", COMPOSE, re.M), "nothing waits for web"


def test_the_web_service_is_built_from_web_and_runs_read_only() -> None:
    web = service("web")
    assert value(web, "context") == "./web"
    assert value(web, "read_only") == "true"
    assert "tmpfs:\n      - /tmp\n" in web
    assert "cap_drop:\n      - ALL\n" in web
    assert "no-new-privileges:true" in web
    assert value(web, "restart") == "always" and value(web, "logging") == "*bounded-logging"
    assert value(web, "test") == '["CMD", "curl", "-fsS", "-o", "/dev/null", "http://127.0.0.1:8080/healthz"]'


def test_deploy_and_ci_check_the_web_service_where_compose_publishes_it() -> None:
    port = re.search(r"^\$WebPort\s+= (\d+)$", DEPLOY, re.M)
    api = re.search(r"^\$WebApi\s+= '(\S+)'$", DEPLOY, re.M)
    assert port and api
    assert f'- "{port.group(1)}:8080"' in service("web")
    assert api.group(1) == value(service("web"), "VITE_API_BASE_URL")
    assert f"node web/deploy/check-site.ts http://127.0.0.1:{port.group(1)} {api.group(1)}" in CI
    assert "docker compose up --build --detach --wait --wait-timeout 180 web" in CI


def test_no_image_takes_what_a_checkout_of_web_installs_or_builds() -> None:
    """web/.gitignore lists what is installed or built there. The api's image takes none of web/; the web image's own
    context and deploy.ps1's archive (from which the NAS builds both) leave each of those directories out."""
    root_ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "web/" in root_ignore
    web_ignore = (ROOT / "web" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    excludes = set(re.findall(r"'--exclude=([^']+)'", DEPLOY))
    made = [
        line.rstrip("/")
        for line in (ROOT / "web" / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.endswith("/") and not line.startswith("#")
    ]
    assert {"node_modules", "dist", "tools/e2e/.browsers"} <= set(made)
    for directory in made:
        assert f"{directory}/" in web_ignore or (directory.startswith("tools/") and "tools/" in web_ignore), directory
        expected = "node_modules" if directory == "node_modules" else f"web/{directory}"
        assert expected in excludes, directory


def test_the_web_image_bases_are_pinned_by_digest() -> None:
    dockerfile = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
    bases = re.findall(r"^FROM (\S+)", dockerfile, re.M)
    assert len(bases) == 2
    for base in bases:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", base), base
    assert bases[0].startswith("node:24.") and bases[1].startswith("nginxinc/nginx-unprivileged:")
    # The site's engines: Node 24 builds it, as CI does.
    engines = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
    assert engines == ">=24 <25"
