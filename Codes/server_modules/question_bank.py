"""Load the server-only question bank required by the coursework task sheet.

The returned dictionary retains file order and additional object members. It
includes correct answers, so callers must build public messages explicitly
instead of sending this object to a client. No socket is opened here.
"""

import json
from pathlib import Path
import re


# Interpret the task sheet's 1 MB file limit as 1,048,576 bytes.
MAX_FILE_BYTES = 1024 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,32}")
_OPTION_KEYS = {"A", "B", "C", "D"}


def _invalid(location, message):
    raise ValueError(f"{location}: {message}")


def _object(value, required, location):
    if not isinstance(value, dict):
        _invalid(location, "must be a JSON object")
    for key in required:
        if key not in value:
            _invalid(f"{location}.{key}", "required field is missing")


def _array(value, minimum, maximum, location):
    if not isinstance(value, list):
        _invalid(location, "must be a JSON array")
    if not minimum <= len(value) <= maximum:
        _invalid(location, f"must contain {minimum} to {maximum} items")


def _integer(value, minimum, maximum, location):
    # bool is an int subclass in Python, but a different type in JSON.
    if type(value) is not int:
        _invalid(location, "must be a JSON integer (not a boolean or float)")
    if not minimum <= value <= maximum:
        _invalid(location, f"must be between {minimum} and {maximum}")


def _string(value, minimum, maximum, location, *, visible=False):
    if not isinstance(value, str):
        _invalid(location, "must be a string")
    if not minimum <= len(value) <= maximum:
        _invalid(location, f"must contain {minimum} to {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        _invalid(location, "must contain valid Unicode characters")
    if visible:
        if any(not character.isprintable() for character in value):
            _invalid(location, "must contain visible text without control characters")
        if minimum and not value.strip():
            _invalid(location, "must contain nonblank visible text")


def _identifier(value, seen, location):
    _string(value, 1, 32, location)
    if _IDENTIFIER.fullmatch(value) is None:
        _invalid(location, "use only ASCII letters, digits, underscore or hyphen")
    if value in seen:
        _invalid(location, "identifier must be unique across the file")
    seen.add(value)


def _reject_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def load_question_bank(path):
    """Read and validate the complete bank before the server starts listening.

    Accepts a string or pathlib.Path. Returns the validated top-level dict,
    including ``schema_version`` and the ordered ``quizzes`` list. File-access
    failures raise OSError; encoding, JSON and schema failures raise ValueError
    with the relevant field path. UTF-8 files with an initial BOM are accepted.
    """
    bank_path = Path(path)
    # Bound the read as well as the accepted size; do not read an oversized
    # input into memory just to reject it afterwards.
    with bank_path.open("rb") as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    if not raw:
        _invalid(str(bank_path), "question-bank file is empty")
    if len(raw) > MAX_FILE_BYTES:
        _invalid(str(bank_path), f"question-bank file exceeds {MAX_FILE_BYTES} bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError(f"{bank_path}: file must use UTF-8 encoding") from error
    try:
        bank = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{bank_path}: invalid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    except RecursionError as error:
        raise ValueError(f"{bank_path}: JSON nesting is too deep") from error
    except ValueError as error:
        raise ValueError(f"{bank_path}: {error}") from error

    _object(bank, ("schema_version", "quizzes"), "question_bank")
    _integer(bank["schema_version"], 1, 1, "schema_version")
    _array(bank["quizzes"], 1, 20, "quizzes")
    quiz_ids = set()
    question_ids = set()
    for quiz_index, quiz in enumerate(bank["quizzes"]):
        location = f"quizzes[{quiz_index}]"
        _object(quiz, ("quiz_id", "title", "description", "questions"), location)
        _identifier(quiz["quiz_id"], quiz_ids, f"{location}.quiz_id")
        _string(quiz["title"], 1, 100, f"{location}.title", visible=True)
        _string(quiz["description"], 0, 300, f"{location}.description", visible=True)
        _array(quiz["questions"], 5, 50, f"{location}.questions")
        for question_index, question in enumerate(quiz["questions"]):
            question_location = f"{location}.questions[{question_index}]"
            _object(
                question,
                ("question_id", "text", "options", "answer", "time_limit", "points"),
                question_location,
            )
            _identifier(question["question_id"], question_ids, f"{question_location}.question_id")
            _string(question["text"], 1, 500, f"{question_location}.text", visible=True)
            _object(question["options"], (), f"{question_location}.options")
            if set(question["options"]) != _OPTION_KEYS:
                _invalid(f"{question_location}.options", "must contain exactly A, B, C and D")
            for key, option in question["options"].items():
                _string(option, 1, 200, f"{question_location}.options.{key}")
            answer = question["answer"]
            if not isinstance(answer, str) or answer not in _OPTION_KEYS:
                _invalid(f"{question_location}.answer", "must be A, B, C or D")
            _integer(question["time_limit"], 5, 60, f"{question_location}.time_limit")
            _integer(question["points"], 1, 1000, f"{question_location}.points")
    return bank
