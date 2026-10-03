"""keel.cli — 测试生命周期命令(manager agent / 人的统一入口)

  keel new <A> [--env-dev URL] [--issue-repo owner/repo] [--root DIR]
  keel status <A> [--root DIR]
  keel contract verify <A> --context ctx.json [--root DIR]
  keel journey run <A> [--section J3] [--root DIR]
  keel report render <A> [--input report.json] [-o out.html]
  keel issue sync <A> --repo owner/repo [--dry-run]
  keel render-report report.json -o report.html   (v0.2 兼容保留)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from .primitives import TestRun
from .report import Finding, Report, Severity

DEFAULT_ROOT = "projects"


def _proj(args) -> "object":
    from .project import KeelProject
    p = Path(args.root) / args.project
    if not p.exists():
        sys.exit(f"项目不存在: {p} (先 keel new {args.project})")
    return KeelProject(p)


def _env_api(meta: dict, which: str = "dev"):
    from .client import Client
    url = (meta.get("env") or {}).get(which)
    if not url:
        sys.exit(f"未登记 {which} 环境地址 (project.json env.{which})")
    return Client(url)


def cmd_new(a):
    from .project import KeelProject
    p = KeelProject.create(a.root, a.project, env_dev=a.env_dev, issue_repo=a.issue_repo)
    print(f"项目已创建: {p.root}")
    print(f"  下一步: 1) contracts/invariants.json 补契约(AI 主笔+签收)"
          f" 2) tests/journeys.py 注册旅程段 3) keel journey run {a.project}")


def cmd_status(a):
    p = _proj(a)
    meta, st = p.meta, p.state
    print(f"项目 {meta['name']} · 创建于 {meta['createdAt']}")
    print(f"环境: dev={meta['env'].get('dev') or '-'} · test={meta['env'].get('test') or '-'}")
    print(f"issue 仓: {meta.get('issueRepo') or '-'}")
    lr = st.get("lastRun")
    if lr:
        flag = "✅" if lr["ok"] else "❌"
        print(f"上轮: {flag} {lr['time']} {lr['journey']} "
              f"{lr['passed']}/{lr['total']}" + (f" ·中止@{lr['abortedAt']}" if lr.get("abortedAt") else ""))
    else:
        print("上轮: 未运行")
    runs = st.get("runs", [])
    ok_n = sum(1 for r in runs if r["ok"])
    print(f"历史: {ok_n}/{len(runs)} 轮绿" + (f" · 基线指纹: {st['baseline']}" if st.get("baseline") else " · 基线: 未采集"))


def cmd_contract_verify(a):
    from .invariants import InvariantSet
    p = _proj(a)
    inv = InvariantSet.load(p.root / "contracts" / "invariants.json")
    ctx = json.loads(Path(a.context).read_text(encoding="utf-8"))
    run = inv.verify(ctx, only=a.scope)
    print(f"契约状态: {inv.stats()}")
    print(run.summary())
    sys.exit(0 if not run.failed else 1)


def cmd_journey_run(a):
    p = _proj(a)
    mod = p.load_journey()
    api = _env_api(p.meta, a.env)
    journey = mod.build_journey(api)
    if a.section:
        journey._sections = [(s, st) for s, st in journey._sections if a.section in s]
        if not journey._sections:
            sys.exit(f"无匹配段: {a.section}")
    result = journey.run()
    # 汇总为报告落盘
    report = Report(f"{p.meta['name']} · 旅程回归", conclusion=(
        "全绿" if result.ok else f"存在失败/中止@{result.aborted_at}"), runs=result.runs,
        findings=[Finding(f"F-{c.name[:40]}", Severity.P2, c.name, str(c.evidence), "")
                  for r in result.runs for c in r.failed])
    ts = time.strftime("%Y%m%d-%H%M%S")
    jp = p.root / "reports" / f"report-{ts}.json"
    report.to_json(str(jp))
    hp = jp.with_suffix(".html")
    hp.write_text(report.render_html(), encoding="utf-8")
    total = sum(len(r.checks) for r in result.runs)
    passed = sum(r.passed for r in result.runs)
    p.record_run(journey.name, result.ok, passed, total, result.aborted_at, str(jp))
    print(result.summary())
    print(f"报告: {jp}")
    sys.exit(0 if result.ok else 1)


def cmd_report_render(a):
    from .report import Report as R
    if a.input:
        data = json.loads(Path(a.input).read_text(encoding="utf-8"))
    else:
        p = _proj(a)
        latest = p.latest_report_json()
        if not latest:
            sys.exit("无 report-*.json; 先 keel journey run")
        data = json.loads(latest.read_text(encoding="utf-8"))
    out = a.output or "report.html"
    Path(out).write_text(R.from_dict(data).render_html(), encoding="utf-8")
    print(f"已生成 {out}")


def cmd_issue_sync(a):
    p = _proj(a)
    latest = p.latest_report_json()
    if not latest:
        sys.exit("无报告; 先 keel journey run")
    data = json.loads(latest.read_text(encoding="utf-8"))
    repo = a.repo or p.meta.get("issueRepo")
    if not repo:
        sys.exit("未指定 --repo 且项目未登记 issueRepo")
    existing = []
    try:
        out = subprocess.run(["gh", "issue", "list", "-R", repo, "--state", "open",
                              "--limit", "200", "--json", "title"],
                             capture_output=True, text=True, timeout=60)
        existing = {i["title"] for i in json.loads(out.stdout or "[]")}
    except Exception:
        pass
    created = 0
    for f in data.get("findings", []):
        title = f"[keel] {f['severity']} {f['id']} {f['title']}"
        body = (f"**发现**: {f['title']}\n\n**证据**: {f.get('evidence','')}\n\n"
                f"**建议**: {f.get('suggestion','') or '-'}\n\n"
                f"_来自 keel 旅程回归 · {data.get('date','')}_")
        if title in existing:
            print(f"跳过(已存在): {title[:60]}")
            continue
        if a.dry_run:
            print(f"[dry-run] 将创建: {title[:70]}")
            created += 1
            continue
        r = subprocess.run(["gh", "issue", "create", "-R", repo,
                            "-t", title, "-b", body, "-l", "keel:auto"],
                           capture_output=True, text=True, timeout=60)
        print(("创建: " + (r.stdout or "").strip()[:80]) if r.returncode == 0
              else f"失败: {r.stderr[:100]}")
        created += 1 if r.returncode == 0 else 0
    print(f"issue sync 完成: {created} 条")


def main(argv: list[str] | None = None) -> int:
    pr = argparse.ArgumentParser("keel")
    pr.add_argument("--root", default=DEFAULT_ROOT, help="项目根目录(默认 projects/)")
    sub = pr.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new");            s.add_argument("project")
    s.add_argument("--env-dev", default=""); s.add_argument("--issue-repo", default="")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("status");         s.add_argument("project"); s.set_defaults(fn=cmd_status)

    s = sub.add_parser("contract", );     sub_ = s.add_subparsers(dest="sub", required=True)
    v = sub_.add_parser("verify");        v.add_argument("project"); v.add_argument("--context", required=True)
    v.add_argument("--scope", default="confirmed"); v.set_defaults(fn=cmd_contract_verify)

    s = sub.add_parser("journey");        sub_ = s.add_subparsers(dest="sub", required=True)
    r = sub_.add_parser("run");           r.add_argument("project")
    r.add_argument("--section"); r.add_argument("--env", default="dev"); r.set_defaults(fn=cmd_journey_run)

    s = sub.add_parser("report");         sub_ = s.add_subparsers(dest="sub", required=True)
    rr = sub_.add_parser("render");       rr.add_argument("project")
    rr.add_argument("--input"); rr.add_argument("-o", "--output"); rr.set_defaults(fn=cmd_report_render)

    s = sub.add_parser("issue");          sub_ = s.add_subparsers(dest="sub", required=True)
    i = sub_.add_parser("sync");          i.add_argument("project")
    i.add_argument("--repo"); i.add_argument("--dry-run", action="store_true"); i.set_defaults(fn=cmd_issue_sync)

    s = sub.add_parser("render-report");  s.add_argument("input")
    s.add_argument("-o", "--output", default="report.html")

    s = sub.add_parser("mcp-server");     s.add_argument("--port", type=int, default=8902)
    s.add_argument("--token", default=""); s.add_argument("--root", default=DEFAULT_ROOT)

    a = pr.parse_args(argv)
    if not hasattr(a, "root"):
        a.root = DEFAULT_ROOT                          # 子解析器未定义时用全局
    if a.cmd == "render-report":                      # v0.2 兼容
        a.project = ""
        cmd_report_render(a); return 0
    if a.cmd == "mcp-server":
        from .mcp_server import serve
        serve(a.port, a.token or None, a.root); return 0
    a.fn(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
