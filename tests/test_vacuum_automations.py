import glob
import json
import os
import re
import unittest
import yaml
from jinja2.nativetypes import NativeEnvironment


def input_constructor(loader, node):
    return loader.construct_scalar(node)

yaml.SafeLoader.add_constructor("!input", input_constructor)
yaml.SafeLoader.add_constructor("!include", input_constructor)


def _parse_rendered_list(val):
    """Safely extracts a Python list from a NativeEnvironment rendered value."""
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        import ast
        try:
            parsed = ast.literal_eval(val.strip())
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


class TestVacuumBlueprints(unittest.TestCase):
    def setUp(self):
        self.env = NativeEnvironment()
        self.env.tests["match"] = lambda val, pat: bool(re.match(pat, str(val)))
        self.env.tests["search"] = lambda val, pat: bool(re.search(pat, str(val)))
        self.env.filters["to_json"] = lambda val: json.dumps(val)


        # Load blueprints
        with open("ha-blueprints/automation/homeassistant/vacuum_reset.yaml", "r", encoding="utf-8") as f:
            self.reset_blueprint = yaml.safe_load(f)

        with open("ha-blueprints/automation/homeassistant/vacuum_queue_manager.yaml", "r", encoding="utf-8") as f:
            self.queue_mgr_blueprint = yaml.safe_load(f)

        # Standard upstairs room definitions from vacuum.og1_robot
        self.upstairs_rooms = {
            "First Floor": [
                {"id": 1, "name": "Secondary Bedroom"},
                {"id": 2, "name": "Living Room"},
                {"id": 3, "name": "Kitchen"},
                {"id": 4, "name": "Closet"},
                {"id": 6, "name": "Corridor"},
                {"id": 7, "name": "Toilet"},
                {"id": 9, "name": "Primary Bedroom"},
            ]
        }

        # Standard ground floor room definitions from vacuum.eg_cleaning_robot
        self.ground_floor_rooms = {
            "Ground Floor": [
                {"id": 1, "name": "Garden"},
                {"id": 2, "name": "Dining Room"},
                {"id": 3, "name": "Office"},
                {"id": 4, "name": "Kitchen"},
                {"id": 5, "name": "Corridor"},
                {"id": 6, "name": "Bathroom"},
            ]
        }

    def _render_reset_skipped_rooms(self, queue_state, corridor_rooms_input, rooms_dict):
        """Helper to render skipped_rooms template from vacuum_reset.yaml"""
        skipped_rooms_template = self.reset_blueprint["variables"]["skipped_rooms"]
        
        # Mock Home Assistant helper states and attributes
        def states_func(entity_id):
            if "rooms_to_clean" in entity_id:
                return queue_state
            return "unknown"

        def state_attr_func(entity_id, attr):
            if attr == "rooms":
                return rooms_dict
            return None

        return self.env.from_string(skipped_rooms_template).render(
            queue_text_helper="input_text.og1_rooms_to_clean",
            states=states_func,
            state_attr=state_attr_func,
            vacuum_ent="vacuum.og1_robot",
            corridor_rooms_input=corridor_rooms_input,
        )

    def _is_ha_truthy(self, val):
        """Replicates Home Assistant's template condition truthiness logic."""
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return val.strip().lower() in ["true", "1", "yes", "on"]
        return bool(val)

    # -------------------------------------------------------------------------
    # Scenario 1: Upstairs False Corridor Skip Bug Fix
    # -------------------------------------------------------------------------
    def test_upstairs_closed_doors_excludes_corridor_from_reset_skips(self):
        """
        When the upstairs robot runs with [1, 2, 6] (Secondary Bedroom, Living Room, Corridor),
        and cannot enter rooms 1 and 2 (doors closed), the queue still has [1, 2, 6] upon docking.
        Ensure Corridor (6) is NEVER announced as skipped.
        """
        skipped = self._render_reset_skipped_rooms(
            queue_state="[1, 2, 6]",
            corridor_rooms_input="[4, 6]",
            rooms_dict=self.upstairs_rooms,
        )
        self.assertIn("Secondary Bedroom", skipped)
        self.assertIn("Living Room", skipped)
        self.assertNotIn("Corridor", skipped)
        self.assertEqual(skipped, ["Secondary Bedroom", "Living Room"])

    # -------------------------------------------------------------------------
    # Scenario 2: Ground Floor Corridor Exclusion
    # -------------------------------------------------------------------------
    def test_ground_floor_excludes_transition_corridors_at_dock(self):
        """
        On the ground floor, corridor_rooms is [3, 5] (Office and Corridor transit nodes).
        Ensure neither is reported as skipped upon dock return.
        """
        skipped = self._render_reset_skipped_rooms(
            queue_state="[2, 3, 4, 5]",
            corridor_rooms_input="[3, 5]",
            rooms_dict=self.ground_floor_rooms,
        )
        self.assertIn("Dining Room", skipped)
        self.assertIn("Kitchen", skipped)
        self.assertNotIn("Office", skipped)
        self.assertNotIn("Corridor", skipped)
        self.assertEqual(skipped, ["Dining Room", "Kitchen"])

    # -------------------------------------------------------------------------
    # Scenario 3: Diverse corridor_rooms input formats
    # -------------------------------------------------------------------------
    def test_corridor_rooms_input_formats(self):
        """Test variations of input formatting: list string, comma string, whitespace, empty."""
        test_inputs = [
            "[4, 6]",
            "4, 6",
            "4,6",
            " [ 4 , 6 ] ",
        ]
        for fmt in test_inputs:
            skipped = self._render_reset_skipped_rooms(
                queue_state="[1, 2, 6]",
                corridor_rooms_input=fmt,
                rooms_dict=self.upstairs_rooms,
            )
            self.assertEqual(skipped, ["Secondary Bedroom", "Living Room"], f"Failed for format: {fmt!r}")

        # Empty / None should not error out
        skipped_empty = self._render_reset_skipped_rooms(
            queue_state="[1, 2, 6]",
            corridor_rooms_input="",
            rooms_dict=self.upstairs_rooms,
        )
        self.assertEqual(skipped_empty, ["Secondary Bedroom", "Living Room", "Corridor"])

    # -------------------------------------------------------------------------
    # Scenario 4: Clean run (empty queue)
    # -------------------------------------------------------------------------
    def test_all_rooms_cleaned_no_skips(self):
        """When queue is empty or empty brackets, skipped_rooms must be empty."""
        for empty_val in ["[]", "", "unknown"]:
            skipped = self._render_reset_skipped_rooms(
                queue_state=empty_val,
                corridor_rooms_input="[4, 6]",
                rooms_dict=self.upstairs_rooms,
            )
            self.assertEqual(skipped, [])

    # -------------------------------------------------------------------------
    # Scenario 5: Queue Manager - Expected Next Room (Case 1 priority)
    # -------------------------------------------------------------------------
    def test_queue_manager_expected_next_room_priority(self):
        """
        When active_segment == current_queue[0], it must be recognized as Case 1 (Expected Next Room),
        even if the room is a corridor (e.g. [6, 1, 2] with active_segment=6).
        """
        choose_block = None
        for step in self.queue_mgr_blueprint["action"]:
            if "choose" in step:
                choose_block = step["choose"]
                break
        self.assertIsNotNone(choose_block, "Could not find choose block in vacuum_queue_manager action")

        # Case 1 condition: active_segment == current_queue[0]
        case1_cond = choose_block[0]["conditions"][0]["value_template"]
        
        # Test Case 1 with corridor at the head of the queue: current_queue = [6, 1, 2], active_segment = 6
        is_case1 = self.env.from_string(case1_cond).render(
            active_segment=6,
            current_queue=[6, 1, 2],
        )
        self.assertTrue(self._is_ha_truthy(is_case1), "Case 1 must trigger when active_segment == current_queue[0]")

        # Test Case 1 queue popping template
        pop_template = choose_block[0]["sequence"][1]["data"]["value"]
        new_queue_val = self.env.from_string(pop_template).render(current_queue=[6, 1, 2])
        self.assertEqual(new_queue_val, [1, 2])

    # -------------------------------------------------------------------------
    # Scenario 6: Queue Manager - Corridor Pass-Through
    # -------------------------------------------------------------------------
    def test_queue_manager_corridor_pass_through_ignored(self):
        """
        When robot enters corridor (6) while heading to room 1 (current_queue=[1, 2, 6]),
        Case 2 (Pass-through) must trigger and ignore the transit.
        """
        choose_block = None
        for step in self.queue_mgr_blueprint["action"]:
            if "choose" in step:
                choose_block = step["choose"]
                break

        case1_cond = choose_block[0]["conditions"][0]["value_template"]
        case2_cond = choose_block[1]["conditions"][0]["value_template"]

        current_queue = [1, 2, 6]
        active_segment = 6
        corridor_rooms_input = "[4, 6]"

        # Case 1 should NOT trigger (6 != 1)
        is_case1 = self.env.from_string(case1_cond).render(
            active_segment=active_segment,
            current_queue=current_queue,
        )
        self.assertFalse(self._is_ha_truthy(is_case1))

        # Case 2 SHOULD trigger (6 is in corridor_list and non_corridor [1, 2] exist)
        is_case2 = self.env.from_string(case2_cond).render(
            active_segment=active_segment,
            current_queue=current_queue,
            corridor_rooms_input=corridor_rooms_input,
        )
        self.assertTrue(self._is_ha_truthy(is_case2))

    # -------------------------------------------------------------------------
    # Scenario 7: Queue Manager - Jump-ahead mid-cycle skip excludes corridor
    # -------------------------------------------------------------------------
    def test_queue_manager_jump_ahead_excludes_corridor_from_skips(self):
        """
        Queue is [1, 2, 6, 7]. Robot jumps directly to 7 (Toilet).
        Case 3 should calculate skipped rooms as [1, 2] only, NOT including Corridor 6.
        """
        choose_block = None
        for step in self.queue_mgr_blueprint["action"]:
            if "choose" in step:
                choose_block = step["choose"]
                break

        case3_seq = choose_block[2]["sequence"]
        skipped_calc_tmpl = case3_seq[0]["variables"]["skipped_rooms"]

        def state_attr_func(entity_id, attr):
            if attr == "rooms":
                return self.upstairs_rooms
            return None

        skipped = self.env.from_string(skipped_calc_tmpl).render(
            current_queue=[1, 2, 6, 7],
            active_segment=7,
            corridor_rooms_input="[4, 6]",
            state_attr=state_attr_func,
            vacuum_ent="vacuum.og1_robot",
        )
        self.assertEqual(skipped, ["Secondary Bedroom", "Living Room"])
        self.assertNotIn("Corridor", skipped)

    # -------------------------------------------------------------------------
    # Scenario 8: Queue Manager - Undocking State Guard (Regression Test)
    # -------------------------------------------------------------------------
    def test_queue_manager_undocking_does_not_trigger_skip(self):
        """
        When the robot undocks, trigger.from_state.state == 'docked'.
        Case 3 condition must evaluate to FALSE to prevent stale current_segment from falsely skipping rooms.
        """
        choose_block = None
        for step in self.queue_mgr_blueprint["action"]:
            if "choose" in step:
                choose_block = step["choose"]
                break

        case3_cond = choose_block[2]["conditions"][0]["value_template"]

        class MockState:
            def __init__(self, state):
                self.state = state

        class MockTrigger:
            def __init__(self, from_state_str):
                self.from_state = MockState(from_state_str) if from_state_str else None

        # When undocking: from_state is 'docked' -> condition must be FALSE
        res_undocking = self.env.from_string(case3_cond).render(
            trigger=MockTrigger("docked"),
            active_segment=2,
            current_queue=[1, 2, 6],
        )
        self.assertFalse(self._is_ha_truthy(res_undocking))

        # During active cleaning transition: from_state is 'cleaning' -> condition must be TRUE
        res_active_cleaning = self.env.from_string(case3_cond).render(
            trigger=MockTrigger("cleaning"),
            active_segment=2,
            current_queue=[1, 2, 6],
        )
        self.assertTrue(self._is_ha_truthy(res_active_cleaning))

    # -------------------------------------------------------------------------
    # Scenario 9: Multi-Map Room Name Resolution
    # -------------------------------------------------------------------------
    def test_multi_map_room_name_resolution(self):
        """
        Dreame integration stores rooms per map: {'EG': [...], 'OG1': [...]}.
        The blueprint flattens across all maps so skipped IDs in any map resolve correctly.
        """
        multi_map_dict = {
            "Ground Floor Map": [
                {"id": 1, "name": "Kitchen"},
                {"id": 2, "name": "Living Room"},
            ],
            "Upstairs Map": [
                {"id": 10, "name": "Attic"},
                {"id": 11, "name": "Office"},
            ],
        }

        skipped = self._render_reset_skipped_rooms(
            queue_state="[2, 11]",
            corridor_rooms_input="[3, 5]",
            rooms_dict=multi_map_dict,
        )
        self.assertIn("Living Room", skipped)
        self.assertIn("Office", skipped)
        self.assertEqual(skipped, ["Living Room", "Office"])

    # -------------------------------------------------------------------------
    # Scenario 10: TTS Announcement Speech Generation in Reset Blueprint
    # -------------------------------------------------------------------------
    def test_reset_tts_announcement_messages(self):
        """
        Test verbal announcement formatting in vacuum_reset.yaml:
        - Vacuum & Mop with skips
        - Vacuum & Mop without skips
        - Vacuum-only with skips
        - Vacuum-only without skips
        - Name prefix handling (avoiding 'The The')
        """
        action_seq = self.reset_blueprint["action"]
        notify_step = None
        for step in action_seq:
            if "if" in step:
                cond = step["if"][0]
                if "notification_script" in cond.get("value_template", ""):
                    notify_step = step["then"][0]
                    break
        self.assertIsNotNone(notify_step, "Could not find notification step in vacuum_reset.yaml")

        msg_template = notify_step["data"]["variables"]["message"]

        # 1. Vacuum and mop with skipped rooms
        msg_mop_skips = self.env.from_string(msg_template).render(
            robot_name="First Floor vacuum",
            skipped_rooms=["Secondary Bedroom", "Living Room"],
            is_vacuum_only=False,
        ).strip()
        self.assertEqual(
            msg_mop_skips,
            "The First Floor vacuum has finished cleaning and is back at its dock, but skipped some rooms: Secondary Bedroom, Living Room. Whenever you have a moment, please remember to clean the robot and replace the water.",
        )

        # 2. Vacuum and mop clean run (no skips)
        msg_mop_clean = self.env.from_string(msg_template).render(
            robot_name="First Floor vacuum",
            skipped_rooms=[],
            is_vacuum_only=False,
        ).strip()
        self.assertEqual(
            msg_mop_clean,
            "The First Floor vacuum has finished cleaning and is back at its dock. Whenever you have a moment, please remember to clean the robot and replace the water.",
        )

        # 3. Vacuum-only with skipped rooms
        msg_vac_skips = self.env.from_string(msg_template).render(
            robot_name="First Floor vacuum",
            skipped_rooms=["Secondary Bedroom"],
            is_vacuum_only=True,
        ).strip()
        self.assertEqual(
            msg_vac_skips,
            "The First Floor vacuum has finished cleaning and is back at its dock, but skipped some rooms: Secondary Bedroom.",
        )

        # 4. Robot name already starting with 'The ' or 'the '
        msg_prefix = self.env.from_string(msg_template).render(
            robot_name="The First Floor vacuum",
            skipped_rooms=[],
            is_vacuum_only=True,
        ).strip()
        self.assertTrue(
            msg_prefix.startswith("The First Floor vacuum"),
            f"Expected message to start with single 'The', got: {msg_prefix}",
        )
        self.assertFalse(msg_prefix.startswith("The The"))

    # -------------------------------------------------------------------------
    # Scenario 11: Queue Manager String Parsing Resiliency
    # -------------------------------------------------------------------------
    def test_queue_manager_queue_parsing_formats(self):
        """
        Test that current_queue variable in vacuum_queue_manager.yaml reliably extracts
        clean integer arrays from various text helper state formats.
        """
        queue_var_tmpl = None
        for step in self.queue_mgr_blueprint["action"]:
            if "variables" in step and "current_queue" in step["variables"]:
                queue_var_tmpl = step["variables"]["current_queue"]
                break
        self.assertIsNotNone(queue_var_tmpl, "Could not find current_queue template in vacuum_queue_manager")

        test_cases = [
            ("[1, 4, 2]", [1, 4, 2]),
            ("1, 4, 2", [1, 4, 2]),
            ("1,4,2", [1, 4, 2]),
            (" [ 10 , 20 ] ", [10, 20]),
            ("[]", []),
            ("", []),
            ("unknown", []),
            ("unavailable", []),
        ]

        for input_str, expected in test_cases:
            def mock_states(entity):
                return input_str

            res = self.env.from_string(queue_var_tmpl).render(
                queue_text_helper="input_text.og1_rooms_to_clean",
                states=mock_states,
            )
            # When NativeEnvironment renders, empty list template might be string or list
            if isinstance(res, str):
                import ast
                try:
                    res = ast.literal_eval(res.strip())
                except Exception:
                    res = []
            self.assertEqual(res, expected, f"Failed parsing: {input_str!r}")

    # -------------------------------------------------------------------------
    # Scenario 12: Maintenance To-Do Task Condition
    # -------------------------------------------------------------------------
    def test_reset_todo_task_creation_condition(self):
        """
        A To-Do maintenance task ('Replace water and clean the robot') must only be created
        if the cycle was NOT vacuum-only.
        """
        action_seq = self.reset_blueprint["action"]
        todo_step = None
        for step in action_seq:
            if "if" in step:
                cond = step["if"][0]
                if "is_vacuum_only" in cond.get("value_template", ""):
                    todo_step = step
                    break
        self.assertIsNotNone(todo_step, "Could not find todo task creation step in vacuum_reset.yaml")

        cond_template = todo_step["if"][0]["value_template"]

        # When vacuum and mop: is_vacuum_only is False -> condition {{ not is_vacuum_only }} evaluates to True
        res_mop = self.env.from_string(cond_template).render(is_vacuum_only=False)
        self.assertTrue(self._is_ha_truthy(res_mop))

        # When vacuum only: is_vacuum_only is True -> condition {{ not is_vacuum_only }} evaluates to False
        res_vac = self.env.from_string(cond_template).render(is_vacuum_only=True)
        self.assertFalse(self._is_ha_truthy(res_vac))

    # -------------------------------------------------------------------------
    # Scenario 13: Queue Manager Case 3 Queue Update Preserves Corridors
    # -------------------------------------------------------------------------
    def test_queue_manager_case3_queue_update_preserves_corridors(self):
        """
        When skipping ahead in Case 3, genuinely skipped non-corridor rooms are popped,
        while unvisited corridor rooms ahead in the queue are preserved at the head.
        e.g., Queue [1, 6, 2, 7], jump to 2. Room 1 is skipped, Corridor 6 is preserved -> [6, 7].
        """
        choose_block = None
        for step in self.queue_mgr_blueprint["action"]:
            if "choose" in step:
                choose_block = step["choose"]
                break

        case3_seq = choose_block[2]["sequence"]
        queue_update_tmpl = None
        for s in case3_seq:
            if s.get("action") == "input_text.set_value":
                queue_update_tmpl = s["data"]["value"]
                break
        self.assertIsNotNone(queue_update_tmpl)

        res_queue = self.env.from_string(queue_update_tmpl).render(
            current_queue=[1, 6, 2, 7],
            active_segment=2,
            corridor_rooms_input="[4, 6]",
        )
        self.assertEqual(list(res_queue), [6, 7])

    # -------------------------------------------------------------------------
    # Scenario 14: Reset Blueprint Condition Guard (Restart/Reload Protection)
    # -------------------------------------------------------------------------
    def test_reset_condition_guard_prevents_restart_triggers(self):
        """
        vacuum_reset.yaml condition must only allow execution when transitioning from an active state,
        blocking spurious runs during Home Assistant restarts (from_state unknown/unavailable/idle/None).
        """
        cond_tmpl = self.reset_blueprint["condition"][0]["value_template"]

        class MockState:
            def __init__(self, s):
                self.state = s

        class MockTrigger:
            def __init__(self, s):
                self.from_state = MockState(s) if s is not None else None

        self.assertTrue(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(trigger=MockTrigger("cleaning"))))
        self.assertTrue(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(trigger=MockTrigger("returning"))))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(trigger=MockTrigger("unavailable"))))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(trigger=MockTrigger("unknown"))))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(trigger=MockTrigger("idle"))))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(trigger=MockTrigger(None))))

    # -------------------------------------------------------------------------
    # Scenario 15: Queue Manager Mop Washing Guard Condition
    # -------------------------------------------------------------------------
    def test_queue_manager_mop_wash_condition_guard(self):
        """
        When the robot pauses cleaning to wash/dry mop pads ('washing', 'returning_to_wash', 'drying'),
        the queue manager condition must evaluate to FALSE so mid-wash segment resets don't mutate the queue.
        """
        cond_tmpl = self.queue_mgr_blueprint["condition"][0]["value_template"]

        def mock_states_for(status):
            return lambda ent: status

        for wash_status in ["washing", "returning_to_wash", "drying"]:
            res = self.env.from_string(cond_tmpl).render(
                state_sensor="sensor.og1_state",
                states=mock_states_for(wash_status),
            )
            self.assertFalse(self._is_ha_truthy(res), f"Status {wash_status} must be blocked by condition")

        for active_status in ["cleaning", "sweeping", "unknown"]:
            res = self.env.from_string(cond_tmpl).render(
                state_sensor="sensor.og1_state",
                states=mock_states_for(active_status),
            )
            self.assertTrue(self._is_ha_truthy(res), f"Status {active_status} must be permitted by condition")

    # -------------------------------------------------------------------------
    # Scenario 16: Queue Manager Docked/Returning Suspension Step
    # -------------------------------------------------------------------------
    def test_queue_manager_docked_returning_suspension(self):
        """
        Verify the stop check in vacuum_queue_manager: when robot state is 'returning', 'docked', or 'idle',
        the automation halts so queue resetting is left exclusively to vacuum_reset.yaml.
        """
        susp_tmpl = None
        for step in self.queue_mgr_blueprint["action"]:
            if "if" in step:
                cond = step["if"][0]
                if "states(vacuum_ent) in ['returning', 'docked', 'idle']" in cond.get("value_template", ""):
                    susp_tmpl = cond["value_template"]
                    break
        self.assertIsNotNone(susp_tmpl)

        def mock_vac_state(s):
            return lambda ent: s

        self.assertTrue(self._is_ha_truthy(self.env.from_string(susp_tmpl).render(vacuum_ent="vacuum.og1", states=mock_vac_state("returning"))))
        self.assertTrue(self._is_ha_truthy(self.env.from_string(susp_tmpl).render(vacuum_ent="vacuum.og1", states=mock_vac_state("docked"))))
        self.assertTrue(self._is_ha_truthy(self.env.from_string(susp_tmpl).render(vacuum_ent="vacuum.og1", states=mock_vac_state("idle"))))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(susp_tmpl).render(vacuum_ent="vacuum.og1", states=mock_vac_state("cleaning"))))

    # -------------------------------------------------------------------------
    # Scenario 17: Vacuum Robot Name Fallback Hierarchy
    # -------------------------------------------------------------------------
    def test_robot_name_fallback_hierarchy(self):
        """
        Test robot_name variable hierarchy:
        1. Custom input text (if configured)
        2. Friendly name attribute
        3. Generic fallback 'robot vacuum'
        """
        name_tmpl = self.reset_blueprint["variables"]["robot_name"]

        def mock_attr_name(n):
            return lambda ent, attr: n if attr == "friendly_name" else None

        # 1. Custom input provided
        res1 = self.env.from_string(name_tmpl).render(
            vacuum_name_input="First Floor vacuum",
            vacuum_ent="vacuum.og1_robot",
            state_attr=mock_attr_name("Dreame Bot L10s Ultra"),
        ).strip()
        self.assertEqual(res1, "First Floor vacuum")

        # 2. Custom input empty, friendly_name present
        res2 = self.env.from_string(name_tmpl).render(
            vacuum_name_input="",
            vacuum_ent="vacuum.og1_robot",
            state_attr=mock_attr_name("Dreame Bot L10s Ultra"),
        ).strip()
        self.assertEqual(res2, "Dreame Bot L10s Ultra")

        # 3. Both empty
        res3 = self.env.from_string(name_tmpl).render(
            vacuum_name_input="",
            vacuum_ent="vacuum.og1_robot",
            state_attr=mock_attr_name(None),
        ).strip()
        self.assertEqual(res3, "robot vacuum")

    # -------------------------------------------------------------------------
    # Scenario 18: Is Vacuum Only Detection Logic
    # -------------------------------------------------------------------------
    def test_is_vacuum_only_evaluation(self):
        """
        is_vacuum_only should be True only if helper is present and state is 'vacuum' (case-insensitive).
        """
        is_vac_tmpl = self.reset_blueprint["variables"]["is_vacuum_only"]

        def mock_helper_state(s):
            return lambda ent: s

        # Case insensitive match for 'vacuum'
        for val in ["vacuum", "Vacuum", "VACUUM"]:
            res = self.env.from_string(is_vac_tmpl).render(
                cleaning_type_helper="input_select.og1_cleaning_type",
                states=mock_helper_state(val),
            )
            self.assertTrue(self._is_ha_truthy(res))

        # Other cleaning modes
        for val in ["vacuum_and_mop", "mop", "custom", "unknown"]:
            res = self.env.from_string(is_vac_tmpl).render(
                cleaning_type_helper="input_select.og1_cleaning_type",
                states=mock_helper_state(val),
            )
            self.assertFalse(self._is_ha_truthy(res))

        # Helper missing ('none')
        res_none = self.env.from_string(is_vac_tmpl).render(
            cleaning_type_helper="none",
            states=mock_helper_state("vacuum"),
        )
        self.assertFalse(self._is_ha_truthy(res_none))

    # -------------------------------------------------------------------------
    # Scenario 19: Dynamic Entity Helper Discovery Regex
    # -------------------------------------------------------------------------
    def test_dynamic_entity_helper_discovery_regex(self):
        """
        Verify the regex pattern selectors for discovering device helper entities.
        """
        dev_entities = [
            "input_text.og1_rooms_to_clean",
            "input_number.og1_currently_cleaned",
            "input_select.og1_cleaning_type",
            "sensor.og1_robot_state",
            "switch.og1_robot_mop",
        ]

        q_helper_tmpl = self.reset_blueprint["variables"]["queue_text_helper"]
        c_helper_tmpl = self.reset_blueprint["variables"]["currently_cleaned_helper"]
        t_helper_tmpl = self.reset_blueprint["variables"]["cleaning_type_helper"]

        res_q = self.env.from_string(q_helper_tmpl).render(dev_entities=dev_entities)
        res_c = self.env.from_string(c_helper_tmpl).render(dev_entities=dev_entities)
        res_t = self.env.from_string(t_helper_tmpl).render(dev_entities=dev_entities)

        self.assertEqual(res_q, "input_text.og1_rooms_to_clean")
        self.assertEqual(res_c, "input_number.og1_currently_cleaned")
        self.assertEqual(res_t, "input_select.og1_cleaning_type")

        # When entity not in list, defaults to 'none'
        res_missing = self.env.from_string(q_helper_tmpl).render(dev_entities=[])
        self.assertEqual(res_missing, "none")

    # -------------------------------------------------------------------------
    # Scenario 20: Missing Helpers Guard Condition
    # -------------------------------------------------------------------------
    def test_queue_manager_missing_helpers_guard(self):
        """
        If either queue_text_helper or currently_cleaned_helper is missing ('none'),
        the guard step must evaluate to True to raise a persistent notification and stop.
        """
        missing_tmpl = self.queue_mgr_blueprint["action"][0]["if"][0]["value_template"]

        # Both present -> False
        res_ok = self.env.from_string(missing_tmpl).render(
            queue_text_helper="input_text.og1_rooms_to_clean",
            currently_cleaned_helper="input_number.og1_currently_cleaned",
        )
        self.assertFalse(self._is_ha_truthy(res_ok))

        # One or both missing -> True
        res_missing_q = self.env.from_string(missing_tmpl).render(
            queue_text_helper="none",
            currently_cleaned_helper="input_number.og1_currently_cleaned",
        )
        self.assertTrue(self._is_ha_truthy(res_missing_q))

        res_missing_both = self.env.from_string(missing_tmpl).render(
            queue_text_helper="none",
            currently_cleaned_helper="none",
        )
        self.assertTrue(self._is_ha_truthy(res_missing_both))


# =============================================================================
# Test Suite for Calendar-Based Vacuum Cleaning Blueprint
# =============================================================================
class TestVacuumCalendarCleaning(unittest.TestCase):
    def setUp(self):
        self.env = NativeEnvironment()
        self.env.tests["match"] = lambda val, pat: bool(re.match(pat, str(val)))
        self.env.tests["search"] = lambda val, pat: bool(re.search(pat, str(val)))
        self.env.filters["to_json"] = lambda val: json.dumps(val)

        with open("ha-blueprints/automation/homeassistant/vacuum_calendar_cleaning.yaml", "r", encoding="utf-8") as f:
            self.blueprint = yaml.safe_load(f)

    def _is_ha_truthy(self, val):
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return val.strip().lower() in ["true", "1", "yes", "on"]
        return bool(val)

    def test_calendar_summary_match_case_insensitive(self):
        """Verify summary filter case insensitivity, whitespace trimming, and substring matching."""
        cond_tmpl = self.blueprint["condition"][0]["value_template"]

        class MockEvent:
            def __init__(self, s):
                self.summary = s

        class MockTrigger:
            def __init__(self, s):
                self.calendar_event = MockEvent(s)

        # Exact match lowercase
        res1 = self.env.from_string(cond_tmpl).render(summary_filter="eg auto cleaning", trigger=MockTrigger("eg auto cleaning"))
        self.assertTrue(self._is_ha_truthy(res1))

        # Mixed case substring match
        res2 = self.env.from_string(cond_tmpl).render(summary_filter="eg auto cleaning", trigger=MockTrigger("EG Auto Cleaning - Morning Run"))
        self.assertTrue(self._is_ha_truthy(res2))

        # Whitespace trimmed
        res3 = self.env.from_string(cond_tmpl).render(summary_filter="  EG Auto Cleaning  ", trigger=MockTrigger("eg auto cleaning"))
        self.assertTrue(self._is_ha_truthy(res3))

        # Non-matching event
        res4 = self.env.from_string(cond_tmpl).render(summary_filter="eg auto cleaning", trigger=MockTrigger("Meeting with Team"))
        self.assertFalse(self._is_ha_truthy(res4))

    def test_calendar_cleaning_sequence_ignored_rooms(self):
        """Verify cleaning_sequence rejects rooms in ignored_rooms list."""
        seq_tmpl = self.blueprint["variables"]["cleaning_sequence"]

        def mock_attr(seq):
            return lambda ent, attr: seq if attr == "cleaning_sequence" else None

        # Ignore rooms 2 and 4
        res = self.env.from_string(seq_tmpl).render(
            vacuum_ent="vacuum.eg_robot",
            ignored_rooms=[2, 4],
            state_attr=mock_attr([1, 2, 3, 4]),
        )
        self.assertEqual(list(res), [1, 3])

        # No ignored rooms
        res_all = self.env.from_string(seq_tmpl).render(
            vacuum_ent="vacuum.eg_robot",
            ignored_rooms=[],
            state_attr=mock_attr([1, 2, 3, 4]),
        )
        self.assertEqual(list(res_all), [1, 2, 3, 4])

    def test_calendar_cleaning_sequence_none_fallback(self):
        """Verify cleaning_sequence safely defaults to empty list if state_attr is None."""
        seq_tmpl = self.blueprint["variables"]["cleaning_sequence"]

        def mock_attr_none(ent, attr):
            return None

        res = self.env.from_string(seq_tmpl).render(
            vacuum_ent="vacuum.eg_robot",
            ignored_rooms=[1],
            state_attr=mock_attr_none,
        )
        self.assertEqual(list(res), [])

    def test_calendar_maintenance_task_gate(self):
        """Verify cleaning is blocked if maintenance task already exists on To-Do list."""
        gate_tmpl = self.blueprint["action"][1]["if"][0]["value_template"]

        class MockTaskCheck:
            def __init__(self, exists):
                self.exists = exists

        # When task exists -> gate is False (cleaning skipped)
        res_exists = self.env.from_string(gate_tmpl).render(robot_task_check=MockTaskCheck(True))
        self.assertFalse(self._is_ha_truthy(res_exists))

        # When task does not exist -> gate is True (proceed)
        res_not_exists = self.env.from_string(gate_tmpl).render(robot_task_check=MockTaskCheck(False))
        self.assertTrue(self._is_ha_truthy(res_not_exists))

    def test_calendar_queue_json_serialization(self):
        """Verify queue JSON serialization for input_text helper."""
        pop_tmpl = self.blueprint["action"][1]["then"][0]["then"][0]["data"]["value"]
        res = self.env.from_string(pop_tmpl).render(cleaning_sequence=[1, 3, 5])
        self.assertEqual(str(res).replace(" ", ""), "[1,3,5]")


# =============================================================================
# Test Suite for Vacuum Scripts (robot_vacuum, consumables, abort, toggle_pause)
# =============================================================================
class TestVacuumScripts(unittest.TestCase):
    def setUp(self):
        self.env = NativeEnvironment()
        self.env.tests["match"] = lambda val, pat: bool(re.match(pat, str(val)))
        self.env.tests["search"] = lambda val, pat: bool(re.search(pat, str(val)))
        self.env.filters["to_json"] = lambda val: json.dumps(val)

        with open("ha-blueprints/script/homeassistant/robot_vacuum.yaml", "r", encoding="utf-8") as f:
            self.rv_bp = yaml.safe_load(f)
        with open("ha-blueprints/script/homeassistant/vacuum_check_consumables.yaml", "r", encoding="utf-8") as f:
            self.cc_bp = yaml.safe_load(f)
        with open("ha-blueprints/script/homeassistant/vacuum_abort.yaml", "r", encoding="utf-8") as f:
            self.ab_bp = yaml.safe_load(f)
        with open("ha-blueprints/script/homeassistant/vacuum_toggle_pause.yaml", "r", encoding="utf-8") as f:
            self.tp_bp = yaml.safe_load(f)

    def _is_ha_truthy(self, val):
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return val != 0
        if isinstance(val, str):
            return val.strip().lower() in ["true", "1", "yes", "on"]
        return bool(val)

    def test_robot_vacuum_missing_entities_detection(self):
        """Verify helper entity validation and notification triggering when helpers are absent."""
        missing_tmpl = self.rv_bp["sequence"][1]["variables"]["missing_entities"]

        # All present
        res_ok = self.env.from_string(missing_tmpl).render(
            queue_text_helper="input_text.og1_rooms",
            clean_type_select="input_select.og1_type",
            cleangenius_select="select.og1_cg",
            cleaning_mode_select="select.og1_cm",
        ).strip()
        self.assertEqual(res_ok, "")

        # Missing helpers
        res_missing = self.env.from_string(missing_tmpl).render(
            queue_text_helper="none",
            clean_type_select="none",
            cleangenius_select="select.og1_cg",
            cleaning_mode_select="select.og1_cm",
        ).strip()
        self.assertIn("Rooms Text Helper", res_missing)
        self.assertIn("Cleaning Type Selector", res_missing)

        # Stop condition
        stop_cond = self.rv_bp["sequence"][2]["if"][0]["value_template"]
        self.assertTrue(self._is_ha_truthy(self.env.from_string(stop_cond).render(missing_entities=res_missing)))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(stop_cond).render(missing_entities="")))

    def test_robot_vacuum_cleaning_mode_selection(self):
        """Verify cleaning mode choose logic for vacuum, mop, vacuum and mop, and deep clean."""
        choose_block = self.rv_bp["sequence"][5]["choose"]
        c1 = choose_block[0]["conditions"][0]["value_template"]
        c2 = choose_block[1]["conditions"][0]["value_template"]

        def mock_states(val):
            return lambda ent: val

        # Vacuum and mop -> routine_cleaning
        self.assertTrue(self._is_ha_truthy(self.env.from_string(c1).render(clean_type_select="input_select.type", states=mock_states("Vacuum and Mop"))))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(c1).render(clean_type_select="input_select.type", states=mock_states("Vacuum"))))

        # Deep clean -> deep_cleaning
        self.assertTrue(self._is_ha_truthy(self.env.from_string(c2).render(clean_type_select="input_select.type", states=mock_states("deep clean"))))

        # Default fallback
        def_action = self.rv_bp["sequence"][5]["default"]
        mode_val_tmpl = def_action[1]["data"]["option"]
        self.assertEqual(self.env.from_string(mode_val_tmpl).render(clean_type_select="input_select.type", states=mock_states("vacuum")), "sweeping")
        self.assertEqual(self.env.from_string(mode_val_tmpl).render(clean_type_select="input_select.type", states=mock_states("mop")), "mopping")

    def test_robot_vacuum_cleaning_mode_rejects_room_selectors(self):
        """Verify cleaning_mode_select rejects per-room selectors with reject('search', 'room_')."""
        mode_select_tmpl = self.rv_bp["sequence"][1]["variables"]["cleaning_mode_select"]
        dev_entities = [
            "select.og1_cleaning_mode",
            "select.og1_room_1_cleaning_mode",
            "select.og1_room_2_cleaning_mode",
        ]
        res = self.env.from_string(mode_select_tmpl).render(dev_entities=dev_entities).strip()
        self.assertEqual(res, "select.og1_cleaning_mode")

    def test_robot_vacuum_queue_parsing_and_empty_guard(self):
        """Verify queue parsing and stop condition when room queue is empty."""
        q_tmpl = self.rv_bp["sequence"][3]["variables"]["current_queue"]
        guard_tmpl = self.rv_bp["sequence"][4]["value_template"]

        def mock_states(s):
            return lambda ent: s

        # Valid queue
        res_raw = self.env.from_string(q_tmpl).render(queue_text_helper="input_text.q", states=mock_states("[1, 3, 5]"))
        res_queue = _parse_rendered_list(res_raw)
        self.assertEqual(res_queue, [1, 3, 5])
        self.assertTrue(self._is_ha_truthy(self.env.from_string(guard_tmpl).render(current_queue=res_queue)))

        # Empty queue
        res_empty_raw = self.env.from_string(q_tmpl).render(queue_text_helper="input_text.q", states=mock_states("[]"))
        res_empty = _parse_rendered_list(res_empty_raw)
        self.assertEqual(res_empty, [])
        self.assertFalse(self._is_ha_truthy(self.env.from_string(guard_tmpl).render(current_queue=res_empty)))

    def test_consumables_threshold_triggers(self):
        """Verify consumable alerts fire when remaining life is under 10%."""
        conds = [step["if"][0]["value_template"] for step in self.cc_bp["sequence"] if "if" in step]
        self.assertEqual(len(conds), 5)

        def mock_attr(attr_name, val):
            return lambda ent, attr: val if attr == attr_name else None

        attr_names = ["main_brush_left", "side_brush_left", "filter_left", "sensor_dirty_left", "wheel_dirty_left"]
        for idx, attr_name in enumerate(attr_names):
            # Under 10% -> triggers
            res_low = self.env.from_string(conds[idx]).render(vacuum_ent="vacuum.og1", state_attr=mock_attr(attr_name, 9))
            self.assertTrue(self._is_ha_truthy(res_low), f"{attr_name} at 9% must trigger")

            # At or above 10% -> does not trigger
            res_ok = self.env.from_string(conds[idx]).render(vacuum_ent="vacuum.og1", state_attr=mock_attr(attr_name, 10))
            self.assertFalse(self._is_ha_truthy(res_ok), f"{attr_name} at 10% must not trigger")

    def test_consumables_missing_attr_safe_default(self):
        """Verify missing consumable attribute defaults to 100 via int(100) to prevent false alerts."""
        cond = self.cc_bp["sequence"][1]["if"][0]["value_template"]

        def mock_attr_none(ent, attr):
            return None

        res = self.env.from_string(cond).render(vacuum_ent="vacuum.og1", state_attr=mock_attr_none)
        self.assertFalse(self._is_ha_truthy(res))

    def test_consumables_task_heading_format(self):
        """Verify maintenance task heading incorporates floor location."""
        heading_tmpl = self.cc_bp["sequence"][1]["then"][0]["data"]["heading"]
        res = self.env.from_string(heading_tmpl).render(floor="Downstairs")
        self.assertEqual(res, "Downstairs Robot - Replace Main Roller Brush")

    def test_abort_script_queue_reset(self):
        """Verify abort script resets queue helper to [] and targets vacuum."""
        cond_tmpl = self.ab_bp["sequence"][2]["if"][0]["value_template"]
        reset_val = self.ab_bp["sequence"][2]["then"][0]["data"]["value"]
        self.assertTrue(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(queue_text_helper="input_text.rooms")))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(cond_tmpl).render(queue_text_helper="none")))
        self.assertEqual(reset_val, "[]")

    def test_toggle_pause_decision_logic(self):
        """Verify toggle pause script resumes on paused/error, pauses on cleaning, and no-ops otherwise."""
        choose = self.tp_bp["sequence"][1]["choose"]
        resume_cond1 = choose[0]["conditions"][0]["conditions"][0]["value_template"]
        resume_cond2 = choose[0]["conditions"][0]["conditions"][1]["value_template"]
        pause_cond = choose[1]["conditions"][0]["value_template"]

        def mock_is_state(expected):
            return lambda ent, state: expected == state

        self.assertTrue(self._is_ha_truthy(self.env.from_string(resume_cond1).render(vacuum_ent="vacuum.og1", is_state=mock_is_state("paused"))))
        self.assertTrue(self._is_ha_truthy(self.env.from_string(resume_cond2).render(vacuum_ent="vacuum.og1", is_state=mock_is_state("error"))))
        self.assertTrue(self._is_ha_truthy(self.env.from_string(pause_cond).render(vacuum_ent="vacuum.og1", is_state=mock_is_state("cleaning"))))
        self.assertFalse(self._is_ha_truthy(self.env.from_string(pause_cond).render(vacuum_ent="vacuum.og1", is_state=mock_is_state("docked"))))


# =============================================================================
# Test Suite for Blueprint Schema Integrity & Global Jinja2 Syntax Validation
# =============================================================================
class TestBlueprintSchemasAndSyntax(unittest.TestCase):
    def setUp(self):
        self.env = NativeEnvironment()
        self.env.tests["match"] = lambda val, pat: bool(re.match(pat, str(val)))
        self.env.tests["search"] = lambda val, pat: bool(re.search(pat, str(val)))
        self.env.filters["to_json"] = lambda val: json.dumps(val)
        self.blueprint_files = glob.glob("ha-blueprints/**/*.yaml", recursive=True)

    def test_all_blueprints_valid_yaml_and_required_keys(self):
        """Verify every blueprint file is valid YAML with mandatory Home Assistant blueprint keys."""
        self.assertGreaterEqual(len(self.blueprint_files), 7)
        for fpath in self.blueprint_files:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            self.assertIsInstance(data, dict, f"{fpath} must be a YAML mapping")
            self.assertIn("blueprint", data, f"{fpath} must contain 'blueprint'")
            self.assertIn("name", data["blueprint"], f"{fpath} blueprint missing 'name'")
            self.assertIn("domain", data["blueprint"], f"{fpath} blueprint missing 'domain'")
            self.assertIn(data["blueprint"]["domain"], ["automation", "script"], f"Invalid domain in {fpath}")
            self.assertIn("input", data["blueprint"], f"{fpath} blueprint missing 'input'")

    def test_all_blueprints_jinja_syntax_compilation(self):
        """Extract and compile every Jinja2 template string across all 7 blueprint files."""
        template_count = 0

        def validate_node(node, filepath):
            nonlocal template_count
            if isinstance(node, str):
                if "{{" in node or "{%" in node:
                    template_count += 1
                    try:
                        self.env.parse(node)
                    except Exception as e:
                        self.fail(f"Jinja parse error in {filepath}:\n{e}\nTemplate:\n{node}")
            elif isinstance(node, dict):
                for k, v in node.items():
                    validate_node(v, filepath)
            elif isinstance(node, list):
                for item in node:
                    validate_node(item, filepath)

        for fpath in self.blueprint_files:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            validate_node(data, fpath)

        self.assertGreaterEqual(template_count, 100, f"Expected 100+ templates compiled, found {template_count}")

    def test_ha_scripts_jinja_syntax_compilation(self):
        """Extract and compile every Jinja2 template string across all 92 files in ha-scripts/."""
        script_files = glob.glob("ha-scripts/**/*.yaml", recursive=True)
        if not script_files:
            self.skipTest("No ha-scripts found in workspace")

        template_count = 0

        def validate_node(node, filepath):
            nonlocal template_count
            if isinstance(node, str):
                if "{{" in node or "{%" in node:
                    template_count += 1
                    try:
                        self.env.parse(node)
                    except Exception as e:
                        self.fail(f"Jinja parse error in {filepath}:\n{e}\nTemplate:\n{node}")
            elif isinstance(node, dict):
                for k, v in node.items():
                    validate_node(v, filepath)
            elif isinstance(node, list):
                for item in node:
                    validate_node(item, filepath)

        for fpath in script_files:
            with open(fpath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            validate_node(data, fpath)

        self.assertGreaterEqual(template_count, 150, f"Expected 150+ templates compiled, found {template_count}")


if __name__ == "__main__":
    unittest.main()

