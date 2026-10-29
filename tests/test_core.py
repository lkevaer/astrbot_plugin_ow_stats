"""Verify durable sender isolation, input handling and actual HTTP payloads."""

import tempfile
import unittest
from pathlib import Path

import httpx

from ..core import EMPTY_QUERY_NOTICE, Bindings, OWClient, has_rated_players, parse_tags, team_tags

TASK = "a" * 32


class CoreTests(unittest.TestCase):
    def test_bindings_survive_restart_and_unbind_only_the_sender(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bindings.sqlite3"
            bindings = Bindings(path)
            bindings.set("qq-a", "sender-a", "甲#1234")
            bindings.set("qq-a", "sender-b", "乙#1234")
            bindings.set("qq-b", "sender-a", "丙#1234")
            restarted = Bindings(path)
            self.assertEqual(restarted.get("qq-a", "sender-a"), "甲#1234")
            restarted.set("qq-a", "sender-a", "丁#1234")
            self.assertEqual(restarted.get("qq-a", "sender-a"), "丁#1234")
            restarted.remove("qq-a", "sender-a")
            self.assertIsNone(restarted.get("qq-a", "sender-a"))
            self.assertEqual(restarted.get("qq-a", "sender-b"), "乙#1234")
            self.assertEqual(restarted.get("qq-b", "sender-a"), "丙#1234")

    def test_unicode_delimiters_duplicates_and_short_suffix_match_website(self):
        self.assertEqual(
            parse_tags("Player＃123，player#123\n队友#12345"),
            ["Player#123", "队友#12345"],
        )
        self.assertEqual(
            len(team_tags([f"队友{i}#1234" for i in range(4)], "本人#1234")), 5
        )
        self.assertEqual(team_tags(["本人#1234"], "本人#1234"), ["本人#1234"])

    def test_invalid_or_excess_targets_are_rejected_without_dropping_players(self):
        for value in ["甲#1234 乙", "甲#12", "甲#1234 https://invalid"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_tags(value)
        self.assertEqual(len(team_tags([f"队友{i}#1234" for i in range(10)], None)), 10)
        with self.assertRaises(ValueError):
            team_tags([f"队友{i}#1234" for i in range(10)], "本人#1234")
        with self.assertRaises(ValueError):
            team_tags([], None)


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_null_or_empty_successful_responses_have_local_deployment_advice(self):
        for payload in (None, [], {}, {"success": True, "data": None}, {"success": True, "data": {"status": "done", "result": None}}):
            client = OWClient("https://ow.test", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
            try:
                with self.assertRaisesRegex(ValueError, EMPTY_QUERY_NOTICE):
                    await client.rating("competitive", ["甲#1234"], 0)
            finally:
                await client.close()

    def test_zero_is_a_valid_score_but_missing_or_nonfinite_values_are_not(self):
        for value in (None, True, float("nan"), float("inf"), "80"):
            self.assertFalse(has_rated_players({"players": [{"score": value}]}))
        self.assertTrue(has_rated_players({"players": [{"score": 0}]}))

    async def test_queue_polling_keeps_one_task_and_returns_unmodified_result(self):
        calls = []
        result = {"players": [], "scoring_version": "from-existing-web-service"}

        def respond(request):
            calls.append(request)
            self.assertEqual(request.headers["X-API-Key"], "test-key")
            if request.method == "POST":
                self.assertEqual(request.url.path, "/api/batch-rating/competitive")
                return httpx.Response(
                    202,
                    json={
                        "success": True,
                        "data": {"status": "queued", "task_id": TASK},
                    },
                )
            self.assertEqual(request.url.path, "/api/batch-rating/tasks/" + TASK)
            if len(calls) == 2:
                return httpx.Response(
                    200, json={"success": True, "data": {"status": "running"}}
                )
            return httpx.Response(
                200,
                json={"success": True, "data": {"status": "done", "result": result}},
            )

        client = OWClient(
            "https://ow.test", "test-key", transport=httpx.MockTransport(respond)
        )
        try:
            self.assertEqual(
                await client.rating("competitive", ["甲#1234"], 0),
                {**result, "task_id": TASK},
            )
            self.assertEqual(len(calls), 3)
        finally:
            await client.close()

    async def test_failed_or_malformed_jobs_never_return_fake_results(self):
        for payload in [
            {"status": "error", "error": "战绩暂未公开"},
            {"status": "done", "result": None},
            {"status": "running", "task_id": "../../other"},
        ]:
            with self.subTest(payload=payload):
                client = OWClient(
                    "https://ow.test",
                    transport=httpx.MockTransport(
                        lambda _: httpx.Response(
                            200, json={"success": True, "data": payload}
                        )
                    ),
                )
                try:
                    with self.assertRaises(ValueError):
                        await client.rating("competitive", ["甲#1234"], 0)
                finally:
                    await client.close()

    async def test_access_errors_have_actionable_messages(self):
        client = OWClient(
            "https://ow.test",
            transport=httpx.MockTransport(lambda _: httpx.Response(401)),
        )
        try:
            with self.assertRaisesRegex(ValueError, "访问码"):
                await client.request("POST", "/api/batch-rating/competitive")
        finally:
            await client.close()
