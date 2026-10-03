"""Keel — 契约驱动的通用 B 端系统穿行测试框架。

L1 契约(contracts/) → L2 通道(client/mcp/ui/schemathesis)
→ L3 原语(primitives/baseline) → L4 旅程(用例编排) → L5 报告(report)。
"""
__version__ = "0.1.0"

from .client import ApiError, ApiResult, Client, RoleMatrix, demo_login
from .primitives import CheckResult, Saga, TestRun
from .baseline import Baseline, Drift, guarded
from .report import Finding, Report, Severity
from .schemathesis import FuzzSummary, build_mini_spec, run_fuzz

__all__ = [
    "ApiError", "ApiResult", "Client", "RoleMatrix", "demo_login",
    "CheckResult", "Saga", "TestRun",
    "Baseline", "Drift", "guarded",
    "Finding", "Report", "Severity",
    "FuzzSummary", "build_mini_spec", "run_fuzz",
]
