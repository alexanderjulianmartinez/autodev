# Autonomous Dev Runtime (AutoDev)

## Technical Specification & Agent Context

Version: v0.1
Purpose: Context document for autonomous agents and developers building the AutoDev Runtime.

---

# 1. Overview

AutoDev Runtime is an **open-source, model-agnostic autonomous engineering runtime** that allows agents to:

* analyze software repositories
* plan engineering tasks
* write and modify code
* run tests
* debug failures
* open pull requests
* optionally deploy working systems

The system is designed to act like an **autonomous software engineer** that operates on engineering tasks such as GitHub issues.

The runtime should support multiple LLM providers and should not be tightly coupled to any specific model.

---

# 2. Core Philosophy

AutoDev should behave like **Terraform for AI development workflows**.

Not:

```
ChatGPT with tools
```

But:

```
Deterministic engineering pipelines executed by agents.
```

Core principles:

* model-agnostic
* pipeline-driven workflows
* deterministic execution
* GitHub-native workflow
* local-first execution
* extensible architecture

---

# 3. Key Features (v1)

The v1 system should allow a user to run:

```
autodev run <github_issue_url>
```

The system will:

1. read the issue
2. analyze the repository
3. generate an implementation plan
4. write code
5. run tests
6. commit changes
7. open a pull request

This workflow is the **minimal autonomous engineering loop**.

---

# 4. System Architecture

High-level architecture:

```
                 CLI
                  │
           Runtime Orchestrator
                  │
            Task Graph Engine
                  │
       ┌──────────┼──────────┐
       │          │          │
    Planner     Coder      Tester
       │          │          │
       └──────────┼──────────┘
                  │
              Tool Layer
                  │
     ┌────────────┼────────────┐
     │            │            │
    Git         Shell       Filesystem
                  │
              Test Runner
                  │
            GitHub Integration
                  │
               Pull Request
```

---

# 5. Repository Structure

Recommended repository layout:

```
autodev/
│
├── core/
│   ├── runtime.py
│   ├── orchestrator.py
│   ├── task_graph.py
│   └── supervisor.py
│
├── agents/
│   ├── planner.py
│   ├── coder.py
│   ├── reviewer.py
│   └── debugger.py
│
├── models/
│   ├── router.py
│   └── adapters/
│       ├── openai_adapter.py
│       ├── anthropic_adapter.py
│       ├── gemini_adapter.py
│       └── local_adapter.py
│
├── tools/
│   ├── git_tool.py
│   ├── shell_tool.py
│   ├── filesystem_tool.py
│   └── test_runner.py
│
├── github/
│   ├── issue_reader.py
│   ├── repo_cloner.py
│   └── pr_creator.py
│
├── cli/
│   └── main.py
│
├── configs/
│   ├── models.yaml
│   └── pipelines.yaml
│
├── examples/
│
├── tests/
│
└── docs/
```

---

# 6. Core Runtime Components

## Runtime Orchestrator

Responsible for:

* coordinating agent execution
* passing context between tasks
* tracking pipeline state

Example interface:

```
runtime.run_pipeline(issue)
```

---

## Task Graph Engine

All workflows should be represented as a **directed acyclic graph (DAG)**.

Example:

```
task: implement_feature

plan
  │
code
  │
test
  │
review
```

Each node:

* receives context
* produces structured output

---

## Supervisor

Supervisor prevents unsafe or broken execution.

Responsibilities:

* detect infinite loops
* prevent destructive shell commands
* limit execution steps
* enforce resource constraints

---

# 7. Agent System

Agents are modular components that perform specific tasks.

Example agents:

```
planner
coder
tester
reviewer
debugger
```

Agent interface:

```python
class Agent:

    def run(self, task, context):
        return result
```

Agents should use tools rather than directly executing system actions.

---

# 8. Model Abstraction Layer

The runtime must support multiple LLM providers.

Unified interface:

```
model.generate(prompt, context)
```

Adapters translate provider APIs to this interface.

Supported providers (initial):

* OpenAI
* Anthropic
* Google
* Local models

Example configuration:

```
models:
  planner: claude-sonnet
  coder: gpt-4.1
  reviewer: claude-opus
```

---

# 9. Tool System

Agents interact with the system through tools.

Example tools:

```
git clone
git commit
file read/write
run shell command
run tests
```

Tool interface:

```python
class Tool:

    def execute(self, input):
        return output
```

Tools enforce guardrails and logging.

---

# 10. GitHub Integration

GitHub issues act as **task inputs**.

Example workflow:

```
autodev run https://github.com/org/repo/issues/23
```

Execution flow:

```
read issue
clone repo
create branch
run pipeline
commit changes
open PR
```

Libraries:

* PyGithub
* GitPython

---

# 11. CLI Interface

Primary user interface.

Example commands:

```
autodev init
autodev run
autodev fix-ci
autodev status
```

Example output:

```
Analyzing issue...
Generating plan...
Writing code...
Running tests...
Opening PR...
```

---

# 12. Minimal Pipeline (v1)

The minimal pipeline should be:

```
issue → plan → code → test → PR
```

Steps:

1. planner agent generates plan
2. coder agent modifies files
3. test runner executes tests
4. commit and open PR

---

# 13. Three Architectural Tricks That Make Autonomous Agents 10× More Reliable

These are critical design patterns used by production autonomous coding systems.

---

## Trick 1: Structured Planning

Agents should generate structured implementation plans.

Example:

```
Plan:

1 modify auth_service.py
2 update token validation logic
3 add test case in test_auth.py
```

The plan becomes the **execution contract**.

Execution must follow the plan.

This reduces hallucinated changes.

---

## Trick 2: Deterministic Task Graphs

Agent workflows should not be free-form loops.

Instead use deterministic pipelines.

Bad:

```
agent.think()
agent.try_again()
```

Good:

```
plan → code → test → review
```

Each stage:

* produces output
* validates results
* passes structured context

This dramatically improves reliability.

---

## Trick 3: Execution Feedback Loops

Agents must read execution outputs.

Example loop:

```
write code
run tests
read failure logs
patch code
repeat
```

The system should retry a limited number of iterations.

Example:

```
max_iterations = 3
```

This enables self-correction.

---

# 14. Logging and Observability

All agent actions must be logged.

Logs should include:

* prompts
* tool calls
* file edits
* command outputs
* errors

This enables debugging and evaluation.

---

# 15. Safety Constraints

Agents should not execute:

```
rm -rf /
sudo operations
network exfiltration
system modification outside repo
```

Shell commands must be sandboxed.

---

# 16. Local-First Execution

The system should run locally.

Installation:

```
pip install autodev
```

Run:

```
autodev run
```

All compute runs locally except model API calls.

---

# 17. Recommended Tech Stack

Language:

```
Python
```

Key libraries:

```
Typer (CLI)
PyGithub
GitPython
pydantic
rich (console UI)
pytest
```

Optional:

```
tree-sitter (code parsing)
ripgrep (repo search)
```

---

# 18. Future Roadmap

## Phase 2

Add:

* debugging agent
* reviewer agent
* repo knowledge graph
* better code search

---

## Phase 3

Add:

* parallel agents
* container sandbox
* CI integration
* long-running sessions

---

## Phase 4

Add:

* autonomous deployment pipelines
* infra agents
* distributed task execution

---

# 19. Killer Feature Candidates

Potential viral features:

```
autodev fix-ci
```

The system:

1 reads CI logs
2 identifies failure
3 patches code
4 opens PR

Developers could use this daily.

---

# 20. Success Criteria for v1

The system is considered successful if it can:

* analyze a GitHub issue
* modify code in a repository
* run tests
* create a valid pull request

---

# 21. Development Goal

The v1 system should be achievable within **3–4 weeks of development**.

Focus on:

* reliability
* minimal architecture
* clear CLI workflow

Avoid building large infrastructure prematurely.
