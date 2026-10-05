"""Pure-Python Vietnamese text normalizer for TTS.

Drop-in replacement for `vinorm.TTSnorm`, which ships a Linux-only x86-64
binary and cannot run on macOS. Covers the cases that matter for narration
scripts: numbers, decimals, percentages, dates, times, currency, units,
ranges and common abbreviations.
"""

import re

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
GROUP_UNITS = ["", "nghìn", "triệu", "tỷ"]


def _read_two_digits(n, full):
    """Read 0..99. `full` means a hundreds position precedes it."""
    tens, units = divmod(n, 10)
    if tens == 0:
        if units == 0:
            return []
        return (["linh"] if full else []) + [DIGITS[units]]
    words = ["mười"] if tens == 1 else [DIGITS[tens], "mươi"]
    if units == 1 and tens > 1:
        words.append("mốt")
    elif units == 4 and tens > 1:
        words.append("tư")
    elif units == 5:
        words.append("lăm")
    elif units:
        words.append(DIGITS[units])
    return words


def _read_three_digits(n, full):
    """Read 0..999. `full` forces 'không trăm' when a larger group precedes."""
    hundreds, rest = divmod(n, 100)
    words = []
    if hundreds or full:
        words += [DIGITS[hundreds], "trăm"]
    return words + _read_two_digits(rest, bool(words))


def number_to_words(n):
    """Convert a non-negative integer to Vietnamese words."""
    if n == 0:
        return DIGITS[0]
    if n >= 10**9:
        high, low = divmod(n, 10**9)
        words = number_to_words(high) + " tỷ"
        if low:
            words += " " + _number_below_billion(low, full=True)
        return words
    return _number_below_billion(n, full=False)


def _number_below_billion(n, full):
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    if full:
        groups += [0] * (3 - len(groups))
    words = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        leading = not words and not full
        words += _read_three_digits(g, full=not leading)
        if GROUP_UNITS[i]:
            words.append(GROUP_UNITS[i])
    return " ".join(words)


def _read_digit_string(s):
    """Read leading-zero digit strings (e.g. phone numbers) digit by digit."""
    return " ".join(DIGITS[int(c)] for c in s)


def _read_int_string(s):
    s = s.replace(".", "").replace(",", "")
    if len(s) > 1 and s.startswith("0"):
        return _read_digit_string(s)
    return number_to_words(int(s))


def _read_decimal(int_part, frac_part):
    words = _read_int_string(int_part) + " phẩy "
    frac = frac_part.rstrip("0") or "0"
    if frac.startswith("0") or len(frac) > 3:
        return words + _read_digit_string(frac)
    return words + number_to_words(int(frac))


def _read_number_token(tok):
    """Read a numeric token, handling Vietnamese separators.

    - 1.000.000 / 1,000,000 -> thousands separators
    - 3,5 / 3.14            -> decimals
    """
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", tok) or re.fullmatch(r"\d{1,3}(?:,\d{3}){2,}", tok):
        return _read_int_string(tok)
    m = re.fullmatch(r"(\d+)[.,](\d+)", tok)
    if m:
        return _read_decimal(m.group(1), m.group(2))
    return _read_int_string(tok)


NUM = r"\d+(?:[.,]\d+)*"

ABBREVIATIONS = {
    "TP.HCM": "thành phố Hồ Chí Minh",
    "TP HCM": "thành phố Hồ Chí Minh",
    "TPHCM": "thành phố Hồ Chí Minh",
    "HCM": "Hồ Chí Minh",
    "TP.": "thành phố ",
    "Tp.": "thành phố ",
    "BHXH": "bảo hiểm xã hội",
    "BHYT": "bảo hiểm y tế",
    "BHTN": "bảo hiểm thất nghiệp",
    "BHNT": "bảo hiểm nhân thọ",
    "VNĐ": "đồng",
    "VND": "đồng",
    "USD": "đô la",
    "v.v.": "vân vân",
    "v.v": "vân vân",
    "A.I": "Ây Ai",
    "AI": "Ây Ai",
}

UNITS = {
    "km/h": "ki lô mét trên giờ",
    "km²": "ki lô mét vuông",
    "km2": "ki lô mét vuông",
    "m²": "mét vuông",
    "m2": "mét vuông",
    "m³": "mét khối",
    "m3": "mét khối",
    "km": "ki lô mét",
    "cm": "xen ti mét",
    "mm": "mi li mét",
    "kg": "ki lô gam",
    "mg": "mi li gam",
    "ml": "mi li lít",
    "GB": "ghi ga bai",
    "MB": "mê ga bai",
    "m": "mét",
    "g": "gam",
    "l": "lít",
}

CURRENCY_SUFFIX = {
    "đ": "đồng",
    "₫": "đồng",
    "k": "nghìn",
    "K": "nghìn",
    "tr": "triệu",
    "tỷ": "tỷ",
}


def _sub_abbreviations(text):
    for abbr in sorted(ABBREVIATIONS, key=len, reverse=True):
        pattern = r"(?<!\w)" + re.escape(abbr) + (r"(?!\w)" if abbr[-1].isalnum() else "")
        text = re.sub(pattern, ABBREVIATIONS[abbr], text)
    return text


def _sub_dates_times(text):
    def date_full(m):
        d, mo, y = int(m.group(2)), int(m.group(3)), int(m.group(4))
        prefix = "" if m.group(1) else "ngày "
        return f"{m.group(1) or ''}{prefix}{number_to_words(d)} tháng {_month(mo)} năm {number_to_words(y)}"

    def date_dm(m):
        d, mo = int(m.group(2)), int(m.group(3))
        prefix = "" if m.group(1) else "ngày "
        return f"{m.group(1) or ''}{prefix}{number_to_words(d)} tháng {_month(mo)}"

    def month_year(m):
        return f"{m.group(1) or ''}tháng {_month(int(m.group(2)))} năm {number_to_words(int(m.group(3)))}"

    def time_hm(m):
        h, mi = int(m.group(1)), int(m.group(2))
        words = f"{number_to_words(h)} giờ"
        if mi:
            words += f" {number_to_words(mi)} phút"
        return words

    text = re.sub(r"((?:ngày|Ngày)\s+)?\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b", date_full, text)
    text = re.sub(r"((?:tháng|Tháng)\s+)?\b(\d{1,2})[/-](\d{4})\b",
                  lambda m: month_year(m) if not m.group(1) else
                  f"{m.group(1)}{_month(int(m.group(2)))} năm {number_to_words(int(m.group(3)))}", text)
    text = re.sub(r"((?:ngày|Ngày)\s+)?\b(\d{1,2})/(\d{1,2})\b(?!/)", date_dm, text)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b", time_hm, text)
    text = re.sub(r"\b(\d{1,2})h(\d{2})\b", time_hm, text)
    text = re.sub(r"\b(\d{1,2})h\b", lambda m: f"{number_to_words(int(m.group(1)))} giờ", text)
    return text


def _month(mo):
    return "tư" if mo == 4 else number_to_words(mo)


def _sub_money_units(text):
    text = re.sub(r"\$\s?(" + NUM + r")", lambda m: f"{_read_number_token(m.group(1))} đô la", text)

    suffixes = "|".join(sorted(map(re.escape, CURRENCY_SUFFIX), key=len, reverse=True))
    text = re.sub(r"\b(" + NUM + r")\s?(" + suffixes + r")(?!\w)",
                  lambda m: f"{_read_number_token(m.group(1))} {CURRENCY_SUFFIX[m.group(2)]}", text)

    text = re.sub(r"\b(" + NUM + r")\s?%", lambda m: f"{_read_number_token(m.group(1))} phần trăm", text)

    units = "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True))
    text = re.sub(r"\b(" + NUM + r")\s?(" + units + r")(?![\w²³])",
                  lambda m: f"{_read_number_token(m.group(1))} {UNITS[m.group(2)]}", text)
    return text


def _sub_ordinals_ranges(text):
    text = re.sub(r"\b(thứ|Thứ)\s+1\b", r"\1 nhất", text)
    text = re.sub(r"\b(thứ|Thứ)\s+4\b", r"\1 tư", text)
    text = re.sub(r"\b(" + NUM + r")\s?[-–]\s?(" + NUM + r")\b",
                  lambda m: f"{_read_number_token(m.group(1))} đến {_read_number_token(m.group(2))}", text)
    return text


def _sub_numbers(text):
    text = re.sub(r"(?<![\w.,])-(" + NUM + r")\b", lambda m: "âm " + _read_number_token(m.group(1)), text)
    return re.sub(NUM, lambda m: _read_number_token(m.group(0)), text)


def normalize(text):
    text = _sub_abbreviations(text)
    text = _sub_dates_times(text)
    text = _sub_money_units(text)
    text = _sub_ordinals_ranges(text)
    text = _sub_numbers(text)
    text = re.sub(r"(?<=\w)\s?/\s?(?=(?:năm|tháng|tuần|ngày|giờ|phút|người|lần)\b)", " mỗi ", text)
    text = re.sub(r"(?<=\w)\s?/\s?(?=\w)", " trên ", text)
    text = text.replace("&", " và ").replace("+", " cộng ").replace("=", " bằng ")
    return re.sub(r"[ \t]+", " ", text).strip()


def TTSnorm(text, unknown=False, lower=False, rule=True):
    """Signature-compatible with `vinorm.TTSnorm` (extra args are ignored)."""
    return normalize(text)


if __name__ == "__main__":
    import sys

    print(normalize(" ".join(sys.argv[1:]) or sys.stdin.read()))
