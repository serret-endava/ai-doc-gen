# src/handlers/cronjob.py
import os
import shutil
import asyncio
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional, Literal, Dict

from git import Repo, GitCommandError
from pydantic import BaseModel, Field

import config
from config import load_config_from_file
from handlers.analyze import AnalyzeHandler, AnalyzeHandlerConfig
from utils import Logger
from utils.dict import merge_dicts
from .base_handler import AbstractHandler
from providers import get_provider
from urllib.parse import urlsplit, urlunsplit, quote

COMMIT_MESSAGE_TITLE = "[AI] Analyzer-Agent: Create/Update AI Analysis"

# Optional filters
IGNORED_PROJECTS: List[int] = []
IGNORED_SUBGROUPS: List[str] = []

# Files the analyzer is expected to produce
EXPECTED_DOCS: Dict[str, str] = {
    ".ai/docs/structure_analysis.md":    "Structure Analysis",
    ".ai/docs/dependency_analysis.md":   "Dependency Analysis",
    ".ai/docs/data_flow_analysis.md":    "Data Flow Analysis",
    ".ai/docs/request_flow_analysis.md": "Request Flow Analysis",
    ".ai/docs/api_analysis.md":          "API Analysis",
}


class JobAnalyzeHandlerConfig(BaseModel):
    # Selection / filtering
    max_days_since_last_commit: Optional[int] = Field(
        default=30,
        description="Maximum days since last commit to consider a project for cronjob execution",
    )
    working_path: Optional[Path] = Field(
        default=Path("/tmp/cronjob/projects"),
        description="Path where projects are cloned for cronjob execution",
    )
    group_project_id: Optional[int] = Field(
        default=3,
        description="Group ID (GitLab) or ignored (Bitbucket) whose projects will be analyzed",
    )
    provider: Optional[Literal["gitlab", "bitbucket"]] = Field(
        default="gitlab",
        description="Provider to use for repo operations (gitlab, bitbucket)",
    )
    # Branching
    source_branch: Optional[str] = Field(
        default=None,
        description="Branch to base the analysis on. If it does not exist, falls back to the repository default.",
    )
    target_branch: Optional[str] = Field(
        default=None,
        description="MR/PR target branch (defaults to repository default).",
    )
    # Bitbucket-only filter (exposed via CLI)
    bitbucket_project_key: Optional[str] = Field(
        default=None,
        description="Bitbucket only: filter repositories by project key (e.g., AID).",
    )
    # Analyzer robustness
    analyzer_max_retries: int = Field(
        default=3,
        description="How many times to retry the analyzer on transient errors.",
    )
    retry_backoff_seconds: float = Field(
        default=3.0,
        description="Seconds to wait between analyzer retries.",
    )
    enforce_docs: bool = Field(
        default=True,
        description="If true, create placeholder files for any missing analysis docs.",
    )


class JobAnalyzeHandler(AbstractHandler):
    def __init__(self, config: JobAnalyzeHandlerConfig = None, provider=None, client=None) -> None:
        super().__init__()
        self._config = config or JobAnalyzeHandlerConfig()
        self._provider_name = (self._config.provider or "gitlab").lower()
        # Pass CLI-only knobs to the provider (e.g., Bitbucket project key)
        self._provider = provider or get_provider(
            name=self._provider_name,
            client=client,
            bitbucket_project_key=self._config.bitbucket_project_key,
        )
        self._config.working_path.mkdir(parents=True, exist_ok=True)

    async def handle(self):
        Logger.info("Starting cronjob handler")

        for project in self._provider.iter_group_projects(self._config.group_project_id):
            try:
                Logger.info(
                    f"Checking project {getattr(project, 'name', '<unknown>')} "
                    f"(ID: {getattr(project, 'id', '<unknown>')})"
                )
                if self._is_applicable_project(project):
                    Logger.debug(f"Project {project.name} (ID: {project.id}) is applicable")
                    await self._handle_project(project)
            except Exception as err:
                Logger.error(
                    f"Error handling project {getattr(project, 'name', '<unknown>')} "
                    f"(ID: {getattr(project, 'id', '<unknown>')}): {err}",
                    data={
                        "project_id": getattr(project, "id", None),
                        "project_name": getattr(project, "name", None),
                    },
                    exc_info=True,
                )

    # ---------- branch helpers ----------
    def _resolve_base_branch(self, project) -> str:
        """
        Decide the base branch to use for analysis and for creating the work branch:
        - If --source-branch is provided and exists, use it.
        - If it doesn't exist (404 or similar), fall back to the project's default branch.
        Portable across providers: use provider.get_branch if available, otherwise branch_exists.
        """
        default_branch = self._provider.get_default_branch(project)
        src = (self._config.source_branch or "").strip()
        if not src:
            return default_branch

        try:
            if hasattr(self._provider, "get_branch"):
                # Providers like GitLab/our Bitbucket have get_branch(project, name) that raises on 404
                self._provider.get_branch(project, src)
                return src
            # Fallback: use branch_exists if get_branch is not available
            if self._provider.branch_exists(project, src):
                return src
            raise RuntimeError(f"Branch '{src}' not found")
        except Exception as e:
            Logger.warning(
                f"Source branch '{src}' not found; falling back to default '{default_branch}'",
                data={"project_id": getattr(project, "id", None), "error": str(e)},
            )
            return default_branch

    def _make_work_branch_name(self, base_branch: str) -> str:
        """
        Create a short-lived work branch name derived from the chosen base branch.
        This avoids pushing directly to protected branches.
        """
        safe = base_branch.replace("/", "-")
        return f"ai-analyzer-{safe}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # ---------- pre-checks / filters ----------
    def _is_applicable_project(self, project) -> bool:
        # Skip archived projects
        if getattr(project, "archived", False):
            return False

        # Skip by subgroup/name-with-namespace (works across providers)
        namespace = (
            getattr(project, "name_with_namespace", None)
            or getattr(project, "full_name", None)
            or getattr(project, "path_with_namespace", None)
            or getattr(project, "name", "")
        ).lower()
        for subgroup in IGNORED_SUBGROUPS:
            if subgroup.lower() in namespace:
                return False

        # Skip by explicit project ID
        pid = getattr(project, "id", None)
        if pid is None and hasattr(project, "get_id"):
            pid = project.get_id()
        try:
            if int(pid) in IGNORED_PROJECTS:
                Logger.debug(f"Project {project.name} is ignored for cronjob")
                return False
        except Exception:
            pass

        # Default branch must exist
        default_branch = self._provider.get_default_branch(project)
        if not default_branch:
            Logger.debug(f"No default branch for {getattr(project, 'name', '<unknown>')}")
            return False

        # Use source_branch if it exists; otherwise, fallback to default
        branch_for_checks = self._resolve_base_branch(project)

        # Get last commit info and staleness
        try:
            commit_info = self._provider.get_last_commit_info(project, branch_for_checks)
        except Exception as e:
            Logger.warning(
                f"Could not get last commit info from '{branch_for_checks}'",
                data={"project_id": getattr(project, "id", None), "error": str(e)},
            )
            return False

        last_msg = (commit_info.get("message") or "")
        if COMMIT_MESSAGE_TITLE in last_msg:
            Logger.debug(f"Project {project.name} is not updated since last analysis")
            return False

        committed_at = commit_info.get("committed_date")
        if committed_at:
            try:
                dt = datetime.fromisoformat(committed_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except Exception:
                dt = datetime.strptime(committed_at[:19], "%Y-%m-%dT%H:%M:%S")
            days = (datetime.now() - dt).days
            if days > self._config.max_days_since_last_commit:
                Logger.debug(f"Project {project.name} is not updated since last analysis")
                return False

        # Simple duplicate guard: avoid similar MRs/PRs by the same bot user
        author_username = self._provider.get_bot_username()
        if self._provider.mr_similar_exists(project, author_username, "[AUTOGENERATED] AI Analysis"):
            Logger.debug("Similar MR already exists")
            return False

        return True

    # ---------- main flow ----------
    async def _handle_project(self, project):
        Logger.info(f"Running cronjob for project {project.name} (ID: {project.id})")
        repo = None
        try:
            repo = self._clone_project(project)
            await self._analyze_project(project=project, repo=repo)
            await self._create_merge_request(project=project, repo=repo)
        finally:
            if repo:
                self._cleanup_project(project=project, repo=repo)

    # ---------- git clone helpers ----------
    def _build_clone_url(self, base_url: str) -> str:
        """
        Normalize the URL and inject credentials based on the provider selected via CLI.
        - Strip any existing 'user@' portion.
        - Bitbucket:   username:app_password
        - GitLab:      oauth2:token
        """
        u = urlsplit(base_url)
        host = (u.hostname or "").lower()
        if not host:
            raise ValueError(f"Bad clone URL: {base_url}")

        # netloc without userinfo
        netloc = host if u.port is None else f"{host}:{u.port}"

        auth = None
        if self._provider_name == "bitbucket":
            bb_user = os.getenv("BITBUCKET_USERNAME")
            bb_pass = os.getenv("BITBUCKET_APP_PASSWORD")
            if bb_user and bb_pass:
                auth = f"{quote(bb_user)}:{quote(bb_pass)}"
        elif self._provider_name == "gitlab":
            gl_token = os.getenv("GITLAB_OAUTH_TOKEN") or os.getenv("GITLAB_TOKEN")
            if gl_token:
                auth = f"oauth2:{quote(gl_token)}"

        if auth:
            netloc = f"{auth}@{netloc}"

        return urlunsplit((u.scheme or "https", netloc, u.path, "", ""))

    def _clone_project(self, project) -> Repo:
        Logger.info(f"Cloning project {project.name} (ID: {project.id})")

        base_url = self._provider.get_http_url(project)
        clone_url = self._build_clone_url(base_url)

        # Decide the base branch (source_branch if exists, else default)
        base_branch = self._resolve_base_branch(project)
        default_branch_name = self._provider.get_default_branch(project)

        project_dir = self._config.working_path / f"{project.name}-{project.id}"
        if project_dir.exists():
            Logger.debug(f"Removing existing project directory {project_dir}")
            shutil.rmtree(project_dir, ignore_errors=True)

        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = "echo"

        # Try to clone the chosen base_branch; on failure (race/permission), fallback to default
        try:
            repo = Repo.clone_from(
                url=clone_url,
                to_path=project_dir,
                branch=base_branch,
                depth=1,
                env=env,
            )
        except GitCommandError as e:
            Logger.warning(
                f"Clone of '{base_branch}' failed, retrying with default branch '{default_branch_name}'",
                data={"stderr": getattr(e, "stderr", None), "stdout": getattr(e, "stdout", None)},
            )
            repo = Repo.clone_from(
                url=clone_url,
                to_path=project_dir,
                branch=default_branch_name,
                depth=1,
                env=env,
            )
            base_branch = default_branch_name  # keep state consistent

        # Always create a short-lived work branch to avoid pushing to protected branches
        work_branch = self._make_work_branch_name(base_branch)
        repo.git.checkout("-b", work_branch)

        # Configure commit identity
        user_name, email = self._provider.get_commit_identity()
        repo.git.config("user.name", user_name)
        repo.git.config("user.email", email)

        Logger.debug(f"Cloned project {project.name} from base '{base_branch}' into work branch '{work_branch}'")
        return repo

    # ---------- analyzer & artifacts ----------
    def _write_placeholder(self, path: Path, title: str, *, reason: Optional[str] = None) -> None:
        """
        Create a minimal placeholder file when an analysis artifact is missing.
        This guarantees all expected doc files are present for the MR/PR.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {title}\n\n",
            "This file was generated automatically as a placeholder.\n",
        ]
        if reason:
            lines.append(f"\n> Note: placeholder due to error: {reason}\n")
        path.write_text("".join(lines), encoding="utf-8")

    async def _analyze_project(self, project, repo: Repo):
        Logger.info(f"Analyzing project {project.name} (ID: {project.id})")

        # Load optional per-repo analyzer config
        args = SimpleNamespace(repo_path=repo.working_dir, config=None)
        project_config = load_config_from_file(args, "analyzer")

        base_config = {"repo_path": Path(repo.working_dir)}
        final_config = merge_dicts(base_config, project_config)

        analyzer = AnalyzeHandler(config=AnalyzeHandlerConfig(**final_config))

        # Retry analyzer a few times to handle transient failures/quota/tool hiccups
        last_err = None
        for attempt in range(1, self._config.analyzer_max_retries + 1):
            try:
                await analyzer.handle()
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt < self._config.analyzer_max_retries:
                    Logger.info(
                        f"Analyzer attempt {attempt} failed, retrying in {self._config.retry_backoff_seconds}s...",
                        data={"error": str(e)},
                    )
                    await asyncio.sleep(self._config.retry_backoff_seconds)
                else:
                    Logger.error("Analyzer failed after retries", exc_info=True)

        # Ensure required artifacts exist (write placeholders if missing)
        if self._config.enforce_docs:
            missing = []
            for rel, title in EXPECTED_DOCS.items():
                p = Path(repo.working_dir) / rel
                if not p.exists():
                    missing.append(p)
                    self._write_placeholder(path=p, title=title, reason=str(last_err) if last_err else None)

            if missing:
                Logger.warning(
                    "Some analysis files were missing and were replaced by placeholders.",
                    data={"missing": [str(m) for m in missing]},
                )

    # ---------- MR/PR creation ----------
    async def _create_merge_request(self, project, repo: Repo):
        Logger.info(f"Creating merge request for project {project.name} (ID: {project.id})")

        repo.git.add(".")
        commit_message = f"{COMMIT_MESSAGE_TITLE}\n\nAnalyzer Version: {config.VERSION}"
        repo.git.commit("-m", commit_message)
        repo.git.push("origin", repo.active_branch.name, "-f")

        title = f"[AUTOGENERATED] AI Analysis for {project.name} - {datetime.now().strftime('%Y-%m-%d')}"
        description = (
            "This merge request contains Updated AI analysis results.\n\n"
            f"Analyzer Version: `{config.VERSION}`\n\n"
            "**Note:** This merge request is automatically created by the AI Analyzer Agent."
        )

        # Target branch defaults to repo default if not specified
        target_branch = self._config.target_branch or self._provider.get_default_branch(project)
        mr = self._provider.create_merge_request(
            project=project,
            source_branch=repo.active_branch.name,  # work branch created from base_branch
            target_branch=target_branch,
            title=title,
            description=description,
        )

        mr_id = getattr(mr, "id", None) or (mr.get("id") if isinstance(mr, dict) else None)
        mr_title = getattr(mr, "title", None) or (mr.get("title") if isinstance(mr, dict) else None)
        mr_url = getattr(mr, "web_url", None) or (mr.get("web_url") if isinstance(mr, dict) else None)

        Logger.debug(
            f"Created merge request {mr_id} for project {project.name} (ID: {project.id})",
            data={"merge_request_id": mr_id, "merge_request_title": mr_title, "web_url": mr_url},
        )

    # ---------- cleanup ----------
    def _cleanup_project(self, project, repo: Repo):
        Logger.info(f"Cleaning up project {project.name} (ID: {project.id})")
        repo.close()
        try:
            repo.git.clear_cache()
        except Exception:
            pass
        project_path = Path(repo.working_dir)
        shutil.rmtree(project_path, ignore_errors=True)
        Logger.debug(f"Cleaned up project {project.name} at {project_path}")
