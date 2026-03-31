# Technical Constraints - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** TECH-002  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines technical constraints, limitations, and requirements that shape the implementation of the Orchestrator Desktop App.

---

## 2. Platform Constraints

### PC1: Operating System
**Constraint:** Application must run on Windows  
**Rationale:** Development environment and target deployment is Windows PC  
**Impact:** 
- Use Windows-compatible file paths
- PowerShell for build scripts
- Windows-specific QSettings storage

**Mitigation:** PyQt6 and Python are cross-platform, but Windows is only tested platform

**Status:** ✅ Accepted

---

### PC2: Python Version
**Constraint:** Python 3.10 or higher required  
**Rationale:** Trinity Core requires Python 3.10+ features  
**Impact:**
- Cannot use Python 3.9 or earlier
- Can use modern Python features (match/case, type hints)

**Verification:** `python --version` must show 3.10+

**Status:** ✅ Enforced

---

### PC3: Desktop Only
**Constraint:** Desktop application only, no mobile or web  
**Rationale:** Bachelor project scope, PyQt6 is desktop framework  
**Impact:**
- No responsive design for mobile
- No web browser compatibility
- Mouse and keyboard input only

**Status:** ✅ Accepted

---

## 3. Framework Constraints

### FC1: UI Framework
**Constraint:** Must use PyQt6  
**Rationale:** Framework decision made in Sprint 0  
**Impact:**
- Qt-specific patterns and APIs
- GPL/Commercial licensing considerations
- Learning curve for PyQt6

**Alternatives Considered:** Electron (rejected - higher overhead)

**Status:** ✅ Implemented

**Reference:** `_runtime/prototypes/FRAMEWORK_DECISION.md`

---

### FC2: Async Framework
**Constraint:** Must use Python asyncio  
**Rationale:** Non-blocking UI during task execution  
**Impact:**
- Async/await syntax required
- QThread integration for Qt compatibility
- Event loop management

**Status:** ✅ Implemented

---

### FC3: Database
**Constraint:** Must use SQLite  
**Rationale:** Lightweight, serverless, built into Python  
**Impact:**
- Single-file database
- No concurrent write optimization
- Limited to local storage

**Alternatives Considered:** PostgreSQL (rejected - overkill), JSON files (rejected - no query capability)

**Status:** ✅ Implemented

---

## 4. Integration Constraints

### IC1: Trinity Core Dependency
**Constraint:** Must integrate with existing Trinity Core  
**Rationale:** Core orchestration functionality provided by Trinity  
**Impact:**
- Cannot modify Trinity Core
- Must use Trinity's adapter interface
- Dependent on Trinity stability

**Mitigation:** Bridge pattern isolates integration

**Status:** ✅ Handled via TrinityBridge

---

### IC2: Gemini API Dependency
**Constraint:** Optional dependency on Gemini API  
**Rationale:** Planning requires LLM, but must work offline  
**Impact:**
- API key required for live mode
- Network dependency in live mode
- Must provide offline fallback

**Mitigation:** Mock mode for offline operation

**Status:** ✅ Handled via testing/gemini_mock

---

### IC3: No External Services
**Constraint:** No cloud services or external dependencies beyond Gemini API  
**Rationale:** Bachelor project, single-user, local deployment  
**Impact:**
- No cloud storage
- No user authentication
- No analytics or telemetry

**Status:** ✅ Accepted

---

## 5. Performance Constraints

### PF1: UI Responsiveness
**Constraint:** UI must respond within 100ms  
**Rationale:** User expectation for desktop applications  
**Impact:**
- All long operations must be async
- No blocking I/O on main thread
- Progress indicators for long tasks

**Measurement:** UI event loop latency

**Status:** ✅ Achieved (<50ms typical)

---

### PF2: History Load Time
**Constraint:** History must load within 1 second for <1000 tasks  
**Rationale:** Acceptable user experience  
**Impact:**
- Database queries must be optimized
- May need pagination for larger histories
- Indexing required

**Measurement:** Time from tab switch to table populated

**Status:** ✅ Achieved (<500ms for 1000 tasks)

---

### PF3: Screenshot Display
**Constraint:** Screenshot must display within 100ms of capture  
**Rationale:** Real-time monitoring requirement  
**Impact:**
- File system monitoring must be efficient
- Image loading must be async
- May need to throttle rapid updates

**Status:** ✅ Achieved

---

### PF4: Memory Usage
**Constraint:** Application should use <500MB RAM  
**Rationale:** Reasonable for desktop application  
**Impact:**
- Limit screenshot caching
- Release resources when not needed
- Avoid memory leaks

**Measurement:** Task Manager / Resource Monitor

**Status:** ✅ Achieved (typical <200MB)

---

## 6. Storage Constraints

### SC1: Local Storage Only
**Constraint:** All data stored locally on PC  
**Rationale:** No cloud infrastructure for bachelor project  
**Impact:**
- No data synchronization
- No backup beyond local backups
- Single point of failure

**Status:** ✅ Accepted

---

### SC2: Screenshot Storage
**Constraint:** Screenshots stored in `_runtime/screenshots/`  
**Rationale:** Consistent with Trinity Core conventions  
**Impact:**
- Directory must be writable
- Disk space can grow unbounded
- Manual cleanup may be needed

**Mitigation:** Frame limits in settings

**Status:** ✅ Implemented with limits

---

### SC3: Database Location
**Constraint:** SQLite database at `_runtime/history.db`  
**Rationale:** Keep runtime data in _runtime folder  
**Impact:**
- Database file must be accessible
- No distributed database
- Backup requires file copy

**Status:** ✅ Implemented

---

## 7. Security Constraints

### SE1: API Key Storage
**Constraint:** API key stored in QSettings  
**Rationale:** Platform-specific secure storage  
**Impact:**
- Windows: Registry
- Not encrypted at rest
- Accessible to user account

**Limitation:** Not production-grade security, acceptable for bachelor project

**Status:** ✅ Implemented

---

### SE2: No Authentication
**Constraint:** No user authentication or access control  
**Rationale:** Single-user application  
**Impact:**
- Anyone with PC access can use app
- No user separation
- No audit trail of who did what

**Status:** ✅ Accepted (out of scope)

---

### SE3: Input Validation Only
**Constraint:** Security limited to input validation  
**Rationale:** Bachelor project, not production system  
**Impact:**
- No encryption
- No secure communication
- No penetration testing

**Status:** ✅ Accepted

---

## 8. Testing Constraints

### TC1: Test Coverage Target
**Constraint:** Must achieve ≥85% code coverage  
**Rationale:** Academic quality standard  
**Impact:**
- All core logic must be tested
- UI tests required
- Integration tests needed

**Measurement:** pytest-cov report

**Status:** ✅ Achieved (86%)

---

### TC2: Mock Mode Required
**Constraint:** All tests must run without live API  
**Rationale:** CI/CD and offline development  
**Impact:**
- Mock mode must be comprehensive
- Tests must not depend on network
- Deterministic test results

**Status:** ✅ Implemented via testing/gemini_mock

---

### TC3: Test Execution Time
**Constraint:** Full test suite should complete within 5 minutes  
**Rationale:** Developer productivity  
**Impact:**
- Tests must be efficient
- May need to parallelize
- Avoid slow integration tests

**Measurement:** `pytest tests/ -v` duration

**Status:** ✅ Achieved (~2 minutes)

---

## 9. Development Constraints

### DC1: Single Developer
**Constraint:** One developer (bachelor student)  
**Rationale:** Bachelor project scope  
**Impact:**
- Limited bandwidth
- No code reviews
- Self-directed decisions

**Mitigation:** Comprehensive documentation, testing

**Status:** ✅ Accepted

---

### DC2: Timeline
**Constraint:** 4-5 sprints within academic semester  
**Rationale:** Academic deadline  
**Impact:**
- Feature prioritization critical
- Must defer non-essential features
- Quality over quantity

**Status:** ✅ Managed (4 sprints completed)

---

### DC3: No Budget
**Constraint:** Zero budget for tools or services  
**Rationale:** Student project  
**Impact:**
- Free/open-source tools only
- No paid APIs beyond Gemini free tier
- No cloud hosting

**Status:** ✅ Accepted

---

## 10. Deployment Constraints

### DP1: Manual Deployment
**Constraint:** Manual installation on single PC  
**Rationale:** Not distributed software  
**Impact:**
- No installer required (nice to have)
- No update mechanism
- No telemetry

**Status:** ✅ Accepted (packaging configs created for future)

---

### DP2: Python Environment
**Constraint:** Requires Python and dependencies installed  
**Rationale:** Not compiled to standalone executable (yet)  
**Impact:**
- User must have Python 3.10+
- Must install requirements.txt
- Environment setup required

**Mitigation:** Packaging configs exist for PyInstaller

**Status:** ✅ Accepted (standalone build possible but not required)

---

### DP3: No CI/CD
**Constraint:** No continuous integration or deployment  
**Rationale:** Single developer, single deployment  
**Impact:**
- Manual testing before commits
- No automated deployment
- No build pipeline

**Status:** ✅ Accepted

---

## 11. Documentation Constraints

### DOC1: Professional Documentation Required
**Constraint:** Must meet academic documentation standards  
**Rationale:** Bachelor degree evaluation criteria  
**Impact:**
- Comprehensive requirements documentation
- Architecture diagrams
- User manual
- Test documentation

**Status:** 🔄 In progress (requirements documentation being created)

---

### DOC2: English Language
**Constraint:** All documentation in English  
**Rationale:** International standard, academic requirement  
**Impact:**
- Code comments in English
- Documentation in English
- UI text in English

**Status:** ✅ Enforced

---

## 12. Licensing Constraints

### LC1: Open Source Dependencies
**Constraint:** All dependencies must be open source  
**Rationale:** No budget, academic project  
**Impact:**
- PyQt6 GPL license
- Must comply with GPL if distributing
- Academic use is acceptable

**Status:** ✅ Compliant

---

### LC2: No Commercial Use
**Constraint:** Not intended for commercial use  
**Rationale:** Bachelor project, GPL dependencies  
**Impact:**
- Academic/educational use only
- No commercial distribution
- No warranty

**Status:** ✅ Accepted

---

## 13. Constraint Summary

| Category | Total Constraints | Status |
|----------|-------------------|--------|
| Platform | 3 | ✅ All accepted |
| Framework | 3 | ✅ All implemented |
| Integration | 3 | ✅ All handled |
| Performance | 4 | ✅ All achieved |
| Storage | 3 | ✅ All implemented |
| Security | 3 | ✅ All accepted |
| Testing | 3 | ✅ All achieved |
| Development | 3 | ✅ All managed |
| Deployment | 3 | ✅ All accepted |
| Documentation | 2 | 🔄 In progress |
| Licensing | 2 | ✅ All compliant |
| **Total** | **32** | **31 ✅, 1 🔄** |

---

## 14. Risk Assessment

### High-Impact Constraints
- **IC1 (Trinity Core):** Dependency on external codebase - Mitigated via bridge pattern
- **IC2 (Gemini API):** Network dependency - Mitigated via mock mode
- **TC1 (Coverage):** Academic requirement - Achieved at 86%

### Medium-Impact Constraints
- **PF1 (UI Responsiveness):** User experience critical - Achieved via async
- **DC2 (Timeline):** Fixed deadline - Managed via scope control

### Low-Impact Constraints
- All others are accepted limitations or successfully implemented

---

## 15. Constraint Traceability

### To Requirements
- PC2 → TR1.1 (Python 3.10+)
- FC1 → TR1.2 (PyQt6)
- FC3 → TR1.3 (SQLite)
- IC1 → TR2.6 (TrinityBridge)
- TC1 → NFR4.1 (≥85% coverage)

### To Architecture
- FC1, FC2 → System Architecture (UI + Async layers)
- IC1 → Bridge Pattern
- FC3 → Repository Pattern (HistoryManager)

---

## References

- System Architecture: `system-architecture.md`
- Integration Requirements: `integration-requirements.md`
- Non-Functional Requirements: `../05-non-functional/`
- Framework Decision: `../../_runtime/prototypes/FRAMEWORK_DECISION.md`
