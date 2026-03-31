# User Personas - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** USR-001  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines user personas for the Orchestrator Desktop App, establishing clear user archetypes to guide design and implementation decisions.

---

## 2. Primary Persona

### P1: Alex - The Bachelor Student Developer

**Demographics:**
- Age: 22-24
- Role: Computer Science student
- Experience: Intermediate Python, learning desktop development
- Environment: Windows PC, local development setup

**Goals:**
- Complete bachelor degree project successfully
- Learn PyQt6 and desktop application patterns
- Build portfolio-worthy project
- Achieve high academic grade
- Create reusable code for future projects

**Frustrations:**
- No visual feedback from Trinity Core execution
- Manual configuration of environment variables
- Difficulty debugging orchestration failures
- No history of previous task executions
- Uncertainty about what the system is doing

**Technical Profile:**
- Comfortable with Python and command line
- Learning PyQt6 for the first time
- Familiar with testing and documentation
- Prefers clear error messages
- Values code quality and maintainability

**Usage Patterns:**
- Develops and tests locally on Windows PC
- Runs tasks multiple times during development
- Needs to see what went wrong when tasks fail
- Reviews history to understand behavior
- Configures settings for different test scenarios

**Success Criteria:**
- Can submit task and see execution immediately
- Understands what the system is doing at all times
- Can review past executions to debug issues
- Can configure settings without editing files
- Application never crashes or loses data

**Quote:**  
*"I need to see what's happening when I run a task, not just wait and hope it works."*

---

## 3. Secondary Personas

### P2: Professor Maria - The Academic Evaluator

**Demographics:**
- Age: 45-55
- Role: Computer Science professor, thesis supervisor
- Experience: Expert in software engineering, evaluates student projects
- Environment: University office, reviews projects on laptop

**Goals:**
- Assess student technical competence
- Verify code quality and testing standards
- Evaluate documentation completeness
- Confirm understanding of design patterns
- Grade final submission fairly

**Frustrations:**
- Students submit poorly documented code
- Missing requirements documentation
- Unclear architecture decisions
- Low test coverage
- No traceability between requirements and implementation

**Technical Profile:**
- Expert in software engineering principles
- Values professional documentation
- Expects industry-standard practices
- Reviews code quality metrics
- Checks for design pattern usage

**Usage Patterns:**
- Reviews documentation before code
- Runs demo to verify functionality
- Checks test coverage reports
- Evaluates architecture diagrams
- Assesses requirements traceability

**Success Criteria:**
- Professional-quality documentation
- Clear requirements and design decisions
- High test coverage (≥85%)
- Working demo without crashes
- Evidence of software engineering best practices

**Quote:**  
*"I need to see that the student understands not just how to code, but how to engineer software professionally."*

---

### P3: Future Developer - The Maintainer

**Demographics:**
- Age: 20-30
- Role: Developer interested in Trinity Core projects
- Experience: Varies, may be junior to senior
- Environment: Any platform, reviewing code on GitHub

**Goals:**
- Understand the architecture
- Learn from implementation patterns
- Extend functionality
- Fix bugs or add features
- Reuse components in other projects

**Frustrations:**
- Undocumented design decisions
- Unclear code structure
- Missing architecture diagrams
- No explanation of why patterns were chosen
- Difficult to understand data flow

**Technical Profile:**
- Competent Python developer
- May not know PyQt6
- Interested in desktop automation
- Values clean, modular code
- Appreciates good documentation

**Usage Patterns:**
- Reads documentation first
- Reviews architecture diagrams
- Explores code structure
- Runs tests to understand behavior
- Looks for extension points

**Success Criteria:**
- Can understand architecture from documentation
- Can extend features without breaking existing code
- Can run tests to verify changes
- Can trace requirements to implementation
- Can reuse components in other projects

**Quote:**  
*"I want to understand why it was built this way, not just what it does."*

---

## 4. Persona Comparison

| Aspect | Alex (Student) | Maria (Professor) | Future Dev |
|--------|----------------|-------------------|------------|
| **Primary Goal** | Complete project | Evaluate quality | Understand & extend |
| **Technical Level** | Intermediate | Expert | Varies |
| **Usage Frequency** | Daily (development) | Once (evaluation) | Occasional (exploration) |
| **Documentation Need** | User manual | Requirements, architecture | All documentation |
| **Quality Focus** | Working demo | Professional standards | Code maintainability |
| **Error Tolerance** | Low (needs debugging) | Zero (must be stable) | Medium (can fix) |

---

## 5. User Needs by Persona

### Alex's Needs (Primary User)
- **UR1.1:** Visual feedback during task execution
- **UR1.2:** Clear error messages when things fail
- **UR1.3:** Task history to review past executions
- **UR1.4:** Easy settings configuration
- **UR1.5:** Reliable operation without crashes
- **UR1.6:** Fast response times (<1s for UI)

### Maria's Needs (Evaluator)
- **UR2.1:** Professional requirements documentation
- **UR2.2:** Architecture diagrams and design decisions
- **UR2.3:** High test coverage (≥85%)
- **UR2.4:** Working demo for presentation
- **UR2.5:** Traceability matrix
- **UR2.6:** Evidence of software engineering practices

### Future Developer's Needs (Maintainer)
- **UR3.1:** Clear architecture documentation
- **UR3.2:** Explained design patterns
- **UR3.3:** Modular, extensible code structure
- **UR3.4:** Comprehensive test suite
- **UR3.5:** Requirements traceability
- **UR3.6:** Code comments and docstrings

---

## 6. Persona-Driven Design Decisions

### For Alex (Primary User)
- **Decision:** Tabbed UI for clear separation of concerns
- **Rationale:** Easy to understand and navigate

- **Decision:** Real-time status log with timestamps
- **Rationale:** Always know what's happening

- **Decision:** Glass box screenshot view
- **Rationale:** See backend execution visually

- **Decision:** SQLite history with search
- **Rationale:** Review past executions for debugging

### For Maria (Evaluator)
- **Decision:** Professional requirements documentation structure
- **Rationale:** Meets academic standards

- **Decision:** 85%+ test coverage target
- **Rationale:** Industry-standard quality metric

- **Decision:** Architecture diagrams in documentation
- **Rationale:** Visual understanding of design

- **Decision:** Traceability matrix
- **Rationale:** Link requirements to implementation

### For Future Developer (Maintainer)
- **Decision:** Event bus pattern for loose coupling
- **Rationale:** Easy to extend without breaking existing code

- **Decision:** Bridge pattern for Trinity Core integration
- **Rationale:** Isolate dependencies, easy to understand

- **Decision:** Comprehensive docstrings
- **Rationale:** Self-documenting code

- **Decision:** Modular UI panel architecture
- **Rationale:** Reusable components

---

## 7. Persona Scenarios

### Alex's Typical Day
1. Opens application to test new feature
2. Submits task with natural language description
3. Watches execution plan appear
4. Monitors status log for progress
5. Views screenshots to see what backend is doing
6. Task fails - reads error message
7. Reviews history to compare with previous run
8. Adjusts settings and tries again
9. Success - reviews full execution in history

### Maria's Evaluation Session
1. Opens requirements documentation
2. Reviews architecture diagrams
3. Checks traceability matrix
4. Runs pytest to see coverage report (86%)
5. Launches application for demo
6. Submits sample task
7. Observes real-time execution
8. Reviews code quality and patterns
9. Grades based on professional standards

### Future Developer's Exploration
1. Reads README and architecture docs
2. Reviews design patterns documentation
3. Explores code structure
4. Runs test suite to understand behavior
5. Identifies extension point (new UI panel)
6. Adds feature using existing patterns
7. Tests verify no breakage
8. Contributes back or uses in own project

---

## 8. Anti-Personas

### AP1: Enterprise Administrator
**Why not a target:**
- Needs multi-user support (out of scope)
- Requires enterprise deployment (not needed)
- Expects regulatory compliance (not applicable)
- Wants cloud integration (local only)

### AP2: Mobile User
**Why not a target:**
- Needs mobile app (desktop only)
- Expects touch interface (mouse/keyboard)
- Wants offline sync (single device)

### AP3: Non-Technical User
**Why not a target:**
- Expects no technical knowledge (requires Python understanding)
- Wants guided wizards (assumes competence)
- Needs extensive help system (minimal help needed)

---

## 9. Persona Validation

### Alex (Primary User)
- **Validated by:** Developer is the primary user
- **Feedback:** All needs addressed in current implementation
- **Status:** ✅ Satisfied

### Maria (Evaluator)
- **Validated by:** Academic standards research
- **Feedback:** Documentation enhancement in progress
- **Status:** 🔄 In progress

### Future Developer (Maintainer)
- **Validated by:** Code review and documentation structure
- **Feedback:** Architecture clear, documentation improving
- **Status:** 🔄 In progress

---

## References

- User Stories: `user-stories.md`
- Use Cases: `use-cases.md`
- User Journey Maps: `user-journey-maps.md`
- Business Objectives: `../01-business/business-objectives.md`
