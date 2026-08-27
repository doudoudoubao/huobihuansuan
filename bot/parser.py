"""自然语言 + 算式解析器。

把用户随手打的一句话拆成「金额 / 源币种 / 目标币种 / 手续费」。

能吃下的写法（不完全列举）::

    100 usd cny            100usd cny          100 美元 人民币
    100美元换人民币          100刀多少人民币       1000円是多少钱
    $100 → ¥                usd cny             100 usd
    (23.5+40)*3 eur cny     99.9*12 usd         1.5k usd jpy
    10万日元 人民币           2w u cny            100 usd cny jpy krw
    100 usd cny +2%         100 usd cny 手续费1.5%
"""

from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException, InvalidOperation

from . import currencies as cur_mod

# --- 连接词：出现在句子里只起“连接”作用，解析前统一抹成空格 -------------------

_CJK_CONNECTORS: tuple[str, ...] = (
    "换算成", "换算", "兑换成", "兑换", "转换成", "折合成", "折合",
    "相当于", "等于多少", "等于", "是多少", "多少钱", "合多少", "值多少",
    "请帮我", "帮我查", "帮我", "请问", "查一下", "查询", "计算", "算一下", "算",
    "换成", "换", "兑", "转成", "转", "到", "变成", "成",
    "多少", "合", "值", "是", "大概", "约等于", "约", "现在", "今天",
    "的话", "的", "呢", "吗", "啊", "呀", "吧", "么", "嘛", "了",
)

_LATIN_CONNECTORS: tuple[str, ...] = (
    "convert", "converted", "exchange", "into", "equals", "equal",
    "worth", "much", "how", "what", "please", "pls", "plz",
    "to", "in", "is", "as", "for", "of", "at", "a", "the",
)

# 注意：不要把 `,` 和 `-` 放进来 —— 前者是千分位，后者是减号，都归表达式处理。
_PUNCT_CONNECTORS = str.maketrans({c: " " for c in "=?？!！~～、。；;:：·—–><»«›‹|"})

# --- 手续费 / 点差 ------------------------------------------------------------

_FEE_RE = re.compile(
    r"(?:(?P<kw>手续费|费率|加点|点差|服务费|fee|spread|markup)\s*(?P<kwsign>[+\-])?\s*(?P<kwval>\d+(?:\.\d+)?)\s*[%％])"
    r"|(?P<sign>[+\-])\s*(?P<val>\d+(?:\.\d+)?)\s*[%％]",
    re.IGNORECASE,
)

# --- 数量级后缀 ---------------------------------------------------------------

_MAGNITUDE_CJK: dict[str, int] = {
    "亿": 100000000,
    "千万": 10000000,
    "百万": 1000000,
    "万": 10000,
    "千": 1000,
    "百": 100,
}

#: 「数字 + 量级 + 可选尾数」。长单位排在前面，否则「千万」会被「千」先吃掉。
#: 尾数后面不能再跟量级字：「1亿2千万」里的 2 属于后面的千万，不是亿的尾数。
_MAGNITUDE_RE = re.compile(r"(\d+(?:\.\d+)?)(亿|千万|百万|万|千|百)(\d+(?![亿万千百]))?")

_MAGNITUDE_LATIN: dict[str, str] = {
    "k": "*1000",
    "w": "*10000",
    "m": "*1000000",
    "b": "*1000000000",
}

_MATH_CHARS = set("0123456789.+-*/()^ \t")

#: 键盘上打不出 × ÷ 的人会用别的字符代替，全角标点也很常见。
#: 这些如果不认，会被当成噪声直接丢掉 —— `18×12` 变 `1812`，静默算错。
_MATH_ALIASES = {
    "×": "*", "✕": "*", "✖": "*", "❌": "*", "∗": "*", "·": "*", "＊": "*",
    "÷": "/", "∕": "/", "／": "/", "⁄": "/", "➗": "/",
    "＋": "+", "➕": "+",
    "－": "-", "−": "-", "➖": "-",
    "（": "(", "）": ")",
}
#: 表情版的运算符（➗ ✖️）后面常跟一个变体选择符 U+FE0F，属于噪声，会被忽略。

#: 直接写「除以」「乘以」的也不少。这些字要限制在数字中间才当运算符 ——
#: 「加」本身就出现在货币名里（加元 / 加币），认宽了会把币种拆掉。
_WORD_OPERATORS = {
    "除以": "/", "除": "/",
    "乘以": "*", "乘": "*",
    "加上": "+", "加": "+",
    "减去": "-", "减": "-",
}
#: 长的排前面，否则「除以」会被「除」先吃掉一半
_WORD_OPERATORS_ORDERED = sorted(_WORD_OPERATORS, key=len, reverse=True)

_REGIONAL_INDICATOR = range(0x1F1E6, 0x1F200)


@dataclass(slots=True)
class ParseResult:
    """解析结果。source / targets 可能为空，交给上层用用户偏好补齐。"""

    amount: Decimal = Decimal(1)
    source: str | None = None
    targets: list[str] = field(default_factory=list)
    fee_percent: Decimal | None = None
    expression: str | None = None
    has_explicit_amount: bool = False
    unknown_tokens: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def is_actionable(self) -> bool:
        """是否值得当成一次换算请求来响应。"""
        return self.error is None and (self.source is not None or self.has_explicit_amount)


# --- 内部工具 -----------------------------------------------------------------


def _cjk_alias_buckets() -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {}
    for key in cur_mod.cjk_alias_pattern():
        buckets.setdefault(key[0], []).append(key)
    for key_list in buckets.values():
        key_list.sort(key=len, reverse=True)
    return buckets


_CJK_BUCKETS: dict[str, list[str]] = _cjk_alias_buckets()


def _strip_connectors(text: str) -> str:
    text = text.translate(_PUNCT_CONNECTORS)
    for word in _CJK_CONNECTORS:
        if word in text:
            text = text.replace(word, " ")
    if re.search(r"[a-z]", text):
        text = re.sub(
            r"\b(?:%s)\b" % "|".join(_LATIN_CONNECTORS),
            " ",
            text,
        )
    return re.sub(r"\s+", " ", text).strip()


def _extract_fee(text: str) -> tuple[str, Decimal | None]:
    """抽出手续费百分比并从原文里删掉。"""
    match = _FEE_RE.search(text)
    if not match:
        return text, None
    if match.group("kwval") is not None:
        raw = match.group("kwval")
        sign = match.group("kwsign") or "+"
    else:
        raw = match.group("val")
        sign = match.group("sign")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return text, None
    if sign == "-":
        value = -value
    cleaned = (text[: match.start()] + " " + text[match.end() :]).strip()
    return cleaned, value


def _read_flag(text: str, i: int) -> tuple[str | None, int]:
    """读取国旗 emoji（两个 regional indicator 组成）。"""
    if i + 1 < len(text) and ord(text[i]) in _REGIONAL_INDICATOR and ord(text[i + 1]) in _REGIONAL_INDICATOR:
        flag = text[i : i + 2]
        code = cur_mod.FLAG_MAP.get(flag)
        if code:
            return code, i + 2
    return None, i


def _scan(text: str, *, context: str | None) -> tuple[list[str], list[str], list[str]]:
    """扫描出货币序列、数学片段序列、无法识别的词。"""
    codes: list[str] = []
    segments: list[str] = [""]
    unknown: list[str] = []
    lowered = text.lower()
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        flag_code, new_i = _read_flag(text, i)
        if flag_code:
            codes.append(flag_code)
            segments.append("")
            i = new_i
            continue

        if ch in cur_mod.SYMBOL_MAP:
            resolved = cur_mod.resolve(ch, context=context)
            if resolved:
                codes.append(resolved.code)
                segments.append("")
                i += 1
                continue

        bucket = _CJK_BUCKETS.get(lowered[i])
        if bucket:
            matched = next((key for key in bucket if lowered.startswith(key, i)), None)
            if matched:
                codes.append(cur_mod.ALIAS_INDEX[matched])
                segments.append("")
                i += len(matched)
                continue

        # 放在货币名之后：「100加币」先被上面认成 CAD，轮不到这里当加号
        word_op = _read_word_operator(text, i, segments[-1])
        if word_op:
            operator, length = word_op
            segments[-1] = segments[-1].rstrip() + operator
            i += length
            continue

        if ch.isalpha() and ch.isascii():
            j = i
            while j < n and text[j].isalpha() and text[j].isascii():
                j += 1
            word = text[i:j]
            resolved = cur_mod.resolve(word, context=context)
            if resolved:
                codes.append(resolved.code)
                segments.append("")
            elif len(word) == 1 and word.lower() in _MAGNITUDE_LATIN and segments[-1].rstrip().endswith(
                tuple("0123456789")
            ):
                segments[-1] = segments[-1].rstrip() + _MAGNITUDE_LATIN[word.lower()]
            elif word.lower() == "x" and _between_digits(segments[-1], text, j):
                # 只在「数字 x 数字」这种夹心位置才当乘号。限得这么死是有原因的：
                # x 也是货币代码的常用字母（MXN / XAU / XPF），但那些都是多字母词，
                # 走上面的 resolve 分支，绝不会掉到这里来。
                segments[-1] = segments[-1].rstrip() + "*"
            else:
                unknown.append(word)
            i = j
            continue

        if ch in _MATH_CHARS or ch == ",":
            segments[-1] += ch
            i += 1
            continue

        if ch in _MATH_ALIASES:
            segments[-1] += _MATH_ALIASES[ch]
            i += 1
            continue

        if ch in "亿万千百":
            segments[-1] += ch
            i += 1
            continue

        # 其他字符（emoji、标点残留）直接忽略
        i += 1

    return codes, segments, unknown


def _between_digits(pending: str, text: str, after: int) -> bool:
    """这个位置是不是夹在两个数字中间（中间可以有空格）。

    `x`、`除以`、`加` 这些既是运算符也是别的东西：x 出现在货币代码里
    （MXN / XAU），「加」出现在货币名里（加元 / 加币）。只有夹心位置才当运算符，
    是最稳的判据 —— `100 x` 这种残句宁可当噪声忽略，
    也好过凭空多出一个运算符把金额算错。
    """
    if not pending.rstrip().endswith(tuple("0123456789")):
        return False
    rest = text[after:].lstrip()
    return bool(rest) and rest[0].isdigit()


def _read_word_operator(text: str, i: int, pending: str) -> tuple[str, int] | None:
    """认「100除以4」这类中文运算词，返回 (运算符, 吃掉的字数)。"""
    for word in _WORD_OPERATORS_ORDERED:
        if text.startswith(word, i) and _between_digits(pending, text, i + len(word)):
            return _WORD_OPERATORS[word], len(word)
    return None


def _normalize_expression(segment: str) -> str:
    expr = segment.strip()
    if not expr:
        return ""
    # 千分位逗号：仅当逗号夹在数字之间才删除
    expr = re.sub(r"(?<=\d),(?=\d{3}\b)", "", expr)
    expr = expr.replace(",", " ")
    expr = _expand_magnitudes(expr)
    expr = expr.replace("^", "**")
    return re.sub(r"\s+", " ", expr).strip()


def _expand_magnitudes(expr: str) -> str:
    """把「3万」「1万5」「1亿2千万」这类中文量级写法展开成算式。

    中文数字有两条隐含规则，照字面替换成 `*10000` 会两条都踩空：

    · 量级后跟**一位**数字，指的是次一级单位。「1万5」是 15000，不是 10005；
      写全了的「1万2500」才是加原数。
    · 相邻的量级段之间是**相加**。「1亿2千万」= 1亿 + 2千万。
    """
    parts: list[str] = []
    cursor = prev_end = 0
    for match in _MAGNITUDE_RE.finditer(expr):
        head, unit, tail = match.group(1), match.group(2), match.group(3)
        value = _MAGNITUDE_CJK[unit]
        if not tail:
            piece = f"({head}*{value})"
        elif len(tail) == 1:
            piece = f"({head}*{value}+{tail}*{value // 10})"
        else:
            piece = f"({head}*{value}+{tail})"

        gap = expr[cursor:match.start()]
        # 两段紧挨着（中间没有运算符）就是中文的连写，补一个加号
        if cursor and match.start() == prev_end and not gap.strip():
            parts.append("+")
        parts.append(gap)
        parts.append(piece)
        cursor = prev_end = match.end()
    parts.append(expr[cursor:])
    return "".join(parts)


_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Constant,
)


def _eval_node(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("unsupported constant")
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise ValueError("unsupported unary op")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ValueError("division by zero")
            return left / right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise ValueError("division by zero")
            return left % right
        if isinstance(node.op, ast.Pow):
            if abs(right) > 12:
                raise ValueError("exponent too large")
            return Decimal(str(float(left) ** float(right)))
        raise ValueError("unsupported binary op")
    raise ValueError("unsupported expression")


def evaluate(expression: str) -> Decimal | None:
    """安全地求值一个纯算术表达式；失败返回 None。"""
    expr = _normalize_expression(expression)
    if not expr or not re.search(r"\d", expr):
        return None
    if len(expr) > 200:
        return None
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return None
    try:
        return _eval_node(tree)
    except (ValueError, ZeroDivisionError, DecimalException, OverflowError, TypeError):
        return None


def _dedupe(codes: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            out.append(code)
    return out


# --- 对外入口 -----------------------------------------------------------------


def parse(text: str, *, context_currency: str | None = None) -> ParseResult:
    """解析一条用户输入。context_currency 用于 ¥ / $ 这类符号消歧。"""
    if not text or not text.strip():
        return ParseResult(error="empty")

    raw = unicodedata.normalize("NFKC", text).strip()
    if len(raw) > 500:
        return ParseResult(error="too_long")

    raw, fee = _extract_fee(raw)
    cleaned = _strip_connectors(raw)
    codes, segments, unknown = _scan(cleaned, context=context_currency)

    amount: Decimal | None = None
    expression: str | None = None
    for segment in segments:
        value = evaluate(segment)
        if value is not None:
            amount = value
            expression = segment.strip()
            break

    ordered = _dedupe(codes)
    source = ordered[0] if ordered else None
    targets = ordered[1:]

    result = ParseResult(
        amount=amount if amount is not None else Decimal(1),
        source=source,
        targets=targets,
        fee_percent=fee,
        expression=expression,
        has_explicit_amount=amount is not None,
        unknown_tokens=unknown,
    )

    # 只有孤零零一个数字、且没有任何币种：仍然算可执行（用默认币种展开）
    if not ordered and amount is None:
        result.error = "no_match"
    return result


def parse_currency_list(text: str, *, limit: int = 12) -> list[str]:
    """从一段文本里抽出货币代码列表，用于 /fav、/setbase 等命令。"""
    if not text:
        return []
    cleaned = _strip_connectors(unicodedata.normalize("NFKC", text).strip())
    codes, _, _ = _scan(cleaned, context=None)
    return _dedupe(codes)[:limit]


def parse_pair(text: str, *, default_source: str, default_target: str) -> tuple[str, str]:
    """给 /rate、/chart 这类命令解析一对货币，缺失部分用默认值补齐。"""
    codes = parse_currency_list(text, limit=2)
    if len(codes) >= 2:
        return codes[0], codes[1]
    if len(codes) == 1:
        source = codes[0]
        target = default_target if default_target != source else default_source
        return source, target
    return default_source, default_target
