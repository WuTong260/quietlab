#!/usr/bin/env python3
"""Deterministic perfect mazes, no files/network/dependencies. SVG to stdout."""
import argparse
import random
import sys
from collections import deque


def generate(width, height, seed):
    if type(width) is not int or type(height) is not int or not (
            2 <= width <= 41 and 2 <= height <= 31):
        raise ValueError("宽度需为 2–41，高度需为 2–31。")
    if type(seed) is not int or not -(2 ** 31) <= seed < 2 ** 31:
        raise ValueError("seed 需为 32 位有符号整数。")
    rng = random.Random(seed)
    graph = [[] for _ in range(width * height)]
    visited, stack = {0}, [0]
    while stack:
        current = stack[-1]
        x, y = current % width, current // width
        candidates = []
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            nx, ny = x + dx, y + dy
            target = ny * width + nx
            if 0 <= nx < width and 0 <= ny < height and target not in visited:
                candidates.append(target)
        if not candidates:
            stack.pop()
            continue
        following = rng.choice(candidates)
        graph[current].append(following)
        graph[following].append(current)
        visited.add(following)
        stack.append(following)
    return graph


def solve(graph):
    """Breadth-first path, including entrance and exit cells."""
    previous, pending = {0: None}, deque([0])
    goal = len(graph) - 1
    while pending:
        current = pending.popleft()
        if current == goal:
            path = []
            while current is not None:
                path.append(current)
                current = previous[current]
            return list(reversed(path))
        for target in graph[current]:
            if target not in previous:
                previous[target] = current
                pending.append(target)
    raise ValueError("迷宫没有可达出口。")


def render_svg(width=25, height=17, seed=20261102, solution=False):
    graph = generate(width, height, seed)
    path = solve(graph)
    cell, left, top = 22, 24, 60
    w, h = width * cell + 48, height * cell + 108
    walls = []
    # Open top edge at the first cell, bottom edge at the final cell.
    walls.append("M %d %d H %d" % (left + cell, top, left + width * cell))
    walls.append("M %d %d H %d" % (left, top + height * cell, left + (width - 1) * cell))
    walls.append("M %d %d V %d" % (left, top, top + height * cell))
    walls.append("M %d %d V %d" % (left + width * cell, top, top + height * cell))
    for index, neighbors in enumerate(graph):
        x, y = left + index % width * cell, top + index // width * cell
        if index % width < width - 1 and index + 1 not in neighbors:
            walls.append("M %d %d v %d" % (x + cell, y, cell))
        if index // width < height - 1 and index + width not in neighbors:
            walls.append("M %d %d h %d" % (x, y + cell, cell))
    route = ""
    if solution:
        points = ["%g,%g" % (left + cell / 2, top - 7)]
        points += ["%g,%g" % (left + (i % width + .5) * cell,
                              top + (i // width + .5) * cell) for i in path]
        points += ["%g,%g" % (left + (width - .5) * cell, top + height * cell + 7)]
        route = '<polyline points="%s" fill="none" stroke="#c45a28" stroke-width="3" stroke-linejoin="round"/>' % " ".join(points)
    return '''<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" role="img" aria-labelledby="title desc">
<title id="title">QuietLab · 迷宫 %d × %d</title>
<desc id="desc">从左上开口进入，到右下开口离开。种子 %d。%s</desc>
<rect width="100%%" height="100%%" fill="#f8f6f0"/>
<g fill="#243b40" font-family="system-ui, sans-serif">
<text x="24" y="30" font-size="18">QUIETLAB / 迷宫散步</text>
<text x="24" y="%d" font-size="12">%d × %d · seed %d%s</text></g>
%s
<path d="%s" stroke="#243b40" stroke-width="1.8" fill="none" stroke-linecap="square"/>
</svg>''' % (w, h, w, h, width, height, seed,
            "已显示答案。" if solution else "未显示答案。", h - 18,
            width, height, seed, " · %d 步" % (len(path) - 1) if solution else "",
            route, " ".join(walls))


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线生成可打印的迷宫 SVG；仅输出到标准输出。")
    parser.add_argument("--width", type=int, default=25)
    parser.add_argument("--height", type=int, default=17)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--solution", action="store_true")
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(render_svg(args.width, args.height, args.seed, args.solution) + "\n")
        return 0
    except ValueError as error:
        sys.stderr.write("错误：" + str(error) + "\n")
        return 2
    except (BrokenPipeError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
