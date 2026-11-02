import io
import unittest

import maze
import menu
import quietlab as q


class MenuTests(unittest.TestCase):
    def session(self, text):
        output = io.StringIO()
        status = menu.main(io.StringIO(text), output)
        self.assertEqual(status, 0)
        return output.getvalue()

    def test_calculator_and_recovery(self):
        output = self.session("1\n1/0\n1\n0.1+0.2\nq\n")
        self.assertIn("错误：", output)
        self.assertIn("0.3", output)
        self.assertNotIn("Traceback", output)

    def test_cancel_and_unknown_choice(self):
        output = self.session("what\n1\n:cancel\nq\n")
        self.assertIn("请选择", output)
        self.assertIn("已返回菜单", output)

    def test_text_block_and_dot_escape(self):
        output = self.session("2\nhello\n..\n.\nq\n")
        self.assertIn('"unicode_codepoints": 8', output)
        self.assertIn('"lines": 2', output)

    def test_empty_block(self):
        output = self.session("2\n.\nq\n")
        self.assertIn('"unicode_codepoints": 0', output)

    def test_json_precision(self):
        output = self.session('3\n{"x":0.123456789012345678901}\n.\nq\n')
        self.assertIn('0.123456789012345678901', output)

    def test_csv_tab(self):
        output = self.session("4\ntab\na\tb\n1\t2\n.\nq\n")
        self.assertIn('"data_rows": 1', output)
        self.assertIn('"maximum": "2"', output)

    def test_task_planner(self):
        output = self.session("5\n60\n读书\n40\n7\n散步\n30\n6\n笔记\n20\n4\n\nq\n")
        self.assertIn("选中 2 项，用时 60/60 分钟，总价值 11", output)
        self.assertIn("读书 · 40 分钟", output)
        self.assertIn("笔记 · 20 分钟", output)

    def test_diff(self):
        output = self.session("6\na\n.\nb\n.\nq\n")
        self.assertIn("-a\n+b\n", output)

    def test_budget_and_invalid_values(self):
        output = self.session("7\n81\n35\n180\n7\nnan\n0\n1\nq\n")
        self.assertIn('"maximum_spend_percentage_points": 46.0', output)
        self.assertIn("有限数", output)

    def test_eof_in_block(self):
        output = self.session("3\n{\n")
        self.assertIn("会话结束", output)
        self.assertNotIn("Traceback", output)

    def test_oversize_line_ends_session_without_running_suffix(self):
        output = self.session("1\n" + "9" * 1025 + "\n1\n999+1\nq\n")
        self.assertIn("超过上限", output)
        self.assertNotIn("1000", output)

    def test_block_byte_limit(self):
        console = menu.Console(io.StringIO("x" * (q.MAX_INPUT // 2) + "\n" + "x" * (q.MAX_INPUT // 2) + "\n.\n"), io.StringIO())
        with self.assertRaises(menu.EndSession):
            console.block("text")

    def test_unicode_byte_limit(self):
        console = menu.Console(io.StringIO("你" * 6 + "\n"), io.StringIO())
        with self.assertRaises(menu.EndSession):
            console.line("", 16)

    def test_integer_validation(self):
        for text in ("abc\n", "-1\n", "99\n"):
            with self.assertRaises(q.InputError):
                menu.Console(io.StringIO(text), io.StringIO()).integer("", 1, 10)
        self.assertEqual(menu.Console(io.StringIO("\n"), io.StringIO()).integer("", 1, 10, 5), 5)

    def test_output_sanitization(self):
        output = io.StringIO()
        menu.Console(output=output).write("\x1b[31m\u202e")
        self.assertNotIn("\x1b", output.getvalue())
        self.assertIn("\\u202e", output.getvalue())


class MazeMenuTests(unittest.TestCase):
    def test_board(self):
        graph = maze.generate(5, 3, 42)
        board = menu.board_text(graph, 5, 3, 0, {0})
        lines = board.splitlines()
        self.assertEqual(len(lines), 7)
        self.assertEqual(set(map(len, lines)), {11})
        self.assertEqual(board.count("@"), 1)
        self.assertEqual(board.count("E"), 1)
        self.assertEqual(lines[0][1], " ")
        self.assertEqual(lines[-1][-2], " ")

    def test_hint_route_from_any_cell(self):
        graph = maze.generate(7, 5, 10)
        for current in range(len(graph)):
            route = menu.route_to_exit(graph, current)
            self.assertEqual(route[0], current)
            self.assertEqual(route[-1], len(graph) - 1)
            for first, second in zip(route, route[1:]):
                self.assertIn(second, graph[first])

    def test_play_to_win_with_hint_wall_and_restart(self):
        graph = maze.generate(2, 2, 0)
        route = maze.solve(graph)
        keys = []
        for first, second in zip(route, route[1:]):
            delta = (second % 2 - first % 2, second // 2 - first // 2)
            keys.append({(1,0):'d', (-1,0):'a', (0,1):'s', (0,-1):'w'}[delta])
        inputs = "8\n2\n2\n0\nw\nh\n" + keys[0] + "\nr\n" + "\n".join(keys) + "\nq\n"
        output = io.StringIO()
        self.assertEqual(menu.main(io.StringIO(inputs), output), 0)
        text = output.getvalue()
        self.assertIn("这边是墙", text)
        self.assertIn("下一步", text)
        self.assertIn("抵达出口", text)
        self.assertIn("实际 %d 步，最短 %d 步" % (len(keys), len(keys)), text)

    def test_quit_game_to_menu(self):
        output = io.StringIO()
        menu.main(io.StringIO("8\n\n\n\nq\n1\n2+3\nq\n"), output)
        self.assertIn("表达式：5", output.getvalue())


if __name__ == "__main__":
    unittest.main()
