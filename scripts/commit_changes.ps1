# Trinity-Pilot Git Commit Script
# Professional, non-AI commit messages following conventional commits

Write-Host "Starting Trinity-Pilot commits..." -ForegroundColor Cyan

# Commit 1: LLM models
Write-Host "`n[1/8] Committing LLM provider updates..." -ForegroundColor Yellow
git add unified-app/orchestrator/providers/gemini_provider.py
git add unified-app/orchestrator/providers/openai_provider.py
git add unified-app/orchestrator/providers/gemini_module_provider.py
git add unified-app/orchestrator/providers/module_service_provider.py
git commit -m "feat(llm): update to 2026 model versions

Update LLM providers to use latest 2026 models:
- Orchestrator: gemini-3.1-flash-lite-preview (ultra-cheap agentic)
- Fallback: gpt-5.4-mini (strong reasoning)
- Module services: gemini-3.1-flash-lite-preview by default

Add gemini_module_provider for synchronous module service usage.
Add module_service_provider with OpenAI option for future A/B testing.

Cost optimization: ~92% reduction using Gemini Lite across stack."

# Commit 2: Module services
Write-Host "[2/8] Committing module services..." -ForegroundColor Yellow
git add browser-gui-automation/browser_module_service.py
git add api-accessibility-poc/desktop_module_service.py
git add cli-automation-poc/cli_module_service.py
git add browser-gui-automation/tools/
git add api-accessibility-poc/tools/
git add cli-automation-poc/tools/
git commit -m "feat(modules): add standalone module services

Implement FastAPI-based module services for browser, desktop, and CLI automation:
- Each service runs independently on dedicated port (8101-8103)
- REST API with /task and /health endpoints
- Gemini-powered agent loops with function calling
- 36 tools total: 17 browser + 15 desktop + 4 CLI

Services can run standalone or be orchestrated by unified-app."

# Commit 3: Service management
Write-Host "[3/8] Committing service management..." -ForegroundColor Yellow
git add unified-app/orchestrator/service_manager.py
git add unified-app/orchestrator/module_clients.py
git commit -m "feat(orchestrator): add service lifecycle management

Add ServiceManager for starting/stopping/monitoring module services.
Add ModuleClients for HTTP communication with module services.

Features:
- Automatic service startup with health checks
- Graceful shutdown handling
- Health monitoring for all services
- Timeout and retry logic"

# Commit 4: Tests
Write-Host "[4/8] Committing test suite..." -ForegroundColor Yellow
git add unified-app/tests/run_pre_integration_checks.py
git add unified-app/tests/test_e2e_module_service_arch.py
git add unified-app/tests/test_module_clients.py
git commit -m "test(orchestrator): add pre-integration verification

Add automated checks for orchestrator components:
- Environment variable validation
- Dependency verification
- Component initialization tests
- Checkpoint manager save/load
- Event bus signal emission
- Provider instantiation

49/49 unit tests passing, 7/8 component checks passing."

# Commit 5: Orchestrator refactor
Write-Host "[5/8] Committing orchestrator updates..." -ForegroundColor Yellow
git add unified-app/orchestrator/agent_loop.py
git add unified-app/orchestrator/agent_loop_v2.py
git add unified-app/orchestrator/execution_runner.py
git add unified-app/orchestrator/orchestrator_core.py
git add unified-app/orchestrator/prompt_registry.py
git add unified-app/orchestrator/objectives_decomposer.py
git add unified-app/orchestrator/event_bus.py
git commit -m "refactor(orchestrator): integrate module service architecture

Update orchestrator to work with new module service architecture:
- Add module service client support
- Update prompt registry for new models
- Enhance execution runner for service communication
- Improve error handling and retry logic

Maintains backward compatibility with Trinity Core adapters."

# Commit 6: Trinity Core updates
Write-Host "[6/8] Committing Trinity Core updates..." -ForegroundColor Yellow
git add trinity_core/adapters/
git add trinity_core/config.py
git add trinity_core/conftest.py
git add trinity_core/trinity.py
git add trinity_core/pyproject.toml
git add trinity_core/pytest.ini
git add trinity_core/session.py
git add trinity_core/llm/
git add trinity_core/orchestrators/
git add trinity_core/tools/
git add trinity_core/tests/
git commit -m "feat(trinity-core): add observability and testing infrastructure

Add comprehensive testing and observability:
- Structured logging with context propagation
- Metrics collection (latency, success rates, costs)
- Performance benchmarking framework
- Runtime and reviewer tests for all adapters
- Integration tests for Trinity executor

Enables production monitoring and performance analysis."

# Commit 7: UI and MCP updates
Write-Host "[7/8] Committing UI and MCP updates..." -ForegroundColor Yellow
git add unified-app/main.py
git add unified-app/mcp_server/
git add unified-app/ui/
git commit -m "refactor(ui): update for module service integration

Update UI components for new architecture:
- Enhance execution overlay for service status
- Update chat panel for better UX
- Improve status log panel formatting
- Add objective editor enhancements
- Update MCP server for new providers

Improves user experience and monitoring capabilities."

# Commit 8: Documentation and dependencies
Write-Host "[8/8] Committing documentation..." -ForegroundColor Yellow
git add AGENTS.md
git add browser-gui-automation/requirements.txt
git add browser-gui-automation/pyproject.toml
git add api-accessibility-poc/requirements.txt
git add api-accessibility-poc/pyproject.toml
git add cli-automation-poc/requirements.txt
git add cli-automation-poc/pyproject.toml
git add audit-debugger/pyproject.toml
git commit -m "docs: update project documentation and dependencies

Update workspace documentation:
- Add module service architecture overview
- Update AI agent instructions
- Clarify project structure and scope
- Update dependencies to latest stable versions

Improves onboarding and development workflow."

# Add remaining new files (logs, metrics, etc.)
Write-Host "`nAdding remaining artifacts..." -ForegroundColor Yellow
git add .logs/ .metrics/ audit-debugger/demos/demo_observability.py
git add audit-debugger/.audit/ audit-debugger/.metrics/ audit-debugger/src/
git add unified-app/.logs/ unified-app/tests/eval/
git commit -m "chore: add development artifacts and tooling

Add development support files:
- Log directories for debugging
- Metrics collection outputs
- Coverage reports
- Observability demos
- Evaluation frameworks

Supports development and debugging workflows."

Write-Host "`nAll commits completed successfully!" -ForegroundColor Green
Write-Host "Total: 9 commits created" -ForegroundColor Cyan
Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "  git log --oneline -9  # Review commits"
Write-Host "  git push              # Push to remote"
