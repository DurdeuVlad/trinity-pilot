# Security Requirements - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** NFR-002  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines security requirements for the Orchestrator Desktop App. Note: This is a bachelor degree project for single-user local deployment, not a production system.

---

## 2. Security Scope

### In Scope
- Input validation
- API key storage
- SQL injection prevention
- Basic data protection

### Out of Scope (Bachelor Project)
- Multi-user authentication
- Encryption at rest
- Network security
- Penetration testing
- Regulatory compliance
- Production-grade security hardening

---

## 3. NFR-S1: Input Validation

### NFR-S1.1: Task Description Validation
**Requirement:** All user input shall be validated before processing

**Validation:**
- Length: 1-1000 characters
- Type: String (UTF-8)
- No code execution from input

**Implementation:**
```python
def _validate_input(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text) > 1000:
        return False
    return True
```

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S1.2: Settings Validation
**Requirement:** Settings values shall be validated before saving

**Validation:**
- Timeout: 1-300 seconds (integer)
- Retry: 0-10 (integer)
- Frame limits: positive integers
- API key: any string (validated on use)

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S1.3: SQL Injection Prevention
**Requirement:** Database queries shall use parameterized queries

**Implementation:**
```python
cursor.execute(
    "INSERT INTO tasks (description, domain) VALUES (?, ?)",
    (description, domain)
)
```

**Protection:** SQLite parameterized queries prevent injection

**Status:** ✅ Implemented

**Priority:** Must Have

---

## 4. NFR-S2: API Key Security

### NFR-S2.1: API Key Storage
**Requirement:** API key shall be stored securely

**Storage:** QSettings (platform-specific secure storage)
- Windows: Registry `HKEY_CURRENT_USER`
- Accessible only to user account
- Not world-readable

**Limitation:** Not encrypted at rest (acceptable for bachelor project)

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S2.2: API Key Display
**Requirement:** API key shall be masked in UI

**Implementation:** QLineEdit with `setEchoMode(QLineEdit.EchoMode.Password)`

**Display:** Shows `***` instead of actual key

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S2.3: API Key Logging
**Requirement:** API key shall not be logged in plain text

**Implementation:**
- Logs show "API key: [REDACTED]"
- No plain text in status messages
- No plain text in error messages

**Status:** ✅ Implemented

**Priority:** Must Have

---

## 5. NFR-S3: Data Protection

### NFR-S3.1: Local Data Only
**Requirement:** All data shall be stored locally

**Storage:**
- Task history: Local SQLite database
- Screenshots: Local file system
- Settings: Local QSettings

**Network:** No data transmitted except to Gemini API

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S3.2: Database File Permissions
**Requirement:** Database file shall be readable only by user

**Permissions:** Windows file system default (user access only)

**Location:** `_runtime/history.db`

**Status:** ✅ Implemented (OS default)

**Priority:** Should Have

---

### NFR-S3.3: Screenshot File Permissions
**Requirement:** Screenshots shall be readable only by user

**Permissions:** Windows file system default (user access only)

**Location:** `_runtime/screenshots/`

**Status:** ✅ Implemented (OS default)

**Priority:** Should Have

---

## 6. NFR-S4: Authentication and Authorization

### NFR-S4.1: No User Authentication
**Requirement:** Application does not require user authentication

**Rationale:** Single-user desktop application

**Implication:** Anyone with PC access can use app

**Status:** ✅ Accepted (out of scope)

**Priority:** N/A (not required)

---

### NFR-S4.2: No Access Control
**Requirement:** No role-based access control

**Rationale:** Single user, no multi-user support

**Implication:** All features accessible to user

**Status:** ✅ Accepted (out of scope)

**Priority:** N/A (not required)

---

## 7. NFR-S5: Network Security

### NFR-S5.1: HTTPS for API
**Requirement:** Gemini API communication shall use HTTPS

**Implementation:** google-generativeai SDK uses HTTPS by default

**Protection:** Encrypted in transit

**Status:** ✅ Implemented (SDK default)

**Priority:** Must Have

---

### NFR-S5.2: API Key Transmission
**Requirement:** API key shall be transmitted securely

**Implementation:** HTTPS headers via SDK

**Protection:** Encrypted in transit

**Status:** ✅ Implemented (SDK default)

**Priority:** Must Have

---

### NFR-S5.3: No Telemetry
**Requirement:** Application shall not send telemetry or analytics

**Implementation:** No telemetry code

**Privacy:** No data leaves user's PC except API calls

**Status:** ✅ Implemented

**Priority:** Must Have

---

## 8. NFR-S6: Error Handling Security

### NFR-S6.1: No Sensitive Data in Errors
**Requirement:** Error messages shall not expose sensitive data

**Implementation:**
- No API keys in error messages
- No file paths in user-facing errors
- No stack traces in UI

**Example:**
```python
# Bad: "API key abc123 is invalid"
# Good: "API key is invalid"
```

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S6.2: Graceful Error Handling
**Requirement:** Errors shall not crash application or expose internals

**Implementation:**
- Try/catch blocks
- User-friendly error messages
- Logging for debugging

**Status:** ✅ Implemented

**Priority:** Must Have

---

## 9. NFR-S7: Code Security

### NFR-S7.1: No Code Injection
**Requirement:** User input shall not be executed as code

**Protection:**
- No `eval()` or `exec()` on user input
- No dynamic imports from user input
- No shell command injection

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S7.2: Dependency Security
**Requirement:** Dependencies shall be from trusted sources

**Sources:**
- PyPI (official Python package index)
- Well-known packages (PyQt6, google-generativeai)
- No unknown or suspicious packages

**Status:** ✅ Implemented

**Priority:** Should Have

---

### NFR-S7.3: No Hardcoded Secrets
**Requirement:** No secrets shall be hardcoded in source code

**Implementation:**
- API key from environment or settings
- No default API keys
- No embedded credentials

**Status:** ✅ Implemented

**Priority:** Must Have

---

## 10. NFR-S8: Session Security

### NFR-S8.1: No Session Persistence
**Requirement:** Execution state shall not persist across restarts

**Implementation:**
- No session tokens
- No persistent authentication
- Fresh start on each launch

**Status:** ✅ Implemented

**Priority:** N/A (not applicable)

---

### NFR-S8.2: Clean Shutdown
**Requirement:** Application shall clean up resources on exit

**Implementation:**
- Close database connections
- Stop background threads
- Release file handles

**Status:** ✅ Implemented

**Priority:** Must Have

---

## 11. NFR-S9: Data Integrity

### NFR-S9.1: Atomic Transactions
**Requirement:** Database writes shall be atomic

**Implementation:** SQLite transactions

**Protection:** No partial writes, rollback on error

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S9.2: Data Validation
**Requirement:** Data shall be validated before storage

**Validation:**
- Type checking
- Range checking
- Format validation

**Status:** ✅ Implemented

**Priority:** Must Have

---

### NFR-S9.3: Backup Capability
**Requirement:** User can manually backup data

**Implementation:** Database is single file, easy to copy

**Backup:** Manual file copy of `_runtime/history.db`

**Status:** ✅ Implemented (manual)

**Priority:** Should Have

---

## 12. Security Risk Assessment

### High Risk (Mitigated)
- **SQL Injection:** ✅ Mitigated via parameterized queries
- **Code Injection:** ✅ Mitigated via no eval/exec
- **API Key Exposure:** ✅ Mitigated via masking and secure storage

### Medium Risk (Accepted)
- **API Key Storage:** ⚠️ Not encrypted at rest (acceptable for bachelor project)
- **Local File Access:** ⚠️ Anyone with PC access can read files (acceptable for single-user)

### Low Risk (Accepted)
- **No Authentication:** ✅ Accepted (single-user application)
- **No Encryption:** ✅ Accepted (local deployment only)

---

## 13. Security Testing

### Tests Implemented
- Input validation tests
- SQL injection prevention tests
- API key masking tests
- Error handling tests

### Tests Not Implemented (Out of Scope)
- Penetration testing
- Security audit
- Vulnerability scanning
- Compliance testing

---

## 14. Security Limitations

### Known Limitations
1. **API key not encrypted at rest** - Stored in QSettings without encryption
2. **No multi-user support** - Anyone with PC access can use app
3. **No audit trail** - No logging of who did what
4. **No network security** - Relies on HTTPS from SDK
5. **No data encryption** - Database and files not encrypted

### Acceptable Because
- Bachelor degree project
- Single-user local deployment
- Not production system
- No sensitive data beyond API key
- Academic use only

---

## 15. Security Best Practices Followed

### ✅ Implemented
- Input validation
- Parameterized queries
- API key masking
- HTTPS for API calls
- No code injection
- Graceful error handling
- No hardcoded secrets
- Atomic transactions

### ⚠️ Partial
- API key storage (secure location but not encrypted)
- File permissions (OS default, not explicitly set)

### ❌ Not Implemented (Out of Scope)
- Encryption at rest
- Multi-user authentication
- Role-based access control
- Security auditing
- Penetration testing

---

## 16. Security Recommendations for Future

### If Deploying to Production
1. Encrypt API key at rest
2. Implement user authentication
3. Add audit logging
4. Encrypt database
5. Security audit and penetration testing
6. Implement rate limiting
7. Add session management
8. Implement RBAC

### Not Needed for Bachelor Project
- All above recommendations are out of scope
- Current security is appropriate for academic project
- Focus is on functionality and code quality, not production security

---

## 17. Compliance

### Not Applicable
- GDPR (no personal data of others)
- HIPAA (no health data)
- PCI DSS (no payment data)
- SOC 2 (not production system)

### Applicable
- Academic integrity (original work)
- Software licensing (GPL compliance for PyQt6)

---

## References

- Technical Constraints: `../04-technical/technical-constraints.md`
- Data Models: `../04-technical/data-models.md`
- Input Validation: `../03-functional/edge-cases.md`
- Quality Metrics: `../07-quality/quality-metrics.md`
