#!/usr/bin/env python3
"""QuietLab: bounded, offline, standard-library tools; input in, output out.

Python 3.9+. This program never opens files, launches subprocesses, accesses the
network, or stores state. Pipe input explicitly; redirect output only if wanted.
"""
import argparse
import ast
import csv
import difflib
import io
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from decimal import Decimal, DecimalException, Underflow, localcontext

VERSION = "1.1.0"
MAX_INPUT = 1_048_576
MAX_EXPRESSION = 1024
MAX_AST_NODES = 160
MAX_DEPTH = 24
MAX_DECIMAL_DIGITS = 1000
MAX_OUTPUT = 2_097_152
MAX_JSON_NODES = 50000
MAX_JSON_DEPTH = 32


class InputError(ValueError):
    """A rejected input, safe to show without a traceback."""


def read_input(stream=None):
    """Read at most one MiB of UTF-8, without reading one byte past the cap+1."""
    stream = stream if stream is not None else sys.stdin.buffer
    data = stream.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise InputError("输入超过 1 MiB 上限。请先缩小数据。")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InputError("输入必须是 UTF-8 文本。") from None


def parse_json(source):
    """Strict JSON: reject NaN, Infinity, duplicate keys and large integers."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InputError("JSON 中有重复键：" + repr(key)[:100])
            result[key] = value
        return result

    def integer(value):
        if len(value.lstrip("-")) > 1000:
            raise InputError("JSON 整数超过 1000 位上限。")
        return int(value)

    def real(value):
        try:
            number = Decimal(value)
        except DecimalException:
            raise InputError("JSON 数值超出可表示范围。") from None
        if not number.is_finite() or abs(number.adjusted()) > 1000:
            raise InputError("JSON 数值超出可表示范围。")
        return number

    def constant(value):
        raise InputError("JSON 不允许 " + value)

    try:
        result = json.loads(source, object_pairs_hook=pairs, parse_int=integer,
                            parse_float=real, parse_constant=constant)
        pending = [(result, 0)]
        nodes = 0
        while pending:
            value, depth = pending.pop()
            nodes += 1
            if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
                raise InputError("JSON 超过 32 层或 50000 个节点的上限。")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        return result
    except json.JSONDecodeError as error:
        raise InputError("JSON 错误：第 %d 行，第 %d 列：%s" %
                         (error.lineno, error.colno, error.msg)) from None
    except (RecursionError, OverflowError):
        raise InputError("JSON 嵌套或数值过大。") from None


def dump_json(value, sort_keys=False):
    """Bounded incremental formatting, preserving Decimal values exactly."""
    chunks, size = [], 0

    def emit(chunk):
        nonlocal size
        chunk = terminal_safe(chunk)
        size += len(chunk.encode("utf-8"))
        if size > MAX_OUTPUT:
            raise InputError("输出超过 2 MiB 上限；请缩小输入。")
        chunks.append(chunk)

    def walk(item, depth):
        if depth > MAX_JSON_DEPTH:
            raise InputError("JSON 嵌套超过 32 层。")
        if isinstance(item, (list, dict)):
            mapping = isinstance(item, dict)
            emit("{" if mapping else "[")
            entries = list(item.items()) if mapping else list(enumerate(item))
            if mapping and sort_keys:
                entries.sort(key=lambda pair: pair[0])
            for index, (key, child) in enumerate(entries):
                emit((",\n" if index else "\n") + "  " * (depth + 1))
                if mapping:
                    emit(json.dumps(key, ensure_ascii=False) + ": ")
                walk(child, depth + 1)
            if entries:
                emit("\n" + "  " * depth)
            emit("}" if mapping else "]")
        elif isinstance(item, Decimal):
            if not item.is_finite():
                raise InputError("JSON 数值必须有限。")
            emit(str(item))
        else:
            try:
                emit(json.dumps(item, ensure_ascii=False, allow_nan=False))
            except (ValueError, TypeError):
                raise InputError("结果超出 JSON 输出范围。") from None

    walk(value, 0)
    return "".join(chunks)


def calculate(source):
    """Interpret arithmetic AST, never eval/exec. Decimal precision is 40."""
    if not source.strip() or len(source) > MAX_EXPRESSION:
        raise InputError("表达式需为 1–1024 个字符。")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (SyntaxError, RecursionError, MemoryError):
        raise InputError("表达式语法不正确或过于复杂。") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise InputError("表达式节点过多。")
    expression = source.strip()

    def bounded(number):
        if not number.is_finite() or (number and abs(number.adjusted()) > 1000):
            raise InputError("结果数量级超过允许范围（10 的 ±1000 次方）。")
        return number

    def visit(node, depth=0):
        if depth > MAX_DEPTH:
            raise InputError("表达式嵌套过深。")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            raw = ast.get_source_segment(expression, node).replace("_", "")
            if not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", raw):
                raise InputError("只支持十进制数字。")
            if len(raw) > MAX_DECIMAL_DIGITS:
                raise InputError("数字过长。")
            return bounded(Decimal(raw))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = visit(node.operand, depth + 1)
            return bounded(result if isinstance(node.op, ast.UAdd) else -result)
        if isinstance(node, ast.BinOp):
            left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return bounded(left + right)
            if isinstance(node.op, ast.Sub):
                return bounded(left - right)
            if isinstance(node.op, ast.Mult):
                return bounded(left * right)
            if isinstance(node.op, ast.Div):
                return bounded(left / right)
            if isinstance(node.op, ast.Pow):
                if right != right.to_integral_value() or abs(right) > 100:
                    raise InputError("幂指数必须是 -100 到 100 的整数。")
                return bounded(left ** int(right))
            raise InputError("只支持 +、-、*、/、** 运算。")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.keywords or not 1 <= len(node.args) <= 16:
                raise InputError("函数需要 1–16 个位置参数。")
            name = node.func.id
            if name not in ("abs", "min", "max", "sqrt"):
                raise InputError("只支持 abs、min、max、sqrt 函数。")
            values = [visit(arg, depth + 1) for arg in node.args]
            if name in ("abs", "sqrt") and len(values) != 1:
                raise InputError(name + " 只接受一个参数。")
            if name == "abs":
                return bounded(abs(values[0]))
            if name == "sqrt":
                return bounded(values[0].sqrt())
            return (min if name == "min" else max)(values)
        raise InputError("表达式中有不支持的语法。")

    try:
        with localcontext() as context:
            context.prec = 40
            context.Emax = 1100
            context.Emin = -1100
            context.traps[Underflow] = True
            value = visit(tree.body)
            return format(value, "f") if abs(value.adjusted()) < 50 else str(value)
    except DecimalException:
        raise InputError("无法计算：除零、负数开方或数值越界。") from None


def text_statistics(source):
    counts = Counter(source)
    lines = source.splitlines()
    duplicate = Counter(line for line in lines if line.strip())
    han = sum("\u3400" <= c <= "\u4dbf" or "\u4e00" <= c <= "\u9fff" or
              "\U00020000" <= c <= "\U000323af" for c in source)
    words = re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*", source)
    controls = Counter("U+%04X" % ord(c) for c in source
                       if unicodedata.category(c).startswith("C") and c not in "\n\r\t")
    return {
        "utf8_bytes": len(source.encode("utf-8")),
        "unicode_codepoints": len(source),
        "non_whitespace_codepoints": sum(not c.isspace() for c in source),
        "lines": len(lines),
        "blank_lines": sum(not line.strip() for line in lines),
        "han_codepoints": han,
        "latin_words": len(words),
        "unique_codepoints": len(counts),
        "character_entropy_bits": round(-sum(n / len(source) * math.log2(n / len(source))
                                               for n in counts.values()), 6) if source else 0,
        "duplicate_nonblank_lines": [
            {"text": line[:240], "count": count, "truncated": len(line) > 240}
            for line, count in duplicate.most_common() if count > 1][:20],
        "unusual_control_codepoints": dict(controls),
    }


def csv_profile(source, delimiter=","):
    """Describe bounded CSV with explicit delimiter and first-row headings."""
    if delimiter not in (",", "\t", ";", "|"):
        raise InputError("分隔符仅支持逗号、tab、分号、竖线。")
    reader = csv.reader(io.StringIO(source, newline=""), delimiter=delimiter, strict=True)
    try:
        header = next(reader, None)
        if not header:
            raise InputError("CSV 缺少表头。")
        if len(header) > 100:
            raise InputError("CSV 最多支持 100 列。")
        stats = [{"name": name, "index": i + 1, "nonempty": 0, "empty": 0,
                  "numeric": 0, "minimum": None, "maximum": None}
                 for i, name in enumerate(header)]
        ragged, row_count = [], 0
        for row in reader:
            # csv.reader skips physically empty lines; a row containing "" is data.
            row_count += 1
            if row_count > 20000:
                raise InputError("CSV 最多支持 20000 行数据。")
            if len(row) != len(header):
                if len(ragged) < 20:
                    ragged.append({"data_row": row_count, "fields": len(row)})
                continue
            for value, stat in zip(row, stats):
                if not value.strip():
                    stat["empty"] += 1
                    continue
                stat["nonempty"] += 1
                if len(value) > 1000:
                    continue
                # Decimal accepts Unicode digits; use a predictable decimal grammar.
                if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value.strip()):
                    continue
                try:
                    number = Decimal(value.strip())
                    if not number.is_finite() or abs(number.adjusted()) > 1000:
                        continue
                except DecimalException:
                    continue
                stat["numeric"] += 1
                stat["minimum"] = number if stat["minimum"] is None else min(stat["minimum"], number)
                stat["maximum"] = number if stat["maximum"] is None else max(stat["maximum"], number)
    except (csv.Error, OverflowError) as error:
        raise InputError("CSV 错误：" + str(error)) from None
    for stat in stats:
        for key in ("minimum", "maximum"):
            if stat[key] is not None:
                stat[key] = str(stat[key])
    return {"data_rows": row_count, "columns": stats,
            "malformed_rows_count": row_count - stats[0]["empty"] - stats[0]["nonempty"],
            "malformed_rows_first_20": ragged,
            "duplicate_headers": [name for name, count in Counter(header).items() if count > 1]}


def plan_tasks(data, minutes):
    """Exact 0/1 knapsack under a minute budget, bounded to 100 x 1440 states.

    Tasks are independent and indivisible; value is user-supplied, not inferred.
    Ties prefer less time, then the lexicographically smaller tuple of indices.
    """
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise InputError("时间预算需为 1–1440 的整数分钟。")
    if not isinstance(data, list) or not 1 <= len(data) <= 100:
        raise InputError("任务需为包含 1–100 项的 JSON 数组。")
    names = set()
    for task in data:
        if not isinstance(task, dict) or set(task) != {"name", "minutes", "value"}:
            raise InputError("每项任务需要且仅需要 name、minutes、value 字段。")
        name = task["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 100 or name in names:
            raise InputError("任务名称需唯一、非空，最多 100 个字符。")
        names.add(name)
        if type(task["minutes"]) is not int or not 1 <= task["minutes"] <= 1440:
            raise InputError("任务 minutes 需为 1–1440 的整数。")
        if type(task["value"]) is not int or not 0 <= task["value"] <= 1000000:
            raise InputError("任务 value 需为 0–1000000 的整数。")
    # Store immutable paths, so each task can only be used once.
    states = [None] * (minutes + 1)
    states[0] = (0, ())
    for index, task in enumerate(data):
        cost = task["minutes"]
        if task["value"] == 0:
            continue
        for used in range(minutes, cost - 1, -1):
            previous = states[used - cost]
            if previous is None:
                continue
            candidate = (previous[0] + task["value"], previous[1] + (index,))
            existing = states[used]
            if existing is None or candidate[0] > existing[0] or (
                    candidate[0] == existing[0] and candidate[1] < existing[1]):
                states[used] = candidate
    best_used = max(range(minutes + 1), key=lambda i: (
        states[i][0] if states[i] else -1, -i))
    value, indices = states[best_used]
    chosen = set(indices)
    return {"budget_minutes": minutes, "used_minutes": best_used,
            "remaining_minutes": minutes - best_used, "total_value": value,
            "selected": [task for i, task in enumerate(data) if i in chosen],
            "unselected": [task for i, task in enumerate(data) if i not in chosen]}


def compare_text(data, context=3):
    if not isinstance(data, dict) or set(data) != {"before", "after"} or not all(
            isinstance(data[k], str) for k in ("before", "after")):
        raise InputError('比较输入必须是 {"before": "…", "after": "…"}。')
    before, after = data["before"], data["after"]
    if before == after:
        return "内容完全一致。"
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    if max(len(a), len(b)) > 2000 or max(len(before), len(after)) > 100000:
        raise InputError("比较上限为每侧 2000 行、100000 字符。")
    # Disable no heuristics: difflib's default autojunk bounds common repeated lines.
    parts = []
    for line in difflib.unified_diff(a, b, fromfile="before", tofile="after", n=context):
        if line.endswith("\n"):
            parts.append(line)
        else:
            parts.append(line + "\n\\ No newline at end of file\n")
    return "".join(parts)


def budget_plan(remaining, reserve, minutes):
    for value in (remaining, reserve):
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise InputError("额度百分比需为 0–100 的有限数。")
    if reserve > remaining:
        raise InputError("预留额度不能大于当前剩余额度。")
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise InputError("时间需为 1–1440 分钟。")
    available = remaining - reserve
    checkpoints = []
    # A ceiling for cumulative consumption, never a demand to use the allowance.
    for elapsed in sorted(set([min(30, minutes), min(60, minutes),
                               min(120, minutes), minutes])):
        spent = available * elapsed / minutes
        checkpoints.append({"elapsed_minutes": elapsed,
                            "maximum_cumulative_spend_percentage_points": round(spent, 2),
                            "minimum_remaining_percent": round(remaining - spent, 2)})
    return {"starting_remaining_percent": remaining, "reserve_percent": reserve,
            "maximum_spend_percentage_points": round(available, 2),
            "duration_minutes": minutes, "checkpoints": checkpoints,
            "note": "仅为手动规划；不读取实时额度、不限制模型调用，也不保证用量。达到预留线应停止。"}


def build_parser():
    parser = argparse.ArgumentParser(
        description="QuietLab：离线、零依赖、输入输出式的小工具箱。不会保存文件。")
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    calc = commands.add_parser("calc", help="安全十进制计算；不执行 Python 代码")
    calc.add_argument("expression", help="表达式；以 - 开头时在表达式前加 --")
    commands.add_parser("text", help="从标准输入读取 UTF-8 文本并统计")
    js = commands.add_parser("json", help="严格校验 JSON，格式化到标准输出")
    js.add_argument("--sort-keys", action="store_true")
    csv_cmd = commands.add_parser("csv", help="概览标准输入中的 CSV；首行为表头")
    csv_cmd.add_argument("--delimiter", choices=[",", "tab", ";", "|"], default=",")
    plan = commands.add_parser("plan", help="选择时间预算内总价值最高的独立任务")
    plan.add_argument("--minutes", required=True, type=int)
    diff = commands.add_parser("diff", help="比较 JSON 中 before / after 两段文本")
    diff.add_argument("--context", type=int, choices=range(0, 11), default=3)
    budget = commands.add_parser("budget", help="手动规划额度；不会读取账户或调用模型")
    budget.add_argument("--remaining", required=True, type=float)
    budget.add_argument("--reserve", type=float, default=30)
    budget.add_argument("--minutes", required=True, type=int)
    return parser


def terminal_safe(text):
    """Render nonprinting control/format characters instead of executing them."""
    return "".join(json.dumps(char, ensure_ascii=True)[1:-1]
                   if unicodedata.category(char).startswith("C") and char not in "\n\t"
                   else char for char in text)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "calc":
            result = calculate(args.expression)
        elif args.command == "budget":
            result = dump_json(budget_plan(args.remaining, args.reserve, args.minutes))
        else:
            source = read_input()
            if args.command == "text":
                result = dump_json(text_statistics(source))
            elif args.command == "json":
                parsed = parse_json(source)
                result = dump_json(parsed, sort_keys=args.sort_keys)
            elif args.command == "csv":
                result = dump_json(csv_profile(source, "\t" if args.delimiter == "tab" else args.delimiter))
            elif args.command == "plan":
                result = dump_json(plan_tasks(parse_json(source), args.minutes))
            elif args.command == "diff":
                result = compare_text(parse_json(source), args.context)
        result = terminal_safe(result)
        if len(result.encode("utf-8")) > MAX_OUTPUT:
            raise InputError("输出超过 2 MiB 上限；请缩小输入。")
        sys.stdout.write(result)
        if not result.endswith("\n"):
            sys.stdout.write("\n")
        return 0
    except (InputError, RecursionError, ValueError) as error:
        message = terminal_safe(str(error)).replace("\n", "\\n").replace("\t", "\\t")
        sys.stderr.write("错误：" + message[:500] + "\n")
        return 2
    except (BrokenPipeError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
