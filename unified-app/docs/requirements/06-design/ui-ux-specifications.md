# UI/UX Specifications - Orchestrator Desktop App

**Project:** unified-app  
**Document ID:** DES-002  
**Last Updated:** 2026-03-14  
**Status:** Active

---

## 1. Purpose

This document defines UI/UX specifications for the Orchestrator Desktop App, including layout, navigation, interaction patterns, and visual design.

---

## 2. Overall UI Structure

### Main Window Layout

```
┌─────────────────────────────────────────────────────┐
│ Orchestrator Desktop App                      [_][□][X]│
├─────────────────────────────────────────────────────┤
│ [Run] [History] [Settings]                          │
├─────────────────────────────────────────────────────┤
│                                                     │
│                  Active Tab Content                 │
│                                                     │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Components:**
- Title bar with window controls
- Tab bar for navigation
- Content area for active tab

---

## 3. Run Tab Layout

```
┌─────────────────────────────────────────────────────┐
│ Task Input Panel                                    │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Task Description:                               │ │
│ │ ┌─────────────────────────────────────────────┐ │ │
│ │ │ Enter task description...                   │ │ │
│ │ └─────────────────────────────────────────────┘ │ │
│ │ Domain: [Auto-detect ▼]  [Run Task] [Cancel]   │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ Execution Plan Panel        │ Glass Box Panel       │
│ ┌─────────────────────────┐ │ ┌───────────────────┐ │
│ │ 1. Step one         [✓] │ │ │                   │ │
│ │ 2. Step two         [→] │ │ │   Screenshot      │ │
│ │ 3. Step three       [ ] │ │ │                   │ │
│ └─────────────────────────┘ │ │ 1920x1080 245KB   │ │
│                             │ └───────────────────┘ │
├─────────────────────────────┴─────────────────────────┤
│ Status Log Panel                                    │
│ ┌─────────────────────────────────────────────────┐ │
│ │ [10:30:00] Task submitted                       │ │
│ │ [10:30:01] Plan generated                       │ │
│ │ [10:30:02] Step 1 started: Launch browser       │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### Task Input Panel
**Location:** Top section
**Height:** ~100px
**Components:**
- Task description text input (multi-line)
- Domain dropdown
- Run Task button (primary action)
- Cancel button (visible during execution)

---

### Execution Plan Panel
**Location:** Middle-left section
**Width:** 40% of content area
**Components:**
- Numbered step list
- Status indicators per step:
  - [ ] Pending (gray)
  - [→] Running (blue)
  - [✓] Completed (green)
  - [✗] Failed (red)

---

### Glass Box Panel
**Location:** Middle-right section
**Width:** 60% of content area
**Components:**
- Screenshot image display (scaled to fit)
- Frame metadata (dimensions, size, FPS)
- Placeholder when no screenshot available

---

### Status Log Panel
**Location:** Bottom section
**Height:** ~150px
**Components:**
- Scrollable text area
- Timestamped messages
- Color-coded severity:
  - INFO: Black
  - WARNING: Orange
  - ERROR: Red
- Auto-scroll to latest

---

## 4. History Tab Layout

```
┌─────────────────────────────────────────────────────┐
│ Search: [________________] [Clear]                  │
├─────────────────────────────────────────────────────┤
│ Description          │ Status    │ Timestamp        │
├──────────────────────┼───────────┼──────────────────┤
│ Open Google and...   │ Success   │ 2026-03-14 10:30 │
│ Search for Python... │ Success   │ 2026-03-14 09:15 │
│ Navigate to...       │ Failed    │ 2026-03-14 08:45 │
│ ...                  │ ...       │ ...              │
└─────────────────────────────────────────────────────┘
```

### History Table
**Columns:**
- Description (truncated if long)
- Status (success/failure/cancelled)
- Timestamp (formatted)

**Interactions:**
- Double-click row to view details
- Search filters in real-time
- Sorted by most recent first

---

## 5. Settings Tab Layout

```
┌─────────────────────────────────────────────────────┐
│ API Configuration                                   │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Gemini API Key: [********************]          │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ Execution Settings                                  │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Timeout (seconds):  [30  ]                      │ │
│ │ Retry Count:        [3   ]                      │ │
│ │ Domain Default:     [Auto-detect ▼]             │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ Frame Capture Settings                              │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Max Frames:         [100 ]                      │ │
│ │ FPS Limit:          [30  ]                      │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│                          [Save Settings]            │
└─────────────────────────────────────────────────────┘
```

### Settings Groups
**API Configuration:**
- API key input (masked)

**Execution Settings:**
- Timeout spinner (1-300)
- Retry count spinner (0-10)
- Domain default dropdown

**Frame Capture Settings:**
- Max frames spinner
- FPS limit spinner

**Actions:**
- Save Settings button (bottom-right)

---

## 6. Interaction Patterns

### Task Submission Flow
1. User enters task description
2. User selects domain (optional)
3. User clicks "Run Task"
4. Submit button disables, Cancel button enables
5. Plan appears in execution plan panel
6. Steps execute with status updates
7. Screenshots appear in glass box panel
8. Status messages stream to log
9. On completion, Submit re-enables

### Task Cancellation Flow
1. User clicks "Cancel" during execution
2. Cancel button disables
3. Orchestrator stops gracefully
4. Status log shows "Task cancelled by user"
5. Submit button re-enables

### History Search Flow
1. User types in search box
2. Table filters in real-time
3. Only matching tasks shown
4. User clears search to show all

### Settings Save Flow
1. User modifies settings
2. User clicks "Save Settings"
3. Validation occurs
4. If valid: "Settings saved successfully"
5. If invalid: Error message, save blocked

---

## 7. Visual Design

### Color Scheme
**Primary Colors:**
- Background: Qt default (light gray)
- Text: Black
- Borders: Light gray

**Status Colors:**
- Success: Green (#4CAF50)
- Error: Red (#F44336)
- Warning: Orange (#FF9800)
- Info: Blue (#2196F3)
- Running: Blue (#2196F3)
- Pending: Gray (#9E9E9E)

### Typography
**Fonts:**
- Default: Qt system font
- Size: 10-12pt
- Monospace: For timestamps and technical text

**Text Styles:**
- Headers: Bold
- Body: Regular
- Timestamps: Monospace
- Errors: Red, bold

### Spacing
**Padding:**
- Panel padding: 10px
- Widget spacing: 5px
- Section spacing: 15px

**Margins:**
- Window margins: 10px
- Panel margins: 5px

---

## 8. Component Specifications

### Buttons

**Primary Button (Run Task):**
- Size: 100x30px
- Color: Blue background, white text
- State: Enabled/Disabled
- Hover: Darker blue

**Secondary Button (Cancel, Save):**
- Size: 80x30px
- Color: Gray background, black text
- State: Enabled/Disabled
- Hover: Darker gray

### Text Inputs

**Task Description:**
- Type: QTextEdit (multi-line)
- Height: 60px
- Placeholder: "Enter task description..."
- Max length: 1000 characters

**Search Box:**
- Type: QLineEdit (single-line)
- Width: 300px
- Placeholder: "Search tasks..."

**API Key:**
- Type: QLineEdit (single-line)
- Echo mode: Password (masked)
- Width: 400px

### Dropdowns

**Domain Selection:**
- Type: QComboBox
- Options: Auto-detect, Browser, Desktop
- Width: 150px

### Spinners

**Numeric Settings:**
- Type: QSpinBox
- Width: 80px
- Step: 1
- Range: Validated per setting

### Tables

**History Table:**
- Type: QTableWidget
- Columns: 3 (Description, Status, Timestamp)
- Row height: 30px
- Alternating row colors
- Sortable: Yes (by timestamp)

---

## 9. Responsive Behavior

### Window Resize
- Minimum size: 800x600px
- Panels resize proportionally
- Text wraps as needed
- Scrollbars appear when needed

### Panel Proportions
- Task Input: Fixed height (~100px)
- Execution Plan: 40% width
- Glass Box: 60% width
- Status Log: Fixed height (~150px)

---

## 10. Accessibility

### Keyboard Navigation
- Tab key: Move between fields
- Enter: Submit form (when in text input)
- Escape: Close dialogs
- Arrow keys: Navigate tables

### Screen Reader Support
- Labels for all inputs
- Alt text for images (if used)
- Semantic HTML structure (N/A for Qt)

### High Contrast
- Default Qt theme supports high contrast
- Text readable against background
- Status colors distinguishable

---

## 11. Error States

### Validation Errors
**Display:** Red text below invalid field
**Example:** "Task description cannot be empty"
**Duration:** Until corrected

### Execution Errors
**Display:** Red message in status log
**Example:** "[ERROR] Step failed: Element not found"
**Duration:** Persistent in log

### Startup Errors
**Display:** Message in status log
**Example:** "Live Gemini blocked: invalid API key"
**Duration:** Until configuration fixed

---

## 12. Loading States

### Task Execution
**Indicator:** 
- Submit button disabled
- Cancel button enabled
- Status log shows progress
- Plan shows current step

### History Loading
**Indicator:**
- Brief delay (<1s)
- No explicit spinner needed (fast enough)

### Screenshot Loading
**Indicator:**
- Placeholder image until loaded
- "Loading..." text if slow

---

## 13. Empty States

### No History
**Display:** "No tasks in history" centered in table
**Action:** None (informational)

### No Screenshot
**Display:** "No frame available" in glass box panel
**Action:** None (informational)

### No Plan
**Display:** Empty execution plan panel
**Action:** None (before task submission)

---

## 14. Dialogs

### Task Details Dialog
**Trigger:** Double-click history row
**Content:**
- Full task description
- Execution plan (formatted)
- Outcome and timestamps
- Error message (if failed)
**Actions:** Close button

### Confirmation Dialogs
**Note:** None currently needed (no destructive actions)

---

## 15. Animations

### Minimal Animations
- No complex animations (desktop app)
- Smooth scrolling in log
- Fade-in for screenshots (Qt default)

---

## 16. Platform Consistency

### Windows Integration
- Native window controls
- System font
- Platform-appropriate styling
- Registry for settings storage

### Qt Theming
- Default Qt theme
- Platform-native appearance
- Consistent with OS

---

## 17. UI Testing

### Manual Testing Checklist
- ✅ All buttons clickable
- ✅ Text inputs accept input
- ✅ Dropdowns show options
- ✅ Tables display data
- ✅ Tabs switch correctly
- ✅ Window resizes properly
- ✅ Scrollbars work
- ✅ Keyboard navigation works

### Automated UI Tests
**Location:** `tests/ui/`
**Coverage:** Critical user paths

---

## 18. Future UI Enhancements

### Not Implemented (Out of Scope)
- Dark mode
- Custom themes
- Drag-and-drop
- Context menus
- Toolbar
- Status bar
- Tooltips
- Icons

**Rationale:** Bachelor project, focus on functionality

---

## References

- User Journey Maps: `../02-user/user-journey-maps.md`
- Usability Requirements: `../05-non-functional/usability-requirements.md`
- Design Patterns: `design-patterns.md`
- Implementation: `ui/panels/`, `ui/views/`
