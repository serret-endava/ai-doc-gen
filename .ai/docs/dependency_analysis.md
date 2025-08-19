# Dependency Analysis

## Internal Dependencies Map
- The project is structured with a clear separation of concerns into directories: `handlers`, `providers`, and `utils` under `src`.
- `handlers` contain the main business logic handlers: `AnalyzeHandler`, `ReadmeHandler`, and `JobAnalyzeHandler` (cronjob).
  - `AnalyzeHandler` depends on `AnalyzerAgent` from `agents.analyzer` and utilities like `Logger` and `get_repo_version`.
  - `ReadmeHandler` depends on `DocumenterAgent` from `agents.documenter` and similar utilities.
  - `JobAnalyzeHandler` integrates with GitLab API and uses `AnalyzeHandler` internally to perform analysis on cloned projects.
- `providers` implement external service integrations for GitLab and Bitbucket, exposing a common interface for project iteration, branch management, MR creation, etc.
  - `get_provider` factory function returns provider instances based on name, supporting `gitlab` and `bitbucket`.
- `utils` provide shared utilities:
  - `Logger` for centralized logging
  - `PromptManager` for managing and rendering YAML-based prompts
  - `retry_client` for HTTP client with retry logic
  - `repo` for git repository utilities
  - `dict` for dictionary utilities

## External Libraries Analysis
- Core dependencies from `pyproject.toml` include:
  - `pydantic` (>=2.11.7) for data validation and settings management
  - `psutil` (>=7.0.0) for system and process utilities
  - `jinja2` (>=3.1.6) for templating (used in `PromptManager`)
  - `ujson` (>=5.10.0) for fast JSON serialization (used in `Logger`)
  - `pydantic-ai[logfire]` (>=0.5.0) for AI-related extensions and logging instrumentation
  - `nest-asyncio` (>=1.6.0) to allow nested asyncio loops
  - `python-gitlab` (>=6.2.0) for GitLab API integration
  - `gitpython` (>=3.1.45) for git repository operations
  - `logfire` (>=4.1.0) for structured logging and telemetry
  - `pyyaml` (>=6.0.2) for YAML parsing (used in `PromptManager`)
  - `python-dotenv` (>=1.1.1) for environment variable loading
  - `opentelemetry-instrumentation-httpx` (>=0.57b0) for HTTP client instrumentation

## Service Integrations
- GitLab integration:
  - Uses `python-gitlab` client wrapped by `GitLabProvider` in `src/providers/gitlab.py`.
  - `JobAnalyzeHandler` uses GitLab API to list projects, clone repos, check branches, create merge requests.
- Bitbucket integration:
  - `BitbucketProvider` in `src/providers/bitbucket.py` uses REST API with `requests`.
  - Supports similar interface as GitLab provider for project iteration, branch checks, MR creation.
- Logging and telemetry:
  - Uses `logfire` for structured logging and telemetry.
  - OpenTelemetry traces are created in handlers (`AnalyzeHandler`, `ReadmeHandler`).
- HTTP client with retry logic is provided by `utils.retry_client` using `httpx` and `tenacity`.

## Dependency Injection Patterns
- Providers are instantiated via a factory function `get_provider` in `src/providers/__init__.py` based on a string name.
- `JobAnalyzeHandler` receives a `Gitlab` client instance injected at construction.
- Handlers receive configuration objects (Pydantic models) injected at construction.
- The main CLI (`src/main.py`) wires together handlers, configs, and providers explicitly.
- No complex DI container or framework is used; dependency injection is manual and explicit.

## Module Coupling Assessment
- Modules are loosely coupled with clear interfaces:
  - Handlers depend on agents and utils.
  - Providers abstract external service APIs.
  - Utils are independent helper modules.
- Some coupling exists between `JobAnalyzeHandler` and GitLab API, but it is encapsulated in the provider.
- Configuration is centralized via Pydantic models, promoting cohesion.
- Logging is centralized via a singleton `Logger`.

## Dependency Graph
- `src/main.py` (CLI entry point)
  - depends on `config`, `handlers`, `providers`, `utils.Logger`
- `handlers/analyze.py`
  - depends on `agents.analyzer`, `utils.repo`, `utils.Logger`, `opentelemetry`
- `handlers/readme.py`
  - depends on `agents.documenter`, `utils.repo`, `utils.Logger`, `opentelemetry`
- `handlers/cronjob.py`
  - depends on `gitlab`, `handlers.analyze`, `utils.Logger`, `config`
- `providers/__init__.py`
  - depends on `gitlab`, `bitbucket`, `config`
- `providers/gitlab.py`
  - depends on `python-gitlab`
- `providers/bitbucket.py`
  - depends on `requests`
- `utils/logger.py`
  - depends on `logging`, `ujson`
- `utils/prompt_manager.py`
  - depends on `jinja2`, `pyyaml`
- `utils/retry_client.py`
  - depends on `httpx`, `tenacity`, `pydantic-ai`

## Potential Dependency Issues
- No circular dependencies detected in the main modules.
- Manual dependency injection may lead to boilerplate in wiring components.
- Tight coupling to GitLab API in `JobAnalyzeHandler` could be abstracted further for better testability.
- Use of global singleton logger may limit flexibility in some contexts.
- External service providers rely on environment variables for credentials, which requires careful management.

---

This analysis provides a comprehensive overview of the dependency structure, external integrations, and internal module relationships to aid maintainers and developers in understanding and evolving the system.
