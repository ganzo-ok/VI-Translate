"""A user's own glossary: terms that must be translated one way, kept in a file.

The file is plain text the user edits in Excel or Notepad, one term per line:
``source term;translation``. A tab works as the separator too, ``#`` starts a
comment, and a first line naming the two languages is skipped. The glossary
only ever adds terms to a translation; a file that cannot be read is an error
the user sees, never a silent translation without the terms they asked for.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

HEADER_WORDS = {"inglese", "italiano", "english", "italian", "source", "target", "termine", "traduzione"}


class GlossaryError(ValueError):
    """The glossary file is missing or cannot be read."""


class Glossary:
    def __init__(self, entries: list[tuple[str, str]]) -> None:
        # The longest terms first, so "HEPA Filter" is matched before "Filter".
        unique = {source.strip(): target.strip() for source, target in entries}
        self.entries = sorted(unique.items(), key=lambda entry: -len(entry[0]))
        # Any run of white space matches a space: justified PDF text often
        # separates its words with tabs, and "Grade\t8" is still "Grade 8".
        self._patterns = [
            (
                re.compile(
                    r"(?<![\w-])" + r"\s+".join(map(re.escape, source.split())) + r"(?![\w-])",
                    re.IGNORECASE,
                ),
                source, target,
            )
            for source, target in self.entries
        ]

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def digest(self) -> str:
        """Changes whenever an entry does, so cached translations made without it are not reused."""
        text = "\n".join(f"{source}\t{target}" for source, target in self.entries)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def terms_in(self, text: str) -> list[tuple[str, str]]:
        """The entries that occur in ``text``: a page's segment needs only those."""
        return [(source, target) for pattern, source, target in self._patterns if pattern.search(text)]

    def tsv(self) -> str:
        return "\n".join(f"{source}\t{target}" for source, target in self.entries)


def load_glossary(path: str | Path) -> Glossary:
    try:
        lines = Path(path).read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        # Excel on Windows saves "CSV" in the system code page unless told otherwise.
        lines = Path(path).read_text(encoding="cp1252").splitlines()
    except OSError as error:
        raise GlossaryError(f"The glossary file could not be read: {Path(path).name}") from error
    entries: list[tuple[str, str]] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        separator = "\t" if "\t" in line else ";"
        if separator not in line:
            continue
        source, target = (part.strip().strip('"') for part in line.split(separator, 1))
        if not source or not target:
            continue
        if source.lower() in HEADER_WORDS and target.lower() in HEADER_WORDS:
            continue
        entries.append((source, target))
    return Glossary(entries)
