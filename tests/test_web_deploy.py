"""R7: the web front end's deployment as the repository has it. docker-compose.yml's web service, the API's
WEB_ORIGINS, the tunnel's dependency, both images' build contexts, the web image's Dockerfile and nginx.conf,
deploy.ps1's probes and archive, and CI's check of the image agree with each other. Compose and CI are read as YAML
(review B36); the lines that do the checking (CI's steps, the Dockerfile's Node check, deploy.ps1's tar options without
its comments) are pinned whole, so that a comment, a `|| true` or another pattern does not pass for them (recheck R1).
Reads files only, but runs the Dockerfile's guard of its build arguments under sh.
中文：仓库里的新前端部署：compose 的 web 服务、API 的 WEB_ORIGINS、隧道的依赖、两个镜像的构建上下文、网页镜像的
Dockerfile 和 nginx.conf、deploy.ps1 的探测和打包、CI 对镜像的核对彼此一致。compose 和 CI 按 YAML 读（B36）；真正做
核对的那几行（CI 的几步、Dockerfile 核对 Node 的那行、deploy.ps1 去掉注释以后的 tar 选项）整行钉住，注释、`|| true`、
换一个匹配式都过不去（复核 R1）。只读文件，Dockerfile 检查构建参数的那段用 sh 跑一遍。"""

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
CI = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
CI_JOB = CI["jobs"]["web-image"]
DOCKERFILE = (ROOT / "web" / "Dockerfile").read_text(encoding="utf-8")
NGINX = (ROOT / "web" / "deploy" / "nginx.conf").read_text(encoding="utf-8")
COMPASS = "https://compass.neu-compass.me"
API = "https://api.neu-compass.me"
# CI's last check of the image, whole: nginx runs as 101, and its log holds no request, not even the malformed one
# check-site sends (the line an error log lowered to info would keep).
CI_USER_AND_LOG = r'''test "$(docker compose exec -T web id -u)" = 101
docker compose logs --no-log-prefix web > web.log
cat web.log
if grep -E 'GET |HEAD |HTTP/1\.|/course/|/assets/|/healthz' web.log; then
  echo "::error::the web container logged a request"
  exit 1
fi'''
NODE_CHECK = r'''RUN node --version | grep -q '^v24\.' || { echo "Not Node 24: $(node --version)" >&2; exit 1; }'''


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


def tar_options() -> list[str]:
    """deploy.ps1's tar options as PowerShell runs them: the $tarExcludes listing without its comments (R1)."""
    listing = re.search(r"^\$tarExcludes = @\((.*?)^\) -join ' '$", DEPLOY, re.M | re.S)
    assert listing
    code = re.sub(r"<#.*?#>", "", listing.group(1), flags=re.S)
    code = re.sub(r"#.*$", "", code, flags=re.M)
    return re.findall(r"'(--[^']+)'", code)


def test_the_site_shared_links_name_is_one_the_api_takes() -> None:
    """The site a build's links name serves that build, so the API must take it: CORS, the cookie's writes and Google's
    way back. The API the build calls is production's."""
    origins = json.loads(mapping(SERVICES["api"]["environment"])["WEB_ORIGINS"])
    assert web_args()["VITE_PUBLIC_BASE_URL"] in origins
    assert web_args()["VITE_API_BASE_URL"] == API


def test_links_name_compass_and_the_api_takes_compass_only() -> None:
    """Decision 2 of the R7 plan, from the switch: links name compass. The beta stayed two weeks after the switch and
    went in R8 (plan, section 3), so the API takes compass alone. 中文：切换以后分享链接指向 compass；beta 留了两周，R8
    去掉了，API 只认 compass。"""
    assert web_args()["VITE_PUBLIC_BASE_URL"] == COMPASS
    assert json.loads(mapping(SERVICES["api"]["environment"])["WEB_ORIGINS"]) == [COMPASS]


def test_the_tunnel_waits_for_the_api_only() -> None:
    """Decision 5 of the R7 plan: a front end that is not healthy keeps neither the tunnel nor the other one down."""
    assert waits_for(SERVICES["cloudflared"]) == {"api"}
    assert [name for name, service in SERVICES.items() if "web" in waits_for(service)] == []


def test_the_stack_has_no_streamlit_service() -> None:
    """R8 deleted the Streamlit UI and with it the `ui` service. 中文：R8 删了 Streamlit，也去掉了 `ui` 服务。"""
    assert set(SERVICES) == {"api", "web", "backup", "cloudflared"}


def test_the_web_service_is_built_from_web_and_hardened() -> None:
    assert WEB["build"]["context"] == "./web"
    assert WEB["read_only"] is True
    assert WEB["tmpfs"] == ["/tmp"]
    assert WEB["cap_drop"] == ["ALL"]
    assert WEB["security_opt"] == ["no-new-privileges:true"]
    # Nothing that undoes it or reaches it, listed by what is there rather than what is not (R1): the image's user 101,
    # no privilege, capability, host namespace or seccomp profile back, no secrets, no volumes.
    assert set(WEB) == {"build", "image", "container_name", "restart", "logging", "read_only", "tmpfs", "cap_drop",
                        "security_opt", "ports", "healthcheck"}
    assert WEB["restart"] == "always" and WEB["logging"] == SERVICES["api"]["logging"]
    assert WEB["healthcheck"]["test"] == ["CMD", "curl", "-fsS", "-o", "/dev/null", "http://127.0.0.1:8080/healthz"]
    # An image of its own: api and backup run neu-compass:latest, which a build of web must never replace.
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

    assert accepted(API, COMPASS)
    for api, site in [("", COMPASS), ("   ", COMPASS), (API, " "), ("http://api.example.test", COMPASS),
                      ("https://", COMPASS), (API, "compass.neu-compass.me")]:
        assert not accepted(api, site), (api, site)


def test_deploy_and_ci_check_the_web_service_where_compose_publishes_it() -> None:
    port = re.search(r"^\$WebPort\s+= (\d+)$", DEPLOY, re.M)
    api = re.search(r"^\$WebApi\s+= '(\S+)'$", DEPLOY, re.M)
    assert port and api
    assert WEB["ports"] == [f"{port.group(1)}:8080"]
    assert api.group(1) == web_args()["VITE_API_BASE_URL"]
    # The job always runs and its failure fails the workflow, every step in the default shell (bash -e); its checks are
    # steps that always run, each pinned whole, so that a `|| true`, a line commented out or another pattern does not
    # pass for one (recheck R1).
    assert not {"if", "continue-on-error", "defaults"} & set(CI_JOB) and "defaults" not in CI
    assert not [step for step in CI_JOB["steps"] if "shell" in step]
    runs = [step["run"].strip() for step in CI_JOB["steps"]
            if "run" in step and "if" not in step and not step.get("continue-on-error")]
    assert "touch .env\ndocker compose up --build --detach --wait --wait-timeout 180 web" in runs
    check_site = f"node web/deploy/check-site.ts http://127.0.0.1:{port.group(1)} {api.group(1)}"
    assert f"{check_site} {web_args()['VITE_PUBLIC_BASE_URL']}" in runs
    assert CI_USER_AND_LOG in runs


def test_nginx_logs_no_request_and_reads_no_body() -> None:
    """The server's own lines in nginx.conf (CI's log check and the nginx mutants see their effect), and no location
    with a log of its own: CI's malformed request is answered at the server's level, so it would never show a
    location's (recheck R1)."""
    for line in ("server_tokens off;", "access_log off;", "error_log /dev/stderr error;", "log_not_found off;",
                 "client_max_body_size 0;", "include /etc/nginx/security-headers.conf;"):
        assert re.search(rf"^    {re.escape(line)}$", NGINX, re.M), line
    assert sorted(re.findall(r"^\s*(access_log|error_log)\b", NGINX, re.M)) == ["access_log", "error_log"]


def test_no_image_takes_what_a_checkout_of_web_installs_or_builds() -> None:
    """web/.gitignore lists what is installed or built there. The api's image takes none of web/; the web image's own
    context and deploy.ps1's archive (from which the NAS builds both) leave each of those directories out."""
    root_ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "web/" in root_ignore
    web_ignore = (ROOT / "web" / ".dockerignore").read_text(encoding="utf-8").splitlines()
    # A local .env would change what Vite builds.
    assert ".env*" in web_ignore
    excludes = {option.removeprefix("--exclude=") for option in tar_options()}
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
    items = tar_options()
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
    # The digest, not the tag, decides which node it is: the build stage checks and stops on any other (B36), the line
    # whole (R1).
    assert NODE_CHECK in DOCKERFILE.splitlines()
    # The site's engines: Node 24 builds it, as CI does.
    engines = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
    assert engines == ">=24 <25"
