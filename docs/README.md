# AutoDev Documentation

## Architecture

AutoDev uses a pipeline-driven architecture:

```
issue → plan → code → test → review → PR
```

## Components

- **Core**: Runtime orchestrator, task graph (DAG), supervisor (safety)
- **Agents**: Planner, Coder, Reviewer, Debugger
- **Models**: Router + adapters for OpenAI, Anthropic, Gemini, and local models
- **Tools**: Shell, Filesystem, Git, TestRunner
- **GitHub**: Issue reader, repo cloner, PR creator
- **CLI**: `autodev init | run | fix-ci | status`

## Configuration

Configuration lives in `~/.autodev/`.

### models.yaml

```yaml
models:
  planner: claude-sonnet
  coder: gpt-4.1
  reviewer: claude-opus
```

### pipelines.yaml

```yaml
pipelines:
  default:
    max_iterations: 3
    stages:
      - name: plan
      - name: code
        depends_on: [plan]
      - name: test
        depends_on: [code]
      - name: review
        depends_on: [test]
```

## Environment Variables

| Variable | Purpose |
|---|---|
| `GITHUB_TOKEN` | Read issues and create PRs |
| `OPENAI_API_KEY` | Use OpenAI models |
| `ANTHROPIC_API_KEY` | Use Anthropic Claude models |
| `GOOGLE_API_KEY` | Use Google Gemini models |
