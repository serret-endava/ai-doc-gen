# Project Title: AI-Powered Code Analysis and Documentation CLI Tool

## Project Overview

This project is a command-line interface (CLI) tool designed to perform asynchronous AI-driven code analysis and documentation generation on software repositories. It integrates with external Git repository services such as GitLab and Bitbucket to automate project analysis, generate detailed markdown reports, and create merge requests with analysis results.

### Purpose and Main Functionality
- Analyze code repositories asynchronously using AI agents.
- Generate comprehensive README documentation automatically.
- Automate scheduled analysis jobs on GitLab projects with merge request creation.
- Provide a modular, extensible CLI interface for various code analysis and documentation tasks.

### Key Features and Capabilities
- CLI commands for analysis (`analyze`), documentation generation (`document`), and scheduled cronjob analysis (`cronjob analyze`).
- Asynchronous execution of AI agents for efficient processing.
- Integration with GitLab and Bitbucket APIs for project discovery, cloning, and merge request management.
- Configuration management via Pydantic models and YAML config files.
- Structured logging and telemetry with OpenTelemetry and Langfuse.
- Resilient HTTP client with retry and exponential backoff.

### Likely Intended Use Cases
- Developers and teams seeking automated insights into codebases.
- Continuous integration pipelines requiring automated code analysis and documentation.
- Scheduled maintenance jobs to keep project documentation and analysis up to date.
- Organizations using GitLab or Bitbucket for source control and merge request workflows.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [C4 Model Architecture](#c4-model-architecture)
- [Repository Structure](#repository-structure)
- [Dependencies and Integration](#dependencies-and-integration)
- [API Documentation](#api-documentation)
- [Development Notes](#development-notes)
- [Known Issues and Limitations](#known-issues-and-limitations)
- [Additional Documentation](#additional-documentation)

---

## Architecture

### High-level Architecture Overview

The system is a modular CLI tool that orchestrates asynchronous AI agents to analyze code repositories and generate documentation. It integrates with external Git services for project management and automates merge request creation. The architecture separates concerns into handlers, agents, providers, and utilities.

### Technology Stack and Frameworks

- Python 3 with asynchronous programming (asyncio)
- Pydantic for data validation and configuration management
- Jinja2 for prompt templating
- OpenTelemetry and Langfuse for telemetry and tracing
- GitLab and Bitbucket API clients
- HTTPX and Tenacity for resilient HTTP client with retry logic
- GitPython for git repository operations

### Component Relationships

```mermaid
flowchart TB
  subgraph CLI
    A[CLI Entry Point (src/main.py)]
  end

  subgraph Handlers
    B1[AnalyzeHandler]
    B2[ReadmeHandler]
    B3[JobAnalyzeHandler]
  end

  subgraph Agents
    C1[AnalyzerAgent]
    C2[DocumenterAgent]
  end

  subgraph Providers
    D1[GitLabProvider]
    D2[BitbucketProvider]
  end

  subgraph Utils
    E1[Logger]
    E2[PromptManager]
    E3[Retrying HTTP Client]
    E4[Repo Utilities]
  end

  A -->|Dispatch commands| B1
  A --> B2
  A --> B3

  B1 -->|Invoke| C1
  B2 -->|Invoke| C2
  B3 -->|Use| B1
  B3 -->|Use| D1

  B1 --> E1
  B2 --> E1
  B3 --> E1

  C1 --> E2
  C2 --> E2

  D1 --> E3
  D2 --> E3

  B3 --> D1

  style A fill:#f9f,stroke:#333,stroke-width:2px
  style B1 fill:#bbf,stroke:#333,stroke-width:1px
  style B2 fill:#bbf,stroke:#333,stroke-width:1px
  style B3 fill:#bbf,stroke:#333,stroke-width:1px
  style C1 fill:#bfb,stroke:#333,stroke-width:1px
  style C2 fill:#bfb,stroke:#333,stroke-width:1px
  style D1 fill:#ffb,stroke:#333,stroke-width:1px
  style D2 fill:#ffb,stroke:#333,stroke-width:1px
  style E1 fill:#fbb,stroke:#333,stroke-width:1px
  style E2 fill:#fbb,stroke:#333,stroke-width:1px
  style E3 fill:#fbb,stroke:#333,stroke-width:1px
  style E4 fill:#fbb,stroke:#333,stroke-width:1px
```

### Key Design Patterns

- Factory pattern for provider instantiation based on configuration.
- Dependency injection via constructor parameters for handlers and providers.
- Asynchronous programming with async/await for concurrency.
- Template rendering for prompt generation using Jinja2.

---

## C4 Model Architecture

<details>
<summary>Context Diagram</summary>

```mermaid
flowchart TB
  User[User (Developer/CI System)]
  CLI[CLI Tool]
  GitLab[GitLab Service]
  Bitbucket[Bitbucket Service]
  LLM[LLM Providers (OpenAI, Gemini)]

  User -->|Runs commands| CLI
  CLI -->|Uses API tokens| GitLab
  CLI -->|Uses API tokens| Bitbucket
  CLI -->|Calls| LLM

  classDef external fill:#f96,stroke:#333,stroke-width:1px,color:#000
  class GitLab,Bitbucket,LLM external
```

</details>

<details>
<summary>Container Diagram</summary>

```mermaid
flowchart TB
  subgraph CLI Tool
    direction TB
    Main[Main CLI Entry (src/main.py)]
    Handlers[Handlers]
    Agents[Agents]
    Providers[Providers]
    Utils[Utilities]
  end

  Main -->|Dispatch commands| Handlers
  Handlers -->|Invoke asynchronously| Agents
  Handlers -->|Use| Providers
  Handlers -->|Use| Utils
  Providers -->|HTTP API calls| ExternalAPIs[GitLab/Bitbucket APIs]
  Agents -->|Call| LLMs[LLM APIs]

  class ExternalAPIs external
  class LLMs external
```

</details>

---

## Repository Structure

| Directory/File         | Purpose                                      |
|-----------------------|----------------------------------------------|
| `src/main.py`          | CLI entry point and command dispatcher       |
| `src/handlers/`        | Command handlers for analyze, document, cronjob |
| `src/agents/`          | AI agent implementations for analysis and documentation |
| `src/providers/`       | External service API clients (GitLab, Bitbucket) |
| `src/utils/`           | Shared utilities (logging, prompt management, HTTP client) |
| `.ai/docs/`            | Generated markdown analysis and documentation files |

---

## Dependencies and Integration

### Internal and External Service Dependencies

- GitLab API for project discovery, cloning, branch and merge request management.
- Bitbucket API for similar repository and pull request management.
- LLM providers (OpenAI, Gemini) for AI-driven code analysis and documentation.
- Logging and telemetry services via OpenTelemetry and Langfuse.

### Event Streams or Message Queues

- None detected; the system operates as a CLI tool without event streaming or message queue integration.

---

## API Documentation

### CLI Commands

| Command           | Description                                | Key Parameters                                   | Output                                   |
|-------------------|--------------------------------------------|-------------------------------------------------|------------------------------------------|
| `analyze`         | Runs code analysis on a repository         | `--repo-path` (required), exclude flags for analysis types | Markdown analysis files in `.ai/docs/`  |
| `document`        | Generates README documentation              | `--repo-path` (required), section exclusion flags, `--use-existing-readme` | `README.md` in repository root           |
| `cronjob analyze` | Automated GitLab project analysis and MR creation | `--max-days-since-last-commit`, `--working-path`, `--group-project-id` | Merge requests with analysis results     |

### Request/Response Formats

- **analyze**
  - Request: CLI arguments parsed into `AnalyzeHandlerConfig` including repository path and analysis options.
  - Response: Markdown files generated under `.ai/docs/` directory.

- **document**
  - Request: CLI arguments parsed into `ReadmeHandlerConfig`.
  - Response: `README.md` file written to repository root.

- **cronjob analyze**
  - Request: CLI arguments parsed into `JobAnalyzeHandlerConfig`.
  - Response: Merge requests created in GitLab projects with analysis results.

### Authentication

- GitLab and Bitbucket API tokens configured via environment variables.
- LLM API keys configured via environment variables.

---

## Development Notes

- Use Pydantic models for configuration and validation.
- Follow asynchronous programming patterns with async/await.
- Logging is centralized via the `Logger` utility.
- Testing should cover handlers, agents, and provider integrations.
- Performance considerations include asynchronous execution and HTTP client retry logic.

---

## Known Issues and Limitations

- No explicit user authentication or authorization middleware; relies on API tokens.
- Manual dependency injection may increase boilerplate.
- Tight coupling to GitLab API in cronjob handler could be abstracted further.
- Additional documentation on agent prompt templates and internal data models would be helpful.

---

## Additional Documentation

- See `.ai/docs/api_analysis.md` for detailed API and integration documentation.
- See `.ai/docs/request_flow_analysis.md` for request lifecycle and flow.
- See `.ai/docs/data_flow_analysis.md` for data modeling and transformation.
- See `.ai/docs/dependency_analysis.md` for dependency and module relationships.

---

*This README was generated automatically based on codebase analysis to assist new developers in understanding and contributing to the project.*
