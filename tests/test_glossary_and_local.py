from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import requests

from pdf2zh.glossary import GlossaryError, load_glossary
from pdf2zh.translator import (
    DeepLTranslator,
    FormulaPlaceholderError,
    OllamaTranslator,
    ServiceUnavailableError,
)

GLOSSARY = """# commento
inglese;italiano
Grade 8;Grado 8
HEPA Filter;filtro HEPA
Filter;filtro
Supply Air\taria di mandata
riga senza separatore
"""


def glossary_file(folder: str, text: str = GLOSSARY, encoding: str = "utf-8") -> Path:
    path = Path(folder) / "glossario.csv"
    path.write_text(text, encoding=encoding)
    return path


def response(status: int, body: object) -> requests.Response:
    reply = requests.Response()
    reply.status_code = status
    reply._content = json.dumps(body).encode("utf-8")
    reply.encoding = "utf-8"
    return reply


class FakeOllama:
    def __init__(self, reply) -> None:
        self.reply = reply
        self.requests: list[dict] = []

    def post(self, url, json, timeout):
        self.requests.append({"url": url, "json": json})
        return self.reply(json)


def answering(translate):
    return lambda body: response(200, {"message": {"content": translate(body["messages"][-1]["content"])}})


class GlossaryFileTests(unittest.TestCase):
    def test_comments_headers_and_broken_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            glossary = load_glossary(glossary_file(folder))
        self.assertEqual(dict(glossary.entries), {
            "Grade 8": "Grado 8", "HEPA Filter": "filtro HEPA", "Filter": "filtro",
            "Supply Air": "aria di mandata",
        })

    def test_a_file_saved_by_excel_in_the_windows_code_page_is_read(self):
        with tempfile.TemporaryDirectory() as folder:
            glossary = load_glossary(glossary_file(folder, "Relative Humidity;umidità relativa\n", "cp1252"))
        self.assertEqual(glossary.entries, [("Relative Humidity", "umidità relativa")])

    def test_only_the_terms_in_a_segment_are_given(self):
        with tempfile.TemporaryDirectory() as folder:
            glossary = load_glossary(glossary_file(folder))
        self.assertEqual(
            glossary.terms_in("Air in Grade 8 passes the hepa filter."),
            [("HEPA Filter", "filtro HEPA"), ("Grade 8", "Grado 8"), ("Filter", "filtro")],
        )
        self.assertEqual(glossary.terms_in("Grade 80 and filtering"), [])

    def test_a_term_matches_across_the_tabs_of_justified_text(self):
        with tempfile.TemporaryDirectory() as folder:
            glossary = load_glossary(glossary_file(folder))
        self.assertIn(("Grade 8", "Grado 8"), glossary.terms_in("Air\tquality\tin\tGrade\t8\tis"))

    def test_a_missing_file_is_an_error_not_an_empty_glossary(self):
        with self.assertRaises(GlossaryError):
            load_glossary(Path("D:/no/such/glossario.csv"))

    def test_the_digest_follows_the_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            first = load_glossary(glossary_file(folder)).digest
            second = load_glossary(glossary_file(folder, GLOSSARY + "Damper;serranda\n")).digest
        self.assertNotEqual(first, second)


class LocalTranslatorTests(unittest.TestCase):
    def local(self, reply, glossary: Path | None = None) -> tuple[OllamaTranslator, FakeOllama]:
        envs = {"glossary": str(glossary)} if glossary else {}
        translator = OllamaTranslator("en", "it", ignore_cache=True, envs=envs)
        server = FakeOllama(reply)
        translator.session = server
        return translator, server

    def test_each_segment_is_translated_with_its_glossary_terms(self):
        with tempfile.TemporaryDirectory() as folder:
            translator, server = self.local(answering(lambda text: f"it:{text}"), glossary_file(folder))
            answers = translator.translate_many(["Air in Grade 8.", "Nothing special."])
        self.assertEqual(answers, ["it:Air in Grade 8.", "it:Nothing special."])
        first, second = (request["json"]["messages"][0]["content"] for request in server.requests)
        self.assertIn('"Grade 8" -> "Grado 8"', first)
        self.assertNotIn("Grado 8", second)
        self.assertIn("Italian", first)
        self.assertEqual(server.requests[0]["json"]["model"], OllamaTranslator.DEFAULT_MODEL)

    def test_a_lost_marker_is_asked_for_again_then_refused(self):
        translator, server = self.local(answering(lambda _text: "Energia conservata."))
        answer = translator.translate_many(["Energy <b0></b0> is conserved."])[0]
        self.assertIsInstance(answer, FormulaPlaceholderError)
        self.assertEqual(len(server.requests), OllamaTranslator.ATTEMPTS)

    def test_a_kept_marker_passes(self):
        translator, _ = self.local(answering(lambda _text: "Energia <b0></b0> conservata."))
        self.assertEqual(translator.translate_many(["Energy <b0></b0> is conserved."]),
                         ["Energia <b0></b0> conservata."])

    def test_ollama_not_running_stops_the_document(self):
        def refused(_body):
            raise requests.ConnectionError("refused")

        translator, server = self.local(refused)
        answers = translator.translate_many(["One.", "Two.", "Three."])
        self.assertTrue(all(isinstance(answer, ServiceUnavailableError) for answer in answers))
        self.assertIn("local translator", str(answers[0]))
        self.assertEqual(len(server.requests), 1)

    def test_a_missing_model_says_how_to_get_it(self):
        translator, _ = self.local(lambda _body: response(404, {"error": "model not found"}))
        answer = translator.translate_many(["One."])[0]
        self.assertIn("ollama pull", str(answer))

    def test_tabs_between_words_travel_and_return_as_spaces(self):
        """Justified text: tabs went to the model, came back, and glued the words."""
        translator, server = self.local(answering(lambda text: text.replace(" ", "\t")))
        answer = translator.translate_many(["<s2>\t Air\tquality\tis\tgood.</s2>"])[0]
        self.assertEqual(server.requests[0]["json"]["messages"][-1]["content"], "<s2> Air quality is good.</s2>")
        self.assertEqual(answer, "<s2> Air quality is good.</s2>")

    def test_line_breaks_in_an_answer_do_not_split_the_segment(self):
        translator, _ = self.local(answering(lambda _text: "Prima riga\nseconda riga"))
        self.assertEqual(translator.translate_many(["First line"]), ["Prima riga seconda riga"])


class DeepLGlossaryTests(unittest.TestCase):
    def test_the_glossary_is_created_once_and_sent_with_a_source_language(self):
        calls: list[tuple[str, str, object]] = []

        class Server:
            def get(self, url, headers, timeout):
                calls.append(("GET", url, None))
                return response(200, {"glossaries": []})

            def post(self, url, headers, timeout, json=None, data=None):
                calls.append(("POST", url, json or data))
                if url.endswith("/glossaries"):
                    return response(201, {"glossary_id": "g-1"})
                return response(200, {"translations": [{"text": f"it:{text}"} for text in json["text"]]})

        with tempfile.TemporaryDirectory() as folder:
            translator = DeepLTranslator(
                "auto", "it", ignore_cache=True,
                envs={"deepl_key": "k:fx", "glossary": str(glossary_file(folder))},
            )
        translator.session = Server()
        translator.translate_many(["One."])
        translator.translate_many(["Two."])
        created = [call for call in calls if call[1].endswith("/glossaries") and call[0] == "POST"]
        self.assertEqual(len(created), 1)
        self.assertIn("Grade 8\tGrado 8", created[0][2]["entries"])
        sent = [call[2] for call in calls if call[1].endswith("/translate")]
        self.assertTrue(all(body["glossary_id"] == "g-1" and body["source_lang"] == "EN" for body in sent))

    def test_a_refused_glossary_only_costs_the_terms(self):
        class Server:
            def get(self, url, headers, timeout):
                return response(403, {})

            def post(self, url, headers, timeout, json=None, data=None):
                if url.endswith("/glossaries"):
                    return response(400, {"message": "unsupported"})
                return response(200, {"translations": [{"text": f"it:{text}"} for text in json["text"]]})

        with tempfile.TemporaryDirectory() as folder:
            translator = DeepLTranslator(
                "en", "it", ignore_cache=True,
                envs={"deepl_key": "k:fx", "glossary": str(glossary_file(folder))},
            )
        translator.session = Server()
        self.assertEqual(translator.translate_many(["One."]), ["it:One."])
        self.assertIsNone(translator.glossary)


if __name__ == "__main__":
    unittest.main()
