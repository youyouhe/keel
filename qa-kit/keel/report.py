"""keel.report — 报告层(发现→证据→建议 · 三段式)

提炼自起源项目全部轮次报告的固定格式。
HTML 汇报模板脱胎于实测工作汇报页(统计卡/矩阵/时间线/缺陷清单)。
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .primitives import Saga, TestRun


class Severity(str, Enum):
    P0 = "P0 阻塞"
    P1 = "P1 严重"
    P2 = "P2 一般"
    P3 = "P3 轻微"
    OBS = "观察"


@dataclass
class Finding:
    """一条缺陷/观察: 发现 → 证据 → 建议。"""
    id: str
    severity: Severity
    title: str
    evidence: str
    suggestion: str = ""
    saga: Saga | None = None

    def render_md(self) -> str:
        lines = [f"**{self.id}（{self.severity.value}）{self.title}**", "",
                 f"- **发现**：{self.title}",
                 f"- **证据**：{self.evidence}"]
        if self.suggestion:
            lines.append(f"- **建议**：{self.suggestion}")
        if self.saga:
            lines.append("")
            lines.append(self.saga.render())
        return "\n".join(lines)


@dataclass
class Report:
    """一轮测试报告: 结论 + 断言汇总 + findings + saga。"""
    title: str
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    conclusion: str = ""
    runs: list[TestRun] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def stats(self) -> dict[str, int]:
        p = sum(r.passed for r in self.runs)
        n = sum(len(r.checks) for r in self.runs)
        by_sev: dict[str, int] = {}
        for f in self.findings:
            by_sev[f.severity.value] = by_sev.get(f.severity.value, 0) + 1
        return {"passed": p, "total": n, "failed": n - p, **by_sev}

    def render_md(self) -> str:
        s = self.stats()
        lines = [f"# {self.title}", "", f"> {self.date} · {s['passed']}/{s['total']} 断言通过",
                 "", f"## 结论", "", self.conclusion, "", "## 断言汇总", ""]
        for r in self.runs:
            lines.append(f"- {r.summary()}")
        if self.findings:
            lines += ["", "## 缺陷与观察", ""]
            lines += [f.render_md() for f in self.findings]
        return "\n".join(lines)

    def render_html(self) -> str:
        s = self.stats()
        esc = html.escape
        cards = "".join(
            f'<div class="card"><div class="n">{v}</div><div class="t">{esc(k)}</div></div>'
            for k, v in s.items())
        rows = "".join(
            f"<tr><td>{esc(r.name or '-')}</td><td>{r.passed}/{len(r.checks)}</td>"
            f"<td>{esc(', '.join(c.name for c in r.failed) or '全绿')}</td></tr>"
            for r in self.runs)
        finds = "".join(
            f"<tr><td><code>{esc(f.id)}</code></td><td>{esc(f.severity.value)}</td>"
            f"<td>{esc(f.title)}</td><td>{esc(f.suggestion or '-')}</td></tr>"
            for f in self.findings) or "<tr><td colspan=4>无</td></tr>"
        return f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>{esc(self.title)}</title><style>
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:0;background:#f7f8fa;color:#1a2332}}
header{{background:linear-gradient(135deg,#1d3a7a,#3d7be8);color:#fff;padding:34px 24px}}
h1{{margin:0 0 4px;font-size:24px}} .sub{{opacity:.9;font-size:13px}}
.wrap{{max-width:1000px;margin:0 auto;padding:20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px}}
.n{{font-size:26px;font-weight:700;color:#2b5fd9}} .t{{font-size:12px;color:#4a5568}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;font-size:13px}}
th{{background:#f0f4fa;text-align:left;padding:8px 12px}} td{{padding:8px 12px;border-top:1px solid #eef1f5}}
h2{{font-size:17px;margin:26px 0 10px;border-left:4px solid #2b5fd9;padding-left:10px}}
footer{{margin-top:30px;color:#4a5568;font-size:12px}}</style></head><body>
<header><h1>{esc(self.title)}</h1><div class="sub">{esc(self.date)} · Keel 报告</div></header>
<div class="wrap"><h2>结论</h2><p>{esc(self.conclusion)}</p>
<h2>统计</h2><div class="grid">{cards}</div>
<h2>断言汇总</h2><table><tr><th>用例组</th><th>通过</th><th>失败项</th></tr>{rows}</table>
<h2>缺陷与观察</h2><table><tr><th>编号</th><th>级别</th><th>发现</th><th>建议</th></tr>{finds}</table>
<footer>Keel · 契约驱动的通用 B 端系统穿行测试框架</footer></div></body></html>"""
