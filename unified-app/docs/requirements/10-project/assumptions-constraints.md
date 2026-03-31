# Assumptions and Constraints - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** PROJ-002  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines assumptions and constraints for the Orchestrator Desktop App project, establishing what we assume to be true and what limits our implementation.

---

## 2. Assumptions

### 2.1 Technical Assumptions

#### A1: Trinity Core Stability
**Assumption:** Trinity Core is stable and functional

**Rationale:** Project depends on Trinity Core for orchestration

**Risk if False:** Integration failures, execution errors

**Mitigation:** Bridge pattern isolates integration

**Status:** ✅ Valid assumption

---

#### A2: PyQt6 Suitability
**Assumption:** PyQt6 is suitable for desktop UI requirements

**Rationale:** Framework decision made in Sprint 0

**Risk if False:** UI limitations, performance issues

**Mitigation:** Prototype validated suitability

**Status:** ✅ Valid assumption

---

#### A3: SQLite Sufficiency
**Assumption:** SQLite is sufficient for task history storage

**Rationale:** Single-user, local deployment

**Risk if False:** Performance issues with large histories

**Mitigation:** Tested with 10,000 records, performs well

**Status:** ✅ Valid assumption

---

#### A4: Mock Mode Viability
**Assumption:** Mock mode enables offline development and testing

**Rationale:** Cannot depend on live API for all testing

**Risk if False:** Tests unreliable, development blocked

**Mitigation:** Mock mode implemented and tested

**Status:** ✅ Valid assumption

---

#### A5: Windows Environment
**Assumption:** Windows environment is available for development and deployment

**Rationale:** Developer's primary environment

**Risk if False:** Cannot develop or deploy

**Mitigation:** N/A (requirement, not assumption)

**Status:** ✅ Valid assumption

---

### 2.2 User Assumptions

#### A6: Technical Competence
**Assumption:** User has basic technical competence (can run Python, install dependencies)

**Rationale:** Bachelor project, not consumer product

**Risk if False:** Installation difficulties

**Mitigation:** User manual provides clear instructions

**Status:** ✅ Valid assumption

---

#### A7: Single User
**Assumption:** Application will be used by single user (developer)

**Rationale:** Bachelor project scope

**Risk if False:** Multi-user conflicts

**Mitigation:** N/A (out of scope)

**Status:** ✅ Valid assumption

---

#### A8: Local Deployment
**Assumption:** Application will run on single PC

**Rationale:** No distributed deployment needed

**Risk if False:** Deployment complexity

**Mitigation:** N/A (out of scope)

**Status:** ✅ Valid assumption

---

### 2.3 Project Assumptions

#### A9: Timeline Sufficiency
**Assumption:** 4-5 sprints is sufficient for core features

**Rationale:** Sprint planning and velocity estimation

**Risk if False:** Incomplete features

**Mitigation:** Feature prioritization, adapter deferral

**Status:** ✅ Valid assumption (4 sprints completed)

---

#### A10: Single Developer Capability
**Assumption:** Single developer can complete project

**Rationale:** Bachelor project scope

**Risk if False:** Project incomplete

**Mitigation:** Scope management, realistic planning

**Status:** ✅ Valid assumption

---

#### A11: No Budget Required
**Assumption:** Free tools and services are sufficient

**Rationale:** Open source tools, Gemini free tier

**Risk if False:** Need paid services

**Mitigation:** Mock mode eliminates API dependency

**Status:** ✅ Valid assumption

---

### 2.4 Quality Assumptions

#### A12: 85% Coverage Achievable
**Assumption:** 85% code coverage is achievable and sufficient

**Rationale:** Industry standard, academic requirement

**Risk if False:** Quality concerns

**Mitigation:** Comprehensive test suite

**Status:** ✅ Valid assumption (86% achieved)

---

#### A13: Manual Testing Acceptable
**Assumption:** Manual testing is acceptable (no CI/CD required)

**Rationale:** Single developer, single deployment

**Risk if False:** Regression risks

**Mitigation:** Comprehensive automated test suite

**Status:** ✅ Valid assumption

---

## 3. Constraints

### 3.1 Platform Constraints

#### C1: Windows Only
**Constraint:** Application must run on Windows

**Type:** Hard constraint

**Rationale:** Development environment, target deployment

**Impact:** No cross-platform testing, Windows-specific paths

**Workaround:** None needed (requirement)

**Status:** ✅ Accepted

---

#### C2: Python 3.10+
**Constraint:** Python 3.10 or higher required

**Type:** Hard constraint

**Rationale:** Trinity Core requirement

**Impact:** Cannot use Python 3.9 or earlier

**Workaround:** None (dependency requirement)

**Status:** ✅ Accepted

---

#### C3: Desktop Only
**Constraint:** Desktop application only

**Type:** Hard constraint

**Rationale:** PyQt6 is desktop framework

**Impact:** No mobile or web versions

**Workaround:** None needed (out of scope)

**Status:** ✅ Accepted

---

### 3.2 Technical Constraints

#### C4: PyQt6 Framework
**Constraint:** Must use PyQt6

**Type:** Hard constraint

**Rationale:** Framework decision (Sprint 0)

**Impact:** Qt-specific patterns, GPL licensing

**Workaround:** None (design decision)

**Status:** ✅ Accepted

---

#### C5: SQLite Database
**Constraint:** Must use SQLite

**Type:** Soft constraint

**Rationale:** Lightweight, serverless, built-in

**Impact:** Single-file database, limited concurrency

**Workaround:** Could swap for other DB (Repository pattern)

**Status:** ✅ Accepted

---

#### C6: Trinity Core Dependency
**Constraint:** Must integrate with Trinity Core

**Type:** Hard constraint

**Rationale:** Core orchestration functionality

**Impact:** Dependent on Trinity stability

**Workaround:** Bridge pattern isolates integration

**Status:** ✅ Accepted

---

#### C7: Gemini API Dependency
**Constraint:** Optional dependency on Gemini API

**Type:** Soft constraint

**Rationale:** Planning requires LLM

**Impact:** Network dependency in live mode

**Workaround:** Mock mode for offline operation

**Status:** ✅ Mitigated

---

### 3.3 Resource Constraints

#### C8: Zero Budget
**Constraint:** No budget for tools or services

**Type:** Hard constraint

**Rationale:** Student project

**Impact:** Free/open-source tools only

**Workaround:** None needed (sufficient tools available)

**Status:** ✅ Accepted

---

#### C9: Single Developer
**Constraint:** One developer only

**Type:** Hard constraint

**Rationale:** Bachelor project

**Impact:** Limited bandwidth, no code reviews

**Workaround:** Comprehensive documentation, testing

**Status:** ✅ Accepted

---

#### C10: Time Limited
**Constraint:** Academic semester timeline

**Type:** Hard constraint

**Rationale:** Academic deadline

**Impact:** Feature prioritization required

**Workaround:** Scope management, deferral

**Status:** ✅ Managed

---

### 3.4 Quality Constraints

#### C11: 85% Coverage Minimum
**Constraint:** Code coverage must be ≥85%

**Type:** Hard constraint

**Rationale:** Academic quality standard

**Impact:** All core logic must be tested

**Workaround:** None (requirement)

**Status:** ✅ Achieved (86%)

---

#### C12: No Critical Bugs
**Constraint:** Zero critical bugs in final submission

**Type:** Hard constraint

**Rationale:** Academic evaluation

**Impact:** Thorough testing required

**Workaround:** None (requirement)

**Status:** ✅ Achieved

---

#### C13: Professional Documentation
**Constraint:** Documentation must meet academic standards

**Type:** Hard constraint

**Rationale:** Academic evaluation criteria

**Impact:** Comprehensive documentation effort

**Workaround:** None (requirement)

**Status:** 🔄 In progress

---

### 3.5 Scope Constraints

#### C14: Single User Only
**Constraint:** No multi-user support

**Type:** Hard constraint

**Rationale:** Out of scope for bachelor project

**Impact:** No authentication, no access control

**Workaround:** None needed (acceptable)

**Status:** ✅ Accepted

---

#### C15: Local Deployment Only
**Constraint:** No cloud or distributed deployment

**Type:** Hard constraint

**Rationale:** Bachelor project scope

**Impact:** No cloud features, no synchronization

**Workaround:** None needed (acceptable)

**Status:** ✅ Accepted

---

#### C16: English Only
**Constraint:** English language only

**Type:** Hard constraint

**Rationale:** Academic requirement

**Impact:** No internationalization

**Workaround:** None needed (acceptable)

**Status:** ✅ Accepted

---

### 3.6 Security Constraints

#### C17: Basic Security Only
**Constraint:** Not production-grade security

**Type:** Soft constraint

**Rationale:** Academic project, not production

**Impact:** API key not encrypted at rest

**Workaround:** Acceptable for scope

**Status:** ✅ Accepted

---

#### C18: No Compliance Requirements
**Constraint:** No regulatory compliance needed

**Type:** Hard constraint

**Rationale:** Academic project

**Impact:** No GDPR, HIPAA, SOC 2

**Workaround:** None needed (out of scope)

**Status:** ✅ Accepted

---

## 4. Assumption Validation

| Assumption | Validated | Method | Result |
|------------|-----------|--------|--------|
| A1: Trinity Core Stability | ✅ | Integration testing | Stable |
| A2: PyQt6 Suitability | ✅ | Prototype | Suitable |
| A3: SQLite Sufficiency | ✅ | Performance testing | Sufficient |
| A4: Mock Mode Viability | ✅ | Testing | Viable |
| A5: Windows Environment | ✅ | Development | Available |
| A6: Technical Competence | ✅ | User testing | Competent |
| A7: Single User | ✅ | Scope definition | Valid |
| A8: Local Deployment | ✅ | Deployment | Valid |
| A9: Timeline Sufficiency | ✅ | Sprint completion | Sufficient |
| A10: Single Developer | ✅ | Project completion | Capable |
| A11: No Budget Required | ✅ | Tool selection | Sufficient |
| A12: 85% Coverage | ✅ | Testing | Achievable (86%) |
| A13: Manual Testing | ✅ | Test execution | Acceptable |

**Validation Status:** All assumptions validated ✅

---

## 5. Constraint Management

### Hard Constraints (Cannot Change)
- C1: Windows Only
- C2: Python 3.10+
- C3: Desktop Only
- C4: PyQt6 Framework
- C6: Trinity Core Dependency
- C8: Zero Budget
- C9: Single Developer
- C10: Time Limited
- C11: 85% Coverage
- C12: No Critical Bugs
- C13: Professional Documentation
- C14: Single User Only
- C15: Local Deployment Only
- C16: English Only
- C18: No Compliance

**Status:** All hard constraints accepted and managed

### Soft Constraints (Can Mitigate)
- C5: SQLite Database (Repository pattern allows swap)
- C7: Gemini API Dependency (Mock mode mitigates)
- C17: Basic Security (Acceptable for scope)

**Status:** All soft constraints mitigated

---

## 6. Risk Assessment

### High Risk Assumptions
- None (all validated)

### Medium Risk Assumptions
- A9: Timeline Sufficiency (managed via scope control)
- A10: Single Developer Capability (managed via realistic planning)

### Low Risk Assumptions
- All others

**Overall Risk:** Low (all assumptions validated, constraints managed)

---

## 7. Constraint Impact

### Positive Impacts
- C9 (Single Developer): Clear decision-making
- C14 (Single User): Simplified architecture
- C15 (Local Deployment): No deployment complexity

### Negative Impacts
- C8 (Zero Budget): Limited tool options (mitigated by open source)
- C10 (Time Limited): Feature deferral (managed)

### Neutral Impacts
- Most constraints are neutral (define scope)

---

## 8. Assumption Changes

### Assumptions That Changed
None - all initial assumptions remained valid

### Assumptions That Were Invalidated
None

### New Assumptions Added
- A13: Manual Testing Acceptable (added during Sprint 1)

---

## 9. Constraint Violations

### Violations Detected
None

### Near Violations
- C10 (Time Limited): Sprint 4 nearly overran, managed by deferring adapters

### Violations Prevented
- Scope management prevented feature creep
- Prioritization prevented timeline overrun

---

## 10. Dependencies on Assumptions

### Critical Dependencies
- Project success depends on A1 (Trinity Core Stability)
- Testing depends on A4 (Mock Mode Viability)
- Completion depends on A9 (Timeline Sufficiency)

### All Dependencies Satisfied
✅ All critical assumptions validated

---

## 11. Constraint Trade-offs

### Accepted Trade-offs
- C14 (Single User) vs Multi-user: Accepted for scope
- C15 (Local Deployment) vs Cloud: Accepted for scope
- C17 (Basic Security) vs Production Security: Accepted for scope

### Rejected Trade-offs
- None (all necessary trade-offs accepted)

---

## 12. Future Considerations

### If Assumptions Change
- If Trinity Core becomes unstable: Implement fallback or alternative
- If timeline extends: Could implement deferred features
- If multi-user needed: Major architecture changes required

### If Constraints Relax
- If budget available: Could use paid services
- If more time: Could implement deferred features
- If team grows: Could parallelize development

**Status:** Not anticipated for bachelor project

---

## References

- Scope Definition: `scope-definition.md`
- Technical Constraints: `../04-technical/technical-constraints.md`
- Business Objectives: `../01-business/business-objectives.md`
- Risks and Mitigations: `risks-mitigations.md`
