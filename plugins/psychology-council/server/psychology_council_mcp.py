#!/usr/bin/env python3
"""Local, dependency-free MCP server for Psychology Council.

Working sessions live only in this process. Durable Markdown is written only by
the explicit, two-step preview/save flow.
"""

from __future__ import annotations

import json
import os
import platform
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SERVER_NAME = "psychology-council"
SERVER_VERSION = "0.1.0"
UI_URI = "ui://psychology-council/council-board-v1.html"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = PLUGIN_ROOT / "ui" / "council-board.html"

CHAMBERS = {
    "深层动力院": ["弗洛伊德", "荣格", "伯恩"],
    "行动改变院": ["斯金纳", "贝克", "班杜拉"],
    "意义成长院": ["罗杰斯", "弗兰克尔", "马斯洛"],
    "关系系统院": ["阿德勒", "鲍尔比", "萨提亚"],
}
MODERN_LENSES = ["文化与权力", "身体与健康", "发展与情境", "研究方法"]
ALLOWED_PHASES = {
    "定框",
    "十二镜扫描",
    "选席",
    "独立立论",
    "交叉质询",
    "价值探索",
    "创新模式",
    "总结",
}
ALLOWED_LABELS = {"事实", "理论", "推演"}
ALLOWED_STATUSES = {"提出", "被质疑", "部分让步", "修订", "用户否认", "暂时保留"}
ALLOWED_EVIDENCE = {"证据较强", "证据混合", "历史/解释性", "个人观察", "未核查"}
SESSIONS: dict[str, dict[str, Any]] = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "").replace("\x00", "")
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    return text.strip()[:limit]


def clean_list(value: Any, *, limit: int = 20, item_limit: int = 1000) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = clean_text(item, item_limit)
        if text:
            result.append(text)
    return result


def clean_claims(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    claims: list[dict[str, str]] = []
    for raw in value[:40]:
        if not isinstance(raw, dict):
            continue
        statement = clean_text(raw.get("statement"), 1600)
        if not statement:
            continue
        label = clean_text(raw.get("label"), 20)
        status = clean_text(raw.get("status"), 30)
        evidence = clean_text(raw.get("evidence_level"), 40)
        claims.append(
            {
                "id": clean_text(raw.get("id"), 60) or uuid.uuid4().hex[:10],
                "lens": clean_text(raw.get("lens"), 80) or "主持人整理",
                "label": label if label in ALLOWED_LABELS else "推演",
                "statement": statement,
                "evidence_level": evidence if evidence in ALLOWED_EVIDENCE else "未核查",
                "falsifier": clean_text(raw.get("falsifier"), 1000),
                "challenge": clean_text(raw.get("challenge"), 1000),
                "status": status if status in ALLOWED_STATUSES else "提出",
            }
        )
    return claims


def clean_tensions(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    tensions: list[dict[str, str]] = []
    for raw in value[:12]:
        if not isinstance(raw, dict):
            continue
        left = clean_text(raw.get("left"), 500)
        right = clean_text(raw.get("right"), 500)
        if left and right:
            tensions.append(
                {
                    "left": left,
                    "right": right,
                    "question": clean_text(raw.get("question"), 900),
                }
            )
    return tensions


def clean_values(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    values: list[dict[str, Any]] = []
    for raw in value[:20]:
        if not isinstance(raw, dict):
            continue
        name = clean_text(raw.get("name"), 100)
        if not name:
            continue
        certainty_raw = raw.get("certainty")
        certainty = None
        if isinstance(certainty_raw, (int, float)):
            certainty = max(0, min(100, int(certainty_raw)))
        values.append(
            {
                "name": name,
                "meaning": clean_text(raw.get("meaning"), 800),
                "behavior_evidence": clean_text(raw.get("behavior_evidence"), 1000),
                "conflicts_with": clean_text(raw.get("conflicts_with"), 300),
                "willing_cost": clean_text(raw.get("willing_cost"), 800),
                "boundary": clean_text(raw.get("boundary"), 800),
                "source": clean_text(raw.get("source"), 300),
                "certainty": certainty,
            }
        )
    return values


def create_session(args: dict[str, Any]) -> dict[str, Any]:
    topic = clean_text(args.get("topic"), 600)
    goal = clean_text(args.get("goal"), 500)
    if not topic or not goal:
        raise ValueError("topic 和 goal 都不能为空")
    session_id = "pc-" + uuid.uuid4().hex[:12]
    timestamp = now_iso()
    session = {
        "schema_version": 1,
        "session_id": session_id,
        "topic": topic,
        "goal": goal,
        "horizon": clean_text(args.get("horizon"), 200),
        "facts": clean_list(args.get("facts"), limit=20),
        "constraints": clean_list(args.get("constraints"), limit=20),
        "phase": "定框",
        "round": 0,
        "selected_lenses": clean_list(args.get("selected_lenses"), limit=4, item_limit=80),
        "claims": [],
        "tensions": [],
        "values": [],
        "open_questions": [],
        "actions": [],
        "created_at": timestamp,
        "updated_at": timestamp,
        "persistence": "ephemeral",
    }
    SESSIONS[session_id] = session
    return deepcopy(session)


def get_session(session_id: str) -> dict[str, Any]:
    session_id = clean_text(session_id, 80)
    if session_id not in SESSIONS:
        raise ValueError("找不到这个临时会话；它可能来自已结束的 MCP 进程")
    return SESSIONS[session_id]


def update_session(args: dict[str, Any]) -> dict[str, Any]:
    session = get_session(args.get("session_id", ""))
    phase = clean_text(args.get("phase"), 40)
    if phase:
        if phase not in ALLOWED_PHASES:
            raise ValueError("未知阶段")
        session["phase"] = phase
    if isinstance(args.get("round"), int):
        session["round"] = max(0, min(99, args["round"]))
    if "facts" in args:
        session["facts"] = clean_list(args.get("facts"), limit=20)
    if "constraints" in args:
        session["constraints"] = clean_list(args.get("constraints"), limit=20)
    if "selected_lenses" in args:
        session["selected_lenses"] = clean_list(args.get("selected_lenses"), limit=4, item_limit=80)
    if "claims" in args:
        session["claims"] = clean_claims(args.get("claims"))
    if "tensions" in args:
        session["tensions"] = clean_tensions(args.get("tensions"))
    if "values" in args:
        session["values"] = clean_values(args.get("values"))
    if "open_questions" in args:
        session["open_questions"] = clean_list(args.get("open_questions"), limit=10)
    if "actions" in args:
        session["actions"] = clean_list(args.get("actions"), limit=6)
    session["updated_at"] = now_iso()
    return deepcopy(session)


def data_dir() -> Path:
    override = os.environ.get("PSYCHOLOGY_COUNCIL_DATA_DIR") or os.environ.get("PLUGIN_DATA")
    if override:
        return Path(override).expanduser().resolve()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Psychology Council"
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "Psychology Council"
    return Path.home() / ".local" / "share" / "psychology-council"


def proposed_path(session: dict[str, Any]) -> Path:
    date = datetime.now().strftime("%Y-%m-%d")
    return data_dir() / f"{date}-{session['session_id']}.md"


def markdown_for(session: dict[str, Any]) -> str:
    lines = [
        "---",
        f"session_id: {session['session_id']}",
        f"date: {datetime.now().strftime('%Y-%m-%d')}",
        "privacy: de-identified",
        "---",
        "",
        "# 心理学十二镜议会记录",
        "",
        "## 议题与目标",
        "",
        f"- 议题：{session['topic']}",
        f"- 目标：{session['goal']}",
    ]
    if session.get("horizon"):
        lines.append(f"- 时间尺度：{session['horizon']}")

    def add_list(title: str, items: list[str]) -> None:
        if items:
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- {item}" for item in items)

    add_list("已知事实", session.get("facts", []))
    add_list("现实限制", session.get("constraints", []))
    add_list("入选视角", session.get("selected_lenses", []))
    if session.get("claims"):
        lines.extend(["", "## 主张与证据边界", ""])
        for claim in session["claims"]:
            lines.append(
                f"- **{claim['lens']}｜{claim['label']}｜{claim['status']}｜{claim['evidence_level']}**：{claim['statement']}"
            )
            if claim.get("falsifier"):
                lines.append(f"  - 会改变判断的新信息：{claim['falsifier']}")
            if claim.get("challenge"):
                lines.append(f"  - 主要质疑：{claim['challenge']}")
    if session.get("tensions"):
        lines.extend(["", "## 保留分歧", ""])
        for tension in session["tensions"]:
            lines.append(f"- {tension['left']} ↔ {tension['right']}")
            if tension.get("question"):
                lines.append(f"  - 待回答：{tension['question']}")
    if session.get("values"):
        lines.extend(["", "## 用户确认的价值", ""])
        for value in session["values"]:
            lines.append(f"- **{value['name']}**：{value.get('meaning') or '含义待继续澄清'}")
            if value.get("behavior_evidence"):
                lines.append(f"  - 行为证据：{value['behavior_evidence']}")
            if value.get("conflicts_with"):
                lines.append(f"  - 冲突价值：{value['conflicts_with']}")
            if value.get("willing_cost"):
                lines.append(f"  - 愿意承担：{value['willing_cost']}")
            if value.get("boundary"):
                lines.append(f"  - 边界：{value['boundary']}")
    add_list("开放问题", session.get("open_questions", []))
    add_list("低风险行动实验", session.get("actions", []))
    lines.extend(
        [
            "",
            "---",
            "本记录是去标识化的个人反思摘要，不是诊断、治疗方案或临床病历。",
            "",
        ]
    )
    return "\n".join(lines)


def preview_save(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    return {
        "session_id": session["session_id"],
        "path": str(proposed_path(session)),
        "markdown": markdown_for(session),
        "requires_confirmation": True,
    }


def save_session(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("confirmed") is not True:
        raise ValueError("只有用户看过预览并明确确认后才能保存")
    session = get_session(args.get("session_id", ""))
    path = proposed_path(session)
    expected = clean_text(args.get("expected_path"), 1200)
    if expected != str(path):
        raise ValueError("expected_path 与当前预览路径不一致，请重新预览")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        raise ValueError("目标文件已存在；为避免覆盖，请新建会话或先处理现有记录")
    path.write_text(markdown_for(session), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    session["persistence"] = "saved-deidentified"
    return {"session_id": session["session_id"], "path": str(path), "saved": True}


def list_saved() -> dict[str, Any]:
    root = data_dir()
    if not root.exists():
        return {"directory": str(root), "items": []}
    items = []
    for path in sorted(root.glob("*.md"), reverse=True)[:100]:
        match = re.search(r"(pc-[0-9a-f]{12})", path.name)
        items.append(
            {
                "session_id": match.group(1) if match else "unknown",
                "path": str(path),
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            }
        )
    return {"directory": str(root), "items": items}


def delete_saved(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("confirmed") is not True:
        raise ValueError("删除前必须向用户显示精确文件并获得明确确认")
    session_id = clean_text(args.get("session_id"), 80)
    if not re.fullmatch(r"pc-[0-9a-f]{12}", session_id):
        raise ValueError("无效的 session_id")
    root = data_dir()
    matches = list(root.glob(f"*-{session_id}.md")) if root.exists() else []
    if len(matches) != 1:
        raise ValueError("没有找到唯一匹配的记录")
    expected = clean_text(args.get("expected_path"), 1200)
    if expected != str(matches[0]):
        raise ValueError("expected_path 不匹配；请先重新列出记录")
    matches[0].unlink()
    return {"session_id": session_id, "path": expected, "deleted": True, "recoverable": False}


def reference_snapshot() -> dict[str, Any]:
    return {
        "chambers": CHAMBERS,
        "modern_lenses": MODERN_LENSES,
        "process_roles": ["主持人", "证据审查员", "价值绘图员", "安全守门员"],
        "principles": [
            "人物是理论代理，不是本人意识",
            "事实看证据，行动看安全与可逆，价值由用户决定",
            "不以多数票或虚假置信度决定结论",
            "每个关键假设都要有反证条件",
            "默认不保存结构化工作状态",
        ],
    }


def ok(data: dict[str, Any], text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "structuredContent": data}


def error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def tool_definitions() -> list[dict[str, Any]]:
    session_id = {"type": "string", "pattern": "^pc-[0-9a-f]{12}$"}
    string_array = {"type": "array", "items": {"type": "string"}}
    return [
        {
            "name": "council_get_reference",
            "title": "查看议会结构",
            "description": "读取十二席、现代空席和主持原则；不读取或保存用户数据。",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "council_create_working_session",
            "title": "建立临时议会状态",
            "description": "为当前 MCP 进程建立临时、非持久的结构化会话。不要传完整原始聊天或不必要的身份信息。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "maxLength": 600},
                    "goal": {"type": "string", "maxLength": 500},
                    "horizon": {"type": "string", "maxLength": 200},
                    "facts": string_array,
                    "constraints": string_array,
                    "selected_lenses": string_array,
                },
                "required": ["topic", "goal"],
                "additionalProperties": False,
            },
        },
        {
            "name": "council_update_working_session",
            "title": "更新临时议会状态",
            "description": "用去标识化的结构化摘要更新轮次、主张、分歧、价值和行动；仍不持久化。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": session_id,
                    "phase": {"type": "string", "enum": sorted(ALLOWED_PHASES)},
                    "round": {"type": "integer", "minimum": 0, "maximum": 99},
                    "facts": string_array,
                    "constraints": string_array,
                    "selected_lenses": string_array,
                    "claims": {"type": "array", "items": {"type": "object"}},
                    "tensions": {"type": "array", "items": {"type": "object"}},
                    "values": {"type": "array", "items": {"type": "object"}},
                    "open_questions": string_array,
                    "actions": string_array,
                },
                "required": ["session_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "council_get_working_session",
            "title": "读取临时议会状态",
            "description": "读取当前 MCP 进程中的结构化会话。",
            "inputSchema": {
                "type": "object",
                "properties": {"session_id": session_id},
                "required": ["session_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "council_render_board",
            "title": "显示议会面板",
            "description": "渲染已经整理好的临时会话。先创建或更新会话，再调用此工具。",
            "inputSchema": {
                "type": "object",
                "properties": {"session_id": session_id},
                "required": ["session_id"],
                "additionalProperties": False,
            },
            "_meta": {
                "ui": {"resourceUri": UI_URI},
                "openai/outputTemplate": UI_URI,
                "openai/toolInvocation/invoking": "正在整理议会面板…",
                "openai/toolInvocation/invoked": "议会面板已就绪",
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "council_preview_save",
            "title": "预览去标识化保存内容",
            "description": "只预览拟保存的 Markdown 和精确路径，不写文件。保存前必须先调用。",
            "inputSchema": {
                "type": "object",
                "properties": {"session_id": session_id},
                "required": ["session_id"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "council_save_deidentified",
            "title": "保存去标识化议会记录",
            "description": "仅在用户看过预览路径和内容并明确确认后写入本地 Markdown。必须原样传回 expected_path。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": session_id,
                    "expected_path": {"type": "string"},
                    "confirmed": {"type": "boolean", "const": True},
                },
                "required": ["session_id", "expected_path", "confirmed"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": False},
        },
        {
            "name": "council_list_saved",
            "title": "列出本地议会记录",
            "description": "列出插件数据目录中的去标识化 Markdown 文件，不读取正文。",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": {"readOnlyHint": True},
        },
        {
            "name": "council_delete_saved",
            "title": "删除本地议会记录",
            "description": "不可恢复地删除一个精确匹配的本地记录。必须先列出记录、展示路径并获得用户明确确认。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": session_id,
                    "expected_path": {"type": "string"},
                    "confirmed": {"type": "boolean", "const": True},
                },
                "required": ["session_id", "expected_path", "confirmed"],
                "additionalProperties": False,
            },
            "annotations": {"readOnlyHint": False, "destructiveHint": True},
        },
    ]


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    try:
        if name == "council_get_reference":
            data = reference_snapshot()
            return ok(data, "已读取十二镜议会结构与边界。")
        if name == "council_create_working_session":
            data = create_session(args)
            return ok(data, f"已建立临时会话 {data['session_id']}；尚未写入磁盘。")
        if name == "council_update_working_session":
            data = update_session(args)
            return ok(data, f"已更新 {data['session_id']} 的临时状态；尚未写入磁盘。")
        if name == "council_get_working_session":
            data = deepcopy(get_session(args.get("session_id", "")))
            return ok(data, f"已读取临时会话 {data['session_id']}。")
        if name == "council_render_board":
            session = deepcopy(get_session(args.get("session_id", "")))
            data = {"session": session, "reference": reference_snapshot()}
            result = ok(data, "已生成议会面板；文本会话仍保留完整信息。")
            result["_meta"] = {"ui": {"resourceUri": UI_URI}}
            return result
        if name == "council_preview_save":
            data = preview_save(args.get("session_id", ""))
            return ok(data, "这是拟保存内容和路径；尚未写入。请向用户展示并等待明确确认。")
        if name == "council_save_deidentified":
            data = save_session(args)
            return ok(data, f"已保存去标识化记录：{data['path']}")
        if name == "council_list_saved":
            data = list_saved()
            return ok(data, f"找到 {len(data['items'])} 条本地记录。")
        if name == "council_delete_saved":
            data = delete_saved(args)
            return ok(data, f"已删除且不可恢复：{data['path']}")
        return error(f"未知工具：{name}")
    except (ValueError, OSError) as exc:
        return error(clean_text(exc, 1200))


def read_ui_resource() -> dict[str, Any]:
    html = UI_PATH.read_text(encoding="utf-8")
    return {
        "contents": [
            {
                "uri": UI_URI,
                "mimeType": "text/html;profile=mcp-app",
                "text": html,
                "_meta": {"ui": {"prefersBorder": True}},
            }
        ]
    }


def dispatch(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion") or "2024-11-05"
        result = {
            "protocolVersion": requested,
            "capabilities": {"tools": {"listChanged": False}, "resources": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tool_definitions()}
    elif method == "tools/call":
        params = message.get("params") or {}
        result = call_tool(clean_text(params.get("name"), 120), params.get("arguments") or {})
    elif method == "resources/list":
        result = {
            "resources": [
                {
                    "uri": UI_URI,
                    "name": "心理学十二镜议会面板",
                    "description": "显示席位、主张、分歧、价值与行动的交互面板。",
                    "mimeType": "text/html;profile=mcp-app",
                }
            ]
        }
    elif method == "resources/read":
        uri = (message.get("params") or {}).get("uri")
        if uri != UI_URI:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32002, "message": "Resource not found"}}
        result = read_ui_resource()
    elif method == "logging/setLevel":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = dispatch(message)
        except Exception as exc:  # keep protocol alive; never leak a traceback to stdout
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": clean_text(exc, 500)},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
