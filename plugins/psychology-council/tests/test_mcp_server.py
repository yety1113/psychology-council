from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


SERVER_PATH = Path(__file__).resolve().parents[1] / "server" / "psychology_council_mcp.py"
SPEC = importlib.util.spec_from_file_location("psychology_council_mcp", SERVER_PATH)
assert SPEC and SPEC.loader
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)


class PsychologyCouncilServerTests(unittest.TestCase):
    def setUp(self) -> None:
        SERVER.SESSIONS.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_data_dir = os.environ.get("PSYCHOLOGY_COUNCIL_DATA_DIR")
        os.environ["PSYCHOLOGY_COUNCIL_DATA_DIR"] = self.temp_dir.name

    def tearDown(self) -> None:
        if self.previous_data_dir is None:
            os.environ.pop("PSYCHOLOGY_COUNCIL_DATA_DIR", None)
        else:
            os.environ["PSYCHOLOGY_COUNCIL_DATA_DIR"] = self.previous_data_dir
        self.temp_dir.cleanup()

    def create_session(self) -> dict:
        return SERVER.create_session(
            {
                "topic": "如何处理重要任务上的拖延？",
                "goal": "辨认维持因素并设计一项可逆实验",
                "facts": ["截止日期还有两周"],
                "selected_lenses": ["贝克", "班杜拉", "伯恩", "萨提亚", "不应保留的第五席"],
            }
        )

    def test_session_is_ephemeral_and_sanitized(self) -> None:
        session = self.create_session()
        self.assertEqual(session["persistence"], "ephemeral")
        self.assertEqual(len(session["selected_lenses"]), 4)
        self.assertEqual(list(Path(self.temp_dir.name).glob("*.md")), [])

        updated = SERVER.update_session(
            {
                "session_id": session["session_id"],
                "phase": "交叉质询",
                "round": 2,
                "claims": [
                    {
                        "lens": "贝克",
                        "label": "理论",
                        "statement": "对失败的灾难化预测可能抬高启动成本。",
                        "evidence_level": "证据混合",
                        "falsifier": "如果启动前没有相关想法，我会下调这一判断。",
                        "status": "被质疑",
                    }
                ],
                "values": [
                    {
                        "name": "自主",
                        "meaning": "能选择工作方式",
                        "certainty": 140,
                    }
                ],
            }
        )
        self.assertEqual(updated["phase"], "交叉质询")
        self.assertEqual(updated["claims"][0]["label"], "理论")
        self.assertEqual(updated["values"][0]["certainty"], 100)

    def test_two_step_save_and_exact_delete(self) -> None:
        session = self.create_session()
        preview = SERVER.preview_save(session["session_id"])
        path = Path(preview["path"])
        self.assertFalse(path.exists())
        self.assertIn("不是诊断、治疗方案或临床病历", preview["markdown"])

        with self.assertRaises(ValueError):
            SERVER.save_session(
                {
                    "session_id": session["session_id"],
                    "expected_path": str(path),
                    "confirmed": False,
                }
            )
        with self.assertRaises(ValueError):
            SERVER.save_session(
                {
                    "session_id": session["session_id"],
                    "expected_path": str(path) + ".wrong",
                    "confirmed": True,
                }
            )

        saved = SERVER.save_session(
            {
                "session_id": session["session_id"],
                "expected_path": str(path),
                "confirmed": True,
            }
        )
        self.assertTrue(saved["saved"])
        self.assertTrue(path.exists())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(SERVER.list_saved()["items"]), 1)

        with self.assertRaises(ValueError):
            SERVER.delete_saved(
                {
                    "session_id": session["session_id"],
                    "expected_path": str(path),
                    "confirmed": False,
                }
            )
        deleted = SERVER.delete_saved(
            {
                "session_id": session["session_id"],
                "expected_path": str(path),
                "confirmed": True,
            }
        )
        self.assertTrue(deleted["deleted"])
        self.assertFalse(deleted["recoverable"])
        self.assertFalse(path.exists())

    def test_render_tool_and_ui_resource_are_wired(self) -> None:
        session = self.create_session()
        result = SERVER.call_tool("council_render_board", {"session_id": session["session_id"]})
        self.assertFalse(result.get("isError", False))
        self.assertEqual(result["_meta"]["ui"]["resourceUri"], SERVER.UI_URI)

        tools = {tool["name"]: tool for tool in SERVER.tool_definitions()}
        self.assertEqual(
            tools["council_render_board"]["_meta"]["ui"]["resourceUri"],
            SERVER.UI_URI,
        )
        resource = SERVER.read_ui_resource()["contents"][0]
        self.assertEqual(resource["mimeType"], "text/html;profile=mcp-app")
        self.assertIn("心理学十二镜议会", resource["text"])

    def test_json_rpc_dispatch(self) -> None:
        initialized = SERVER.dispatch(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        listed = SERVER.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertGreaterEqual(len(listed["result"]["tools"]), 9)


if __name__ == "__main__":
    unittest.main()
