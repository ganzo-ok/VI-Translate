from __future__ import annotations

import json
import unittest

import requests

from pdf2zh.translator import (
    GOOGLE_API_ENDPOINT,
    GOOGLE_MOBILE_ENDPOINT,
    DeepLKeyError,
    DeepLQuotaError,
    DeepLTranslator,
    GoogleTranslator,
    RateLimitedError,
    ServiceUnavailableError,
    result_lines,
)
from tests.test_service_outage import blocked, google_answer, translator_answering


def api_answer(translated: str) -> requests.Response:
    """What the API endpoint returns: the text split into sentence pieces."""
    pieces = [[part, "source", None, None] for part in translated.split("|")]
    return google_answer(200, GOOGLE_API_ENDPOINT, json.dumps([pieces, None, "en"]))


def line_by_line(text: str) -> requests.Response:
    translated = "\n".join(f"it:{line}" if line.strip() else line for line in text.split("\n"))
    return api_answer(translated)


class DeepLAnswer:
    """A fake DeepL session: records each request and answers from `reply`."""

    def __init__(self, reply) -> None:
        self.reply = reply
        self.requests: list[dict] = []

    def post(self, endpoint, json, headers, timeout):
        self.requests.append({"endpoint": endpoint, "json": json, "headers": headers})
        return self.reply(json)


def deepl_response(status: int, body: object) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode("utf-8")
    response.encoding = "utf-8"
    return response


def deepl_translating(body: dict) -> requests.Response:
    return deepl_response(200, {"translations": [{"text": f"it:{text}"} for text in body["text"]]})


def deepl(reply, key: str = "secret:fx") -> tuple[DeepLTranslator, DeepLAnswer]:
    translator = DeepLTranslator("en", "it", ignore_cache=True, envs={"deepl_key": key})
    session = DeepLAnswer(reply)
    translator.session = session
    translator.sleep = lambda _seconds: None
    return translator, session


class GoogleApiEndpointTests(unittest.TestCase):
    def test_the_api_answer_is_read_with_its_line_breaks(self):
        page = json.dumps([[["Uno.\n\n", "One.\n\n"], ["Due.", "Two."]], None, "en"])
        self.assertEqual(result_lines(page), ["Uno.", "Due."])

    def test_requests_go_to_the_api_endpoint(self):
        translator = GoogleTranslator("en", "it", ignore_cache=True)
        self.assertEqual(translator.endpoint, GOOGLE_API_ENDPOINT)
        params = translator._params("Hello")
        self.assertEqual(params["client"], "gtx")
        self.assertEqual((params["sl"], params["tl"], params["q"]), ("en", "it", "Hello"))

    def test_the_browser_still_opens_the_page_a_person_can_verify(self):
        translator = GoogleTranslator("en", "it", ignore_cache=True, envs={"google_browser": True})
        self.assertEqual(translator.endpoint, GOOGLE_MOBILE_ENDPOINT)
        self.assertEqual(set(translator._params("Hello")), {"q", "sl", "tl"})

    def test_a_page_travels_as_one_api_request(self):
        translator, _clock, google = translator_answering(line_by_line)
        segments = [f"Sentence {number}." for number in range(20)]
        self.assertEqual(translator.translate_many(segments), [f"it:{text}" for text in segments])
        self.assertEqual(len(google.sent), 1)


class RefusalRetryTests(unittest.TestCase):
    def test_a_refusal_is_waited_out_before_it_is_believed(self):
        refusals = [blocked(), blocked()]
        translator, clock, google = translator_answering(
            # Not "or": a 429 response is falsy.
            lambda text: refusals.pop() if refusals else line_by_line(text)
        )
        translator.block_retry_waits = (30.0, 90.0)
        self.assertEqual(translator.translate_many(["One.", "Two."]), ["it:One.", "it:Two."])
        self.assertEqual(len(google.sent), 3)
        self.assertIn(30.0, clock.sleeps)
        self.assertIn(90.0, clock.sleeps)

    def test_a_refusal_that_lasts_stops_the_document(self):
        translator, _clock, google = translator_answering(lambda _text: blocked())
        translator.block_retry_waits = (30.0, 90.0)
        answers = translator.translate_many(["One.", "Two."])
        self.assertTrue(all(isinstance(answer, RateLimitedError) for answer in answers))
        self.assertEqual(len(google.sent), 3)
        # The block is remembered: the next page sends nothing.
        translator.translate_many(["Three."])
        self.assertEqual(len(google.sent), 3)


class UnexplainedFailureTests(unittest.TestCase):
    """A run once left all 288 pages in English, and said nothing, this way."""

    def test_a_failure_nothing_explains_stops_the_document(self):
        def broken(_text):
            raise RuntimeError("answer nobody expected")

        translator, _clock, google = translator_answering(broken)
        for page in range(5):
            answers = translator.translate_many([f"Page {page}, one.", f"Page {page}, two."])
        self.assertTrue(all(isinstance(answer, ServiceUnavailableError) for answer in answers))
        sent = len(google.sent)
        translator.translate_many(["One more page."])
        self.assertEqual(len(google.sent), sent)
        self.assertEqual(translator.stats["error_RuntimeError"], GoogleTranslator.UNEXPLAINED_FAILURES_ALLOWED)

    def test_a_success_in_between_resets_the_count(self):
        state = {"calls": 0}

        def every_other(text):
            state["calls"] += 1
            if state["calls"] % 4 == 0:
                return line_by_line(text)
            raise RuntimeError("glitch")

        translator, _clock, _google = translator_answering(every_other)
        translator.translate_many(["One."])
        translator.translate_many(["Two."])
        self.assertIsNone(translator._terminal_error)

    def test_a_redirect_loop_is_an_outage_not_a_glitch(self):
        def loop(_text):
            raise requests.TooManyRedirects("Exceeded 30 redirects.")

        translator, _clock, google = translator_answering(loop)
        answers = translator.translate_many(["One.", "Two."])
        self.assertTrue(all(isinstance(answer, ServiceUnavailableError) for answer in answers))
        self.assertGreater(translator.stats["error_TooManyRedirects"], 0)

    def test_answers_are_counted_by_status(self):
        translator, _clock, _google = translator_answering(line_by_line)
        translator.translate_many(["One."])
        self.assertEqual(translator.stats["http_200"], 1)

    def test_unexplained_failures_go_to_deepl(self):
        def broken(_text):
            raise RuntimeError("answer nobody expected")

        translator, _clock, _google = translator_answering(broken)
        translator.fallback, _session = deepl(deepl_translating)
        self.assertEqual(translator.translate_many(["One.", "Two."]), ["it:One.", "it:Two."])


class FallbackTests(unittest.TestCase):
    def test_what_google_refuses_goes_to_deepl(self):
        translator, _clock, google = translator_answering(lambda _text: blocked())
        translator.fallback, session = deepl(deepl_translating)
        stages: list[str] = []
        translator.on_status = lambda stage, _done, _total: stages.append(stage)
        self.assertEqual(translator.translate_many(["One.", "Two."]), ["it:One.", "it:Two."])
        self.assertEqual(translator.translate_many(["Three."]), ["it:Three."])
        self.assertEqual(len(google.sent), 1)
        self.assertEqual(len(session.requests), 2)
        self.assertIn("fallback", stages)

    def test_a_key_in_the_settings_turns_the_fallback_on(self):
        self.assertIsNone(GoogleTranslator("en", "it", ignore_cache=True).fallback)
        translator = GoogleTranslator("en", "it", ignore_cache=True, envs={"deepl_key": "k:fx"})
        self.assertIsInstance(translator.fallback, DeepLTranslator)

    def test_translated_segments_never_go_to_deepl(self):
        translator, _clock, _google = translator_answering(line_by_line)
        translator.fallback, session = deepl(deepl_translating)
        translator.translate_many(["One."])
        self.assertEqual(session.requests, [])


class DeepLTests(unittest.TestCase):
    def test_free_keys_use_the_free_host(self):
        free, _ = deepl(deepl_translating, key="abc:fx")
        paid, _ = deepl(deepl_translating, key="abc")
        self.assertIn("api-free.deepl.com", free.endpoint)
        self.assertIn("api.deepl.com", paid.endpoint)
        self.assertNotIn("api-free", paid.endpoint)

    def test_markers_travel_as_tags_and_prose_is_escaped(self):
        translator, session = deepl(deepl_translating)
        answer = translator.translate_many(["If a < b then <b0></b0> & <s1>bold</s1>"])
        sent = session.requests[0]["json"]
        self.assertEqual(sent["text"], ["If a &lt; b then <b0></b0> &amp; <s1>bold</s1>"])
        self.assertEqual(sent["tag_handling"], "xml")
        self.assertEqual(sent["target_lang"], "IT")
        self.assertEqual(answer, ["it:If a < b then <b0></b0> & <s1>bold</s1>"])

    def test_an_empty_marker_written_as_one_tag_is_restored(self):
        translator, _ = deepl(
            lambda body: deepl_response(200, {"translations": [{"text": "Energia <b0/> conservata."}]})
        )
        self.assertEqual(translator.translate_many(["Energy <b0></b0> is conserved."]),
                         ["Energia <b0></b0> conservata."])

    def test_a_lost_marker_is_an_error_not_a_translation(self):
        translator, _ = deepl(
            lambda body: deepl_response(200, {"translations": [{"text": "Energia conservata."}]})
        )
        self.assertIsInstance(translator.translate_many(["Energy <b0></b0> is conserved."])[0], Exception)

    def test_a_refused_key_and_a_spent_quota_say_so(self):
        for status, error in ((403, DeepLKeyError), (456, DeepLQuotaError)):
            with self.subTest(status=status):
                translator, session = deepl(lambda body, s=status: deepl_response(s, {"message": "no"}))
                answers = translator.translate_many(["One.", "Two."])
                self.assertTrue(all(isinstance(answer, error) for answer in answers))
                translator.translate_many(["Three."])
                self.assertEqual(len(session.requests), 1)

    def test_a_busy_service_is_retried_then_reported(self):
        translator, session = deepl(lambda body: deepl_response(429, {}))
        answer = translator.translate_many(["One."])[0]
        self.assertIsInstance(answer, ServiceUnavailableError)
        self.assertEqual(len(session.requests), len(DeepLTranslator.RETRY_WAITS) + 1)

    def test_english_targets_name_a_variant(self):
        translator = DeepLTranslator("it", "en", ignore_cache=True, envs={"deepl_key": "k:fx"})
        session = DeepLAnswer(deepl_translating)
        translator.session = session
        translator.translate_many(["Ciao."])
        self.assertEqual(session.requests[0]["json"]["target_lang"], "EN-US")
        self.assertEqual(session.requests[0]["json"]["source_lang"], "IT")


class DeepLFailureTests(unittest.TestCase):
    def test_deepl_failures_have_their_own_codes(self):
        from app.errors import describe_failure

        self.assertEqual(describe_failure(DeepLKeyError("refused")).code, "E-DEEPL-01")
        self.assertEqual(describe_failure(DeepLQuotaError("spent")).code, "E-DEEPL-02")


if __name__ == "__main__":
    unittest.main()
