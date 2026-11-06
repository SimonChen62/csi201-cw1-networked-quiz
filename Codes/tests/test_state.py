"""Member D: Unit tests for client local state management."""

import sys
import unittest
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client_modules"))

from state import ClientState, PlayerInfo, QuestionInfo


class TestClientState(unittest.TestCase):
    def setUp(self):
        self.state = ClientState()
        self.state.set_connected("u1", "Alice")

    def test_01_connection_state(self):
        """测试连接与断开状态"""
        self.assertTrue(self.state.connected)
        self.assertEqual(self.state.user_id, "u1")
        
        # 断开连接应清空所有状态
        self.state.set_disconnected()
        self.assertFalse(self.state.connected)
        self.assertIsNone(self.state.current_room_id)

    def test_02_enter_and_leave_room(self):
        """测试进入和离开房间，以及房主判断"""
        players = [
            {"user_id": "u1", "name": "Alice", "ready": True},
            {"user_id": "u2", "name": "Bob", "ready": False}
        ]
        self.state.enter_room("room-A", host_id="u1", players=players)
        
        self.assertEqual(self.state.current_room_id, "room-A")
        self.assertTrue(self.state.is_host)  # u1 是房主
        self.assertEqual(len(self.state.players_in_room), 2)
        self.assertTrue(self.state.players_in_room["u1"].ready)
        
        # 离开房间应清理干净
        self.state.leave_room()
        self.assertIsNone(self.state.current_room_id)
        self.assertFalse(self.state.is_host)
        self.assertEqual(len(self.state.players_in_room), 0)

    def test_03_update_players_keep_score(self):
        """测试更新玩家列表时，旧分数不会被意外清零"""
        self.state.enter_room("room-A", "u1", [{"user_id": "u1", "name": "Alice", "score": 100}])
        self.assertEqual(self.state.players_in_room["u1"].score, 100)
        
        # 服务器发来新更新，没带 score 字段
        self.state.update_room_players([{"user_id": "u1", "name": "Alice", "ready": True}])
        # 分数应保留，准备状态应更新
        self.assertEqual(self.state.players_in_room["u1"].score, 100)
        self.assertTrue(self.state.players_in_room["u1"].ready)

    def test_04_question_flow_and_duplicate_prevention(self):
        """测试发题、答题、公布答案的流转"""
        # 【修改点】先将玩家加入房间，确保在房间内开始游戏
        self.state.enter_room("room-1", "u1", [{"user_id": "u1", "name": "Alice"}])
        
        self.state.start_game()
        self.assertEqual(self.state.room_phase, "RUNNING")
        
        # 1. 收到题目（即使服务端错误地带有 answer，也应该被忽略）
        q_data = {
            "question_id": "q1",
            "text": "What is TCP?",
            "options": {"A": "UDP", "B": "Stream"},
            "time_limit": 15,
            "points": 100,
            "answer": "B"  # 故意传答案，验证 state 是否忽略
        }
        self.state.set_question(q_data)
        
        self.assertIsNotNone(self.state.current_question)
        self.assertFalse(hasattr(self.state.current_question, "answer")) # 确认没保存答案
        self.assertFalse(self.state.has_answered_current_question)
        
        # 2. 提交答案，标记已答
        self.state.mark_answered()
        self.assertTrue(self.state.has_answered_current_question)
        
        # 3. 题目结束，收到结果
        result_data = {
            "question_id": "q1",
            "answer": "B",
            "scores": {"u1": 100}
        }
        self.state.set_question_result(result_data)
        
        self.assertIsNone(self.state.current_question) # 题目已关闭
        self.assertIsNotNone(self.state.last_result)
        self.assertEqual(self.state.last_result.correct_answer, "B")
        
        # 验证分数更新成功
        self.assertEqual(self.state.players_in_room["u1"].score, 100)

    def test_05_state_isolation(self):
        """测试切换房间时，比赛数据不会串房"""
        # 在 Room A 玩了一半
        self.state.enter_room("room-A", "u1", [])
        self.state.start_game()
        self.state.set_question({"question_id": "q1", "text": "Q1", "options": {}})
        
        # 离开 Room A，进入 Room B
        self.state.leave_room()
        self.state.enter_room("room-B", "u1", [])
        
        # 验证 Room A 的题目数据没带过来
        self.assertIsNone(self.state.current_question)
        self.assertIsNone(self.state.last_result)
        self.assertEqual(self.state.room_phase, "WAITING")

    def test_06_thread_safe_snapshot(self):
        """测试快照深拷贝，以及高并发读取不崩溃"""
        self.state.enter_room("room-A", "u1", [{"user_id": "u1", "name": "Alice"}])
        
        # 1. 测试深拷贝隔离
        snap1 = self.state.get_snapshot()
        snap1["players"]["u1"]["score"] = 9999  # 篡改快照
        snap2 = self.state.get_snapshot()
        self.assertEqual(snap2["players"]["u1"]["score"], 0) # 内部状态未被篡改

        # 2. 多线程并发读写测试
        def modify_state():
            for i in range(100):
                self.state.update_room_players([
                    {"user_id": f"u{i}", "name": f"P{i}"}
                ])
                time.sleep(0.001)

        def read_state():
            for _ in range(100):
                snap = self.state.get_snapshot()
                # 模拟 UI 遍历字典
                for uid, p in snap["players"].items():
                    pass
        
        t1 = threading.Thread(target=modify_state)
        t2 = threading.Thread(target=read_state)
        t1.start(); t2.start()
        t1.join(); t2.join()
        # 如果没有报 RuntimeError: dictionary changed size during iteration，说明快照机制有效


if __name__ == "__main__":
    unittest.main()
