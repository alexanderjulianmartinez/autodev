"""AutoDev GitHub integration."""

from autodev.github.ci_intake import CIIntakeService
from autodev.github.ci_runner import CIRunData, CIRunReader
from autodev.github.issue_reader import IssueData, IssueReader
from autodev.github.pr_creator import PRCreator
from autodev.github.repo_cloner import RepoCloner

# GitHubGitAdapter and its factory are in the adapters subpackage.
# Import from autodev.github.adapters.git_platform directly to avoid
# a circular import chain through autodev.integrations.base.
# (autodev.github.adapters.git_platform is not re-exported here.)

__all__ = [
    "CIIntakeService",
    "CIRunData",
    "CIRunReader",
    "IssueData",
    "IssueReader",
    "PRCreator",
    "RepoCloner",
]
