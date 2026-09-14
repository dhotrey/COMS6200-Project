"""Seven diagnostic tools, with measured test delay around the existing gateway."""

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
from telemetry.schemas import TOOL_SCHEMAS, validate_arguments
from telemetry.validate import ValidationError, require_host


TOOLS = []
for original in TOOL_SCHEMAS.values():
    schema = deepcopy(original)
    parameters = schema["parameters"]
    parameters["required"] = list(parameters["properties"])
    for property_schema in parameters["properties"].values():
        property_schema.pop("default", None)
    TOOLS.append({"type": "function", "strict": True, **schema})

TOOLS.append({
    "type": "function",
    "name": "nmap",
    "description": "Placeholder for a port probe. Not implemented; returns an explicit error.",
    "strict": True,
    "parameters": {
        "type": "object",
        "properties": {
            "src": deepcopy(TOOL_SCHEMAS["ping"]["parameters"]["properties"]["src"]),
            "dst": deepcopy(TOOL_SCHEMAS["ping"]["parameters"]["properties"]["dst"]),
            "proto": {"type": "string", "enum": ["tcp", "udp"]},
            "port": {"type": "integer", "minimum": 1, "maximum": 65535},
        },
        "required": ["src", "dst", "proto", "port"],
        "additionalProperties": False,
    },
})

gateway = TelemetryGateway()


def nmap(src: str, dst: str, proto: str, port: int) -> dict:
    """Reserved until the network probe implementation is chosen."""
    raise NotImplementedError("nmap is not implemented")


def _validate(name: str, arguments: dict) -> dict:
    if not isinstance(arguments, dict):
        raise ValidationError("INVALID_ARGUMENT", "tool arguments must be an object")
    if name != "nmap":
        return validate_arguments(name, arguments)
    if set(arguments) != {"src", "dst", "proto", "port"}:
        raise ValidationError("INVALID_ARGUMENT", "nmap requires exactly src, dst, proto and port")
    require_host(arguments["src"])
    require_host(arguments["dst"])
    if arguments["proto"] not in ("tcp", "udp"):
        raise ValidationError("INVALID_ARGUMENT", "proto must be tcp or udp")
    port = arguments["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValidationError("INVALID_ARGUMENT", "port must be an integer from 1 to 65535")
    return arguments


def _execute(name: str, arguments: str) -> dict:
    started = time.perf_counter()
    parsed = None
    delay = execution = 0.0
    invalid = False
    try:
        parsed = json.loads(arguments)
        _validate(name, parsed)
    except (json.JSONDecodeError, TypeError, ValidationError) as exc:
        invalid = True
        result = envelope.error(name, getattr(exc, "code", "INVALID_ARGUMENT"), str(exc))
    else:
        try:
            minimum = float(os.getenv("TOOL_DELAY_MIN_SECONDS", "1"))
            maximum = float(os.getenv("TOOL_DELAY_MAX_SECONDS", "10"))
            if not (math.isfinite(minimum) and math.isfinite(maximum) and 0 <= minimum <= maximum):
                raise ValueError("tool delay must be finite and 0 <= minimum <= maximum")
            delay = random.uniform(minimum, maximum)
            time.sleep(delay)
            execution_started = time.perf_counter()
            try:
                result = nmap(**parsed) if name == "nmap" else getattr(gateway, name)(**parsed)
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
