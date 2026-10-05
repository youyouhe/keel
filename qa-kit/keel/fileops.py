"""keel.fileops — 项目空间文件读写(MCP file_put/file_get 核心)

沙箱规则(S1-S6):
- S1 路径必须落在 projects/<A>/ 内(realpath 校验, 拒绝绝对路径与 .. 逃逸)
- S2 项目须已存在
- S3 单文件 ≤ 1MB
- S4 保留路径禁写: project.json, reports/**(历史报告只读)
- S5 写权限 = Bearer token(信任边界: journeys.py 会被动态执行 → token 持有者
     可在 Keel 服务器执行任意代码, 仅限可信局域网; 详见 keel_guide)
- S6 每次写入追加审计日志 logs/file_put.log
"""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

MAX_FILE = 1024 * 1024
RESERVED = ("project.json",)            # 禁写(相对项目根)
RESERVED_PREFIXES = ("reports/",)       # 禁写前缀
GET_RETURN_LIMIT = 64 * 1024            # file_get 返回上限(MCP token 保护)


class FileOpError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def _resolve(project_root: Path, rel_path: str, op: str) -> Path:
    """S1: 路径沙箱——必须落在项目根内。"""
    if not rel_path or rel_path.startswith(("/", "\\")) or "\\" in rel_path:
        raise FileOpError("PATH_ESCAPED", f"非法路径 {rel_path!r}(禁止绝对路径/反斜杠)")
    p = (project_root / rel_path).resolve()
    root = project_root.resolve()
    if not str(p).startswith(str(root) + str(p.drive and "\\" or "/")) and p != root:
        raise FileOpError("PATH_ESCAPED", f"路径越界: {rel_path}")
    if op == "put":
        rel = p.relative_to(root).as_posix()
        if rel in RESERVED or any(rel.startswith(r) for r in RESERVED_PREFIXES):
            raise FileOpError("RESERVED_PATH", f"保留路径禁写: {rel}")
    return p


def file_put(root: str, project: str, path: str, content: str,
             encoding: str = "utf8", create_dirs: bool = True,
             expected_version: int | None = None) -> dict:
    from .project import KeelProject
    if not KeelProject.valid_name(project):
        raise FileOpError("PROJECT_NOT_FOUND", f"非法项目名 {project!r}")
    proj = (Path(root) / project).resolve()
    if not proj.exists():
        raise FileOpError("PROJECT_NOT_FOUND", f"项目不存在: {project}")
    target = _resolve(proj, path, "put")

    if encoding == "base64":
        try:
            data = base64.b64decode(content)
        except Exception:
            raise FileOpError("INVALID_ENCODING", "base64 解码失败")
    elif encoding == "utf8":
        data = content.encode("utf-8")
    else:
        raise FileOpError("INVALID_ENCODING", f"未知 encoding: {encoding}")

    if len(data) > MAX_FILE:
        raise FileOpError("FILE_TOO_LARGE", f"{len(data)} 字节超 {MAX_FILE} 上限")

    # 乐观锁: 版本存独立 sidecar(.keel-versions.json), 不污染被测文件内容
    # (反馈②: 原实现从文件内容读 _version, 写入不回写 → 永远 0, 乐观锁失灵)
    vfile = proj / ".keel-versions.json"
    versions = {}
    if vfile.exists():
        try:
            versions = json.loads(vfile.read_text(encoding="utf-8"))
        except Exception:
            versions = {}
    vkey = target.relative_to(proj).as_posix()
    version = versions.get(vkey, 0)
    if expected_version is not None and version != expected_version:
        raise FileOpError("VERSION_CONFLICT", f"期望 v{expected_version} 实际 v{version}")

    if create_dirs:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    # 版本号递增并持久化
    versions[vkey] = version + 1
    vfile.write_text(json.dumps(versions, ensure_ascii=False, indent=1), encoding="utf-8")

    # S6 审计
    log_dir = Path(root).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "file_put.log", "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "project": project, "path": path,
                            "bytes": len(data), "encoding": encoding},
                           ensure_ascii=False) + "\n")
    return {"ok": True, "path": path, "bytes": len(data), "version": version + 1}


def file_get(root: str, project: str, path: str) -> dict:
    from .project import KeelProject
    if not KeelProject.valid_name(project):
        raise FileOpError("PROJECT_NOT_FOUND", f"非法项目名 {project!r}")
    proj = (Path(root) / project).resolve()
    if not proj.exists():
        raise FileOpError("PROJECT_NOT_FOUND", f"项目不存在: {project}")
    target = _resolve(proj, path, "get")
    if not target.exists():
        raise FileOpError("NOT_FOUND", f"文件不存在: {path}")
    stat = target.stat()
    content = target.read_text(encoding="utf-8", errors="replace")
    truncated = len(content) > GET_RETURN_LIMIT
    # 版本号从 sidecar 读(与 file_put 同源)
    vfile = proj / ".keel-versions.json"
    version = 0
    if vfile.exists():
        try:
            versions = json.loads(vfile.read_text(encoding="utf-8"))
            version = versions.get(target.relative_to(proj).as_posix(), 0)
        except Exception:
            version = 0
    return {"path": path, "content": content[:GET_RETURN_LIMIT],
            "truncated": truncated, "size": stat.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "version": version}
