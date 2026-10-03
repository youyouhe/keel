"""keel.schemathesis — REST 通道 fuzz 封装

提炼自一期实战: 手写 mini OpenAPI spec → st run --checks all,
8 秒 42 case 发现 3 类人工从未覆盖的参数校验缺陷。
写端点不进 spec(fuzz 写保护); Windows GBK 终端需 PYTHONIOENCODING=utf-8。
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

MINI_SPEC_TEMPLATE = """openapi: 3.0.3
info:
  title: {title} (Keel 逆向 mini spec)
  version: 0.1.0-keel
servers:
  - url: {base_url}
paths:
{paths}
"""

GET_PATH_TEMPLATE = """  {path}:
    get:
      operationId: {op_id}
      parameters:
{params}
      responses:
        "200": {{ description: OK, content: {{ application/json: {{ schema: {{ type: object }} }} }} }}
"""


@dataclass
class FuzzSummary:
    generated: int = 0
    failures: int = 0
    failure_kinds: list[str] = field(default_factory=list)
    seed: str = ""
    raw_tail: str = ""

    def __str__(self) -> str:
        return (f"fuzz: {self.generated} case / {self.failures} failures"
                + (f" · {self.failure_kinds}" if self.failure_kinds else " · 全绿"))


def build_mini_spec(base_url: str, title: str,
                    read_paths: dict[str, list[tuple[str, dict[str, str]]]]) -> str:
    """生成只读 mini spec。read_paths = {path: [(参数名, schema_yml), ...]}
    schema_yml 示例: '{ type: string }' / '{ type: string, enum: [A, B] }'
    写端点有意不进 spec(fuzz 写保护)。"""
    paths = []
    for path, params in read_paths.items():
        op = path.strip("/").replace("/", "_").replace("-", "_")
        plines = [f"        - {{ name: {n}, in: query, required: true, schema: {s} }}"
                  for n, s in params]
        paths.append(GET_PATH_TEMPLATE.format(path=path, op_id=op, params="\n".join(plines)))
    return MINI_SPEC_TEMPLATE.format(title=title, base_url=base_url, paths="".join(paths))


def run_fuzz(spec_path: str | Path, base_url: str, token: str | None = None,
             max_examples: int = 30, st_bin: str = "st",
             extra_args: list[str] | None = None) -> FuzzSummary:
    """执行 schemathesis run 并解析摘要。

    前置: pip install schemathesis (CLI=st)。
    返回 FuzzSummary; failures>0 时 raw_tail 含 reproduce 命令。
    """
    cmd = [st_bin, "run", str(spec_path), "--url", base_url,
           "--checks", "all", "--max-examples", str(max_examples)]
    if token:
        cmd += ["-H", f"Authorization: Bearer {token}"]
    if extra_args:
        cmd += extra_args
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=1800)
    out = proc.stdout or ""
    s = FuzzSummary(raw_tail=out[-3000:])
    m = re.search(r"(\d+) generated,\s*(?:\d+ found )?(\d+) (?:unique )?failures?", out)
    if m:
        s.generated, s.failures = int(m.group(1)), int(m.group(2))
    s.failure_kinds = re.findall(r"❌ ([^:\n]+)", out)
    if seed := re.search(r"Seed: (\d+)", out):
        s.seed = seed.group(1)
    return s
