"""Diagnostic tools, with measured test delay around the existing gateway."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import math
import os
import random
import time

from telemetry import envelope
from telemetry.gateway import TelemetryGateway
from agent.limits import runtime_limits
from telemetry.schemas import TOOL_SCHEMAS, schema_list, validate_arguments
from telemetry.validate import ValidationError, require_host


TOOLS = []
for original in schema_list():
    schema = deepcopy(original)
    parameters = schema["parameters"]
    parameters["required"] = list(parameters["properties"])
    for property_schema in parameters["properties"].values():
        property_schema.pop("default", None)
    TOOLS.append({"type": "function", "strict": True, **schema})

gateway = TelemetryGateway()

def _execute(name: str, arguments: str) -> dict:
    started = time.perf_counter()
    parsed = None
    delay = execution = 0.0
    invalid = False
    try:
        parsed = json.loads(arguments)
        validate_arguments(name, parsed)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        invalid = True
        result = envelope.error(name, getattr(exc, "code", "INVALID_ARGUMENT"), str(exc))
    else:
        try:
            limits = runtime_limits()
            minimum = float(limits["tool_delay_min_seconds"])
            maximum = float(limits["tool_delay_max_seconds"])
            if not (math.isfinite(minimum) and math.isfinite(maximum) and 0 <= minimum <= maximum):
                raise ValueError("tool delay must be finite and 0 <= minimum <= maximum")
            delay = random.uniform(minimum, maximum)
            time.sleep(delay)
            execution_started = time.perf_counter()
            try:
                result = getattr(gateway, name)(**parsed)
            finally:
                execution = time.perf_counter() - execution_started
        except NotImplementedError as exc:
            result = envelope.error(name, "NOT_IMPLEMENTED", str(exc))
        except Exception as exc:
            result = envelope.error(name, "TOOL_ERROR", str(exc))
    return {
        **result,
        "name": name,
        "arguments": parsed,
        "invalid": invalid,
        "delay_seconds": delay,
        "execution_seconds": execution,
        "duration_seconds": time.perf_counter() - started,
    }


async def execute_tool(name: str, arguments: str) -> dict:
    """Keep sleep and diagnostics off the event loop.

    Cancelling cannot kill an in-flight thread. Wait for its bounded diagnostic
    and gateway cleanup before propagating cancellation, so the next turn cannot
    overlap it (particularly important for iperf's shared server port).
    """
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="network-tool")
    worker = executor.submit(_execute, name, arguments)
    cancelled = False
    try:
        while not worker.done():
            try:
                await asyncio.sleep(.05)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError
        return worker.result()
    finally:
        executor.shutdown(wait=True)
