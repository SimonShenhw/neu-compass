"""R7: the web front end's deployment as the repository has it. docker-compose.yml's web service, the API's
WEB_ORIGINS, the tunnel's dependency, both images' build contexts, the web image's Dockerfile and nginx.conf,
deploy.ps1's probes and archive, and CI's check of the image agree with each other. Compose and CI are read as YAML,
so that neither a comment nor another way of writing the same thing decides (review B36). Reads files only, but runs
the Dockerfile's guard of its build arguments under sh.
中文：仓库里的新前端部署：compose 的 web 服务、API 的 WEB_ORIGINS、隧道的依赖、两个镜像的构建上下文、网页镜像的
Dockerfile 和 nginx.conf、deploy.ps1 的探测和打包、CI 对镜像的核对彼此一致。compose 和 CI 按 YAML 读，注释和换一种
写法都骗不过（B36）。只读文件，Dockerfile 检查构建参数的那段用 sh 跑一遍。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml  # PyYAML: the dev extra's pre-commit needs it, as the runtime's huggingface-hub does.

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SERVICES: dict[str, dict[str, Any]] = COMPOSE["services"]
WEB = SERVICES["web"]
DEPLOY = (ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
CI_JOB = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))["jobs"]["web-image"]
DOCKERFILE = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
NGINX = (ROOT / "web" / "deploy" / "nginx.conf").read_text(encoding="utf-8")
BETA = "https://beta.neu-compass.me"
API = "https://api.neu-compass.me"


def mapping(value: Any) -> dict[str, str]:
    """Compose's environment or build args, written as a map or as a list of NAME=value."""
    if isinstance(value, list):
        return dict(item.split("=", 1) for item in value)
    return {key: str(item) for key, item in (value or {}).items()}


def waits_for(service: dict[str, Any]) -> set[str]:
    """The services a service's depends_on names, in its short form (a list) or its long one (a map)."""
    return set(service.get("depends_on") or [])


def web_args() -> dict[str, str]:
    return mapping(WEB["build"].get("args"))


def test_the_site_shared_links_name_is_one_the_api_takes() -> None:
    """The site a build's links name serves that build, so the API must take it: CORS, the cookie's writes and Google's
    way back. The API the build calls is production's."""
    origins = json.loads(mapping(SERVICES["api"]["environment"])["WEB_ORIGINS"])
    assert web_args()["VITE_PUBLIC_BASE_URL"] in origins
    assert web_args()["VITE_API_BASE_URL"] == API


def test_during_the_beta_links_name_the_beta_and_only_it_is_taken() -> None:
    """Decision 2 of the R7 plan, until the switch: the one assertion the switch changes (compass, and both origins)."""
    assert web_args()["VITE_PUBLIC_BASE_URL"] == BETA
    assert json.loads(mapping(SERVICES["api"]["environment"])["WEB_ORIGINS"]) == [BETA]


def test_the_tunnel_waits_for_the_api_only() -> None:
    """Decision 5 of the R7 plan: a front end that is not healthy keeps neither the tunnel nor the other one down."""
    assert waits_for(SERVICES["cloudflared"]) == {"api"}
    assert [name for name, service in SERVICES.items() if "web" in waits_for(service)] == []


def test_the_web_service_is_built_from_web_and_hardened() -> None:
    assert WEB["build"]["context"] == "./web"
    assert WEB["read_only"] is True
    assert WEB["tmpfs"] == ["/tmp"]
    assert WEB["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in WEB["security_opt"]
    # Nothing that undoes it or reaches it: the image's user 101, no privilege or capability back, no secrets.
    assert not {"user", "privileged", "cap_add", "env_file", "volumes"} & set(WEB)
    assert WEB["restart"] == "always" and WEB["logging"] == SERVICES["api"]["logging"]
    assert WEB["healthcheck"]["test"] == ["CMD", "curl", "-fsS", "-o", "/dev/null", "http://127.0.0.1:8080/healthz"]
    # An image of its own: api, ui and backup run neu-compass:latest, which a build of web must never replace.
    assert WEB["image"] not in {service.get("image") for name, service in SERVICES.items() if name != "web"}


def test_the_dockerfile_takes_the_build_arguments_compose_gives() -> None:
    """Both, or the build falls back to production's API and compass for its links (B36): nothing else would see it."""
    assert set(web_args()) == {"VITE_API_BASE_URL", "VITE_PUBLIC_BASE_URL"}
    for name in web_args():
        assert f"\nARG {name}\n" in DOCKERFILE, name


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh to run the guard with")
def test_the_web_image_refuses_a_build_argument_that_is_not_an_https_origin() -> None:
    """A value of spaces only once passed `test -n`, and the build fell back to its defaults (A36). The guard runs here
    as the build stage's sh runs it."""
    guard = re.search(r"^RUN (for value in .*?done) \\\n", DOCKERFILE, re.M | re.S)
    assert guard, "the Dockerfile guards its two build arguments"
    assert guard.group(1).startswith('for value in "$VITE_API_BASE_URL" "$VITE_PUBLIC_BASE_URL"; do')

    def accepted(api: str, site: str) -> bool:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "VITE_API_BASE_URL": api, "VITE_PUBLIC_BASE_URL": site}
        return subprocess.run(["sh", "-c", guard.group(1)], env=env, capture_output=True, check=False).returncode == 0

    assert accepted(API, BETA)
    for api, site in [("", BETA), ("   ", BETA), (API, " "), ("http://api.example.test", BETA), ("https://", BETA),
                      (API, "beta.neu-compass.me")]:
        assert not accepted(api, site), (api, site)


def test_deploy_and_ci_check_the_web_service_where_compose_publishes_it() -> None:
    port = re.search(r"^\$WebPort\s+= (\d+)$", DEPLOY, re.M)
    api = re.search(r"^\$WebApi\s+= '(\S+)'$", DEPLOY, re.M)
    assert port and api
    assert WEB["ports"] == [f"{port.group(1)}:8080"]
    assert api.group(1) == web_args()["VITE_API_BASE_URL"]
    # The job's checks: steps that always run and whose failure fails the job.
    runs = [step["run"].strip() for step in CI_JOB["steps"]
            if "run" in step and "if" not in step and not step.get("continue-on-error")]
    assert any(run.endswith("docker compose up --build --detach --wait --wait-timeout 180 web") for run in runs)
    check_site = f"node web/deploy/check-site.ts http://127.0.0.1:{port.group(1)} {api.group(1)}"
    assert f"{check_site} {web_args()['VITE_PUBLIC_BASE_URL']}" in runs
    assert any(run.startswith('test "$(docker compose exec -T web id -u)" = 101') for run in runs)
    assert any("docker compose logs --no-log-prefix web > web.log" in run and "grep -E" in run and "exit 1" in run
               for run in runs)


def test_nginx_logs_no_request_and_reads_no_body() -> None:
    """The server's own lines in nginx.conf (CI's log check and the nginx mutants see their effect)."""
    for line in ("server_tokens off;", "access_log off;", "error_log /dev/stderr error;", "log_not_found off;",
                 "client_max_body_size 0;", "include /etc/nginx/security-headers.conf;"):
        assert re.search(rf"^    {re.escape(line)}$", NGINX, re.M), line


def test_no_image_takes_what_a_checkout_of_web_installs_or_builds() -> None:
    """web/.gitignore lists what is installed or built there. The api's image takes none of web/; the web image's own
    context and deploy.ps1's archive (from which the NAS builds both) leave each of those directories out."""
    root_ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "web/" in root_ignore
    web_ignore = (ROOT / "web" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    # A local .env would change what Vite builds.
    assert ".env*" in web_ignore
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


def test_deploy_archive_leaves_out_what_lives_at_the_root_only_there() -> None:
    """deploy.ps1's archive: the root's own folders anchored (tar's names start with ./), so that no folder of web/'s
    sources is left out for sharing a name (B36); the rest, node_modules and web/'s build output, at any depth; and
    every exclude before the member, or tar ignores it."""
    listing = re.search(r"^\$tarExcludes = @\((.*?)^\) -join ' '$", DEPLOY, re.M | re.S)
    assert listing
    items = re.findall(r"'(--[^']+)'", listing.group(1))
    anchored = items[items.index("--anchored") + 1: items.index("--no-anchored")]
    assert items[-1] == "--no-anchored" and items.count("--anchored") == 1
    assert {f"--exclude=./{name}" for name in ("tests", "eval", "docs", "backups", "runtime-data", "cloudflared")} <= set(
        anchored)
    assert all(item.startswith("--exclude=./") for item in anchored)
    unanchored = items[: items.index("--anchored")]
    assert {"--exclude=node_modules", "--exclude=.env", "--exclude=web/dist", "--exclude=web/tools/e2e/.browsers"} <= set(
        unanchored)
    assert "tar $tarExcludes --totals -czf /dev/null ." in DEPLOY
    assert "tar $tarExcludes -czf - . | ssh" in DEPLOY


def test_the_web_image_bases_are_pinned_by_digest() -> None:
    bases = re.findall(r"^FROM (\S+)", DOCKERFILE, re.M)
    assert len(bases) == 2
    for base in bases:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", base), base
    assert bases[0].startswith("node:24.") and bases[1].startswith("nginxinc/nginx-unprivileged:")
    # The digest, not the tag, decides which node it is: the build stage checks (B36).
    assert "RUN node --version | grep -q '^v24\\.'" in DOCKERFILE
    # The site's engines: Node 24 builds it, as CI does.
    engines = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
    assert engines == ">=24 <25"
