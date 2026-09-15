"""Tests for CLI sport command parsing and routing."""

from __future__ import annotations

import unittest

from src import cli


class CLISportParsingTests(unittest.TestCase):
    """Test that CLI correctly parses --sport and sport subcommands."""

    def setUp(self):
        """Build the parser once."""
        self.parser = cli.build_parser()

    def test_card_publish_with_sport_nfl(self):
        """card publish --date 2026-09-17 --sport nfl parses."""
        args = self.parser.parse_args(
            ["card", "publish", "--date", "2026-09-17", "--sport", "nfl"])

        self.assertEqual(args.command, "card")
        self.assertEqual(args.card_command, "publish")
        self.assertEqual(args.date, "2026-09-17")
        self.assertEqual(args.sport, "nfl")

    def test_card_publish_default_sport_is_mlb(self):
        """card publish without --sport defaults to mlb."""
        args = self.parser.parse_args(
            ["card", "publish", "--date", "2026-09-17"])

        self.assertEqual(args.sport, "mlb")

    def test_card_settle_with_sport_nfl(self):
        """card settle --date 2026-09-17 --sport nfl parses."""
        args = self.parser.parse_args(
            ["card", "settle", "--date", "2026-09-17", "--sport", "nfl"])

        self.assertEqual(args.command, "card")
        self.assertEqual(args.card_command, "settle")
        self.assertEqual(args.sport, "nfl")

    def test_card_record_with_sport_nfl(self):
        """card record --sport nfl parses."""
        args = self.parser.parse_args(
            ["card", "record", "--sport", "nfl"])

        self.assertEqual(args.command, "card")
        self.assertEqual(args.card_command, "record")
        self.assertEqual(args.sport, "nfl")

    def test_card_publish_rejects_invalid_sport(self):
        """card publish --sport cricket is rejected."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["card", "publish", "--date", "2026-09-17", "--sport", "cricket"])

    def test_nfl_capture_parses(self):
        """nfl capture parses."""
        args = self.parser.parse_args(["nfl", "capture"])

        self.assertEqual(args.command, "nfl")
        self.assertEqual(args.nfl_command, "capture")

    def test_tennis_discover_parses(self):
        """tennis discover parses."""
        args = self.parser.parse_args(["tennis", "discover"])

        self.assertEqual(args.command, "tennis")
        self.assertEqual(args.tennis_command, "discover")

    def test_tennis_capture_parses(self):
        """tennis capture parses."""
        args = self.parser.parse_args(["tennis", "capture"])

        self.assertEqual(args.command, "tennis")
        self.assertEqual(args.tennis_command, "capture")

    def test_tennis_results_parses(self):
        """tennis results --date 2026-09-14 parses."""
        args = self.parser.parse_args(
            ["tennis", "results", "--date", "2026-09-14"])

        self.assertEqual(args.command, "tennis")
        self.assertEqual(args.tennis_command, "results")
        self.assertEqual(args.date, "2026-09-14")

    def test_tennis_results_requires_date(self):
        """tennis results without --date fails."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["tennis", "results"])

    def test_nfl_command_requires_subcommand(self):
        """nfl without subcommand fails."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["nfl"])

    def test_tennis_command_requires_subcommand(self):
        """tennis without subcommand fails."""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["tennis"])


if __name__ == "__main__":
    unittest.main()
