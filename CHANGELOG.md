# 📝 Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- **Consumable Check Script Blueprint (`vacuum_check_consumables.yaml`):** New script blueprint that checks if any of the 5 vacuum consumables (main brush, side brush, filter, sensors, wheels) are under 10% life and creates task reminders on a Home Assistant To-Do list.
- **Vacuum Abort Script Blueprint (`vacuum_abort.yaml`):** New script blueprint that clears the rooms queue helper dynamically and returns the vacuum robot to its base.
- **Vacuum Toggle Pause Script Blueprint (`vacuum_toggle_pause.yaml`):** New script blueprint that toggles between playing and paused/error states for a vacuum robot.
- **Automated Blueprint Test Suite (`tests/test_vacuum_automations.py`):** Added comprehensive 37-scenario unit test suite using `NativeEnvironment` verifying:
  - Vacuum Reset & Queue Manager (room skipping, corridor pass-through, priority ordering, Case 3 jump-aheads with corridor preservation, undocking/mop-washing guards, restart protection, multi-map room resolution, regex discovery, TTS synthesis).
  - Calendar Cleaning Blueprint (case-insensitive summary matching, `ignored_rooms` exclusion, null sequence defaulting, To-Do maintenance task gate, JSON queue formatting).
  - Vacuum Scripts (missing helper discovery alerts, CleanGenius & cleaning mode branching, room selector rejection, queue parsing/empty guard, consumable threshold triggers & defaulting, abort queue clearing, toggle pause routing).
  - Schema & Jinja Syntax Compiler (schema validation and compilation of 103+ Jinja templates across all 7 blueprints, plus compilation of 173+ templates across all 92 `ha-scripts/` files).

### Changed
- **Queue Manager Automation Blueprint (`vacuum_queue_manager.yaml`):**
  - Re-ordered choose cases so that **Expected Next Room** is evaluated first with highest priority before the corridor pass-through check, ensuring corridors at the head of the queue are cleanly processed and popped.
  - Made corridor room parsing type-safe and resilient against string/integer type mismatches in Jinja filtering.
- **Reset & Notify Automation Blueprint (`vacuum_reset.yaml`):**
  - Resolved `TypeError` in `reject('in', parsed_corridor_rooms)` by evaluating corridor IDs as native integers in local template scope with strict whitespace stripping, ensuring configured corridor rooms (e.g. `[4, 6]`) are never falsely announced as skipped upon dock return.

### Fixed
- **Reset & Notify Automation Blueprint (`vacuum_reset.yaml`):** Fixed false-positive "could not clean corridor" speech announcement when the upstairs robot encounters closed doors in secondary bedrooms and living room.
- **Queue Manager Automation Blueprint (`vacuum_queue_manager.yaml`):** Fixed pass-through trap where the queue manager stopped all updates whenever non-corridor rooms remained queued, preventing legitimate cleaning of corridor rooms.

## [1.1.3] - 2026-06-29


### Changed
- **Reset & Notify Automation (`vacuum_reset.yaml`):** Added logic to resolve any remaining rooms in the queue as skipped prior to resetting the queue helper. Included the list of skipped rooms dynamically within the final vocal dock completion announcement.
- **Queue Manager Automation (`vacuum_queue_manager.yaml`):** Removed redundant premature ending handler and triggers to prevent race conditions and overlapping verbal announcements. De-duplicated queue clearing and delegate final announcements entirely to `vacuum_reset.yaml`.

## [1.1.2] - 2026-06-26

### Changed
- **Reset & Notify Automation (`vacuum_reset.yaml`):** Updated trigger to use the vacuum's `task_status_sensor` state transitioning to `"completed"` instead of listening to the global `dreame_vacuum_task_status` event, improving trigger reliability. Added a `task_status_sensor` input to support specifying the sensor. Removed event-filtering condition.
- **Queue Manager Automation (`vacuum_queue_manager.yaml`):** Added a dynamic `state_sensor` lookup to query the vacuum's actual state sensor instead of checking the non-existent `vacuum_state` attribute. Added state triggers for `docked`, `returning`, and `idle` to ensure the premature cleaning cycle end handler is reliably executed. Updated room name resolution to flatten segment lists across all maps, resolving name lookup failure for skipped rooms.

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
