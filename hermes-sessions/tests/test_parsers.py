"""Unit tests for the pure parsing, bounding, and redaction helpers."""
import json

import pytest

from hermes_sessions_cli import parsers


class TestPreviewAndRedaction:
    def test_preview_bounds_long_text(self):
        assert parsers.preview("x" * 500, 20) == "x" * 17 + "..."

    def test_preview_collapses_newlines_into_one_line(self):
        assert parsers.preview("a\n\nb\tc") == "a b c"

    def test_preview_returns_none_for_missing_and_blank_values(self):
        assert parsers.preview(None) is None
        assert parsers.preview("   \n ") is None

    def test_preview_serializes_structures(self):
        assert parsers.preview({"a": 1}) == '{"a":1}'

    @pytest.mark.parametrize("bound", [0, -1, -1000])
    def test_a_non_positive_bound_never_means_unbounded(self, bound):
        """A bound of 0 or less must clamp to 1 character, not disable bounding."""
        rendered = parsers.preview("y" * 500, bound)
        assert rendered == "…"

    @pytest.mark.parametrize(
        "text",
        [
            "Authorization: Bearer abcdefghijklmnop",
            "use sk-abcdefghijklmnopqrst here",
            "token ghp_abcdefghijklmnopqrst",
            "slack xoxb-1234567890-abcdef",
            "api_key=supersecretvalue",
            'password: "hunter2hunter2"',
            "client_secret = abcd1234efgh",
        ],
    )
    def test_preview_redacts_credential_shapes(self, text):
        rendered = parsers.preview(text, 500)
        assert "[REDACTED]" in rendered
        for secret in ("abcdefghijklmnop", "supersecretvalue", "hunter2hunter2", "abcd1234efgh"):
            if secret in text:
                assert secret not in rendered

    def test_preview_leaves_ordinary_text_alone(self):
        assert parsers.preview("read the file and report") == "read the file and report"


class TestTime:
    def test_to_iso_renders_utc(self):
        assert parsers.to_iso(0) == "1970-01-01T00:00:00Z"

    def test_to_iso_passes_through_none(self):
        assert parsers.to_iso(None) is None

    def test_to_iso_rejects_unrepresentable_values(self):
        assert parsers.to_iso(1e30) is None

    def test_format_local_time_handles_missing_and_malformed(self):
        assert parsers.format_local_time(None) == ""
        assert parsers.format_local_time("not-a-timestamp") == ""

    @pytest.mark.parametrize("value,seconds", [("30m", 1800), ("5h", 18000), ("7d", 604800), ("2w", 1209600)])
    def test_parse_since_accepts_documented_units(self, value, seconds):
        import time

        cutoff = parsers.parse_since(value)
        assert abs((time.time() - cutoff) - seconds) < 5

    def test_parse_since_passes_through_none(self):
        assert parsers.parse_since(None) is None

    @pytest.mark.parametrize("value", ["", "5", "5y", "abc", "-3d"])
    def test_parse_since_rejects_malformed_windows(self, value):
        if value == "":
            assert parsers.parse_since(value) is None
            return
        with pytest.raises(ValueError):
            parsers.parse_since(value)


class TestDateSelectors:
    def test_no_selector_returns_none(self):
        assert parsers.resolve_date_selector() is None

    def test_single_date_spans_one_local_day(self):
        start, end = parsers.resolve_date_selector(date="2026-09-19")
        assert end - start == 86400

    def test_range_is_inclusive_of_the_end_day(self):
        start, end = parsers.resolve_date_selector(date_range="2026-09-01..2026-09-03")
        assert end - start == 3 * 86400

    def test_week_aliases_span_seven_days(self):
        start, end = parsers.resolve_date_selector(date_alias="this_week")
        assert end - start == 7 * 86400

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"date": "19-09-2026"},
            {"date_range": "2026-09-01"},
            {"date_range": "2026-09-03..2026-09-01"},
            {"date_alias": "next_week"},
            {"date": "2026-09-01", "date_alias": "today"},
        ],
    )
    def test_malformed_selectors_raise(self, kwargs):
        with pytest.raises(ValueError):
            parsers.resolve_date_selector(**kwargs)


class TestToolCalls:
    def test_parses_hermes_tool_call_payload(self):
        raw = json.dumps(
            [{"id": "a", "call_id": "b", "type": "function",
              "function": {"name": "terminal", "arguments": '{"command": "ls"}'}}]
        )
        calls = parsers.parse_tool_calls(raw)
        assert calls == [{"id": "b", "name": "terminal", "arguments": {"command": "ls"}}]

    @pytest.mark.parametrize("raw", [None, "", "not json", "{}", "[]", '[null]', '[{"function": {}}]'])
    def test_malformed_payloads_yield_no_calls(self, raw):
        assert parsers.parse_tool_calls(raw) == []

    def test_non_json_arguments_become_an_empty_mapping(self):
        raw = json.dumps([{"id": "a", "function": {"name": "t", "arguments": "not json"}}])
        assert parsers.parse_tool_calls(raw)[0]["arguments"] == {}

    def test_arguments_already_decoded_are_kept(self):
        assert parsers.parse_arguments({"a": 1}) == {"a": 1}


class TestTodosAndSkills:
    def test_extracts_positional_todo_items(self):
        rows = parsers.extract_todos(
            {"todos": [{"content": "one", "status": "pending"}, {"content": "two", "status": "done"}]}
        )
        assert [row["position"] for row in rows] == [0, 1]
        assert rows[1]["status"] == "done"

    @pytest.mark.parametrize("arguments", [{}, {"todos": "nope"}, {"todos": [{}]}, {"todos": [None]}])
    def test_malformed_todo_payloads_yield_nothing(self, arguments):
        assert parsers.extract_todos(arguments) == []

    def test_missing_status_is_labelled_unknown(self):
        assert parsers.extract_todos({"todos": [{"content": "x"}]})[0]["status"] == "unknown"

    @pytest.mark.parametrize(
        "content,expected",
        [("/answer-comments now", "answer-comments"), ("/recap", "recap"),
         ("  /demo arg", "demo"), ("not a command", None), ("//", None), (None, None), ("", None)],
    )
    def test_slash_command_detection(self, content, expected):
        assert parsers.slash_command_name(content) == expected

    def test_skill_name_prefers_arguments(self):
        assert parsers.skill_name_from_result('{"name": "from-result"}', {"name": "from-args"}) == "from-args"

    def test_skill_name_falls_back_to_the_result_payload(self):
        assert parsers.skill_name_from_result('{"name": "from-result"}', {}) == "from-result"

    def test_skill_name_is_none_when_nothing_names_it(self):
        assert parsers.skill_name_from_result("not json", {}) is None


class TestStatusAndSegmentation:
    @pytest.mark.parametrize(
        "content,expected",
        [
            (None, "pending"),
            ('{"success": true}', "success"),
            ('{"success": false}', "error"),
            ('{"error": "boom"}', "error"),
            # Hermes writes a null `error` and a zero `exit_code` on success;
            # a substring match on "error" would misread every one of these.
            ('{"output": "", "exit_code": 0, "error": null}', "success"),
            ('{"output": "[]", "exit_code": 0, "error": null}', "success"),
            ('{"output": "", "exit_code": 0, "error": ""}', "success"),
            ('{"output": "", "exit_code": 2, "error": null}', "error"),
            ('{"output": "", "exit_code": 0, "error": "boom"}', "error"),
            ('{"output": "no such file"}', "success"),
            ("Traceback (most recent call last):", "error"),
            ("plain output", "success"),
            ("", "success"),
            ("[1, 2, 3]", "success"),
        ],
    )
    def test_tool_status_classification(self, content, expected):
        assert parsers.tool_status(content) == expected

    def test_tool_status_reads_a_nested_failure_flag(self):
        assert parsers.tool_status('{"result": {"success": false}}') == "success"

    def test_conversations_split_at_compaction_boundaries(self):
        messages = [
            {"role": "user", "_compressed_summary": 0},
            {"role": "assistant", "_compressed_summary": 0},
            {"role": "user", "_compressed_summary": 1},
            {"role": "assistant", "_compressed_summary": 0},
        ]
        segments = parsers.segment_conversations(messages)
        assert [len(segment) for segment in segments] == [2, 2]

    def test_a_session_without_compaction_has_one_conversation(self):
        assert len(parsers.segment_conversations([{"role": "user", "_compressed_summary": 0}])) == 1

    def test_no_messages_yields_no_conversations(self):
        assert parsers.segment_conversations([]) == []

    def test_turns_open_at_each_user_message(self):
        messages = [
            {"role": "user"}, {"role": "assistant"}, {"role": "tool"},
            {"role": "user"}, {"role": "assistant"},
        ]
        assert [len(turn) for turn in parsers.segment_turns(messages)] == [3, 2]

    def test_messages_before_the_first_user_message_form_a_leading_turn(self):
        messages = [{"role": "session_meta"}, {"role": "user"}, {"role": "assistant"}]
        assert [len(turn) for turn in parsers.segment_turns(messages)] == [1, 2]


class TestProjectNames:
    @pytest.mark.parametrize(
        "cwd,expected",
        [("/work/demo", "demo"), ("/work/demo/", "demo"), ("/", "/"),
         (None, parsers.NO_WORKSPACE), ("", parsers.NO_WORKSPACE), ("   ", parsers.NO_WORKSPACE)],
    )
    def test_project_name_from_cwd(self, cwd, expected):
        assert parsers.project_name(cwd) == expected


class TestTokens:
    def test_effective_tokens_weights_cache_reads(self):
        row = {"input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 5000}
        assert parsers.effective_tokens(row) == 1700

    def test_absent_counters_are_treated_as_zero(self):
        assert parsers.effective_tokens({}) == 0
