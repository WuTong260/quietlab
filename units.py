#!/usr/bin/env python3
"""Bounded unit conversion using exact rational factors; no I/O except CLI."""
import argparse
import re
import sys
from dataclasses import dataclass
from decimal import Decimal, DecimalException, Underflow, localcontext
from fractions import Fraction

import quietlab as q


@dataclass(frozen=True)
class Unit:
    dimension: str
    factor: Fraction
    offset: Fraction = Fraction(0)


def unit(dimension, factor, offset="0"):
    return Unit(dimension, Fraction(factor), Fraction(offset))


UNITS = {
    "m": unit("length", "1"), "km": unit("length", "1000"),
    "cm": unit("length", "0.01"), "mm": unit("length", "0.001"),
    "um": unit("length", "0.000001"), "in": unit("length", "0.0254"),
    "ft": unit("length", "0.3048"), "yd": unit("length", "0.9144"),
    "mi": unit("length", "1609.344"), "nmi": unit("length", "1852"),
    "kg": unit("mass", "1"), "g": unit("mass", "0.001"),
    "mg": unit("mass", "0.000001"), "t": unit("mass", "1000"),
    "lb": unit("mass", "0.45359237"), "oz": unit("mass", "0.028349523125"),
    "s": unit("time", "1"), "ms": unit("time", "0.001"),
    "us": unit("time", "0.000001"), "min": unit("time", "60"),
    "h": unit("time", "3600"), "day": unit("time", "86400"),
    "m/s": unit("speed", "1"), "km/h": unit("speed", "5/18"),
    "mph": unit("speed", "0.44704"), "kn": unit("speed", "463/900"),
    "B": unit("data", "1"), "bit": unit("data", "1/8"),
    "KB": unit("data", "1000"), "MB": unit("data", "1000000"),
    "GB": unit("data", "1000000000"), "TB": unit("data", "1000000000000"),
    "KiB": unit("data", "1024"), "MiB": unit("data", "1048576"),
    "GiB": unit("data", "1073741824"), "TiB": unit("data", "1099511627776"),
    "K": unit("temperature", "1"),
    "C": unit("temperature", "1", "273.15"),
    "F": unit("temperature", "5/9", "45967/180"),
}

ALIASES = {
    "米": "m", "千米": "km", "公里": "km", "厘米": "cm", "毫米": "mm",
    "微米": "um", "µm": "um", "μm": "um", "英寸": "in", "英尺": "ft", "英里": "mi",
    "千克": "kg", "公斤": "kg", "克": "g", "毫克": "mg", "吨": "t", "磅": "lb",
    "秒": "s", "毫秒": "ms", "微秒": "us", "分钟": "min", "小时": "h", "天": "day",
    "字节": "B", "比特": "bit", "kB": "KB",
    "°C": "C", "℃": "C", "摄氏度": "C", "°F": "F", "℉": "F", "华氏度": "F", "开尔文": "K",
}


def resolve(name):
    if not isinstance(name, str) or len(name) > 30:
        raise q.InputError("单位名称过长或类型不正确。")
    name = name.strip()
    name = ALIASES.get(name, name)
    if name not in UNITS:
        raise q.InputError("未知单位：%s；使用 units.py --list 查看。" % q.terminal_safe(name))
    return name, UNITS[name]


def convert(expression, source, target):
    source_name, source_unit = resolve(source)
    target_name, target_unit = resolve(target)
    if source_unit.dimension != target_unit.dimension:
        raise q.InputError("不能换算不同维度的单位。")
    validated = q.calculate(expression)
    literal = expression.strip().replace("_", "")
    # Preserve a plain literal before checking physical bounds. Expressions use
    # the calculator's documented 40-digit working precision.
    if re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", literal):
        value = Fraction(Decimal(literal))
    else:
        value = Fraction(Decimal(validated))
    base = value * source_unit.factor + source_unit.offset
    if source_unit.dimension == "temperature" and base < 0:
        raise q.InputError("绝对温度不能低于 0 K。")
    result = (base - target_unit.offset) / target_unit.factor
    try:
        with localcontext() as context:
            context.prec = 40
            context.Emax, context.Emin = 1100, -1100
            context.traps[Underflow] = True
            number = Decimal(result.numerator) / Decimal(result.denominator)
            if number and abs(number.adjusted()) > 1000:
                raise q.InputError("换算结果数量级超过 ±1000 的范围。")
            # Normalize within the same precision context, without rounding again.
            number = number.normalize() if number else Decimal(0)
            return format(number, "f") if abs(number.adjusted()) < 50 else str(number)
    except DecimalException:
        raise q.InputError("换算结果超出允许范围。") from None


def list_units():
    labels = {"length": "长度", "mass": "质量", "time": "时间", "speed": "速度",
              "data": "数据量", "temperature": "温度（绝对温度）"}
    return "\n".join(label + "：" + " / ".join(
        name for name, value in UNITS.items() if value.dimension == dimension)
        for dimension, label in labels.items())


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线单位换算；有理数换算系数，40 位十进制结果。")
    parser.add_argument("--list", action="store_true", help="列出支持的单位")
    parser.add_argument("expression", nargs="?")
    parser.add_argument("source", nargs="?")
    parser.add_argument("target", nargs="?")
    args = parser.parse_args(argv)
    if args.list:
        print(list_units())
        return 0
    if None in (args.expression, args.source, args.target):
        parser.error("需要数值表达式、原单位和目标单位；或使用 --list")
    try:
        print(convert(args.expression, args.source, args.target))
        return 0
    except q.InputError as error:
        sys.stderr.write("错误：" + q.terminal_safe(str(error)).replace("\n", "\\n") + "\n")
        return 2
    except (BrokenPipeError, KeyboardInterrupt):
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
