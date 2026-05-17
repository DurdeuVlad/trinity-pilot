# Trinity Pilot — Architecture Diagrams

---

## 1. System Overview

High-level components and how they connect.

```mermaid
graph TB
    subgraph UI["UI Layer (PySide6 / Qt)"]
        MW[MainWindow]
        WB[WorkflowBridge]
        WT[_WorkerThread\nasyncio loop in QThread]
    end

    subgraph Orchestration["Orchestration Layer"]
        PL[ObjectivePlanner\nbreaks task → objectives]
        OR[AsyncTaskOrchestrator\nruns objectives in order]
        RV[Reviewer\npass / fail / steer]
    end

    subgraph Workers["Domain Workers  —  ReAct Loop"]
        TW[TerminalWorker\nshell / PowerShell]
        BW[BrowserWorker\nPlaywright]
        DW[DesktopWorker\npywinauto / pyautogui]
    end

    subgraph LLM["LLM Layer"]
        GM[GeminiProvider\ngemini-2.5-flash]
    end

    subgraph Memory["Memory Layer"]
        TS[TaskStore\nSQLite]
        OS[ObjectiveStateStore\nSQLite]
    end

    subgraph Signals["Signal Bus  (asyncio.Queue)"]
        SG[ObjectiveDone\nObjectiveFailed\nStuckSignal\nSteeringMessage\nBudgetWarning]
    end

    MW -->|user submits task| WB
    WB -->|start_task| WT
    WT -->|run| OR
    OR -->|plan| PL
    PL -->|LLM call| GM
    PL -->|ObjectiveSpec list| OR
    OR -->|dispatch objective| TW & BW & DW
    TW & BW & DW -->|LLM calls| GM
    TW & BW & DW -->|evidence dict| RV
    RV -->|LLM call| GM
    RV -->|pass/fail/steer| OR
    OR -->|write status| TS & OS
    OR -->|emit| SG
    SG -->|forwarded| WB
    WB -->|on_done callback| MW
```

---

## 2. Task Lifecycle — Sequence Diagram

From user click to result shown in UI.

```mermaid
sequenceDiagram
    actor User
    participant UI as MainWindow
    participant Bridge as WorkflowBridge
    participant Thread as _WorkerThread
    participant Orch as AsyncTaskOrchestrator
    participant Planner as ObjectivePlanner
    participant Worker as DomainWorker
    participant LLM as Gemini 2.5-flash
    participant DB as SQLite

    User->>UI: types task, clicks Submit
    UI->>Bridge: start_task(user_request)
    Bridge->>DB: save TaskRecord (RUNNING)
    Bridge->>Thread: QThread.start()

    Thread->>Orch: run(user_request, task_id)
    Orch->>Planner: plan(user_request)
    Planner->>LLM: "break into objectives"
    LLM-->>Planner: [ObjectiveSpec, ...]
    Planner-->>Orch: objective list

    loop for each ObjectiveSpec
        Orch->>Worker: execute(spec)

        loop ReAct steps (max N)
            Worker->>LLM: system_prompt + history + tools
            LLM-->>Worker: thought + tool_call
            Worker->>Worker: dispatch tool (shell/browser/GUI)
            Worker-->>LLM: tool_result
        end

        Worker-->>Orch: evidence dict
        Orch->>LLM: review evidence vs success_tests
        LLM-->>Orch: pass / fail / steer

        alt passed
            Orch->>DB: update objective DONE
            Orch->>Bridge: emit ObjectiveDone
        else failed / blocker
            Orch->>DB: update objective FAILED
            Orch->>Bridge: emit StuckSignal
        end
    end

    Orch->>DB: update task COMPLETED / FAILED
    Thread->>Bridge: task_finished signal (DirectConnection)
    Bridge->>UI: on_done(result)
    UI->>User: show result
```

---

## 3. ReAct Loop — Worker Internals

How a single objective is executed inside any domain worker.

```mermaid
flowchart TD
    A([ObjectiveSpec received]) --> B[Build system prompt\n+ environment context]
    B --> C[Send to Gemini\nwith tool declarations]
    C --> D{Response type?}

    D -->|thought + tool_call| E[Dispatch tool]
    D -->|finish success| K([Return evidence — PASS])
    D -->|finish failure| L([Return evidence — FAIL])
    D -->|report_blocking| M([Raise WorkerBlocker])

    E --> F{Tool type}
    F -->|shell command| G[run subprocess\ncapture stdout/stderr]
    F -->|browser action| H[Playwright API\nnavigate / click / read]
    F -->|desktop action| I[launch_app / focus_window\ntype_text / press_key]
    F -->|write_file| J[pathlib.write_text]

    G & H & I & J --> N[Append to evidence\nupdate state snapshot]
    N --> O{Step budget\nexceeded?}
    O -->|no| C
    O -->|yes| P([Raise BudgetExceeded])

    style K fill:#2d6a4f,color:#fff
    style L fill:#a4161a,color:#fff
    style M fill:#e07a5f,color:#fff
    style P fill:#6b4226,color:#fff
```

---

## 4. Signal Architecture

How the orchestrator communicates status back to the UI without blocking.

```mermaid
graph LR
    subgraph Worker Thread ["asyncio thread  (QThread)"]
        OR[Orchestrator]
        WK[Worker]
        OR -->|await signals.put| Q[(asyncio.Queue)]
    end

    subgraph Signals
        direction TB
        S1[ObjectiveStarted]
        S2[StepCompleted]
        S3[ObjectiveDone]
        S4[ObjectiveFailed]
        S5[StuckSignal\nuser_question]
        S6[SteeringMessage]
        S7[BudgetWarning]
    end

    Q --> S1 & S2 & S3 & S4 & S5 & S6 & S7

    subgraph UI Thread
        CB[on_done callback\nDirectConnection]
        MW[MainWindow\nupdate UI]
    end

    S3 & S4 -->|task done| CB
    S5 -->|needs user input| MW
    CB --> MW
```

---

## 5. Domain Worker Hierarchy

Class relationships.

```mermaid
classDiagram
    class DomainWorker {
        <<abstract>>
        +execute(spec) dict
        +domain() DomainType
    }

    class AgenticWorkerMixin {
        <<mixin>>
        -llm: LLMProvider
        -messages: list[LLMMessage]
        +run_loop(spec, evidence, tools, max_steps)
        #_dispatch_tool(name, args, evidence)
        #_worker_tools() list
        #_worker_system_prompt() str
        #_worker_state_snapshot(evidence) str
    }

    class TerminalWorker {
        +domain = terminal
        +execute(spec)
        #_dispatch_tool() run_command / write_file
    }

    class BrowserWorker {
        +domain = browser
        +execute(spec)
        #_dispatch_tool() navigate / click / read_page
    }

    class DesktopWorker {
        +domain = desktop
        -_target_window: str
        +execute(spec)
        #_dispatch_tool() launch_app / focus_window / type_text
        #_ensure_target_focused()
    }

    class GeminiProvider {
        +complete_with_tools(messages, tools)
        -_build_contents()  preserves thought_signature
    }

    DomainWorker <|-- TerminalWorker
    DomainWorker <|-- BrowserWorker
    DomainWorker <|-- DesktopWorker
    AgenticWorkerMixin <|-- TerminalWorker
    AgenticWorkerMixin <|-- BrowserWorker
    AgenticWorkerMixin <|-- DesktopWorker
    AgenticWorkerMixin --> GeminiProvider : uses
```

---

## 6. Data Flow — What Travels Between Components

```mermaid
graph LR
    A[user_request\nstring] -->|Planner| B

    B["ObjectiveSpec\n───────────\nobjective_id\ngoal\ndomain\nrequired_capabilities\nrisk_class\nmax_attempts\nsuccess_tests\nevidence_bundle"]

    B -->|Worker executes| C

    C["Evidence Dict\n───────────\nstdout / stderr\nscreenshot bytes\naction_log\nlaunched_pids\nwritten_files\nerror"]

    C -->|Reviewer checks| D

    D["ReviewResult\n───────────\npassed: bool\nfailure_reason\nsteering_message"]

    D -->|Orchestrator writes| E

    E["TaskRecord  +  DB\n───────────\ntask_id\nstatus: RUNNING→DONE\nobjective results\nevidence"]
```

---

## Key Design Decisions (one-liners for slides)

| Decision | Why |
|---|---|
| ReAct loop per objective | AI reasons before each tool call — self-corrects without scripting every step |
| asyncio + QThread bridge | Non-blocking UI while orchestrator runs; DirectConnection prevents callback deadlock |
| Gemini 2.5-flash (thinking model) | Handles multi-step planning; thought_signature preserved for multi-turn stability |
| Evidence dict pattern | Every worker returns the same shape — Reviewer and tests make uniform assertions |
| Signal bus (asyncio.Queue) | Decouples orchestrator from UI; same queue used in tests for behavioral assertions |
| PID tracking in evidence | Desktop cleanup is precise — no process list scanning, works for any spawned app |
