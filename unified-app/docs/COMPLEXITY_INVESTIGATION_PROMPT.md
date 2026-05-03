# Prompt: Investigate Unified App Complexity Claim

## Claim to Investigate

> "The unified app is too complex for its own good and overengineered and breaks at any change"

## Investigation Framework

Conduct a forensic analysis of the unified-app codebase to determine the validity of this claim. Evaluate against these dimensions:

### 1. Code Volume & Density Analysis

Measure and report:
- Lines of code by module (main.py, orchestrator/, ui/, mcp_server/)
- Cyclomatic complexity of key functions (orchestrator_core.py, main.py)
- Number of classes and their inheritance depth
- Signal/slot connection density (EventBus usage patterns)
- State transition complexity

### 2. Architectural Complexity Indicators

Identify and assess:
- **Signal spaghetti**: How many signals connect across how many components?
- **State fragmentation**: Where is state stored? (event bus, UI components, orchestrator, database)
- **Callback hell**: Depth of async chains and callback nesting
- **Circular dependencies**: Any import cycles between orchestrator/ui/main?
- **Mixin/inheritance overuse**: How many parent classes do key widgets have?

### 3. Change Impact Analysis

For each major module, determine:
- If I change X, how many files/modules could break?
- How many tests would need updating?
- What's the blast radius of a UI change? An orchestrator change?

Specific scenarios to trace:
- Adding a new state to the chat panel
- Modifying the execution flow
- Adding a new event type
- Changing the objective generation logic
- Adding a new domain (e.g., "mobile")

### 4. Over-Engineering Signals

Look for:
- Abstraction layers that don't abstract (indirection without benefit)
- Premature generalization ("this might be needed someday" code)
- Unused or over-flexible configuration options
- Design patterns applied where simpler solutions exist
- Comment-to-code ratio indicating excessive explanation needs

### 5. Fragility Evidence

Find:
- Race conditions in signal handling
- Implicit dependencies between UI and orchestrator
- Hardcoded assumptions that break easily
- Exception handling that masks or swallows errors
- Singleton abuse (EventBus, HistoryManager)

### 6. Test Coverage vs. Complexity

Compare:
- Unit test coverage for complex modules
- Integration test coverage for state transitions
- What paths are untested but critical?

## Investigation Methodology

1. **Static Analysis** - Use tools like radon, pylint, mypy where applicable
2. **Dependency Graph** - Map imports and signal connections
3. **Change Simulation** - Trace hypothetical changes through the system
4. **Documentation/Code Ratio** - Is the README longer than the code it explains?
5. **Historical Analysis** - Check git history for files with most churn

## Deliverables

Provide a structured report with:

### Executive Summary
- Verdict: VALID / PARTIALLY VALID / NOT VALID with confidence level
- Top 3 complexity pain points
- Top 3 most fragile components

### Detailed Findings
- Metrics table (complexity scores, file sizes, connection counts)
- Dependency diagram (Mermaid or ASCII)
- Specific code smells with file:line citations
- Risk matrix: components vs. change fragility

### Evidence-Based Counterpoints
If the claim is overstated, provide evidence of:
- Why the complexity is justified
- What would break if simplified
- Successful recent changes that didn't cause cascading failures

### Recommendations (if complexity is confirmed)
Ranked list of simplification opportunities:
1. Quick wins (low risk, high clarity benefit)
2. Structural improvements (medium effort, medium benefit)
3. Architectural refactors (high effort, high benefit)

## Context Files to Analyze

Primary:
- `main.py` - Main window, signal wiring, startup logic
- `orchestrator/orchestrator_core.py` - Core workflow coordination
- `orchestrator/event_bus.py` - Event routing
- `orchestrator/trinity_bridge.py` - Core handoff layer
- `ui/panels/chat_panel.py` - Chat UI state machine
- `ui/overlay/execution_overlay.py` - Full-screen HUD

Secondary:
- `orchestrator/clarification_engine.py`
- `orchestrator/macro_planner.py`
- `orchestrator/objectives_decomposer.py`
- `mcp_server/` - Internal tooling surfaces

## Evaluation Criteria

Score the unified-app on:

| Dimension | 1 (Simple) | 5 (Complex) | Score |
|-----------|------------|-------------|-------|
| Cognitive Load | Easy to understand | Requires extensive docs | _/5 |
| Change Safety | Local changes stay local | Changes cascade everywhere | _/5 |
| Debuggability | Clear error traces | Hidden failures, async chaos | _/5 |
| Testability | Easy to mock/test | Requires full app context | _/5 |
| Modularity | Clean boundaries | Tight coupling | _/5 |

## Final Output Format

```markdown
## Verdict: [VALIDITY] (Confidence: X%)

### Complexity Score: X/5
### Fragility Score: X/5
### Over-Engineering Score: X/5

### Key Evidence
- [Specific finding 1 with file:line]
- [Specific finding 2 with file:line]
- [Specific finding 3 with file:line]

### Counter-Evidence (if applicable)
- [Why complexity might be justified]

### Recommended Actions
1. [Highest priority fix]
2. [Second priority fix]
3. [Long-term structural improvement]
```

---

**Investigation Scope**: trinity-pilot/unified-app/ directory
**Focus**: Subjective claim validation through objective metrics
**Timebox**: Deep but bounded analysis - don't spend hours on perfect graphs
