# Request Flow Analysis

## Entry Points Overview

The primary entry point for the system is the CLI interface defined in `src/main.py`. The CLI accepts commands such as `analyze`, `document`, and `cronjob analyze`. Each command corresponds to a specific handler that processes the request asynchronously.

- `analyze`: Invokes the `AnalyzeHandler` to perform code analysis on a specified repository.
- `document`: Invokes the `ReadmeHandler` to generate README documentation.
- `cronjob analyze`: Invokes the `JobAnalyzeHandler` to run scheduled analysis jobs on GitLab projects.

The CLI parses command-line arguments, loads configuration, sets up logging, and dispatches to the appropriate handler.

## Request Routing Map

- CLI command parsing in `src/main.py` routes requests based on the `command` and `sub_command` arguments.
- `analyze` command routes to `AnalyzeHandler` in `src/handlers/analyze.py`.
- `document` command routes to `ReadmeHandler` in `src/handlers/readme.py`.
- `cronjob analyze` command routes to `JobAnalyzeHandler` in `src/handlers/cronjob.py`.

Each handler is configured with a Pydantic config model that merges CLI args and config file values.

## Middleware Pipeline

The system is a CLI tool and does not have traditional HTTP middleware. However, it includes preprocessing steps:

- Configuration loading and merging from CLI args and YAML config files (`src/config.py`).
- Logging setup with file and console handlers (`src/utils/logger.py`).
- Telemetry instrumentation with OpenTelemetry and Langfuse (conditional on config).

These steps act as middleware-like preprocessing before the handler's main logic executes.

## Controller/Handler Analysis

- `AnalyzeHandler` (`src/handlers/analyze.py`): Initializes an `AnalyzerAgent` and runs analysis asynchronously. It uses OpenTelemetry spans for tracing.
- `ReadmeHandler` (`src/handlers/readme.py`): Initializes a `DocumenterAgent` and runs documentation generation asynchronously with tracing.
- `JobAnalyzeHandler` (`src/handlers/cronjob.py`): Runs scheduled analysis jobs on GitLab projects. It clones projects, runs analysis via `AnalyzeHandler`, creates merge requests, and cleans up.

All handlers inherit from `BaseHandler` which enforces an async `handle()` method.

## Authentication & Authorization Flow

- GitLab API access is managed via OAuth tokens configured in environment variables (`GITLAB_OAUTH_TOKEN`).
- The `JobAnalyzeHandler` uses the GitLab client with this token to list projects, clone repos, and create merge requests.
- No explicit user authentication or authorization middleware is present since this is a CLI tool.

## Error Handling Pathways

- Handlers log errors with structured logging using the centralized `Logger` utility.
- The `JobAnalyzeHandler` catches exceptions per project to continue processing other projects.
- CLI argument parsing errors cause the program to exit with error codes.
- Unknown commands or subcommands print error messages and exit.

## Request Lifecycle Diagram

```text
User CLI Input
    |
    v
Argument Parsing (src/main.py)
    |
    v
Configuration Loading & Merging (src/config.py)
    |
    v
Logging & Telemetry Setup (src/main.py, src/utils/logger.py)
    |
    v
Dispatch to Handler (AnalyzeHandler, ReadmeHandler, JobAnalyzeHandler)
    |
    v
Handler.handle() async execution
    |
    v
Agent Execution (AnalyzerAgent, DocumenterAgent)
    |
    v
Result returned and logged
    |
    v
CLI exits with status
```

This flow captures the lifecycle of a request from CLI input through configuration, logging, handler execution, and final exit.

---

This analysis is based on the current codebase in the `src/` directory and environment configuration.
