"""Demo orchestrator — runs an end-to-end pilot demo on a single processo.

Public API:
    DemoRequest, DemoResult, SourceMode, run_demo
"""

from __future__ import annotations

from juris.demo.orchestrator import DemoRequest, DemoResult, SourceMode, run_demo

__all__ = ["DemoRequest", "DemoResult", "SourceMode", "run_demo"]
