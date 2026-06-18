# 📝 Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.1] - 2026-06-18

### Fixed
- **Queue Manager Automation (`vacuum_queue_manager.yaml`):** Fixed scope bug where `'!input vacuum_entity'` inside Jinja template strings was processed as a literal string. Replaced with local variable `vacuum_ent` and moved the `variables:` block to the top of the automation for clean order of evaluation.
- **Queue Manager Automation (`vacuum_queue_manager.yaml`):** Added safe dict attribute access `.get()` when querying the vacuum's `rooms` metadata map to prevent Jinja errors if vacuum states are undefined/null.
- **Reset & Notify Automation (`vacuum_reset.yaml`):** Fixed schema syntax bug where `conditions:` was used at the root level instead of standard `condition:`.
- **Reset & Notify Automation (`vacuum_reset.yaml`):** Replaced `.startswith(vacuum_ent)` check with exact match `== vacuum_ent` to prevent false positive triggers on other vacuums sharing name prefixes.

### Changed
- **Codebase-wide:** Unified commenting style across all four blueprints by removing numeric prefixes (e.g., `# 1. ...`, `# Step 3: ...`) and standardizing comments to clean, descriptive sentences.
- **Codebase-wide:** Unified and renamed key input fields and internal helper variables across all blueprints for improved clarity, readability, and naming consistency:
  - Renamed all instances of dynamic queue state lookup `text_helper` to `queue_text_helper`.
  - Renamed CleanGenius selector helper `genie_select` to `cleangenius_select`.
  - Renamed cleaning mode selector helper `mode_select` to `cleaning_mode_select`.
  - Unified target To-Do list inputs by renaming `todo_entity` to `todo_list` in the Calendar automation to match the Reset automation.
  - Unified notification scripts by renaming `notify_script` to `notification_script` in the Reset automation to match the Queue Manager.
  - Renamed `todo_header_text` to `todo_title` in the Reset automation to reflect its usage as the To-Do item's title.
- **Codebase-wide:** Added descriptive `description` parameter keys to all inputs in the `input:` blocks of all blueprints. These descriptions are displayed directly to users in the Home Assistant UI when configuring automations or scripts.

## [1.1.0] - 2026-06-09

### Added
- **Queue Manager Automation:** Added premature cleaning cycle end handler. If the vacuum docks, returns, or goes idle while rooms are still in the queue (and resume is not set), it parses the skipped rooms, triggers a notification script, resets the queue, and stops gracefully.

### Changed
- **Queue Manager Automation:** Improved reliability of Jinja template parsing for `current_queue` and `parsed_corridor_rooms` using regex replacement and sanitization.
- **Calendar-Based Vacuum Automation:** Optimized event summary string trimming and case-insensitive check templates.

---

## [1.0.4] - 2026-02-15

### Fixed
- **Reset & Notify Automation:** Simplified cleanup automation flow and fixed issues with reset sequence and notifications.

---

## [1.0.3] - 2026-02-14

### Changed
- **Calendar-Based Vacuum Automation:** Updated input handling and dynamic helper associations.
- **Reset & Notify Automation:** Refined Device ID and Label discovery queries.
- **Advanced Vacuum Script:** Improved discovery debugging alerts and missing entity listings.

---

## [1.0.2] - 2026-02-12

### Fixed
- **Reset & Notify Automation:** Corrected a minor syntax issue in the automation condition block.

---

## [1.0.1] - 2026-02-11

### Fixed
- **Calendar-Based Vacuum Automation:** Fixed calendar event start trigger and event summary matching logic.

---

## [1.0.0] - 2026-02-10

### Added
- Initial release of the Dreame Vacuum Blueprint Suite containing:
  - **Advanced Vacuum Script (`script/homeassistant/robot_vacuum.yaml`)**
  - **Calendar-Based Vacuum Automation (`automation/homeassistant/vacuum_calendar_cleaning.yaml`)**
  - **Queue Manager Automation (`automation/homeassistant/vacuum_queue_manager.yaml`)**
  - **Reset & Notify Automation (`automation/homeassistant/vacuum_reset.yaml`)**
