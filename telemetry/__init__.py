"""Bounded structured telemetry gateway for COMS6200.

This package is the M4 agent-facing diagnostic interface. It does not
implement fault injection, a scripted troubleshooter, or an LLM agent.
"""

from telemetry.gateway import TelemetryGateway
from telemetry.schemas import CANONICAL_TOOL_NAMES, TOOL_SCHEMAS, schema_list, validate_arguments

__all__ = ["CANONICAL_TOOL_NAMES", "TOOL_SCHEMAS", "TelemetryGateway", "schema_list", "validate_arguments"]
