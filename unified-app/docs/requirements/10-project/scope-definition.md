# Scope Definition - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** PROJ-001  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines the scope of the Orchestrator Desktop App project, clearly establishing what is included, excluded, and deferred.

---

## 2. Project Overview

**Project Name:** Orchestrator Desktop App (unified-app)  
**Project Type:** Bachelor degree capstone project  
**Duration:** 4-5 sprints  
**Team:** Single developer (student)  
**Purpose:** Desktop UI for task orchestration on Trinity Core

---

## 3. In Scope

### 3.1 Core Features

#### Task Submission and Execution
- Natural language task input
- Domain selection (browser, desktop, auto-detect)
- Task validation
- Task cancellation
- Execution orchestration via Trinity Core

**Status:** ✅ Implemented

---

#### Execution Planning
- Plan generation via MacroPlanner
- Plan display in UI
- Step-by-step execution
- Step status tracking
- Mock mode fallback

**Status:** ✅ Implemented

---

#### Real-Time Monitoring
- Status log with timestamps
- Execution plan with progress
- Screenshot capture and display
- Frame metadata (dimensions, size, FPS)
- UI state management

**Status:** ✅ Implemented

---

#### Task History
- SQLite database persistence
- History table display
- Search and filter
- Task details view
- Status tracking (success/failure/cancelled)

**Status:** ✅ Implemented

---

#### Settings Management
- API key configuration
- Timeout and retry settings
- Domain defaults
- Frame capture limits
- Persistent settings (QSettings)

**Status:** ✅ Implemented

---

#### Startup and Mode Detection
- Live Gemini mode
- Mock mode fallback
- Startup preflight checks
- Configuration validation
- Readiness state management

**Status:** ✅ Implemented

---

### 3.2 Quality Deliverables

#### Testing
- Unit tests (45 tests)
- Integration tests (26 tests)
- UI tests (15 tests)
- Code coverage ≥85% (actual: 86%)
- All acceptance criteria verified

**Status:** ✅ Implemented

---

#### Documentation
- User Manual
- Quick Start Guide
- FAQ
- Sprint completion reports
- Requirements documentation (30+ documents)
- Architecture documentation

**Status:** ✅ Implemented

---

#### Packaging
- PyInstaller spec file
- NSIS installer script
- Build scripts (PowerShell)
- Requirements.txt

**Status:** ✅ Implemented

---

## 4. Out of Scope

### 4.1 Features Not Included

#### Multi-User Support
**Reason:** Single-user bachelor project  
**Impact:** No user authentication, no access control  
**Alternative:** Single-user local deployment

---

#### Cloud Integration
**Reason:** Local deployment only  
**Impact:** No cloud storage, no synchronization  
**Alternative:** Local SQLite database

---

#### Mobile/Web Versions
**Reason:** Desktop application only  
**Impact:** No responsive design, no mobile UI  
**Alternative:** PyQt6 desktop application

---

#### Plugin System
**Reason:** Out of scope for bachelor project  
**Impact:** No extensibility via plugins  
**Alternative:** Modular architecture allows code extension

---

#### Advanced Analytics
**Reason:** Not required for bachelor project  
**Impact:** No usage analytics, no telemetry  
**Alternative:** Basic task history

---

#### Internationalization
**Reason:** English only for academic project  
**Impact:** No multi-language support  
**Alternative:** English UI and documentation

---

#### Enterprise Features
**Reason:** Academic project, not production system  
**Impact:** No RBAC, no audit logs, no compliance  
**Alternative:** Basic security appropriate for scope

---

### 4.2 Quality Features Not Included

#### Production Security
**Reason:** Bachelor project, not production deployment  
**Impact:** No encryption at rest, basic security only  
**Alternative:** Input validation, API key masking

---

#### Regulatory Compliance
**Reason:** No regulatory requirements  
**Impact:** No GDPR, HIPAA, SOC 2 compliance  
**Alternative:** Academic integrity compliance

---

#### Enterprise Deployment
**Reason:** Single PC deployment  
**Impact:** No installer, no update mechanism, no CI/CD  
**Alternative:** Manual installation, packaging configs available

---

## 5. Deferred Features

### 5.1 Browser Adapter Integration
**Status:** Deferred from PoC Stabilization epic  
**Reason:** Time constraints, not critical for demo  
**Future:** Can be integrated when browser-gui-automation is stable  
**Impact:** Auto-detect may not route to browser correctly

---

### 5.2 Desktop Adapter Integration
**Status:** Deferred from PoC Stabilization epic  
**Reason:** Time constraints, not critical for demo  
**Future:** Can be integrated when desktop-ai-agent is stable  
**Impact:** Auto-detect may not route to desktop correctly

---

### 5.3 Live Acceptance Tests
**Status:** Partially implemented (3 tests, skip if offline)  
**Reason:** Requires live Gemini API key  
**Future:** Can be run with `POC_LIVE_TEST=1`  
**Impact:** Full end-to-end testing requires manual execution

---

### 5.4 Production Configuration
**Status:** Deferred  
**Reason:** Not needed for bachelor project  
**Future:** Real GEMINI_API_KEY setup, CI secrets  
**Impact:** Demo uses mock mode

---

## 6. Scope Boundaries

### 6.1 Functional Boundaries

**Included:**
- Task submission and execution
- Real-time monitoring
- History management
- Settings configuration

**Excluded:**
- Task scheduling
- Task templates
- Batch execution
- Task sharing

---

### 6.2 Technical Boundaries

**Included:**
- PyQt6 desktop UI
- SQLite database
- Gemini API integration
- Mock mode fallback

**Excluded:**
- Web interface
- Cloud database
- Other LLM providers
- Distributed execution

---

### 6.3 Platform Boundaries

**Included:**
- Windows desktop
- Python 3.10+
- Local deployment

**Excluded:**
- Linux support (untested)
- macOS support (untested)
- Mobile platforms
- Web browsers

---

## 7. Scope Changes

### 7.1 Approved Changes

**Change 1: Mock Mode Added**
- **Date:** Sprint 0
- **Reason:** Enable offline development and testing
- **Impact:** Positive - enables testing without API key
- **Status:** Implemented

**Change 2: Adapters Deferred**
- **Date:** Sprint 4
- **Reason:** Time constraints, focus on core features
- **Impact:** Neutral - core features complete
- **Status:** Deferred

**Change 3: Enhanced Documentation**
- **Date:** 2026-03-14
- **Reason:** Academic evaluation requirements
- **Impact:** Positive - professional documentation
- **Status:** In progress

---

### 7.2 Rejected Changes

**Rejected 1: Multi-User Support**
- **Reason:** Out of scope for bachelor project
- **Impact:** None - single user sufficient

**Rejected 2: Cloud Synchronization**
- **Reason:** Local deployment only
- **Impact:** None - local storage sufficient

**Rejected 3: Plugin System**
- **Reason:** Complexity vs benefit
- **Impact:** None - modular architecture sufficient

---

## 8. Scope Verification

### 8.1 Requirements Coverage

**Functional Requirements:** 30/30 implemented (100%)  
**User Stories:** 22/24 implemented (92%)  
**Use Cases:** 7/7 implemented (100%)  
**Acceptance Criteria:** 32/32 verified (100%)

**Status:** ✅ All in-scope requirements met

---

### 8.2 Feature Completeness

**Core Features:** 6/6 complete (100%)  
**Quality Features:** All complete  
**Documentation:** 30+ documents  
**Testing:** 86 tests, 86% coverage

**Status:** ✅ All in-scope features complete

---

## 9. Scope Constraints

### 9.1 Time Constraints
- 4-5 sprints (academic semester)
- Single developer
- Academic deadline

**Impact:** Feature prioritization, adapter deferral

---

### 9.2 Resource Constraints
- Zero budget
- No team
- No infrastructure

**Impact:** Local deployment, free tools only

---

### 9.3 Technical Constraints
- Python 3.10+ required
- Windows environment
- Trinity Core dependency

**Impact:** Platform limitations, integration constraints

---

## 10. Success Criteria

### 10.1 Minimum Success
- ✅ All core features implemented
- ✅ Application runs without crashes
- ✅ Code coverage ≥85%
- ✅ Working demo for presentation

**Status:** ✅ Achieved

---

### 10.2 Full Success
- ✅ All in-scope features complete
- ✅ Professional documentation
- ✅ Comprehensive testing
- ✅ Quality metrics met
- 🔄 Enhanced requirements documentation

**Status:** 🔄 Nearly achieved (documentation in progress)

---

### 10.3 Stretch Goals (Not Required)
- ⚠️ Browser adapter integration (deferred)
- ⚠️ Desktop adapter integration (deferred)
- ⚠️ Live acceptance tests (partial)
- ⚠️ Standalone executable (configs exist, not built)

**Status:** ⚠️ Deferred (acceptable)

---

## 11. Stakeholder Agreement

### Student/Developer
**Agrees:** All in-scope features implemented  
**Satisfied:** Yes  
**Concerns:** None

### Academic Supervisor
**Agrees:** Scope appropriate for bachelor project  
**Satisfied:** Expected (pending final review)  
**Concerns:** None anticipated

---

## 12. Scope Management

### 12.1 Scope Creep Prevention
- Clear scope definition (this document)
- Regular scope review
- Prioritization of core features
- Deferral of non-critical features

**Status:** ✅ Managed successfully

---

### 12.2 Scope Change Process
1. Identify proposed change
2. Assess impact on timeline and quality
3. Approve or reject
4. Document decision
5. Update scope document

**Status:** ✅ Process followed

---

## 13. Future Scope

### 13.1 Potential Extensions
- Browser adapter integration
- Desktop adapter integration
- Task templates
- Batch execution
- Export/import history
- Advanced search
- Task scheduling

**Status:** Documented for future reference

---

### 13.2 Production Readiness
If deploying to production, would need:
- Multi-user support
- Authentication and authorization
- Encryption at rest
- Production security hardening
- CI/CD pipeline
- Monitoring and logging
- Backup and recovery

**Status:** Out of scope for bachelor project

---

## References

- Business Objectives: `../01-business/business-objectives.md`
- Client Brief: `../01-business/client-brief.md`
- Functional Requirements: `../03-functional/functional-requirements.md`
- Assumptions and Constraints: `assumptions-constraints.md`
- Dependencies: `dependencies.md`
