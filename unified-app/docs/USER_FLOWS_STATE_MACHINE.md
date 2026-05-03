# Trinity Pilot Unified App - User Flows State Machine

## Overview

This document maps all possible user flows in the Trinity Pilot Unified App as a **closed state machine**. The state machine captures every state a user can be in, and all valid transitions between states.

## Architecture Context

```
User -> Trinity Unified Desktop -> finalized objective + selected MCP target -> Trinity Core -> visible MCP tools
```

The Unified App owns:
- PyQt6 desktop UI
- Clarification and conversation state
- Objective preview generation and editing
- Final objective confirmation
- Target selection and Desktop -> Core handoff
- Execution status display and local history

## Global State Machine

```mermaid
stateDiagram-v2
    [*] --> AppInitializing
    AppInitializing --> StartupBlocked : config_error
    AppInitializing --> AppIdle : startup_ready
    
    StartupBlocked --> AppIdle : settings_saved
    StartupBlocked --> [*] : app_closed
    
    AppIdle --> Clarifying : user_message_sent
    AppIdle --> StartupBlocked : config_error
    AppIdle --> [*] : app_closed
    
    Clarifying --> AppIdle : clarification_failed
    Clarifying --> ReadyToRun : task_confirmed
    Clarifying --> ReviewingObjectives : objectives_preview_ready
    
    ReadyToRun --> Executing : run_requested
    ReadyToRun --> Clarifying : task_modified
    ReadyToRun --> ReviewingObjectives : regenerate_objectives
    ReadyToRun --> AppIdle : new_task_requested
    
    ReviewingObjectives --> Executing : run_requested
    ReviewingObjectives --> ReadyToRun : objectives_confirmed
    ReviewingObjectives --> Clarifying : modify_requested
    ReviewingObjectives --> AppIdle : new_task_requested
    
    Executing --> AppIdle : execution_complete
    Executing --> Paused : pause_requested
    Executing --> HumanInTheLoop : blocker_detected
    Executing --> ErrorState : execution_failed
    Executing --> AppIdle : cancel_requested
    
    Paused --> Executing : resume_requested
    Paused --> AppIdle : cancel_requested
    
    HumanInTheLoop --> Executing : blocker_resolved
    HumanInTheLoop --> Paused : pause_requested
    HumanInTheLoop --> AppIdle : cancel_requested
    
    ErrorState --> AppIdle : error_acknowledged
    ErrorState --> Executing : retry_requested
    ErrorState --> Clarifying : replan_requested
    
    AppIdle --> HistoryBrowsing : history_tab_selected
    AppIdle --> SettingsEditing : settings_tab_selected
    
    HistoryBrowsing --> AppIdle : run_tab_selected
    HistoryBrowsing --> ReadyToRun : load_task_from_history
    HistoryBrowsing --> Executing : rerun_task
    
    SettingsEditing --> AppIdle : run_tab_selected
    SettingsEditing --> AppIdle : settings_saved
    SettingsEditing --> StartupBlocked : invalid_config
```

## Detailed State Definitions

### Application States

| State | Description | Entry Actions | Exit Actions |
|-------|-------------|---------------|--------------|
| **AppInitializing** | App is starting up, loading config, running preflight checks | Load settings, probe AI providers, check Trinity Core health | - |
| **StartupBlocked** | Cannot proceed due to missing/invalid configuration | Display blocking message in chat panel | - |
| **AppIdle** | Ready for user input, waiting for task description | Enable input field, clear previous state | - |

### Clarification States

| State | Description | Entry Actions | Exit Actions |
|-------|-------------|---------------|--------------|
| **Clarifying** | Engaged in back-and-forth to clarify user intent | Show thinking indicator, disable input temporarily | - |
| **ReadyToRun** | Task is confirmed, ready for execution | Show "Run" button, enable objective editing | - |
| **ReviewingObjectives** | Objectives preview displayed for user approval | Show objective editor widget | - |

### Execution States

| State | Description | Entry Actions | Exit Actions |
|-------|-------------|---------------|--------------|
| **Executing** | Task is being executed by Trinity Core | Show execution overlay, minimize main window (if desktop/browser domain) | Restore main window |
| **Paused** | Execution paused at user request | Show paused overlay, restore main window | - |
| **HumanInTheLoop** | Waiting for human action (CAPTCHA, confirmation) | Show blocker overlay with instructions | - |
| **ErrorState** | Execution failed with error | Show error details, offer retry/replan options | - |

### Navigation States

| State | Description | Entry Actions | Exit Actions |
|-------|-------------|---------------|--------------|
| **HistoryBrowsing** | Viewing task history tab | Load history from database | - |
| **SettingsEditing** | Viewing/editing settings tab | Load current settings | Save settings |

## Sub-State Machines

### 1. Clarification Flow State Machine

```mermaid
stateDiagram-v2
    [*] --> AwaitingUserInput
    
    AwaitingUserInput --> ProcessingMessage : user_sends_message
    
    ProcessingMessage --> NeedsClarification : intent_unclear
    ProcessingMessage --> ReadyConfirmed : intent_clear
    ProcessingMessage --> ClarificationError : provider_error
    
    NeedsClarification --> AwaitingUserInput : show_question
    
    ReadyConfirmed --> AwaitingConfirmation : show_summary
    
    AwaitingConfirmation --> GeneratingObjectives : user_confirms
    AwaitingConfirmation --> AwaitingUserInput : user_rejects/modifies
    
    GeneratingObjectives --> ObjectivesReady : preview_generated
    GeneratingObjectives --> AwaitingUserInput : generation_failed
    
    ObjectivesReady --> AwaitingUserInput : user_edits_objectives
    ObjectivesReady --> SubmittedForExecution : user_approves_run
    
    ClarificationError --> AwaitingUserInput : show_fallback_ready
    
    SubmittedForExecution --> [*]
```

### 2. Execution Flow State Machine

```mermaid
stateDiagram-v2
    [*] --> PreparingExecution
    
    PreparingExecution --> DomainRouting : determine_domain
    
    DomainRouting --> CLIExecution : domain=cli
    DomainRouting --> BrowserExecution : domain=browser
    DomainRouting --> DesktopExecution : domain=desktop
    DomainRouting --> MultiDomainExecution : domain=mixed
    
    CLIExecution --> StepRunning : execute_steps
    BrowserExecution --> StepRunning : execute_steps
    DesktopExecution --> StepRunning : execute_steps
    MultiDomainExecution --> StepRunning : execute_steps
    
    StepRunning --> StepCompleted : step_success
    StepRunning --> StepFailed : step_failure
    StepRunning --> AwaitingHumanInput : human_action_required
    
    StepCompleted --> StepRunning : next_step
    StepCompleted --> ExecutionComplete : all_steps_done
    
    StepFailed --> Replanning : retry_allowed
    StepFailed --> ExecutionFailed : retry_exhausted
    StepFailed --> AwaitingHumanInput : blocker_detected
    
    Replanning --> StepRunning : replan_success
    Replanning --> ExecutionFailed : replan_failed
    
    AwaitingHumanInput --> StepRunning : human_resolved
    AwaitingHumanInput --> ExecutionCancelled : user_cancels
    
    ExecutionComplete --> [*]
    ExecutionFailed --> [*]
    ExecutionCancelled --> [*]
```

### 3. History Interaction State Machine

```mmdb
stateDiagram-v2
    [*] --> HistoryListView
    
    HistoryListView --> Filtering : apply_filters
    HistoryListView --> TaskSelected : user_selects_task
    HistoryListView --> Importing : import_requested
    
    Filtering --> HistoryListView : filters_applied
    
    TaskSelected --> TaskDetailView : show_details
    
    TaskDetailView --> HistoryListView : back_to_list
    TaskDetailView --> RunTabWithTask : load_into_chat
    TaskDetailView --> Executing : rerun_task
    TaskDetailView --> Exporting : export_selected
    
    Importing --> HistoryListView : import_complete
    
    Exporting --> TaskDetailView : export_complete
    
    RunTabWithTask --> [*]
```

### 4. Settings Management State Machine

```mermaid
stateDiagram-v2
    [*] --> SettingsView
    
    SettingsView --> EditingProvider : change_provider
    SettingsView --> EditingAPIKey : change_api_key
    SettingsView --> TogglingOptions : toggle_options
    
    EditingProvider --> Validating : save_requested
    EditingAPIKey --> Validating : save_requested
    TogglingOptions --> Validating : save_requested
    
    Validating --> SettingsSaved : validation_pass
    Validating --> SettingsError : validation_fail
    
    SettingsSaved --> AppIdle : settings_applied
    
    SettingsError --> EditingProvider : fix_provider
    SettingsError --> EditingAPIKey : fix_api_key
    SettingsError --> TogglingOptions : fix_options
```

### 5. Overlay Control State Machine (During Execution)

```mermaid
stateDiagram-v2
    [*] --> OverlayHidden
    
    OverlayHidden --> OverlayShowing : execution_started
    
    OverlayShowing --> StepInProgress : step_started
    
    StepInProgress --> StepCompleted : step_success
    StepInProgress --> StepFailed : step_failure
    StepInProgress --> BlockerDetected : human_action_needed
    StepInProgress --> PausedOverlay : pause_requested
    
    StepCompleted --> StepInProgress : next_step
    StepCompleted --> OverlayHiding : execution_complete
    
    StepFailed --> StepInProgress : retry_step
    StepFailed --> OverlayHiding : max_retries_reached
    
    BlockerDetected --> StepInProgress : blocker_resolved
    BlockerDetected --> PausedOverlay : pause_requested
    
    PausedOverlay --> StepInProgress : resume_requested
    PausedOverlay --> OverlayHiding : cancel_requested
    
    OverlayHiding --> OverlayHidden : overlay_dismissed
```

## Event-Driven Transitions

The state machine is driven by events emitted via the EventBus:

```mermaid
flowchart LR
    UserAction[User Action] --> UI[UI Component]
    UI -->|pyqtSignal| EventBus[Event Bus]
    EventBus -->|slot| Orchestrator[Orchestrator Core]
    Orchestrator -->|state_change| StateManager[State Manager]
    StateManager -->|update| UI
```

### Key Events by Category

**Chat & Clarification:**
- `chat_message(role, text)` - Add message to chat
- `clarification_ready(confirmed_task)` - Task is clarified and ready
- `objectives_preview_ready(task, objectives)` - Objectives generated
- `objectives_modify_done(success)` - Objectives modification complete

**Task Execution:**
- `task_submitted(description, domain)` - User submitted task
- `plan_generated(steps)` - Execution plan created
- `step_started(index, description)` - Step execution started
- `step_completed(index, payload)` - Step completed successfully
- `step_failed(index, error)` - Step failed
- `execution_complete(payload)` - Full execution complete
- `execution_started()` - Execution beginning
- `execution_ended()` - Execution finished

**Control Signals:**
- `task_cancel_requested()` - User requested cancellation
- `steer_input(text)` - User provided mid-run guidance
- `blocker_detected(message)` - Human action required
- `blocker_resolved()` - Human action completed

**System:**
- `preflight_done(readiness)` - Startup preflight complete
- `app_busy(busy)` - App busy state changed
- `desktop_takeover_started(domain)` - Desktop/browser takeover
- `desktop_takeover_ended()` - Takeover complete

## Error Handling Flows

```mermaid
stateDiagram-v2
    [*] --> NormalOperation
    
    NormalOperation --> ProviderError : AI_provider_fail
    NormalOperation --> NetworkError : network_timeout
    NormalOperation --> ConfigError : invalid_config
    NormalOperation --> ExecutionError : runtime_error
    
    ProviderError --> NormalOperation : fallback_ready
    ProviderError --> StartupBlocked : persistent_failure
    
    NetworkError --> NormalOperation : retry_success
    NetworkError --> StartupBlocked : retry_exhausted
    
    ConfigError --> SettingsEditing : user_opens_settings
    ConfigError --> StartupBlocked : critical_config_missing
    
    ExecutionError --> Replanning : auto_retry
    ExecutionError --> UserIntervention : human_action_needed
    ExecutionError --> TaskFailed : unrecoverable
    
    Replanning --> NormalOperation : replan_success
    
    UserIntervention --> NormalOperation : intervention_complete
    UserIntervention --> TaskCancelled : user_cancels
    
    TaskFailed --> [*]
    TaskCancelled --> [*]
```

## State Transition Table

| From State | Event | To State | Condition |
|------------|-------|----------|-----------|
| AppInitializing | preflight_success | AppIdle | - |
| AppInitializing | preflight_fail | StartupBlocked | - |
| StartupBlocked | settings_saved | AppIdle | config_valid |
| AppIdle | user_message | Clarifying | - |
| Clarifying | clarification_success | ReadyToRun | - |
| Clarifying | clarification_fail | AppIdle | - |
| ReadyToRun | run_requested | Executing | - |
| ReadyToRun | regenerate_requested | ReviewingObjectives | - |
| ReviewingObjectives | run_requested | Executing | - |
| ReviewingObjectives | modify_requested | Clarifying | - |
| Executing | execution_complete | AppIdle | - |
| Executing | pause_requested | Paused | - |
| Executing | blocker_detected | HumanInTheLoop | - |
| Executing | cancel_requested | AppIdle | - |
| Paused | resume_requested | Executing | - |
| HumanInTheLoop | blocker_resolved | Executing | - |
| AppIdle | history_selected | HistoryBrowsing | - |
| HistoryBrowsing | load_task | ReadyToRun | - |
| AppIdle | settings_selected | SettingsEditing | - |
| SettingsEditing | settings_saved | AppIdle | valid |

## Terminal States

The following states can only transition to a terminal condition:

- **ExecutionFailed** - Can transition to AppIdle (acknowledge) or Executing (retry)
- **TaskCancelled** - Transitions to AppIdle
- **AppClosed** - Terminal state

## Entry Points & Exit Conditions

**Entry Points:**
1. Application launch → `AppInitializing`
2. Task pipe submission → `ReadyToRun` or `AppIdle`
3. History rerun → `Executing`

**Exit Conditions:**
1. User closes window → `AppClosed`
2. Shutdown command from pipe → `AppClosed`
3. Fatal error → `AppClosed`

## Visual State Representation

### Chat Panel States

```
┌─────────────────────────────────────────┐
│  IDLE        THINKING    READY_TO_RUN   │
│  ┌─────┐     ┌─────┐     ┌─────────┐   │
│  │input│     │●●● │     │[Run]    │   │
│  └─────┘     └─────┘     │[Edit]   │   │
│                          └─────────┘   │
├─────────────────────────────────────────┤
│  REVIEWING_OBJS    EXECUTING           │
│  ┌────────────┐    ┌────────────┐      │
│  │obj1 [✓]    │    │  OVERLAY   │      │
│  │obj2 [✓]    │    │  ACTIVE    │      │
│  │[Run] [Edit]│    │  ▶ Step 2  │      │
│  └────────────┘    └────────────┘      │
└─────────────────────────────────────────┘
```

## Appendix: EventBus Signal Reference

```python
# Task lifecycle
task_submitted = pyqtSignal(str, str)           # description, domain
pipe_task_submitted = pyqtSignal(str, str, str) # description, domain, request_id
steer_input = pyqtSignal(str)                    # guidance text
task_cancel_requested = pyqtSignal()
task_policy_stop_requested = pyqtSignal(str)

# Plan & execution
plan_generated = pyqtSignal(list)                # steps
step_started = pyqtSignal(int, str)              # index, description
step_completed = pyqtSignal(int, dict)           # index, payload
step_failed = pyqtSignal(int, object)            # index, error
step_detail = pyqtSignal(int, int, str, str)     # obj_idx, step_num, action, result
plan_state_updated = pyqtSignal(int, dict)       # index, state
status_update = pyqtSignal(str, str)             # message, level
cli_step_progress = pyqtSignal(int, dict)        # obj_index, step_payload

# Execution state
execution_complete = pyqtSignal(dict)            # payload
app_busy = pyqtSignal(bool)                      # busy state
execution_started = pyqtSignal()
execution_ended = pyqtSignal()
run_started = pyqtSignal(str)                    # run_id
run_ended = pyqtSignal(str)                      # run_id

# System control
command_reset_requested = pyqtSignal()
command_shutdown_requested = pyqtSignal()
desktop_takeover_started = pyqtSignal(str)       # domain
desktop_takeover_ended = pyqtSignal()
preflight_done = pyqtSignal(object)              # StartupReadiness

# Chat & clarification
chat_message = pyqtSignal(str, str)              # role, text
clarification_ready = pyqtSignal(str)            # confirmed task
objectives_preview_ready = pyqtSignal(str, list) # task, objectives
objectives_modify_done = pyqtSignal(bool)        # success
task_result_ready = pyqtSignal(str, dict)        # answer, summary

# Human-in-the-loop
blocker_detected = pyqtSignal(str)               # message
blocker_resolved = pyqtSignal()
```

---

*Generated for Trinity Pilot Unified App - Desktop orchestration layer*
