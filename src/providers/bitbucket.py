# providers/bitbucket.py
import os
import requests
from dataclasses import dataclass
from typing import Iterator, Optional, Dict, Any
from urllib.parse import quote

DEFAULT_API_URL = "https://api.bitbucket.org/2.0"

@dataclass
class _BBProjectRef:
    """
    Lightweight repository reference the handler can work with.
    We keep `.id` for parity with the GitLab shape (here it’s the repo slug).
    """
    id: str          # repo slug (used as a stable id within a workspace)
    slug: str
    uuid: str
    name: str
    full_name: str   # "<workspace>/<slug>"


class BitbucketProvider:
    """
    Bitbucket Cloud provider exposing the SAME surface expected by your handler:

      - iter_group_projects(group_id) -> Iterator[_BBProjectRef]
      - get_default_branch(project) -> str | None
      - get_http_url(project) -> str
      - get_last_commit_info(project, branch) -> {"message", "committed_date"}
      - branch_exists(project, name) -> bool
      - get_branch(project, name) -> dict | raises if 404 (added for parity)
      - mr_similar_exists(project, author_username, search) -> bool
      - create_merge_request(project, source_branch, target_branch, title, description) -> dict-like
      - get_bot_username() -> str
      - get_commit_identity() -> tuple[str, str]

    Required env vars:
      - BITBUCKET_USERNAME
      - BITBUCKET_APP_PASSWORD
      - BITBUCKET_WORKSPACE

    Optional:
      - BITBUCKET_API_URL (defaults to https://api.bitbucket.org/2.0)
      - BITBUCKET_USER_NAME / BITBUCKET_USER_EMAIL (git commit identity)

    NOTE:
      `project_key` is now passed via constructor to allow CLI flags.
    """

    def __init__(self, project_key: Optional[str] = None) -> None:
        # Base API URL and credentials
        self.api_url = os.getenv("BITBUCKET_API_URL", DEFAULT_API_URL).rstrip("/")
        self.username = os.environ["BITBUCKET_USERNAME"]
        self.app_password = os.environ["BITBUCKET_APP_PASSWORD"]
        self.workspace = os.environ["BITBUCKET_WORKSPACE"]

        # Project filter coming from CLI (or None for “all repos in workspace”)
        self.project_key = project_key

        # Reuse a single session (auth + default headers)
        self.s = requests.Session()
        self.s.auth = (self.username, self.app_password)
        self.s.headers.update({
            "Accept": "application/json",
            "User-Agent": "ai-doc-gen/bitbucket-provider"
        })

        # Cache for /user response
        self._me_cache: Optional[Dict[str, Any]] = None

    # ----------------- HTTP utils -----------------
    def _get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        ok_404: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        GET wrapper with optional 404 tolerance.
        If ok_404=True and the server returns 404, return None instead of raising.
        """
        r = self.s.get(url, params=params, timeout=30)
        if ok_404 and r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def _post(self, url: str, json: Dict[str, Any]) -> Dict[str, Any]:
        """Simple POST wrapper that raises on non-2xx."""
        r = self.s.post(url, json=json, timeout=30)
        r.raise_for_status()
        return r.json()

    def _me(self) -> Dict[str, Any]:
        """Fetch current authenticated user once and cache it."""
        if self._me_cache is None:
            self._me_cache = self._get(f"{self.api_url}/user")
        return self._me_cache

    # ----------------- Repository enumeration -----------------
    def iter_group_projects(self, group_id: int) -> Iterator[_BBProjectRef]:
        """
        Bitbucket Cloud has no 'group' like GitLab. We enumerate repositories in the WORKSPACE.
        `group_id` is ignored to keep the signature consistent with the GitLab provider.
        Optionally filter by project key if one was provided to the constructor.
        """
        url = f"{self.api_url}/repositories/{self.workspace}"
        params: Dict[str, Any] = {"pagelen": 100}
        if self.project_key:
            # Bitbucket search query: filter by project key
            params["q"] = f'project.key="{self.project_key}"'

        while url:
            data = self._get(url, params=params)
            for repo in data.get("values", []):
                yield _BBProjectRef(
                    id=repo["slug"],
                    slug=repo["slug"],
                    uuid=repo["uuid"],
                    name=repo["name"],
                    full_name=repo["full_name"],  # "workspace/slug"
                )
            # Pagination: `next` already contains a cursor; no need to repeat params
            url = data.get("next")
            params = None

    # ----------------- Repository properties -----------------
    def get_default_branch(self, project: _BBProjectRef) -> Optional[str]:
        """
        Return the main branch name (e.g., 'main' or 'master').
        Returns None if the repo has no main branch configured yet.
        """
        data = self._get(f"{self.api_url}/repositories/{self.workspace}/{project.slug}")
        main = data.get("mainbranch") or {}
        return main.get("name")

    def get_http_url(self, project: _BBProjectRef) -> str:
        """
        Return the HTTPS clone URL. Raises if not present (rare).
        Example: https://bitbucket.org/<workspace>/<repo>.git
        """
        data = self._get(f"{self.api_url}/repositories/{self.workspace}/{project.slug}")
        clones = (data.get("links") or {}).get("clone", [])
        https = next((c for c in clones if c.get("name") == "https"), None)
        if not https or not https.get("href"):
            raise RuntimeError(f"HTTPS clone URL not found for {project.full_name}")
        return https["href"]

    def get_last_commit_info(self, project: _BBProjectRef, branch: str) -> Dict[str, Any]:
        """
        Fetch the latest commit on the given branch.
        Returns a dict with 'message' and 'committed_date'. If no commits, returns empty fields.
        """
        data = self._get(
            f"{self.api_url}/repositories/{self.workspace}/{project.slug}/commits/{quote(branch)}",
            params={"pagelen": 1},
        )
        values = data.get("values", [])
        if not values:
            return {"message": "", "committed_date": None}
        c = values[0]
        # Bitbucket timestamps look like "2025-08-17T09:21:15+00:00"
        return {
            "message": c.get("message", "") or "",
            "committed_date": c.get("date"),
        }

    # ----------------- Branches -----------------
    def branch_exists(self, project: _BBProjectRef, name: str) -> bool:
        """
        Direct branch lookup; 404 means it does not exist.
        URL-escape the branch name to handle slashes or spaces.
        """
        data = self._get(
            f"{self.api_url}/repositories/{self.workspace}/{project.slug}/refs/branches/{quote(name)}",
            ok_404=True,
        )
        return data is not None

    def get_branch(self, project: _BBProjectRef, name: str) -> Dict[str, Any]:
        """
        Parity helper with GitLab provider:
        - Returns the branch object when it exists.
        - Raises `requests.HTTPError` (status 404) when it doesn't.
        """
        data = self._get(
            f"{self.api_url}/repositories/{self.workspace}/{project.slug}/refs/branches/{quote(name)}",
            ok_404=False,
        )
        return data

    # ----------------- Pull Requests (MR equivalent) -----------------
    def mr_similar_exists(self, project: _BBProjectRef, author_username: str, search: str) -> bool:
        """
        Check if an open PR exists with a similar title (and, when possible, same author).
        Uses Bitbucket's query language:
          - state="OPEN" AND title ~ "text"
          - optionally author.uuid or author.nickname
        """
        # Defensive escaping for quotes inside the search string
        safe_search = search.replace('"', r'\"')
        q = f'state="OPEN" AND title ~ "{safe_search}"'

        # Try to narrow by author identity (falls back to title-only if /user fails)
        try:
            me = self._me()
            if me.get("uuid"):
                q += f' AND author.uuid = "{me["uuid"]}"'
            elif author_username:
                q += f' AND author.nickname = "{author_username}"'
        except Exception:
            pass

        data = self._get(
            f"{self.api_url}/repositories/{self.workspace}/{project.slug}/pullrequests",
            params={"q": q, "pagelen": 1},
        )
        return (data.get("size") or 0) > 0

    def create_merge_request(
        self,
        project: _BBProjectRef,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> Dict[str, Any]:
        """
        Create a pull request (MR equivalent) on Bitbucket Cloud.
        Returns a dict containing at least id/title/web_url for logging.
        """
        payload = {
            "title": title,
            "description": description,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": target_branch}},
            "close_source_branch": False,
        }
        data = self._post(
            f"{self.api_url}/repositories/{self.workspace}/{project.slug}/pullrequests",
            json=payload,
        )
        return {
            "id": data.get("id"),
            "title": data.get("title"),
            "web_url": (data.get("links") or {}).get("html", {}).get("href"),
        }

    # ----------------- Identity helpers -----------------
    def get_bot_username(self) -> str:
        """
        Return the bot's username to match PR author filtering.
        Priority:
          1) BITBUCKET_USERNAME (the login used with App Password)
          2) /user.nickname (or legacy username)
        """
        env_user = os.getenv("BITBUCKET_USERNAME")
        if env_user:
            return env_user
        me = self._me()
        return me.get("nickname") or me.get("username") or "unknown"

    def get_commit_identity(self) -> tuple[str, str]:
        """
        Name/email used for git commits made by the bot.
        You can define BITBUCKET_USER_NAME / BITBUCKET_USER_EMAIL;
        sensible defaults are provided as fallback.
        """
        name = os.getenv("BITBUCKET_USER_NAME", "AI Analyzer")
        email = os.getenv("BITBUCKET_USER_EMAIL", "ai-doc@company.com")
        return name, email
