import os
import tempfile
import unittest

from tools import terminology_check


class TerminologyCheckTests(unittest.TestCase):
    def test_load_dictionary_returns_term_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dictionary = os.path.join(tmpdir, "dictionary.yaml")
            with open(dictionary, "w", encoding="utf-8") as handle:
                handle.write("terms:\n  - pattern: foo\n    correct: bar\n")

            terms = terminology_check.load_dictionary(dictionary)

            self.assertEqual(terms, [{"pattern": "foo", "correct": "bar"}])

    def test_check_file_reports_matching_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            document = os.path.join(tmpdir, "sample.md")
            with open(document, "w", encoding="utf-8") as handle:
                handle.write("first line\n禁止語 Forbidden Term\nclean line\n")

            issues = terminology_check.check_file(
                document,
                [{"pattern": "forbidden term", "correct": "allowed term"}],
            )

            self.assertEqual(issues, [(2, "forbidden term", "allowed term")])

    def test_check_file_skips_metadata_code_and_english_only_prose(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            document = os.path.join(tmpdir, "sample.md")
            with open(document, "w", encoding="utf-8") as handle:
                handle.write(
                    "---\nstatus: draft\n---\n"
                    "English or English\n"
                    "```text\n日本語 or 日本語\n```\n"
                    "日本語 `left or right` 本文\n"
                    "日本語 or 日本語\n"
                )

            issues = terminology_check.check_file(
                document,
                [{"pattern": " or ", "correct": "または"}],
            )

            self.assertEqual(issues, [(9, " or ", "または")])

    def test_check_file_skips_binary_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            document = os.path.join(tmpdir, "sample.md")
            with open(document, "wb") as handle:
                handle.write(b"\xff\xfe\x00\x00")

            issues = terminology_check.check_file(
                document,
                [{"pattern": "irrelevant", "correct": "replacement"}],
            )

            self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
