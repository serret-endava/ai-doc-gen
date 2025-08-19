# src/providers/__init__.py
import os
from typing import Optional

import config
from .gitlab import GitLabProvider


def get_provider(name: str = "gitlab", client=None, **kwargs):
    """
    Returns the provider instance.
    Priority:
      1) explicit `name` argument (e.g., "gitlab", "bitbucket")
      2) default "gitlab"
    """
    match name.lower():
        case "gitlab":
            if client is None:
                from gitlab import Gitlab
                client = Gitlab(
                    url=config.GITLAB_API_URL,
                    oauth_token=config.GITLAB_OAUTH_TOKEN,
                )
            return GitLabProvider(gitlab_client=client)
        case "bitbucket":
            from .bitbucket import BitbucketProvider
            return BitbucketProvider(project_key=kwargs.get("bitbucket_project_key"))
        case _:
            raise ValueError(
                f"Provider not supported: {name} ... "
                "provider should be: gitlab, bitbucket"
            )
