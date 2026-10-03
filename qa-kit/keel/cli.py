"""keel.cli — 命令行入口(报告渲染/契约校验)

用法:
  python -m keel render-report report.json -o report.html
"""
from __future__ import annotations

import argparse
import sys

from .report import Report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser("keel")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render-report", help="report.json → html")
    r.add_argument("input")
    r.add_argument("-o", "--output", default="report.html")
    a = p.parse_args(argv)
    if a.cmd == "render-report":
        import json as _json
        rep = Report.from_dict(_json.loads(open(a.input, encoding="utf-8").read()))
        open(a.output, "w", encoding="utf-8").write(rep.render_html())
        print(f"已生成 {a.output}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
