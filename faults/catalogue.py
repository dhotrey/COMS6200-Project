"""Frozen automated fault catalogue identity.

Fault Catalogue v1 defines F1–F5 for paired LLM vs scripted-baseline experiments.
Any semantic change to targets, selectors, workloads, or reset behaviour must
increment this version (or be explicitly documented as a new catalogue).
"""

FAULT_CATALOGUE_VERSION = "v1"
FAULT_CATALOGUE_STATUS = "frozen"  # set after live verification; candidates may still edit
