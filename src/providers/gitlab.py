# src/providers/gitlab_provider.py
import os
from datetime import datetime
from typing import Iterator, Optional, Dict, Any

import gitlab
from gitlab.v4.objects.projects import Project
from gitlab.v4.objects.branches import ProjectBranch
from gitlab.exceptions import GitlabGetError, GitlabListError, GitlabCreateError

DEFAULT_API_URL = "https://gitlab.com"

class GitLabProvider:
    """
    Compatibility provider for the current handler. Exposes the minimal surface:

      - iter_group_projects(group_id) -> Iterator[Project]
      - get_default_branch(project) -> str | None
      - get_branch(project, name) -> ProjectBranch
      - branch_exists(project, name) -> bool
      - get_last_commit_info(project, branch) -> {"message", "committed_date"}
      - mr_similar_exists(project, author_username, search) -> bool
      - create_merge_request(project, source_branch, target_branch, title, description) -> MR object
      - get_http_url(project) -> str
      - get_bot_username() -> str
      - get_commit_identity() -> tuple[str, str]
    """

    def __init__(self, gitlab_client: Optional[gitlab.Gitlab] = None) -> None:
        """
        Accepts an injected python-gitlab client. If not provided, builds one from env:
          - GITLAB_API_URL or GITLAB_URL (defaults to https://gitlab.com)
        """
        if gitlab_client is not None:
            self.gl = gitlab_client
        else:
            
            base_url = os.getenv("BITBUCKET_API_URL", DEFAULT_API_URL).rstrip("/")
            private_token = os.environ.get("GITLAB_OAUTH_TOKEN")
            if private_token:
                self.gl = gitlab.Gitlab(base_url, private_token=private_token)
            else:
                raise RuntimeError("Missing GITLAB_OAUTH_TOKEN.")

    # -------- Group project discovery --------
    def iter_group_projects(self, group_id: int) -> Iterator[Project]:
        """
        Yield full Project objects for all projects in the given group (including subgroups).
        """
        try:
            group = self.gl.groups.get(id=group_id)
        except GitlabGetError as e:
            raise RuntimeError(f"Failed to get group {group_id}: {e}")

        try:
            for grp_proj in group.projects.list(iterator=True, include_subgroups=True):
                # grp_proj is a lightweight reference; fetch the full Project
                yield self.gl.projects.get(id=grp_proj.get_id())
        except GitlabListError as e:
            raise RuntimeError(f"Failed to list projects for group {group_id}: {e}")

    # -------- Repo / branch helpers --------
    def get_default_branch(self, project: Project) -> Optional[str]:
        """Return the project's default branch name (or None)."""
        return getattr(project, "default_branch", None)

    def get_http_url(self, project: Project) -> str:
        """Return the HTTPS clone URL for the project."""
        url = getattr(project, "http_url_to_repo", None)
        if not url:
            # Optional: fallback to SSH if you want
            raise RuntimeError(f"http_url_to_repo not found for project {project.id}")
        return url

    def get_branch(self, project: Project, name: str) -> ProjectBranch:
        """Return a branch object by exact name (raises if not found)."""
        try:
            return project.branches.get(name)
        except GitlabGetError as e:
            raise RuntimeError(f"Branch '{name}' not found in project {project.id}: {e}")

    def branch_exists(self, project: Project, name: str) -> bool:
        """
        Check if a branch exists by exact name.
        Using branches.get(name) is stricter than list(search=...).
        """
        try:
            project.branches.get(name)
            return True
        except GitlabGetError as e:
            if e.response_code == 404:
                return False
            raise

    def get_last_commit_info(self, project: Project, branch: str) -> Dict[str, Any]:
        """
        Return last commit info for the given branch as:
          {"message": <str>, "committed_date": <ISO8601 str or None>}
        """
        br = self.get_branch(project, branch)
        commit = getattr(br, "commit", None) or {}
        return {
            "message": commit.get("message", "") or "",
            "committed_date": commit.get("committed_date"),
        }

    # -------- Merge requests --------
    def mr_similar_exists(
        self,
        project: Project,
        author_username: Optional[str],
        search: str,
    ) -> bool:
        """
        Return True if there is an OPEN MR authored by the given (or current) user
        with a title/description matching the `search` text.
        """
        if author_username is None:
            author_username = self.get_bot_username()
        try:
            mrs = project.mergerequests.list(
                state="opened",
                author_username=author_username,
                search=search,
            )
            return len(mrs) > 0
        except GitlabListError as e:
            raise RuntimeError(f"Failed to list MRs in project {project.id}: {e}")

    def create_merge_request(
        self,
        project: Project,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ):
        """Create a merge request and return the MR object."""
        try:
            return project.mergerequests.create(
                {
                    "source_branch": source_branch,
                    "target_branch": target_branch,
                    "title": title,
                    "description": description,
                }
            )
        except GitlabCreateError as e:
            raise RuntimeError(f"Failed to create MR in project {project.id}: {e}")

    # -------- Identity --------
    def get_bot_username(self) -> str:
        """
        Return the bot's username:
          1) use GITLAB_USER_USERNAME if present (backward-compatible),
          2) otherwise, read the authenticated user from the API.
        """
        env_user = os.getenv("GITLAB_USER_USERNAME")
        if env_user:
            return env_user
        try:
            me = self.gl.user  # authenticated user
            uname = getattr(me, "username", None)
            if uname:
                return uname
        except Exception:
            pass
        raise RuntimeError("Cannot determine GitLab username (set GITLAB_USER_USERNAME or use a valid token).")

    def get_commit_identity(self) -> tuple[str, str]:
        """
        Return (name, email) to configure git commits performed by the bot.
        Falls back to sensible defaults if env vars are missing.
        """
        name = os.getenv("GITLAB_USER_NAME", "AI Analyzer")
        email = os.getenv("GITLAB_USER_EMAIL", "ai-doc@company.com")
        return name, email
