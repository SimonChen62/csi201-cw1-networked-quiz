"""Normative question-bank boundaries, complete validation and real startup."""

import contextlib
import io
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server
from server_modules.question_bank import MAX_FILE_BYTES, load_question_bank

CODES = Path(__file__).resolve().parents[1]


def make_bank(quiz_count=1, question_count=5):
    return {
        "schema_version": 1,
        "quizzes": [{
            "quiz_id": f"quiz-{q}", "title": "Quiz", "description": "",
            "questions": [{
                "question_id": f"Q{q}_{i}", "text": "Which option?",
                "options": {"A": "One", "B": "Two", "C": "Three", "D": "Four"},
                "answer": "A", "time_limit": 5, "points": 1,
            } for i in range(question_count)],
        } for q in range(quiz_count)],
    }


class QuestionBankTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "bank.json"

    def write_bank(self, bank):
        self.path.write_text(json.dumps(bank, ensure_ascii=False), encoding="utf-8")
        return self.path

    def reject(self, bank, field):
        self.write_bank(bank)
        with self.assertRaises(ValueError) as raised:
            load_question_bank(self.path)
        self.assertIn(field, str(raised.exception))

    def test_minimum_bank_and_path_object_are_accepted(self):
        bank = make_bank()
        self.assertEqual(load_question_bank(self.write_bank(bank)), bank)

    def test_file_order_and_additional_members_are_preserved(self):
        bank = make_bank(2)
        bank["quizzes"].reverse()
        bank["quizzes"][0]["questions"].reverse()
        bank["metadata"] = {"revision": 1.5, "tags": ["extra"]}
        quiz = bank["quizzes"][0]
        quiz["notes"] = "accepted"
        quiz["questions"][0]["explanation"] = {"source": "sample"}
        self.assertEqual(load_question_bank(str(self.write_bank(bank))), bank)

    def test_utf8_and_initial_bom_are_accepted(self):
        bank = make_bank()
        bank["quizzes"][0]["title"] = "网络知识测验"
        bank["quizzes"][0]["questions"][0]["options"]["A"] = "选项一"
        self.write_bank(bank)
        self.assertEqual(load_question_bank(self.path), bank)
        self.path.write_bytes(b"\xef\xbb\xbf" + self.path.read_bytes())
        self.assertEqual(load_question_bank(self.path), bank)

    def test_file_size_boundary_and_empty_file(self):
        payload = json.dumps(make_bank()).encode("utf-8")
        self.path.write_bytes(payload + b" " * (MAX_FILE_BYTES - len(payload)))
        self.assertEqual(len(load_question_bank(self.path)["quizzes"]), 1)
        with self.path.open("ab") as output:
            output.write(b" ")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            load_question_bank(self.path)
        self.path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            load_question_bank(self.path)

    def test_missing_file_is_an_os_error(self):
        with self.assertRaises(FileNotFoundError):
            load_question_bank(self.path)

    def test_invalid_utf8_json_and_nonstandard_constants_are_rejected(self):
        for payload in (b"\xff", b"{", b"  ", b'{"schema_version":NaN}',
                        b'{"schema_version":Infinity}', b'{"schema_version":-Infinity}'):
            with self.subTest(payload=payload):
                self.path.write_bytes(payload)
                with self.assertRaises(ValueError):
                    load_question_bank(self.path)

    def test_top_level_must_be_an_object(self):
        for value in ([], None, "bank", 1, True):
            with self.subTest(value=value):
                self.reject(value, "question_bank")

    def test_every_required_field_is_checked(self):
        for level, fields in (
            ("root", ("schema_version", "quizzes")),
            ("quiz", ("quiz_id", "title", "description", "questions")),
            ("question", ("question_id", "text", "options", "answer", "time_limit", "points")),
        ):
            for field in fields:
                with self.subTest(level=level, field=field):
                    bank = make_bank()
                    target = bank if level == "root" else bank["quizzes"][0]
                    if level == "question":
                        target = target["questions"][0]
                    del target[field]
                    self.reject(bank, field)

    def test_schema_version_is_integer_one_not_boolean(self):
        for value in (0, 2, True, False, 1.0, "1", None):
            with self.subTest(value=value):
                bank = make_bank()
                bank["schema_version"] = value
                self.reject(bank, "schema_version")

    def test_quiz_and_question_array_types_and_count_boundaries(self):
        self.assertEqual(len(load_question_bank(self.write_bank(make_bank(20, 50)))["quizzes"]), 20)
        for count in (0, 21):
            with self.subTest(quizzes=count):
                self.reject(make_bank(count), "quizzes")
        for count in (0, 4, 51):
            with self.subTest(questions=count):
                self.reject(make_bank(question_count=count), "questions")
        for value in (None, {}, "array", 5):
            for level in ("quizzes", "questions"):
                with self.subTest(level=level, value=value):
                    bank = make_bank()
                    target = bank if level == "quizzes" else bank["quizzes"][0]
                    target[level] = value
                    self.reject(bank, level)

    def test_quizzes_and_questions_must_be_objects(self):
        for value in (None, [], "object", 1):
            for level in ("quiz", "question"):
                with self.subTest(level=level, value=value):
                    bank = make_bank()
                    if level == "quiz":
                        bank["quizzes"][0] = value
                    else:
                        bank["quizzes"][0]["questions"][0] = value
                    self.reject(bank, "must be a JSON object")

    def test_identifier_types_charset_and_length(self):
        for field in ("quiz_id", "question_id"):
            for value in ("", "x" * 33, "contains space", "a/b", "中文", 1, None, []):
                with self.subTest(field=field, value=value):
                    bank = make_bank()
                    target = bank["quizzes"][0]
                    if field == "question_id":
                        target = target["questions"][0]
                    target[field] = value
                    self.reject(bank, field)
        bank = make_bank()
        bank["quizzes"][0]["quiz_id"] = "aZ_0-" + "x" * 27
        bank["quizzes"][0]["questions"][0]["question_id"] = "q" * 32
        load_question_bank(self.write_bank(bank))

    def test_duplicate_quiz_and_global_question_ids_are_rejected(self):
        bank = make_bank(2)
        bank["quizzes"][1]["quiz_id"] = bank["quizzes"][0]["quiz_id"]
        self.reject(bank, "quizzes[1].quiz_id")
        for quiz_index in (0, 1):
            with self.subTest(target_quiz=quiz_index):
                bank = make_bank(2)
                bank["quizzes"][quiz_index]["questions"][4]["question_id"] = "Q0_0"
                self.reject(bank, "question_id")

    def test_text_types_lengths_visibility_and_valid_boundaries(self):
        for field, maximum, allow_empty in (("title", 100, False), ("description", 300, True), ("text", 500, False)):
            invalid = [None, 12, [], "x" * (maximum + 1), "line\nbreak", "bad\x00text"]
            if not allow_empty:
                invalid += ["", "   "]
            for value in invalid:
                with self.subTest(field=field, value=repr(value)[:30]):
                    bank = make_bank()
                    target = bank["quizzes"][0]
                    if field == "text":
                        target = target["questions"][0]
                    target[field] = value
                    self.reject(bank, field)
            for value in (("", "x" * maximum) if allow_empty else ("x", "x" * maximum)):
                bank = make_bank()
                target = bank["quizzes"][0]
                if field == "text":
                    target = target["questions"][0]
                target[field] = value
                load_question_bank(self.write_bank(bank))

    def test_options_require_exact_keys_and_string_values(self):
        options = make_bank()["quizzes"][0]["questions"][0]["options"]
        invalid = [None, list(options.values()), {**options, "E": "extra"},
                   {k: v for k, v in options.items() if k != "D"}]
        invalid += [{**options, "A": value} for value in ("", "x" * 201, 1, None, [])]
        for value in invalid:
            with self.subTest(value=value):
                bank = make_bank()
                bank["quizzes"][0]["questions"][0]["options"] = value
                self.reject(bank, "options")
        bank = make_bank()
        bank["quizzes"][0]["questions"][0]["options"]["A"] = "x" * 200
        load_question_bank(self.write_bank(bank))

    def test_answers_must_be_one_of_four_uppercase_letters(self):
        for value in ("", "a", "AB", "E", 1, None, [], {}):
            with self.subTest(value=value):
                bank = make_bank()
                bank["quizzes"][0]["questions"][0]["answer"] = value
                self.reject(bank, "answer")
        for value in "ABCD":
            bank = make_bank()
            bank["quizzes"][0]["questions"][0]["answer"] = value
            load_question_bank(self.write_bank(bank))

    def test_numeric_ranges_and_json_integer_types(self):
        for field, low, high in (("time_limit", 5, 60), ("points", 1, 1000)):
            for value in (low - 1, high + 1, True, False, float(low), str(low), None, []):
                with self.subTest(field=field, value=value):
                    bank = make_bank()
                    bank["quizzes"][0]["questions"][0][field] = value
                    self.reject(bank, field)
            for value in (low, high):
                bank = make_bank()
                bank["quizzes"][0]["questions"][0][field] = value
                load_question_bank(self.write_bank(bank))

    def test_entire_file_is_validated_including_last_question(self):
        bank = make_bank(2)
        bank["quizzes"][1]["questions"][-1]["points"] = 1001
        self.reject(bank, "quizzes[1].questions[4].points")

    def test_both_repository_banks_are_valid(self):
        for name, counts in (("questions.json", [5, 5]), ("questions_50.json", [10] * 5)):
            with self.subTest(name=name):
                bank = load_question_bank(CODES / name)
                self.assertEqual([len(q["questions"]) for q in bank["quizzes"]], counts)

    def test_failed_validation_happens_before_any_socket_is_created(self):
        bank = make_bank(2)
        bank["quizzes"][1]["questions"][-1]["options"]["E"] = "extra"
        self.write_bank(bank)
        output = io.StringIO()
        with mock.patch.object(server.socket, "socket") as socket_factory, contextlib.redirect_stdout(output):
            code = server.main(["--host", "127.0.0.1", "--port", "0", "--questions", str(self.path)])
        self.assertEqual(code, 1)
        socket_factory.assert_not_called()
        self.assertNotIn("SERVER_READY", output.getvalue())
        self.assertIn("quizzes[1].questions[4].options", output.getvalue())

    def test_real_server_starts_with_teacher_bank_and_accepts_tcp(self):
        environment = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        process = subprocess.Popen(
            [sys.executable, "-B", "server.py", "--host", "127.0.0.1", "--port", "0", "--questions", "questions_50.json"],
            cwd=CODES, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8",
        )
        lines = queue.Queue()
        reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            ready = lines.get(timeout=8).strip()
            self.assertRegex(ready, r"^SERVER_READY 127\.0\.0\.1 \d+$")
            with socket.create_connection(("127.0.0.1", int(ready.split()[-1])), timeout=2):
                self.assertIsNone(process.poll())
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdout.close()


if __name__ == "__main__":
    unittest.main()
