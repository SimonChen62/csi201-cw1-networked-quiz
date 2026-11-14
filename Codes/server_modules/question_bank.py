"""B: question-bank loading and full schema validation.

The examiner may replace the submitted ``questions.json`` with any other file
that follows the Coursework I schema ("the examiner may replace the submitted
development file with another valid file that follows this schema"). This
loader therefore validates every constraint stated in the Specification
instead of relying on the shape of the shipped sample.

Contract with A (``Codes/server.py``):
    * success      -> returns a non-None ``QuestionBank`` object
    * file problem -> raises ``OSError`` (missing file, permission, ...)
    * format issue -> raises ``ValueError`` with a located diagnostic
    * A never re-validates the returned object, so this module owns the schema.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 1024 * 1024      # Specification: maximum accepted file size 1 MB
MAX_QUIZZES = 20                  # quizzes: 1 to 20 objects
MIN_QUESTIONS = 5                 # questions: 5 to 50 objects
MAX_QUESTIONS = 50
MAX_ID_LENGTH = 32                # quiz_id / question_id: 1-32 characters
ID_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
OPTION_KEYS = ("A", "B", "C", "D")
MIN_TIME_LIMIT = 5                # seconds
MAX_TIME_LIMIT = 60
MIN_POINTS = 1
MAX_POINTS = 1000
MAX_TITLE_VISIBLE = 100
MAX_DESCRIPTION_VISIBLE = 300
MAX_TEXT_VISIBLE = 500
MAX_OPTION_CHARS = 200

_MISSING = object()


def _unicode_text(value, where):
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _invalid(where, "text must contain valid Unicode") from exc


def _reject_constant(value):
    raise ValueError(f"nonstandard JSON constant: {value}")


def _invalid(where, problem):
    return ValueError(f"{where}: {problem}")


def _is_integer(value):
    # bool is a subclass of int, but ``true`` is not a valid integer field.
    return isinstance(value, int) and not isinstance(value, bool)


def _required(container, key, where):
    value = container.get(key, _MISSING)
    if value is _MISSING:
        raise _invalid(where, f"missing required field {key!r}")
    return value


def _require_text(value, where, field_name, minimum, maximum):
    if not isinstance(value, str):
        raise _invalid(where, f"{field_name} must be a string, got {type(value).__name__}")
    _unicode_text(value, where)
    visible = len(value)
    if visible < minimum or visible > maximum or (minimum and not value.strip()):
        raise _invalid(
            where,
            f"{field_name} must have {minimum}-{maximum} visible characters, got {visible}",
        )
    if value and not value.isprintable():
        raise _invalid(where, f"{field_name} must not contain control characters")
    return value


def _require_id(value, where, field_name):
    if not isinstance(value, str):
        raise _invalid(where, f"{field_name} must be a string, got {type(value).__name__}")
    if not ID_PATTERN.fullmatch(value) or len(value) > MAX_ID_LENGTH:
        raise _invalid(
            where,
            f"{field_name} must be 1-{MAX_ID_LENGTH} characters of letters, digits, "
            f"underscore or hyphen, got {value!r}",
        )
    return value


def _require_int_range(value, where, field_name, minimum, maximum):
    if not _is_integer(value):
        raise _invalid(where, f"{field_name} must be an integer, got {type(value).__name__}")
    if not minimum <= value <= maximum:
        raise _invalid(where, f"{field_name} must be {minimum}-{maximum}, got {value}")
    return value


@dataclass(frozen=True)
class Question:
    """One validated question; ``answer`` stays server-side."""

    question_id: str
    text: str
    options: dict
    answer: str
    time_limit: int
    points: int

    def as_dict(self):
        """Return the mapping C's ``GameEngine`` expects (answer included)."""
        return {
            "question_id": self.question_id,
            "text": self.text,
            "options": dict(self.options),
            "answer": self.answer,
            "time_limit": self.time_limit,
            "points": self.points,
        }

    def public_dict(self):
        """Return the fields a client may see while the question is open."""
        return {
            "question_id": self.question_id,
            "text": self.text,
            "options": dict(self.options),
            "time_limit": self.time_limit,
            "points": self.points,
        }


@dataclass(frozen=True)
class Quiz:
    """One validated quiz, ordered exactly as it appears in the file."""

    quiz_id: str
    title: str
    description: str
    questions: tuple

    @property
    def question_count(self):
        return len(self.questions)

    def public_view(self):
        """Metadata safe to publish before play (no text, options or answers)."""
        return {
            "quiz_id": self.quiz_id,
            "title": self.title,
            "description": self.description,
            "question_count": self.question_count,
        }

    def question_payloads(self):
        """Questions for ``GameEngine.create_match``; copies, so a match is isolated."""
        return [question.as_dict() for question in self.questions]


@dataclass(frozen=True)
class QuestionBank:
    """Read-only, fully validated bank shared by every room."""

    schema_version: int
    quizzes: tuple

    def get_quiz(self, quiz_id):
        """Return the ``Quiz`` for ``quiz_id``, or ``None`` when absent."""
        for quiz in self.quizzes:
            if quiz.quiz_id == quiz_id:
                return quiz
        return None

    def public_list(self):
        """Return ``quizzes`` for the ``list_quizzes`` response."""
        return [quiz.public_view() for quiz in self.quizzes]


def load_question_bank(path):
    """Read and fully validate a question bank.

    Args:
        path: Path to the JSON file, as given on the command line.

    Returns:
        A ``QuestionBank`` instance (never ``None``).

    Raises:
        OSError: The file cannot be read.
        ValueError: The file is empty, too large, not UTF-8, not JSON, or
            violates any schema constraint.
    """
    file_path = Path(path)
    with file_path.open("rb") as source:
        raw = source.read(MAX_FILE_BYTES + 1)  # Bound memory; OSError propagates.

    origin = str(path)
    if not raw:
        raise ValueError(f"{origin}: question bank file is empty")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(
            f"{origin}: question bank file is {len(raw)} bytes, limit is {MAX_FILE_BYTES}"
        )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"{origin}: file is not valid UTF-8 ({exc.reason} at byte {exc.start})"
        ) from exc

    try:
        payload = json.loads(text, parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{origin}: invalid JSON ({exc.msg} at line {exc.lineno} column {exc.colno})"
        ) from exc
    except (ValueError, RecursionError) as exc:
        raise ValueError(f"{origin}: invalid JSON ({exc})") from exc

    return _parse_bank(payload, origin)


def _parse_bank(payload, origin):
    """Validate the top-level object and every quiz/question inside it."""
    if not isinstance(payload, dict):
        raise _invalid(origin, f"top level must be a JSON object, got {type(payload).__name__}")

    schema_version = _required(payload, "schema_version", origin)
    if not _is_integer(schema_version) or schema_version != 1:
        raise _invalid(origin, f"schema_version must be the integer 1, got {schema_version!r}")

    quizzes_raw = _required(payload, "quizzes", origin)
    if not isinstance(quizzes_raw, list):
        raise _invalid(origin, f"quizzes must be an array, got {type(quizzes_raw).__name__}")
    if not 1 <= len(quizzes_raw) <= MAX_QUIZZES:
        raise _invalid(origin, f"quizzes must contain 1-{MAX_QUIZZES} quizzes, got {len(quizzes_raw)}")

    quiz_ids = set()
    question_ids = set()
    quizzes = []
    for index, quiz_raw in enumerate(quizzes_raw):
        quizzes.append(_parse_quiz(quiz_raw, f"{origin}: quizzes[{index}]", quiz_ids, question_ids))

    return QuestionBank(schema_version=schema_version, quizzes=tuple(quizzes))


def _parse_quiz(quiz_raw, where, quiz_ids, question_ids):
    if not isinstance(quiz_raw, dict):
        raise _invalid(where, f"quiz must be a JSON object, got {type(quiz_raw).__name__}")

    quiz_id = _require_id(_required(quiz_raw, "quiz_id", where), where, "quiz_id")
    if quiz_id in quiz_ids:
        raise _invalid(where, f"duplicate quiz_id {quiz_id!r}")
    quiz_ids.add(quiz_id)

    title = _require_text(_required(quiz_raw, "title", where), where, "title", 1, MAX_TITLE_VISIBLE)
    description = _require_text(
        _required(quiz_raw, "description", where),
        where,
        "description",
        0,
        MAX_DESCRIPTION_VISIBLE,
    )

    questions_raw = _required(quiz_raw, "questions", where)
    if not isinstance(questions_raw, list):
        raise _invalid(where, f"questions must be an array, got {type(questions_raw).__name__}")
    if not MIN_QUESTIONS <= len(questions_raw) <= MAX_QUESTIONS:
        raise _invalid(
            where,
            f"questions must contain {MIN_QUESTIONS}-{MAX_QUESTIONS} questions, "
            f"got {len(questions_raw)}",
        )

    questions = []
    for index, question_raw in enumerate(questions_raw):
        questions.append(
            _parse_question(question_raw, f"{where}.questions[{index}]", question_ids)
        )

    return Quiz(
        quiz_id=quiz_id,
        title=title,
        description=description,
        questions=tuple(questions),
    )


def _parse_question(question_raw, where, question_ids):
    if not isinstance(question_raw, dict):
        raise _invalid(where, f"question must be a JSON object, got {type(question_raw).__name__}")

    question_id = _require_id(
        _required(question_raw, "question_id", where), where, "question_id"
    )
    if question_id in question_ids:
        raise _invalid(where, f"duplicate question_id {question_id!r} (must be unique in the file)")
    question_ids.add(question_id)

    text = _require_text(_required(question_raw, "text", where), where, "text", 1, MAX_TEXT_VISIBLE)

    options = _required(question_raw, "options", where)
    if not isinstance(options, dict):
        raise _invalid(where, f"options must be an object, got {type(options).__name__}")
    if set(options.keys()) != set(OPTION_KEYS):
        raise _invalid(
            where,
            f"options must contain exactly {', '.join(OPTION_KEYS)}, got {sorted(options.keys())}",
        )
    for key in OPTION_KEYS:
        value = options[key]
        if not isinstance(value, str):
            raise _invalid(where, f"options[{key}] must be a string, got {type(value).__name__}")
        _unicode_text(value, f"{where}.options[{key}]")
        if not 1 <= len(value) <= MAX_OPTION_CHARS:
            raise _invalid(
                where,
                f"options[{key}] must have 1-{MAX_OPTION_CHARS} characters, got {len(value)}",
            )

    answer = _required(question_raw, "answer", where)
    if not isinstance(answer, str) or answer not in OPTION_KEYS:
        raise _invalid(where, f"answer must be exactly one of A, B, C or D, got {answer!r}")

    time_limit = _require_int_range(
        _required(question_raw, "time_limit", where),
        where,
        "time_limit",
        MIN_TIME_LIMIT,
        MAX_TIME_LIMIT,
    )
    points = _require_int_range(
        _required(question_raw, "points", where), where, "points", MIN_POINTS, MAX_POINTS
    )

    # Extra object members are allowed for forward compatibility and are ignored.
    return Question(
        question_id=question_id,
        text=text,
        options={key: options[key] for key in OPTION_KEYS},
        answer=answer,
        time_limit=time_limit,
        points=points,
    )


def main(argv=None):
    """Command-line self-check: validate a bank and print a short summary."""
    import sys

    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print("usage: python -m server_modules.question_bank <questions.json>", flush=True)
        return 2
    try:
        bank = load_question_bank(args[0])
    except (OSError, ValueError) as exc:
        print(f"question bank rejected: {exc}", flush=True)
        return 1
    for quiz in bank.quizzes:
        print(f"{quiz.quiz_id}: {quiz.question_count} questions", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
