import asyncio
import json
import threading
import unittest
from unittest.mock import patch

from agent import tools
from telemetry import envelope
from telemetry.schemas import TOOL_SCHEMAS


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_validation_never_reaches_gateway_or_sleep(self):
        with patch.object(tools, "gateway") as gateway, patch.object(tools.time, "sleep") as sleep:
            for name, args in [
                ("unknown", "{}"), ("ping", "{"), ("ping", "[]"),
                ("ping", '{"src":"h1","dst":"h2","count":true}'),
                ("get_topology", '{"extra":1}'),
                ("nmap", '{"src":"h1","dst":"h2","proto":"tcp","port":0}'),
            ]:
                result = await tools.execute_tool(name, args)
                self.assertTrue(result["invalid"])
                self.assertFalse(result["ok"])
                self.assertEqual(result["delay_seconds"], 0)
            self.assertFalse(gateway.mock_calls)
            sleep.assert_not_called()

    async def test_gateway_result_and_timing_are_preserved(self):
        with patch.object(tools.gateway, "get_topology", return_value=envelope.ok("get_topology", {"switches": []})) as call, patch.dict("os.environ", {"TOOL_DELAY_MIN_SECONDS": "0", "TOOL_DELAY_MAX_SECONDS": "0"}):
            result = await tools.execute_tool("get_topology", "{}")
        call.assert_called_once_with()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"switches": []})
        self.assertFalse(result["invalid"])
        self.assertGreaterEqual(result["duration_seconds"], result["execution_seconds"])

    async def test_nmap_is_explicitly_unimplemented(self):
        hosts = TOOL_SCHEMAS["ping"]["parameters"]["properties"]["src"]["enum"]
        with patch.dict("os.environ", {"TOOL_DELAY_MIN_SECONDS": "0", "TOOL_DELAY_MAX_SECONDS": "0"}):
            result = await tools.execute_tool("nmap", json.dumps({"src": hosts[0], "dst": hosts[1], "proto": "tcp", "port": 80}))
        self.assertEqual(result["error"]["code"], "NOT_IMPLEMENTED")
        self.assertFalse(result["invalid"])

    async def test_blocking_work_runs_outside_event_loop(self):
        loop_thread = threading.get_ident()
        worker_threads = []
        def sleep(seconds):
            worker_threads.append(threading.get_ident())
        with patch.object(tools.time, "sleep", side_effect=sleep), patch.object(tools.gateway, "get_topology", return_value=envelope.ok("get_topology", {})), patch.object(tools.random, "uniform", return_value=4.5):
            result = await tools.execute_tool("get_topology", "{}")
        self.assertEqual(result["delay_seconds"], 4.5)
        self.assertNotEqual(worker_threads[0], loop_thread)

    def test_seven_strict_schemas_do_not_mutate_originals(self):
        self.assertEqual(len(tools.TOOLS), 7)
        for schema in tools.TOOLS:
            self.assertTrue(schema["strict"])
            params = schema["parameters"]
            self.assertEqual(set(params["required"]), set(params["properties"]))
            self.assertFalse(params["additionalProperties"])
        self.assertNotIn("count", TOOL_SCHEMAS["ping"]["parameters"]["required"])

    async def test_cancellation_waits_for_gateway_cleanup(self):
        started, finish, cleaned_up = threading.Event(), threading.Event(), threading.Event()

        def diagnostic():
            started.set()
            finish.wait(timeout=2)
            cleaned_up.set()
            return envelope.ok("get_topology", {})

        with patch.object(tools.gateway, "get_topology", side_effect=diagnostic), patch.dict("os.environ", {"TOOL_DELAY_MIN_SECONDS": "0", "TOOL_DELAY_MAX_SECONDS": "0"}):
            task = asyncio.create_task(tools.execute_tool("get_topology", "{}"))
            for _ in range(200):
                if started.is_set():
                    break
                await asyncio.sleep(.01)
            self.assertTrue(started.is_set())
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cleaned_up.is_set())


if __name__ == "__main__":
    unittest.main()
