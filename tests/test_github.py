"""Tests for GitHub integration components."""

import pytest

from autodev.github.issue_reader import IssueReader


class TestIssueReader:
    def test_url_parsing_valid(self):
        reader = IssueReader()
        owner, repo, number = reader.parse_url("https://github.com/octocat/Hello-World/issues/42")
        assert owner == "octocat"
        assert repo == "Hello-World"
        assert number == 42

    def test_invalid_url_raises(self):
        reader = IssueReader()
        with pytest.raises(ValueError, match="Invalid GitHub issue URL"):
            reader.parse_url("https://github.com/octocat/Hello-World/pull/42")

    def test_no_token_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        reader = IssueReader()
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            reader.read("https://github.com/octocat/Hello-World/issues/1")

    def test_invalid_url_in_read_raises(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
        reader = IssueReader()
        with pytest.raises(ValueError, match="Invalid GitHub issue URL"):
            reader.read("https://notgithub.com/issues/1")


class TestPRCreator:
    def test_no_token_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        from autodev.github.pr_creator import PRCreator

        creator = PRCreator()
        with pytest.raises(EnvironmentError, match="GITHUB_TOKEN"):
            creator.create(
                repo_full_name="owner/repo",
                branch_name="feature/test",
                title="Test PR",
                body="Test body",
            )
