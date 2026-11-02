#!/usr/bin/env python3
"""QuietLab's offline terminal menu. No persistence or file/network access."""
import sys
from collections import deque

import maze
import quietlab as q
import units


class EndSession(Exception):
    pass


class CancelAction(Exception):
    pass


class Console:
    def __init__(self, source=None, output=None):
        self.source = source if source is not None else sys.stdin
        self.output = output if output is not None else sys.stdout

    def write(self, message=""):
        message = q.terminal_safe(str(message))
        if len(message.encode("utf-8")) > q.MAX_OUTPUT:
            raise q.InputError("输出超过 2 MiB 上限。")
        self.output.write(message + "\n")
        self.output.flush()

    def line(self, prompt, maximum=1024):
        self.output.write(prompt)
        self.output.flush()
        line = self.source.readline(maximum + 2)
        if not line:
            raise EndSession()
        # Abort rather than interpreting an unread oversized suffix as commands.
        if len(line.encode("utf-8")) > maximum + (1 if line.endswith("\n") else 0):
            self.write("输入超过上限，已结束会话。")
            raise EndSession()
        line = line.removesuffix("\n").removesuffix("\r")
        if line == ":cancel":
            raise CancelAction()
        return line

    def block(self, title):
        self.write(title + "（单独一行 . 结束；.. 表示一个点；:cancel 返回）")
        lines, size = [], 0
        for _ in range(20000):
            line = self.line("", q.MAX_INPUT)
            if line == ".":
                # A typed line represents one newline, including a final newline.
                return "".join(lines)
            if line == "..":
                line = "."
            size += len(line.encode("utf-8")) + 1
            if size > q.MAX_INPUT:
                self.write("输入超过 1 MiB 上限，已结束会话。")
                raise EndSession()
            lines.append(line + "\n")
        self.write("输入超过 20000 行上限，已结束会话。")
        raise EndSession()

    def integer(self, prompt, minimum, maximum, default=None):
        raw = self.line(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise q.InputError("请输入整数。") from None
        if not minimum <= value <= maximum:
            raise q.InputError("整数需在 %d–%d 之间。" % (minimum, maximum))
        return value


def route_to_exit(graph, start):
    previous, pending = {start: None}, deque([start])
    while pending:
        current = pending.popleft()
        if current == len(graph) - 1:
            route = []
            while current is not None:
                route.append(current)
                current = previous[current]
            return list(reversed(route))
        for neighbor in graph[current]:
            if neighbor not in previous:
                previous[neighbor] = current
                pending.append(neighbor)
    raise q.InputError("没有可达出口。")


def board_text(graph, width, height, player, visited):
    cells = [["#"] * (width * 2 + 1) for _ in range(height * 2 + 1)]
    cells[0][1], cells[-1][-2] = " ", " "
    for index, neighbors in enumerate(graph):
        x, y = index % width * 2 + 1, index // width * 2 + 1
        cells[y][x] = "." if index in visited else " "
        for neighbor in neighbors:
            nx, ny = neighbor % width * 2 + 1, neighbor // width * 2 + 1
            cells[(y + ny) // 2][(x + nx) // 2] = " "
    cells[1][1] = "S"
    cells[-2][-2] = "E"
    cells[player // width * 2 + 1][player % width * 2 + 1] = "@"
    return "\n".join("".join(row) for row in cells)


def play_maze(console):
    width = console.integer("宽度 2–25 [15]：", 2, 25, 15)
    height = console.integer("高度 2–17 [9]：", 2, 17, 9)
    seed = console.integer("种子 [20261102]：", -(2 ** 31), 2 ** 31 - 1, 20261102)
    graph = maze.generate(width, height, seed)
    player, steps, visited = 0, 0, {0}
    console.write("@ 是你，E 是出口，. 是走过的格子；w/a/s/d 移动，h 提示，r 重来，q 返回。")
    while True:
        console.write(board_text(graph, width, height, player, visited))
        if player == len(graph) - 1:
            console.write("抵达出口！实际 %d 步，最短 %d 步。" % (steps, len(maze.solve(graph)) - 1))
            return
        command = console.line("移动：", 16).strip().lower()
        if command == "q":
            return
        if command == "r":
            player, steps, visited = 0, 0, {0}
            continue
        if command == "h":
            route = route_to_exit(graph, player)
            following = route[1]
            dx = following % width - player % width
            dy = following // width - player // width
            key = {(1, 0): "d（右）", (-1, 0): "a（左）", (0, 1): "s（下）", (0, -1): "w（上）"}[(dx, dy)]
            console.write("下一步：%s；距出口 %d 步。" % (key, len(route) - 1))
            continue
        if command not in ("w", "a", "s", "d"):
            console.write("请输入 w/a/s/d、h、r 或 q。")
            continue
        dx, dy = {"w": (0, -1), "a": (-1, 0), "s": (0, 1), "d": (1, 0)}[command]
        nx, ny = player % width + dx, player // width + dy
        target = ny * width + nx
        if not (0 <= nx < width and 0 <= ny < height) or target not in graph[player]:
            console.write("这边是墙。")
            continue
        player, steps = target, steps + 1
        visited.add(player)


def task_planner(console):
    minutes = console.integer("可用时间（1–1440 分钟）：", 1, 1440)
    tasks = []
    console.write("依次输入任务，名称留空结束；任务互相独立，每项最多做一次。")
    while len(tasks) < 100:
        name = console.line("任务名称：", 400).strip()
        if not name:
            break
        if len(name) > 100 or any(task["name"] == name for task in tasks):
            raise q.InputError("名称需唯一且最多 100 个字符。")
        duration = console.integer("所需分钟：", 1, 1440)
        value = console.integer("你的价值评分（0–1000000）：", 0, 1000000)
        tasks.append({"name": name, "minutes": duration, "value": value})
    result = q.plan_tasks(tasks, minutes)
    console.write("选中 %d 项，用时 %d/%d 分钟，总价值 %d。" % (
        len(result["selected"]), result["used_minutes"], minutes, result["total_value"]))
    for task in result["selected"]:
        console.write("  %s · %d 分钟 · 价值 %d" % (task["name"], task["minutes"], task["value"]))


def perform(choice, console):
    if choice == "1":
        console.write(q.calculate(console.line("表达式：")))
    elif choice == "2":
        console.write(q.dump_json(q.text_statistics(console.block("粘贴文本"))))
    elif choice == "3":
        console.write(q.dump_json(q.parse_json(console.block("粘贴 JSON"))))
    elif choice == "4":
        delimiter = console.line("分隔符 [, / tab / ; / |]，回车用逗号：").strip() or ","
        console.write(q.dump_json(q.csv_profile(console.block("粘贴 CSV"), "\t" if delimiter == "tab" else delimiter)))
    elif choice == "5":
        task_planner(console)
    elif choice == "6":
        before = console.block("原文本")
        after = console.block("新文本")
        console.write(q.compare_text({"before": before, "after": after}))
    elif choice == "7":
        try:
            remaining = float(console.line("当前剩余百分比（手动填写）："))
            reserve = float(console.line("希望预留百分比："))
        except ValueError:
            raise q.InputError("百分比需为数字。") from None
        minutes = console.integer("剩余分钟：", 1, 1440)
        console.write(q.dump_json(q.budget_plan(remaining, reserve, minutes)))
    elif choice == "8":
        play_maze(console)
    elif choice == "9":
        console.write(units.list_units())
        expression = console.line("数值或表达式：")
        source = console.line("原单位：", 120)
        target = console.line("目标单位：", 120)
        console.write(units.convert(expression, source, target) + " " + units.resolve(target)[0])
    else:
        console.write("请选择 1–9 或 q。")


def main(source=None, output=None):
    console = Console(source, output)
    try:
        console.write("QuietLab · 离线交互菜单\n输入只用于本次会话，结束后不保存；输入 :cancel 可返回菜单。")
        while True:
            console.write("\n1 计算器    2 文本概览    3 JSON 整理    4 CSV 概览\n5 任务规划  6 文本比较    7 额度规划     8 迷宫散步\n9 单位换算  q 退出")
            try:
                choice = console.line("选择：", 16).strip().lower()
                if choice == "q":
                    break
                perform(choice, console)
            except CancelAction:
                console.write("已返回菜单。")
            except (q.InputError, ValueError, RecursionError) as error:
                console.write("错误：" + str(error)[:500])
    except (EndSession, KeyboardInterrupt):
        console.write("\n会话结束。")
    except BrokenPipeError:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
