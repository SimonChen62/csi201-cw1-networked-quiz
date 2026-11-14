"""B: tests for the question-bank loader (Task 1 validation rules).

Every case in the Coursework I schema table gets at least one test: a valid file
is accepted, and each single-constraint violation makes the whole file invalid
with a ``ValueError``. The shipped ``questions.json`` is also loaded as-is.
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
sys.path.insert(0, str(CODE_ROOT / "server_modules"))

from question_bank import MAX_FILE_BYTES, load_question_bank

SHIPPED_BANK = CODE_ROOT / "questions.json"


def minimal_bank():
    """Return a valid bank with one quiz and the minimum five questions."""
    questions = [
        {
            "question_id": f"Q{index}",
            "text": f"Question number {index}?",
            "options": {"A": "alpha", "B": "beta", "C": "gamma", "D": "delta"},
            "answer": "A",
            "time_limit": 15,
            "points": 100,
        }
        for index in range(1, 6)
    ]
    return {
        "schema_version": 1,
        "quizzes": [
            {
                "quiz_id": "network-basics",
                "title": "Networking Fundamentals",
                "description": "Five introductory questions",
                "questions": questions,
            }
        ],
    }


class BankTestCase(unittest.TestCase):
    """Helpers to write a payload to a temporary file and load it."""

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self._tempdir.name)

    def tearDown(self):
        self._tempdir.cleanup()

    def write(self, payload, name="bank.json"):
        path = self.temp_path / name
        if isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def load(self, payload):
        return load_question_bank(self.write(payload))

    def assert_invalid(self, payload, fragment=""):
        with self.assertRaises(ValueError) as caught:
            self.load(payload)
        if fragment:
            self.assertIn(fragment, str(caught.exception))
        return caught.exception


class ValidBankTests(BankTestCase):
    def test_shipped_bank_loads(self):
        bank = load_question_bank(SHIPPED_BANK)
        self.assertEqual(bank.schema_version, 1)
        self.assertEqual(len(bank.quizzes), 2)
        self.assertEqual([quiz.question_count for quiz in bank.quizzes], [5, 5])

    def test_minimal_bank_loads(self):
        bank = self.load(minimal_bank())
        quiz = bank.get_quiz("network-basics")
        self.assertIsNotNone(quiz)
        self.assertEqual(quiz.question_count, 5)
        self.assertIsNone(bank.get_quiz("missing-quiz"))

    def test_boundary_values_are_accepted(self):
        payload = minimal_bank()
        payload["quizzes"][0]["title"] = "T" * 100
        payload["quizzes"][0]["description"] = "D" * 300
        for question in payload["quizzes"][0]["questions"]:
            question["text"] = "Q" * 500
            question["options"]["A"] = "O" * 200
            question["time_limit"] = 5
            question["points"] = 1
        payload["quizzes"][0]["questions"][0]["time_limit"] = 60
        payload["quizzes"][0]["questions"][0]["points"] = 1000
        bank = self.load(payload)
        self.assertEqual(bank.quizzes[0].questions[0].time_limit, 60)
        self.assertEqual(bank.quizzes[0].questions[0].points, 1000)

    def test_additional_object_members_are_ignored(self):
        payload = minimal_bank()
        payload["unknown_top_level"] = {"anything": True}
        payload["quizzes"][0]["unknown_quiz_field"] = "ignored"
        payload["quizzes"][0]["questions"][0]["hint"] = "ignored"
        bank = self.load(payload)
        self.assertEqual(bank.quizzes[0].questions[0].question_id, "Q1")

    def test_public_view_hides_answers_and_text(self):
        bank = load_question_bank(SHIPPED_BANK)
        public = bank.public_list()
        self.assertEqual(
            sorted(public[0].keys()),
            ["description", "question_count", "quiz_id", "title"],
        )
        self.assertNotIn("answer", json.dumps(public))

    def test_question_payloads_keep_answer_for_the_engine(self):
        bank = load_question_bank(SHIPPED_BANK)
        payloads = bank.quizzes[0].question_payloads()
        self.assertEqual(payloads[0]["question_id"], "NET001")
        self.assertIn("answer", payloads[0])
        # A copy, so a running match can never mutate the shared bank.
        payloads[0]["options"]["A"] = "changed"
        self.assertEqual(bank.quizzes[0].questions[0].options["A"], "UDP")


class FileLevelTests(BankTestCase):
    def test_missing_file_raises_oserror(self):
        with self.assertRaises(OSError):
            load_question_bank(self.temp_path / "absent.json")

    def test_empty_file_is_invalid(self):
        with self.assertRaises(ValueError) as caught:
            load_question_bank(self.write(b""))
        self.assertIn("empty", str(caught.exception))

    def test_file_over_one_megabyte_is_invalid(self):
        payload = minimal_bank()
        payload["padding"] = "x" * (MAX_FILE_BYTES + 10)
        self.assert_invalid(payload, "limit is")

    def test_invalid_utf8_is_invalid(self):
        with self.assertRaises(ValueError) as caught:
            load_question_bank(self.write(b'{"schema_version": 1, "\xff\xfe": 2}'))
        self.assertIn("UTF-8", str(caught.exception))

    def test_broken_json_is_invalid(self):
        with self.assertRaises(ValueError) as caught:
            load_question_bank(self.write(b'{"schema_version": 1,'))
        self.assertIn("invalid JSON", str(caught.exception))

    def test_top_level_must_be_an_object(self):
        self.assert_invalid([{"schema_version": 1}], "top level")


class SchemaFieldTests(BankTestCase):
    def test_schema_version_must_be_exactly_integer_one(self):
        for bad in (0, 2, "1", True, None):
            with self.subTest(value=bad):
                payload = minimal_bank()
                payload["schema_version"] = bad
                self.assert_invalid(payload, "schema_version")

    def test_schema_version_is_required(self):
        payload = minimal_bank()
        del payload["schema_version"]
        self.assert_invalid(payload, "schema_version")

    def test_quizzes_count_bounds(self):
        for bad in (0, 21):
            with self.subTest(count=bad):
                payload = minimal_bank()
                quiz = payload["quizzes"][0]
                payload["quizzes"] = []
                for index in range(bad):
                    clone = copy.deepcopy(quiz)
                    clone["quiz_id"] = f"quiz-{index}"
                    for q_index in range(len(clone["questions"])):
                        clone["questions"][q_index]["question_id"] = f"Q{index}-{q_index}"
                    payload["quizzes"].append(clone)
                self.assert_invalid(payload, "quizzes must contain")

    def test_quiz_id_charset_and_length(self):
        for bad in ("network basics", "quiz@1", "", "x" * 33):
            with self.subTest(quiz_id=bad):
                payload = minimal_bank()
                payload["quizzes"][0]["quiz_id"] = bad
                self.assert_invalid(payload, "quiz_id")

    def test_duplicate_quiz_id(self):
        payload = minimal_bank()
        payload["quizzes"].append(copy.deepcopy(payload["quizzes"][0]))
        self.assert_invalid(payload, "duplicate quiz_id")

    def test_title_bounds(self):
        for bad in ("", "   ", "T" * 101):
            with self.subTest(title=bad):
                payload = minimal_bank()
                payload["quizzes"][0]["title"] = bad
                self.assert_invalid(payload, "title")

    def test_description_bounds(self):
        payload = minimal_bank()
        payload["quizzes"][0]["description"] = "D" * 301
        self.assert_invalid(payload, "description")

    def test_description_is_required_but_may_be_empty(self):
        payload = minimal_bank()
        payload["quizzes"][0]["description"] = ""
        self.load(payload)

        payload = minimal_bank()
        del payload["quizzes"][0]["description"]
        self.assert_invalid(payload, "description")

    def test_questions_count_bounds(self):
        for bad in (4, 51):
            with self.subTest(count=bad):
                payload = minimal_bank()
                template = payload["quizzes"][0]["questions"][0]
                payload["quizzes"][0]["questions"] = []
                for index in range(bad):
                    clone = copy.deepcopy(template)
                    clone["question_id"] = f"QX{index}"
                    payload["quizzes"][0]["questions"].append(clone)
                self.assert_invalid(payload, "questions must contain")

    def test_question_id_must_be_unique_in_the_whole_file(self):
        payload = minimal_bank()
        second = copy.deepcopy(payload["quizzes"][0])
        second["quiz_id"] = "second-quiz"
        payload["quizzes"].append(second)
        self.assert_invalid(payload, "duplicate question_id")

    def test_question_id_charset(self):
        payload = minimal_bank()
        payload["quizzes"][0]["questions"][0]["question_id"] = "Q 1"
        self.assert_invalid(payload, "question_id")

    def test_text_bounds(self):
        for bad in ("", "T" * 501):
            with self.subTest(length=len(bad)):
                payload = minimal_bank()
                payload["quizzes"][0]["questions"][0]["text"] = bad
                self.assert_invalid(payload, "text")

    def test_options_must_be_exactly_abcd(self):
        for options in (
            {"A": "a", "B": "b", "C": "c"},
            {"A": "a", "B": "b", "C": "c", "D": "d", "E": "e"},
        ):
            with self.subTest(options=sorted(options)):
                payload = minimal_bank()
                payload["quizzes"][0]["questions"][0]["options"] = options
                self.assert_invalid(payload, "options")

    def test_option_value_bounds_and_type(self):
        payload = minimal_bank()
        payload["quizzes"][0]["questions"][0]["options"]["A"] = ""
        self.assert_invalid(payload, "options[A]")

        payload = minimal_bank()
        payload["quizzes"][0]["questions"][0]["options"]["B"] = 5
        self.assert_invalid(payload, "options[B]")

    def test_answer_must_be_one_uppercase_option(self):
        for bad in ("E", "b", "", 1, None):
            with self.subTest(answer=bad):
                payload = minimal_bank()
                payload["quizzes"][0]["questions"][0]["answer"] = bad
                self.assert_invalid(payload, "answer")

    def test_time_limit_bounds_and_type(self):
        for bad in (4, 61, "15", True):
            with self.subTest(value=bad):
                payload = minimal_bank()
                payload["quizzes"][0]["questions"][0]["time_limit"] = bad
                self.assert_invalid(payload, "time_limit")

    def test_points_bounds_and_type(self):
        for bad in (0, 1001, "100", False):
            with self.subTest(value=bad):
                payload = minimal_bank()
                payload["quizzes"][0]["questions"][0]["points"] = bad
                self.assert_invalid(payload, "points")

    def test_missing_required_question_field(self):
        for field in ("question_id", "text", "options", "answer", "time_limit", "points"):
            with self.subTest(field=field):
                payload = minimal_bank()
                del payload["quizzes"][0]["questions"][0][field]
                self.assert_invalid(payload, field)

    def test_diagnostic_points_at_the_offending_question(self):
        payload = minimal_bank()
        payload["quizzes"][0]["questions"][3]["points"] = 5000
        error = self.assert_invalid(payload, "quizzes[0].questions[3]")
        self.assertIn("points", str(error))


if __name__ == "__main__":
    unittest.main()
