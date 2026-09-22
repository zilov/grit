"""Unit tests for the tutorial's command matcher and hint generator (pure string logic)."""

import pytest

from grit.core.tutorial import (
    _safe_to_run,
    expected_line,
    hint_for,
    matches,
    parse_command,
)
from grit.core.tutorial_lessons import SCENARIOS, Lesson, find_scenario

TICKET = "TUTORIAL-1"
KNOWN = {"setup", "status", "pretext-to-asm", "blast-contaminants", "hic-remapping", "untrack"}

PLAIN = Lesson(title="t", why="w", task="do it", command="pretext-to-asm")
HAP2 = Lesson(
    title="t",
    why="w",
    task="do it",
    command="hic-remapping",
    args=["--hap2"],
    flag_hints={"--hap2": "hic-remapping runs one haplotype per invocation."},
)
STEP = Lesson(
    title="t",
    why="w",
    task="do it",
    command="untrack",
    args=["-s", "blast_contaminants"],
    flag_hints={"--step": "untrack needs -s <step>."},
)


class TestParse:
    def test_short_and_long_ticket_are_the_same(self):
        assert parse_command(["grit", "setup", "-t", TICKET]) == parse_command(
            ["grit", "setup", "--ticket", TICKET]
        )

    def test_equals_form_is_the_same(self):
        assert parse_command(["grit", "setup", "--ticket=" + TICKET]).ticket == TICKET

    def test_leading_grit_is_optional(self):
        assert parse_command(["setup", "-t", TICKET]).subcommand == "setup"

    def test_flag_order_does_not_matter(self):
        a = parse_command(["grit", "hic-remapping", "-t", TICKET, "--hap2"])
        b = parse_command(["grit", "hic-remapping", "--hap2", "-t", TICKET])
        assert a == b

    def test_dry_run_is_ignored(self):
        assert parse_command(["grit", "setup", "-t", TICKET, "--dry-run"]) == parse_command(
            ["grit", "setup", "-t", TICKET]
        )

    def test_tutorial_plumbing_is_ignored(self):
        parsed = parse_command(
            ["grit", "--config", "/x/y.yaml", "--yaml", "/a/b.yaml", "setup", "-t", TICKET]
        )
        assert parsed == parse_command(["grit", "setup", "-t", TICKET])

    def test_step_value_is_part_of_the_answer(self):
        assert parse_command(["grit", "untrack", "-s", "foo"]).flags == frozenset({"--step=foo"})


class TestMatches:
    def test_exact(self):
        assert matches(parse_command(["grit", "pretext-to-asm", "-t", TICKET]), PLAIN, TICKET)

    def test_with_dry_run_typed_anyway(self):
        got = parse_command(["grit", "pretext-to-asm", "-t", TICKET, "--dry-run"])
        assert matches(got, PLAIN, TICKET)

    def test_missing_flag_does_not_match(self):
        assert not matches(parse_command(["grit", "hic-remapping", "-t", TICKET]), HAP2, TICKET)

    def test_extra_flag_does_not_match(self):
        got = parse_command(["grit", "pretext-to-asm", "-t", TICKET, "--hap2"])
        assert not matches(got, PLAIN, TICKET)

    def test_wrong_ticket_does_not_match(self):
        assert not matches(parse_command(["grit", "pretext-to-asm", "-t", "RC-9"]), PLAIN, TICKET)

    def test_step_value_must_match(self):
        got = parse_command(["grit", "untrack", "-t", TICKET, "-s", "wrong_step"])
        assert not matches(got, STEP, TICKET)


class TestHints:
    def _hint(self, tokens, lesson=PLAIN):
        return hint_for(parse_command(tokens), lesson, TICKET, KNOWN)

    def test_unknown_command_points_at_help(self):
        assert "--help" in self._hint(["grit", "pretext-to-agp", "-t", TICKET])

    def test_wrong_step_names_both(self):
        hint = self._hint(["grit", "setup", "-t", TICKET])
        assert "setup" in hint and "pretext-to-asm" in hint

    def test_missing_ticket_says_so(self):
        assert "-t" in self._hint(["grit", "pretext-to-asm"])

    def test_wrong_ticket_names_the_sandbox_one(self):
        assert TICKET in self._hint(["grit", "pretext-to-asm", "-t", "RC-9"])

    def test_missing_flag_uses_the_lesson_s_own_explanation(self):
        hint = self._hint(["grit", "hic-remapping", "-t", TICKET], HAP2)
        assert hint == "hic-remapping runs one haplotype per invocation."

    def test_extra_flag_is_named(self):
        assert "--hap2" in self._hint(["grit", "pretext-to-asm", "-t", TICKET, "--hap2"])

    def test_wrong_step_value_falls_back_to_the_flag_hint(self):
        hint = self._hint(["grit", "untrack", "-t", TICKET, "-s", "nope"], STEP)
        assert hint == "untrack needs -s <step>."

    def test_no_command_at_all(self):
        assert "grit" in hint_for(parse_command(["grit"]), PLAIN, TICKET, KNOWN)


class TestScenarios:
    def test_every_lesson_names_a_registered_command(self):
        from grit.core.click_cli import cli

        for scenario in SCENARIOS:
            for lesson in scenario.lessons:
                assert lesson.command in cli.commands, (
                    f"{scenario.key}: {lesson.command!r} is not a registered grit command"
                )

    def test_every_scenario_yaml_exists(self):
        for scenario in SCENARIOS:
            assert scenario.yaml_path.exists(), scenario.yaml_path

    def test_scenario_tickets_are_unique(self):
        tickets = [s.ticket for s in SCENARIOS]
        assert len(tickets) == len(set(tickets))

    def test_expected_line_round_trips_through_the_matcher(self):
        for scenario in SCENARIOS:
            for lesson in scenario.lessons:
                line = expected_line(lesson, scenario.ticket).split()
                assert matches(parse_command(line), lesson, scenario.ticket)

    def test_every_lesson_explains_the_flags_it_asks_for(self):
        """A lesson that demands a flag must be able to say why, or its hint is useless."""
        for scenario in SCENARIOS:
            for lesson in scenario.lessons:
                for flag in lesson.args:
                    if flag.startswith("-"):
                        name = {"-s": "--step", "-u": "--untracked"}.get(flag, flag)
                        assert name in lesson.flag_hints, f"{scenario.key}/{lesson.command}: {name}"

    @pytest.mark.parametrize("key", [s.key for s in SCENARIOS])
    def test_find_scenario(self, key):
        assert find_scenario(key).key == key

    def test_find_scenario_unknown(self):
        assert find_scenario("nope") is None


class TestSafeToRun:
    """A non-matching command is executed only when running it can't teach the wrong thing."""

    def _run(self, tokens, lesson=PLAIN):
        rest = tokens[1:] if tokens and tokens[0] == "grit" else tokens
        return _safe_to_run(parse_command(tokens), lesson, TICKET, rest)

    def test_status_on_this_ticket_runs(self):
        assert self._run(["grit", "status", "-t", TICKET])

    def test_another_step_is_not_run(self):
        """A stray mutating step would invalidate the next lesson's status claim."""
        assert not self._run(["grit", "blast-contaminants", "-t", TICKET])

    def test_help_runs_even_without_a_ticket(self):
        assert self._run(["grit", "pretext-to-asm", "--help"])

    def test_missing_ticket_is_not_run(self):
        """--yaml makes -t optional, so grit would invent a ticket from the filename."""
        assert not self._run(["grit", "pretext-to-asm"])

    def test_foreign_ticket_is_not_run(self):
        assert not self._run(["grit", "status", "-t", "RC-9999"])

    def test_the_lesson_s_own_step_with_wrong_flags_is_not_run(self):
        assert not self._run(["grit", "hic-remapping", "-t", TICKET], HAP2)
