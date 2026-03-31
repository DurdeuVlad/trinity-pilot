# User Journey Maps - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** USR-004  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document maps end-to-end user journeys through the Orchestrator Desktop App, identifying touchpoints, emotions, pain points, and opportunities for improvement.

---

## 2. Journey Map Template

Each journey includes:
- **Persona:** Which user
- **Scenario:** What they're trying to accomplish
- **Phases:** Major stages of the journey
- **Actions:** What user does
- **Touchpoints:** UI elements interacted with
- **Thoughts:** What user is thinking
- **Emotions:** How user feels (😊 positive, 😐 neutral, 😟 negative)
- **Pain Points:** Friction or problems
- **Opportunities:** Potential improvements

---

## 3. Journey 1: First-Time User - Complete a Task

**Persona:** Alex (Student Developer)  
**Scenario:** First time using the app to execute a browser automation task  
**Goal:** Successfully submit and complete a task

### Phase 1: Application Launch

**Actions:**
- Launches application via `python main.py`
- Sees main window appear

**Touchpoints:**
- Windows taskbar
- Application window
- Run tab (default)

**Thoughts:**
- "Does this work?"
- "What do I need to configure first?"

**Emotions:** 😐 Curious, slightly uncertain

**Pain Points:**
- Unsure if API key is needed
- No onboarding guidance

**Opportunities:**
- Add first-run wizard
- Show startup status prominently

---

### Phase 2: Startup Validation

**Actions:**
- Sees startup message in status log
- Reads "Startup mode: mock fallback ready"

**Touchpoints:**
- Status log panel
- Startup message

**Thoughts:**
- "OK, mock mode is active"
- "I can test without API key"

**Emotions:** 😊 Relieved

**Pain Points:**
- None (mock mode works smoothly)

**Opportunities:**
- Explain what mock mode means
- Link to settings for API key setup

---

### Phase 3: Task Submission

**Actions:**
- Types task description: "Open Google and search for Python tutorials"
- Leaves domain as "Auto-detect"
- Clicks "Run Task" button

**Touchpoints:**
- Task input text field
- Domain dropdown
- Run Task button

**Thoughts:**
- "Will this understand my request?"
- "What domain should I use?"

**Emotions:** 😐 Hopeful but uncertain

**Pain Points:**
- Unsure about domain selection
- No examples or hints

**Opportunities:**
- Add placeholder text with example
- Show tooltip for domain options

---

### Phase 4: Execution Monitoring

**Actions:**
- Watches execution plan appear
- Sees steps: "1. Launch browser", "2. Navigate to Google", etc.
- Monitors status log for progress
- Sees screenshots appear in glass box panel

**Touchpoints:**
- Execution plan panel
- Status log panel
- Glass box panel
- Step status indicators

**Thoughts:**
- "Oh, I can see what it's planning!"
- "The screenshots show what's happening!"
- "This is actually working!"

**Emotions:** 😊 Excited, engaged

**Pain Points:**
- None (everything works as expected)

**Opportunities:**
- Add step timing information
- Show estimated completion time

---

### Phase 5: Task Completion

**Actions:**
- Sees final step complete
- Reads "Task completed successfully" message
- Notices Run Task button re-enabled

**Touchpoints:**
- Status log final message
- Run Task button
- Execution plan (all steps completed)

**Thoughts:**
- "It worked!"
- "That was easier than expected"

**Emotions:** 😊 Satisfied, accomplished

**Pain Points:**
- None

**Opportunities:**
- Add celebration animation
- Suggest next actions

---

### Phase 6: Review History

**Actions:**
- Clicks History tab
- Sees completed task in list
- Double-clicks to view details

**Touchpoints:**
- History tab
- Task history table
- Task details dialog

**Thoughts:**
- "I can see what I ran"
- "Good for debugging later"

**Emotions:** 😊 Confident

**Pain Points:**
- None

**Opportunities:**
- Add export history feature
- Add task replay option

---

## 4. Journey 2: Experienced User - Debug Failed Task

**Persona:** Alex (Student Developer)  
**Scenario:** Task failed, need to understand why and fix it  
**Goal:** Identify failure cause and successfully retry

### Phase 1: Task Failure

**Actions:**
- Submits task
- Watches execution
- Sees step 3 fail with error

**Touchpoints:**
- Execution plan (step marked failed)
- Status log (error message)

**Thoughts:**
- "What went wrong?"
- "Is the error message helpful?"

**Emotions:** 😟 Frustrated

**Pain Points:**
- Error message may be technical
- Unclear how to fix

**Opportunities:**
- Improve error message clarity
- Suggest corrective actions

---

### Phase 2: Error Investigation

**Actions:**
- Reads error message: "Element not found: search box"
- Checks screenshot to see page state
- Realizes page loaded differently

**Touchpoints:**
- Status log error details
- Glass box screenshot
- Frame metadata

**Thoughts:**
- "The page structure changed"
- "I need to adjust my task description"

**Emotions:** 😐 Understanding the problem

**Pain Points:**
- Need to infer solution from error
- No suggested fixes

**Opportunities:**
- Add "common fixes" suggestions
- Link to troubleshooting guide

---

### Phase 3: Review History

**Actions:**
- Switches to History tab
- Compares failed task with previous successful one
- Identifies difference in task description

**Touchpoints:**
- History tab
- Task comparison

**Thoughts:**
- "Last time I was more specific"
- "I should add more details"

**Emotions:** 😊 Found the solution

**Pain Points:**
- Manual comparison needed
- No diff view

**Opportunities:**
- Add task comparison feature
- Highlight differences automatically

---

### Phase 4: Retry with Fix

**Actions:**
- Returns to Run tab
- Enters improved task description
- Submits task
- Watches execution succeed

**Touchpoints:**
- Run tab
- Task input
- Execution monitoring

**Thoughts:**
- "This should work now"
- "Yes, it's working!"

**Emotions:** 😊 Relieved, successful

**Pain Points:**
- None

**Opportunities:**
- Add "retry with modifications" button in history

---

## 5. Journey 3: Academic Supervisor - Evaluate Project

**Persona:** Professor Maria (Academic Evaluator)  
**Scenario:** Reviewing student project for grading  
**Goal:** Assess technical quality and completeness

### Phase 1: Documentation Review

**Actions:**
- Opens requirements folder
- Reads README.md index
- Reviews business objectives
- Checks traceability matrix

**Touchpoints:**
- File explorer
- Markdown documentation
- Requirements structure

**Thoughts:**
- "This is well-organized"
- "Professional documentation structure"
- "Clear traceability"

**Emotions:** 😊 Impressed

**Pain Points:**
- None

**Opportunities:**
- Add PDF export for easier reading

---

### Phase 2: Code Quality Check

**Actions:**
- Runs `pytest tests/ -v --cov`
- Reviews coverage report: 86%
- Checks test results: 26/26 passing

**Touchpoints:**
- Terminal
- Coverage report
- Test output

**Thoughts:**
- "Exceeds 85% requirement"
- "All tests passing"
- "Good quality"

**Emotions:** 😊 Satisfied

**Pain Points:**
- None

**Opportunities:**
- Add HTML coverage report
- Include quality metrics dashboard

---

### Phase 3: Demo Execution

**Actions:**
- Launches application
- Sees clean startup
- Submits sample task
- Watches execution complete successfully

**Touchpoints:**
- Application window
- All UI panels
- Execution flow

**Thoughts:**
- "Works as documented"
- "UI is intuitive"
- "No crashes"

**Emotions:** 😊 Confident in quality

**Pain Points:**
- None

**Opportunities:**
- Add demo mode with pre-loaded tasks

---

### Phase 4: Architecture Review

**Actions:**
- Reviews architecture diagrams
- Reads design patterns documentation
- Checks code structure

**Touchpoints:**
- Documentation
- Diagrams
- Source code

**Thoughts:**
- "Clear separation of concerns"
- "Good use of patterns"
- "Maintainable code"

**Emotions:** 😊 Approving

**Pain Points:**
- None

**Opportunities:**
- Add interactive architecture explorer

---

## 6. Journey 4: Future Developer - Extend Functionality

**Persona:** Future Developer (Maintainer)  
**Scenario:** Adding new UI panel for task templates  
**Goal:** Extend app without breaking existing code

### Phase 1: Understanding Architecture

**Actions:**
- Reads architecture documentation
- Reviews design patterns
- Studies existing UI panels

**Touchpoints:**
- Documentation
- Source code
- Diagrams

**Thoughts:**
- "Event bus for communication"
- "Panels are modular"
- "I can follow this pattern"

**Emotions:** 😊 Confident

**Pain Points:**
- None (good documentation)

**Opportunities:**
- Add developer guide
- Include extension examples

---

### Phase 2: Implementation

**Actions:**
- Creates new panel class
- Follows existing panel pattern
- Connects to event bus
- Adds to main window tabs

**Touchpoints:**
- Code editor
- Existing panel code
- Event bus

**Thoughts:**
- "Pattern is clear"
- "Easy to integrate"

**Emotions:** 😊 Productive

**Pain Points:**
- None

**Opportunities:**
- Add panel template generator

---

### Phase 3: Testing

**Actions:**
- Runs existing tests (all pass)
- Adds tests for new panel
- Verifies no regressions

**Touchpoints:**
- Test suite
- New test files

**Thoughts:**
- "Tests still pass"
- "My changes didn't break anything"

**Emotions:** 😊 Confident

**Pain Points:**
- None

**Opportunities:**
- Add test coverage for new code

---

## 7. Emotional Journey Summary

### First-Time User Journey
```
😐 → 😊 → 😐 → 😊 → 😊 → 😊
Launch  Startup  Submit  Monitor  Complete  History
```

**Overall Sentiment:** Positive (4/6 positive touchpoints)

---

### Debug Journey
```
😟 → 😐 → 😊 → 😊
Failure  Investigate  Compare  Success
```

**Overall Sentiment:** Recovery to positive

---

### Supervisor Journey
```
😊 → 😊 → 😊 → 😊
Docs  Quality  Demo  Architecture
```

**Overall Sentiment:** Consistently positive

---

### Developer Journey
```
😊 → 😊 → 😊
Understand  Implement  Test
```

**Overall Sentiment:** Consistently positive

---

## 8. Key Insights

### Strengths
1. **Clear visual feedback** - Users appreciate seeing execution progress
2. **Mock mode** - Removes API key barrier for first use
3. **Task history** - Valuable for debugging and learning
4. **Professional documentation** - Meets academic standards
5. **Modular architecture** - Easy to extend

### Pain Points
1. **No onboarding** - First-time users uncertain about setup
2. **Domain selection** - Unclear when to use which option
3. **Error messages** - Could be more actionable
4. **No task comparison** - Manual diff needed for debugging

### Opportunities
1. **First-run wizard** - Guide initial setup
2. **Example tasks** - Show what's possible
3. **Improved error messages** - Suggest fixes
4. **Task comparison** - Highlight differences
5. **Demo mode** - Pre-loaded tasks for evaluation

---

## 9. Journey Metrics

| Journey | Duration | Touchpoints | Positive Moments | Pain Points | Success Rate |
|---------|----------|-------------|------------------|-------------|--------------|
| First-Time User | 5-10 min | 15 | 4 | 2 | 100% |
| Debug Task | 10-15 min | 12 | 2 | 2 | 100% |
| Supervisor Eval | 30-45 min | 16 | 4 | 0 | 100% |
| Developer Extend | 2-4 hours | 10 | 3 | 0 | 100% |

---

## References

- User Personas: `user-personas.md`
- User Stories: `user-stories.md`
- Use Cases: `use-cases.md`
- Usability Requirements: `../05-non-functional/usability-requirements.md`
