import json
import os
import tempfile
from pathlib import Path

from autodev.agents.base import AgentContext
from autodev.core.runtime import Orchestrator
from autodev.core.schemas import IsolationMode


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    issue_path = (
        repo_root
        / "docs/github_issue_drafts/backlog_v2"
        / "ad-028-define-base-integration-interfaces-and-typed-capability-contracts.md"
    )
    issue_body = issue_path.read_text(encoding="utf-8")
    issue_title = issue_body.splitlines()[0].lstrip("#").strip()

    work_dir = tempfile.mkdtemp(prefix="autodev_ad028_")
    isolation_mode = IsolationMode(os.environ.get("AUTODEV_ISOLATION_MODE", "snapshot"))
    orch = Orchestrator(work_dir=work_dir, dry_run=True, isolation_mode=isolation_mode)

    def fake_read_issue(ctx: AgentContext) -> AgentContext:
        meta = dict(ctx.metadata)
        meta.update(
            {
                "backlog_item_id": "AD-028",
                "issue_title": issue_title,
                "issue_body": issue_body,
                "repo_full_name": "alexanderjulianmartinez/autodev",
            }
        )
        return ctx.model_copy(update={"metadata": meta})

    orch._read_issue = fake_read_issue
    os.chdir(repo_root)
    ctx = orch.run_pipeline("https://github.com/alexanderjulianmartinez/autodev/issues/5")

    diff_path = str(ctx.metadata.get("implementation_diff_path", "")).strip()
    diff_excerpt = ""
    if diff_path and Path(diff_path).exists():
        diff_excerpt = "\n".join(
            Path(diff_path).read_text(encoding="utf-8", errors="ignore").splitlines()[:80]
        )

    result = {
        "work_dir": work_dir,
        "isolation_mode": isolation_mode.value,
        "run_id": ctx.metadata.get("run_id"),
        "review_decision": ctx.metadata.get("review_decision"),
        "review_summary": ctx.metadata.get("review_summary"),
        "plan": ctx.plan,
        "planning_mode": ctx.metadata.get("planning_mode"),
        "execution_strategy": ctx.metadata.get("execution_strategy"),
        "likely_target_files": ctx.metadata.get("likely_target_files"),
        "requested_changes": ctx.metadata.get("requested_changes"),
        "files_modified": ctx.files_modified,
        "validation_results": ctx.validation_results[:1000],
        "promote_stage": orch.stage_outputs.get("promote"),
        "implement_stage": orch.stage_outputs.get("implement"),
        "diff_path": diff_path,
        "diff_excerpt": diff_excerpt,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
