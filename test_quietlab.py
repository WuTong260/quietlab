"""Behavior, rejection, algorithm and resource-bound tests; no data files."""
import ast
import io
import itertools
import json
import random
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

import maze
import quietlab as q


ROOT = Path(__file__).resolve().parent


class CalculatorTests(unittest.TestCase):
    def test_exact_decimal(self):
        self.assertEqual(q.calculate("0.1 + 0.2"), "0.3")
        self.assertEqual(q.calculate("9007199254740993 + 1"), "9007199254740994")

    def test_operators(self):
        for expression, expected in [
            ("2 + 3 * 4", "14"), ("(2+3)*4", "20"),
            ("2**-3", "0.125"), ("-2**2", "-4"),
            ("sqrt(81)", "9"), ("max(2, -3, abs(-5))", "5"),
            ("min(2,3)", "2"), ("1_000 / 4", "250"),
            (".25 + 2.5e-1", "0.50"), ("  3 + 4 ", "7")]:
            with self.subTest(expression=expression):
                self.assertEqual(q.calculate(expression), expected)

    def test_rejections(self):
        for expression in [
            "__import__('os')", "open('anything')", "(1).__class__", "[1]",
            "True", "sqrt(-1)", "1/0", "0**-1", "2**101", "2**.5",
            "9**9**9", "2 << 30", "0xdead", "1e1001", "1e-1001", "1e-1000**100",
            "sqrt(1,2)", "max()", "abs(x=1)", "1%2", "1//2",
            "x", "lambda: 1", "a:=1", "", "1+", "-" * 40 + "1",
            "1+" * 100 + "1", "9" * 1025]:
            with self.subTest(expression=expression):
                with self.assertRaises(q.InputError):
                    q.calculate(expression)

    def test_precision_is_bounded(self):
        self.assertEqual(len(q.calculate("1/3").split(".")[1]), 40)


class JsonTests(unittest.TestCase):
    def test_decimal_values_preserved(self):
        source = '{"x": 0.123456789012345678901234567890123456789, "y": 1e400}'
        result = q.dump_json(q.parse_json(source))
        self.assertIn("0.123456789012345678901234567890123456789", result)
        self.assertEqual(q.parse_json(source), q.parse_json(result))

    def test_zero_and_negative_zero(self):
        for source in ("0.0", "-0.0", "1e-1000", "1e1000"):
            self.assertEqual(q.parse_json(source), q.parse_json(q.dump_json(q.parse_json(source))))

    def test_invalid(self):
        for source in ['{"a":1,"a":2}', 'NaN', 'Infinity', '[1,]',
                       '1e1001', '1e-1001', '1e999999999999999999999999',
                       '9' * 1001, '[' * 34 + '0' + ']' * 34,
                       '[' + ','.join('0' for _ in range(50001)) + ']']:
            with self.subTest(source=source[:50]):
                with self.assertRaises(q.InputError):
                    q.parse_json(source)

    def test_sorted_keys_and_surrogates(self):
        result = q.dump_json(q.parse_json('{"z":"\\ud800", "a":"\\u202e"}'), True)
        self.assertLess(result.index('"a"'), result.index('"z"'))
        self.assertIn('\\ud800', result)
        self.assertIn('\\u202e', result)
        result.encode("utf-8")

    def test_output_budget_checked_during_serialization(self):
        with self.assertRaises(q.InputError):
            q.dump_json(["x" * 100] * 22000)

    def test_roundtrip_structures(self):
        cases = [None, [], {}, True, False, [1, "你好", {"a": [None, False]}],
                 {"quotes": '"\\\n\t', "number": Decimal("1.234567890123456789")}]
        for value in cases:
            self.assertEqual(value, q.parse_json(q.dump_json(value)))


class TextTests(unittest.TestCase):
    def test_empty(self):
        stats = q.text_statistics("")
        self.assertEqual(stats["lines"], 0)
        self.assertEqual(stats["character_entropy_bits"], 0)

    def test_unicode(self):
        stats = q.text_statistics("你好 hello\n\n你好 hello\n\x1b")
        self.assertEqual(stats["han_codepoints"], 4)
        self.assertEqual(stats["latin_words"], 2)
        self.assertEqual(stats["lines"], 4)
        self.assertEqual(stats["blank_lines"], 1)
        self.assertEqual(stats["duplicate_nonblank_lines"][0]["count"], 2)
        self.assertEqual(stats["unusual_control_codepoints"], {"U+001B": 1})

    def test_codepoint_definition(self):
        self.assertEqual(q.text_statistics("e\u0301")["unicode_codepoints"], 2)
        self.assertEqual(q.text_statistics("👩‍💻")["unicode_codepoints"], 3)

    def test_input_limits(self):
        self.assertEqual(q.read_input(io.BytesIO(b"\xef\xbb\xbfhello")), "hello")
        for data in (b"\xff", b"x" * (q.MAX_INPUT + 1)):
            with self.assertRaises(q.InputError):
                q.read_input(io.BytesIO(data))


class CsvTests(unittest.TestCase):
    def test_profile(self):
        result = q.csv_profile('name,score\n"A, B",10\nC,2.5\nD,\nwrong,row,extra\n')
        self.assertEqual(result["data_rows"], 4)
        self.assertEqual(result["malformed_rows_count"], 1)
        score = result["columns"][1]
        self.assertEqual(score["minimum"], "2.5")
        self.assertEqual(score["maximum"], "10")
        self.assertEqual(score["numeric"], 2)
        self.assertEqual(score["empty"], 1)

    def test_quoted_newlines(self):
        result = q.csv_profile('a;b\r\n"one\ntwo";3\r\n', ";")
        self.assertEqual(result["data_rows"], 1)
        self.assertEqual(result["columns"][0]["nonempty"], 1)

    def test_duplicate_headers(self):
        self.assertEqual(q.csv_profile("a,a\n1,2")["duplicate_headers"], ["a"])

    def test_numeric_rules(self):
        result = q.csv_profile("x\nNaN\nInfinity\n1e1001\n-1e3\n.25\n１２\n")
        self.assertEqual(result["columns"][0]["numeric"], 2)
        self.assertEqual(result["columns"][0]["minimum"], "-1E+3")

    def test_bad_input(self):
        for source in ("", 'a,b\n"unterminated', "," * 100,
                       "a\n" + "x\n" * 20001):
            with self.subTest(source=source[:50]):
                with self.assertRaises(q.InputError):
                    q.csv_profile(source)


class PlannerTests(unittest.TestCase):
    def test_greedy_counterexample(self):
        tasks = [{"name": "a", "minutes": 10, "value": 60},
                 {"name": "b", "minutes": 20, "value": 100},
                 {"name": "c", "minutes": 30, "value": 120}]
        result = q.plan_tasks(tasks, 50)
        self.assertEqual(result["total_value"], 220)
        self.assertEqual([x["name"] for x in result["selected"]], ["b", "c"])

    def test_against_exhaustive_search(self):
        rng = random.Random(20261102)
        for _ in range(150):
            count, budget = rng.randrange(1, 10), rng.randrange(1, 40)
            tasks = [{"name": str(i), "minutes": rng.randrange(1, 20),
                      "value": rng.randrange(0, 30)} for i in range(count)]
            feasible = []
            for flags in itertools.product([False, True], repeat=count):
                indices = tuple(i for i, flag in enumerate(flags) if flag)
                used = sum(tasks[i]["minutes"] for i in indices)
                value = sum(tasks[i]["value"] for i in indices)
                if used <= budget:
                    feasible.append((value, used, indices))
            best = min(feasible, key=lambda x: (-x[0], x[1], x[2]))
            result = q.plan_tasks(tasks, budget)
            actual = (result["total_value"], result["used_minutes"],
                      tuple(int(x["name"]) for x in result["selected"]))
            self.assertEqual(actual, best)

    def test_tasks_only_once(self):
        result = q.plan_tasks([{"name": "a", "minutes": 1, "value": 1}], 10)
        self.assertEqual(result["total_value"], 1)

    def test_rejected_inputs(self):
        cases = [[], {}, [1], [{"name": "a", "minutes": True, "value": 1}],
                 [{"name": "a", "minutes": 1, "value": -1}],
                 [{"name": "a", "minutes": 1, "value": Decimal("1.5")}],
                 [{"name": "a", "minutes": 1, "value": 1}] * 2]
        for tasks in cases:
            with self.assertRaises(q.InputError):
                q.plan_tasks(tasks, 30)
        with self.assertRaises(q.InputError):
            q.plan_tasks([{"name": "a", "minutes": 1, "value": 1}], 1441)


class DiffAndBudgetTests(unittest.TestCase):
    def test_diff(self):
        self.assertEqual(q.compare_text({"before": "a", "after": "a"}), "内容完全一致。")
        result = q.compare_text({"before": "a\n", "after": "b"})
        self.assertIn("-a\n+b\n", result)
        self.assertIn("\\ No newline at end of file", result)

    def test_diff_limit(self):
        with self.assertRaises(q.InputError):
            q.compare_text({"before": "a\n" * 2001, "after": "b"})
        with self.assertRaises(q.InputError):
            q.compare_text({"before": 1, "after": "b"})

    def test_budget(self):
        result = q.budget_plan(81, 35, 180)
        self.assertEqual(result["maximum_spend_percentage_points"], 46)
        self.assertEqual(result["checkpoints"][-1]["minimum_remaining_percent"], 35)
        self.assertEqual(len(q.budget_plan(10, 10, 1)["checkpoints"]), 1)

    def test_budget_errors(self):
        for remaining, reserve, minutes in [(20, 30, 60), (float("nan"), 0, 1),
                                             (float("inf"), 0, 1), (81, -1, 1),
                                             (101, 30, 1), (81, 30, 0)]:
            with self.assertRaises(q.InputError):
                q.budget_plan(remaining, reserve, minutes)

    def test_control_characters(self):
        self.assertEqual(q.terminal_safe("a\x1b[31m\r\u202e\nb"), "a\\u001b[31m\\r\\u202e\nb")


class MazeTests(unittest.TestCase):
    def test_perfect_maze_invariants(self):
        for width, height, seed in [(2, 2, 0), (25, 17, 20261102), (41, 31, -1)]:
            graph = maze.generate(width, height, seed)
            self.assertEqual(len(graph), width * height)
            self.assertEqual(sum(map(len, graph)), 2 * (len(graph) - 1))
            seen, pending = {0}, [0]
            while pending:
                current = pending.pop()
                for target in graph[current]:
                    self.assertIn(current, graph[target])
                    distance = abs(current % width - target % width) + abs(current // width - target // width)
                    self.assertEqual(distance, 1)
                    if target not in seen:
                        seen.add(target)
                        pending.append(target)
            self.assertEqual(len(seen), len(graph))
            route = maze.solve(graph)
            self.assertEqual((route[0], route[-1]), (0, len(graph) - 1))
            self.assertEqual(len(set(route)), len(route))
            for a, b in zip(route, route[1:]):
                self.assertIn(b, graph[a])

    def test_deterministic_and_svg(self):
        self.assertEqual(maze.generate(5, 5, 1), maze.generate(5, 5, 1))
        self.assertNotEqual(maze.generate(5, 5, 1), maze.generate(5, 5, 2))
        for solution in (True, False):
            root = ET.fromstring(maze.render_svg(solution=solution))
            self.assertEqual(root.tag, "{http://www.w3.org/2000/svg}svg")
            self.assertEqual("<polyline" in maze.render_svg(solution=solution), solution)

    def test_limits(self):
        for width, height, seed in [(1, 10, 0), (42, 10, 0), (10, 32, 0), (5, 5, 2**31)]:
            with self.assertRaises(ValueError):
                maze.generate(width, height, seed)


class CliTests(unittest.TestCase):
    def run_cli(self, *args, source=""):
        return subprocess.run([sys.executable, "-B", str(ROOT / "quietlab.py"), *args],
                              input=source, capture_output=True, text=True, timeout=5)

    def test_commands(self):
        cases = [("calc", ["0.1+0.2"], ""), ("text", [], "你好 hello"),
                 ("json", ["--sort-keys"], '{"b":2,"a":1.1}'),
                 ("csv", [], "a,b\n1,2\n"),
                 ("plan", ["--minutes", "10"], '[{"name":"a","minutes":5,"value":2}]'),
                 ("diff", [], '{"before":"a","after":"b"}'),
                 ("budget", ["--remaining", "81", "--minutes", "180"], "")]
        for command, args, source in cases:
            with self.subTest(command=command):
                result = self.run_cli(command, *args, source=source)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout)
                self.assertEqual(result.stderr, "")

    def test_error_status(self):
        result = self.run_cli("calc", "1/0")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_utf8(self):
        result = subprocess.run([sys.executable, "-B", str(ROOT / "quietlab.py"), "text"],
                                input=b"\xff", capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)

    def test_no_capability_imports_or_unsafe_calls(self):
        forbidden_imports = {"os", "socket", "subprocess", "shutil", "urllib", "pathlib"}
        forbidden_calls = {"open", "eval", "exec", "compile", "__import__"}
        for filename in ("quietlab.py", "maze.py", "menu.py", "units.py"):
            tree = ast.parse((ROOT / filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({name.name.split(".")[0] for name in node.names} & forbidden_imports)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn(node.module.split(".")[0], forbidden_imports)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, forbidden_calls)


if __name__ == "__main__":
    unittest.main()
