from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

HEAVENLY_STEMS = ["갑", "을", "병", "정", "무", "기", "경", "신", "임", "계"]
EARTHLY_BRANCHES = ["자", "축", "인", "묘", "진", "사", "오", "미", "신", "유", "술", "해"]
HEAVENLY_STEMS_HANJA = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
EARTHLY_BRANCHES_HANJA = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 1900~2100 음력 데이터(만세력 공개 구현체 기준)
LUNAR_DATA = [
    0x04BD8,
    0x04AE0,
    0x0A570,
    0x054D5,
    0x0D260,
    0x0D950,
    0x16554,
    0x056A0,
    0x09AD0,
    0x055D2,
    0x04AE0,
    0x0A5B6,
    0x0A4D0,
    0x0D250,
    0x1D255,
    0x0B540,
    0x0D6A0,
    0x0ADA2,
    0x095B0,
    0x14977,
    0x04970,
    0x0A4B0,
    0x0B4B5,
    0x06A50,
    0x06D40,
    0x1AB54,
    0x02B60,
    0x09570,
    0x052F2,
    0x04970,
    0x06566,
    0x0D4A0,
    0x0EA50,
    0x06E95,
    0x05AD0,
    0x02B60,
    0x186E3,
    0x092E0,
    0x1C8D7,
    0x0C950,
    0x0D4A0,
    0x1D8A6,
    0x0B550,
    0x056A0,
    0x1A5B4,
    0x025D0,
    0x092D0,
    0x0D2B2,
    0x0A950,
    0x0B557,
    0x06CA0,
    0x0B550,
    0x15355,
    0x04DA0,
    0x0A5B0,
    0x14573,
    0x052B0,
    0x0A9A8,
    0x0E950,
    0x06AA0,
    0x0AEA6,
    0x0AB50,
    0x04B60,
    0x0AAE4,
    0x0A570,
    0x05260,
    0x0F263,
    0x0D950,
    0x05B57,
    0x056A0,
    0x096D0,
    0x04DD5,
    0x04AD0,
    0x0A4D0,
    0x0D4D4,
    0x0D250,
    0x0D558,
    0x0B540,
    0x0B6A0,
    0x195A6,
    0x095B0,
    0x049B0,
    0x0A974,
    0x0A4B0,
    0x0B27A,
    0x06A50,
    0x06D40,
    0x0AF46,
    0x0AB60,
    0x09570,
    0x04AF5,
    0x04970,
    0x064B0,
    0x074A3,
    0x0EA50,
    0x06B58,
    0x055C0,
    0x0AB60,
    0x096D5,
    0x092E0,
    0x0C960,
    0x0D954,
    0x0D4A0,
    0x0DA50,
    0x07552,
    0x056A0,
    0x0ABB7,
    0x025D0,
    0x092D0,
    0x0CAB5,
    0x0A950,
    0x0B4A0,
    0x0BAA4,
    0x0AD50,
    0x055D9,
    0x04BA0,
    0x0A5B0,
    0x15176,
    0x052B0,
    0x0A930,
    0x07954,
    0x06AA0,
    0x0AD50,
    0x05B52,
    0x04B60,
    0x0A6E6,
    0x0A4E0,
    0x0D260,
    0x0EA65,
    0x0D530,
    0x05AA0,
    0x076A3,
    0x096D0,
    0x04AFB,
    0x04AD0,
    0x0A4D0,
    0x1D0B6,
    0x0D250,
    0x0D520,
    0x0DD45,
    0x0B5A0,
    0x056D0,
    0x055B2,
    0x049B0,
    0x0A577,
    0x0A4B0,
    0x0AA50,
    0x1B255,
    0x06D20,
    0x0ADA0,
    0x14B63,
    0x09370,
    0x049F8,
    0x04970,
    0x064B0,
    0x168A6,
    0x0EA50,
    0x06B20,
    0x1A6C4,
    0x0AAE0,
    0x0A2E0,
    0x0D2E3,
    0x0C960,
    0x0D557,
    0x0D4A0,
    0x0DA50,
    0x05D55,
    0x056A0,
    0x0A6D0,
    0x055D4,
    0x052D0,
    0x0A9B8,
    0x0A950,
    0x0B4A0,
    0x0B6A6,
    0x0AD50,
    0x055A0,
    0x0ABA4,
    0x0A5B0,
    0x052B0,
    0x0B273,
    0x06930,
    0x07337,
    0x06AA0,
    0x0AD50,
    0x14B55,
    0x04B60,
    0x0A570,
    0x054E4,
    0x0D160,
    0x0E968,
    0x0D520,
    0x0DAA0,
    0x16AA6,
    0x056D0,
    0x04AE0,
    0x0A9D4,
    0x0A2D0,
    0x0D150,
    0x0F252,
    0x0D520,
]

SOLAR_TERM_C_20TH = [
    6.11,
    20.84,
    4.6295,
    19.4599,
    6.3826,
    21.4155,
    5.59,
    20.888,
    6.318,
    21.86,
    6.5,
    22.2,
    7.928,
    23.65,
    8.35,
    23.95,
    8.44,
    23.822,
    9.098,
    24.218,
    8.218,
    23.08,
    7.9,
    22.6,
]

SOLAR_TERM_C_21ST = [
    5.4055,
    20.12,
    3.87,
    18.73,
    5.63,
    20.646,
    4.81,
    20.1,
    5.52,
    21.04,
    5.678,
    21.37,
    7.108,
    22.83,
    7.5,
    23.13,
    7.646,
    23.042,
    8.318,
    23.438,
    7.438,
    22.36,
    7.18,
    21.94,
]

SOLAR_TERM_YEAR_DELTA: dict[int, dict[int, int]] = {}

MONTH_BRANCHES = {
    1: "인",
    2: "묘",
    3: "진",
    4: "사",
    5: "오",
    6: "미",
    7: "신",
    8: "유",
    9: "술",
    10: "해",
    11: "자",
    12: "축",
}

STEM_ELEMENT = {
    "갑": "목",
    "을": "목",
    "병": "화",
    "정": "화",
    "무": "토",
    "기": "토",
    "경": "금",
    "신": "금",
    "임": "수",
    "계": "수",
}

STEM_YINYANG = {
    "갑": "양",
    "을": "음",
    "병": "양",
    "정": "음",
    "무": "양",
    "기": "음",
    "경": "양",
    "신": "음",
    "임": "양",
    "계": "음",
}

BRANCH_MAIN_ELEMENT = {
    "자": "수",
    "축": "토",
    "인": "목",
    "묘": "목",
    "진": "토",
    "사": "화",
    "오": "화",
    "미": "토",
    "신": "금",
    "유": "금",
    "술": "토",
    "해": "수",
}

BRANCH_YINYANG = {
    "자": "양",
    "축": "음",
    "인": "양",
    "묘": "음",
    "진": "양",
    "사": "음",
    "오": "양",
    "미": "음",
    "신": "양",
    "유": "음",
    "술": "양",
    "해": "음",
}

BRANCH_HIDDEN_STEMS = {
    "자": ["계"],
    "축": ["기", "계", "신"],
    "인": ["갑", "병", "무"],
    "묘": ["을"],
    "진": ["무", "을", "계"],
    "사": ["병", "무", "경"],
    "오": ["정", "기"],
    "미": ["기", "을", "정"],
    "신": ["경", "임", "무"],
    "유": ["신"],
    "술": ["무", "신", "정"],
    "해": ["임", "갑"],
}

ELEMENT_ORDER = ["목", "화", "토", "금", "수"]
ELEMENT_GENERATES = {"목": "화", "화": "토", "토": "금", "금": "수", "수": "목"}
ELEMENT_CONTROLS = {"목": "토", "토": "수", "수": "화", "화": "금", "금": "목"}
HEAVENLY_STEM_HAP = {frozenset({"갑", "기"}), frozenset({"을", "경"}), frozenset({"병", "신"}), frozenset({"정", "임"}), frozenset({"무", "계"})}
EARTHLY_BRANCH_HAP = {frozenset({"자", "축"}), frozenset({"인", "해"}), frozenset({"묘", "술"}), frozenset({"진", "유"}), frozenset({"사", "신"}), frozenset({"오", "미"})}
EARTHLY_BRANCH_CHUNG = {frozenset({"자", "오"}), frozenset({"축", "미"}), frozenset({"인", "신"}), frozenset({"묘", "유"}), frozenset({"진", "술"}), frozenset({"사", "해"})}

SHICHEN_HOUR_MAP = {
    "자시": 23,
    "축시": 1,
    "인시": 3,
    "묘시": 5,
    "진시": 7,
    "사시": 9,
    "오시": 11,
    "미시": 13,
    "신시": 15,
    "유시": 17,
    "술시": 19,
    "해시": 21,
}

DATE_RE = re.compile(
    r"(?P<year>(?:19|20)\d{2})\s*[./\-년]\s*(?P<month>1[0-2]|0?[1-9])\s*[./\-월]\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*일?"
)
SHORT_YEAR_DATE_RE = re.compile(
    r"(?<!\d)(?:['’])?(?P<year>\d{2})\s*년\s*(?P<month>1[0-2]|0?[1-9])\s*[./\-월]\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*일?"
)
COMPACT_DATE_RE = re.compile(r"\b(?P<year>(?:19|20)\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])\b")
COMPACT_SHORT_DATE_RE = re.compile(r"\b(?P<year>\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>0[1-9]|[12]\d|3[01])\b")
MONTH_DAY_RE = re.compile(r"(?P<month>1[0-2]|0?[1-9])\s*월\s*(?P<day>3[01]|[12]\d|0?[1-9])\s*일")
MERIDIEM_HOUR_RE = re.compile(
    r"(?P<marker>오전|오후|am|pm|AM|PM|새벽|아침|저녁|밤)\s*(?P<hour>2[0-3]|[01]?\d)\s*시(?:\s*(?P<minute>[0-5]?\d)\s*분?)?"
)
HOUR_MINUTE_RE = re.compile(r"(?P<hour>2[0-3]|[01]?\d)\s*(?:시|:)\s*(?P<minute>[0-5]?\d)?\s*분?")
HOUR_ONLY_RE = re.compile(r"(?P<hour>2[0-3]|[01]?\d)\s*시")
UNKNOWN_HOUR_RE = re.compile(r"(생시|출생시간|태어난\s*시간)\s*(모름|미상|몰라)")


@dataclass
class BirthInfoPartial:
    year: int | None = None
    month: int | None = None
    day: int | None = None
    hour: int | None = None
    minute: int | None = None
    is_lunar: bool | None = None
    is_leap_month: bool | None = None

    def has_any(self) -> bool:
        return any(
            value is not None
            for value in (
                self.year,
                self.month,
                self.day,
                self.hour,
                self.minute,
                self.is_lunar,
                self.is_leap_month,
            )
        )

    def is_complete(self) -> bool:
        return (
            self.year is not None
            and self.month is not None
            and self.day is not None
            and self.hour is not None
        )


@dataclass
class FourPillarsResult:
    year: str
    month: str
    day: str
    hour: str
    year_hanja: str
    month_hanja: str
    day_hanja: str
    hour_hanja: str
    hour_known: bool = True
    year_stem: str = ""
    year_branch: str = ""
    month_stem: str = ""
    month_branch: str = ""
    day_stem: str = ""
    day_branch: str = ""
    hour_stem: str | None = None
    hour_branch: str | None = None

    def korean_string(self) -> str:
        if self.hour_known:
            return f"{self.year}년주, {self.month}월주, {self.day}일주, {self.hour}시주"
        return f"{self.year}년주, {self.month}월주, {self.day}일주, 시주 미상"

    def hanja_string(self) -> str:
        if self.hour_known:
            return f"{self.year_hanja}年柱, {self.month_hanja}月柱, {self.day_hanja}日柱, {self.hour_hanja}時柱"
        return f"{self.year_hanja}年柱, {self.month_hanja}月柱, {self.day_hanja}日柱, 時柱未詳"


@dataclass
class SajuReplyContext:
    has_birth_hint: bool
    is_complete: bool
    missing_fields: list[str]
    birth: BirthInfoPartial
    question_text: str
    birth_summary: str
    four_pillars: FourPillarsResult | None
    hour_unknown: bool
    error_message: str | None


def _expand_two_digit_year(year_2d: int) -> int:
    if year_2d < 0 or year_2d > 99:
        raise ValueError("2자리 연도 범위를 벗어났습니다.")
    return 2000 + year_2d if year_2d <= 30 else 1900 + year_2d


def _get_leap_month(year: int) -> int:
    return LUNAR_DATA[year - 1900] & 0xF


def _get_leap_month_days(year: int) -> int:
    leap_month = _get_leap_month(year)
    if leap_month:
        return 30 if (LUNAR_DATA[year - 1900] & 0x10000) else 29
    return 0


def _get_lunar_month_days(year: int, month: int) -> int:
    return 30 if (LUNAR_DATA[year - 1900] & (0x10000 >> month)) else 29


def _get_lunar_year_days(year: int) -> int:
    total = 348
    i = 0x8000
    while i > 0x8:
        total += 1 if (LUNAR_DATA[year - 1900] & i) else 0
        i >>= 1
    return total + _get_leap_month_days(year)


def lunar_to_solar(year: int, month: int, day: int, is_leap_month: bool) -> tuple[int, int, int]:
    if year < 1900 or year > 2100:
        raise ValueError("음력 변환은 1900~2100년만 지원합니다.")
    if month < 1 or month > 12:
        raise ValueError("월 정보가 잘못되었습니다.")
    if day < 1 or day > 30:
        raise ValueError("일 정보가 잘못되었습니다.")

    base = date(1900, 1, 31)
    offset = 0

    for i in range(1900, year):
        offset += _get_lunar_year_days(i)

    leap_month = _get_leap_month(year)
    is_leap = False
    i = 1
    while i < month:
        if leap_month > 0 and i == leap_month and not is_leap:
            offset += _get_leap_month_days(year)
            is_leap = True
            continue
        offset += _get_lunar_month_days(year, i)
        i += 1

    if is_leap_month and leap_month == month:
        offset += _get_lunar_month_days(year, month)

    offset += day - 1
    converted = base + timedelta(days=offset)
    return converted.year, converted.month, converted.day


def _get_solar_term_date(year: int, term_index: int) -> date:
    if year < 1901 or year > 2100:
        raise ValueError("절기 계산 지원 범위는 1901~2100년입니다.")

    year_in_century = year % 100
    coeffs = SOLAR_TERM_C_20TH if year <= 2000 else SOLAR_TERM_C_21ST
    coeff = coeffs[term_index]
    # 통상절기 계산식: floor(y*0.2422 + C) - floor((y-1)/4)
    day = int(year_in_century * 0.2422 + coeff) - int((year_in_century - 1) / 4)
    day += SOLAR_TERM_YEAR_DELTA.get(term_index, {}).get(year, 0)
    month = term_index // 2 + 1
    return date(year, month, max(1, day))


def _get_year_pillar(year: int) -> tuple[str, str]:
    return HEAVENLY_STEMS[(year - 4) % 10], EARTHLY_BRANCHES[(year - 4) % 12]


def _get_month_pillar(year: int, month: int, day: int) -> tuple[str, str]:
    current = date(year, month, day)
    lichun = _get_solar_term_date(year, 2)
    adjusted_year = year - 1 if current < lichun else year

    month_starts: list[tuple[int, date]] = []
    for month_no in range(1, 12):
        term_index = month_no * 2
        month_starts.append((month_no, _get_solar_term_date(adjusted_year, term_index)))
    # 12월(축월)은 다음 해 소한부터 시작
    month_starts.append((12, _get_solar_term_date(adjusted_year + 1, 0)))

    solar_term_month = 11  # 입춘 이전 구간의 기본값: 자월
    for month_no, start_date in month_starts:
        if current >= start_date:
            solar_term_month = month_no
        else:
            break

    year_stem = (adjusted_year - 4) % 10
    month_stem_idx = ((year_stem % 5) * 2 + solar_term_month + 1) % 10
    return HEAVENLY_STEMS[month_stem_idx], MONTH_BRANCHES.get(solar_term_month, "인")


def _get_day_pillar(year: int, month: int, day: int) -> tuple[str, str]:
    base_date = date(1992, 10, 24)
    base_ganji_num = 9
    target = date(year, month, day)
    diff = (target - base_date).days
    ganji = ((base_ganji_num + diff) % 60 + 60) % 60
    return HEAVENLY_STEMS[ganji % 10], EARTHLY_BRANCHES[ganji % 12]


def _get_hour_pillar(day_stem: str, hour: int, minute: int) -> tuple[str, str]:
    adjusted_hour = 0 if hour == 23 else hour
    total_minutes = adjusted_hour * 60 + minute
    shichen = ((total_minutes + 60) // 120) % 12
    day_stem_idx = HEAVENLY_STEMS.index(day_stem)
    hour_stem_base = (day_stem_idx % 5) * 2
    hour_stem_idx = (hour_stem_base + shichen) % 10
    return HEAVENLY_STEMS[hour_stem_idx], EARTHLY_BRANCHES[shichen]


def calculate_four_pillars(birth: BirthInfoPartial, *, allow_unknown_hour: bool = False) -> FourPillarsResult:
    if birth.year is None or birth.month is None or birth.day is None:
        raise ValueError("사주 계산 입력값이 부족합니다.")
    if birth.hour is None and not allow_unknown_hour:
        raise ValueError("사주 계산을 위해 생년월일과 생시가 필요합니다.")

    minute = birth.minute or 0
    year = birth.year
    month = birth.month
    day = birth.day

    if birth.is_lunar:
        year, month, day = lunar_to_solar(year, month, day, bool(birth.is_leap_month))

    year_stem, year_branch = _get_year_pillar(year)
    month_stem, month_branch = _get_month_pillar(year, month, day)
    day_stem, day_branch = _get_day_pillar(year, month, day)
    hour_known = birth.hour is not None
    if hour_known:
        hour_stem, hour_branch = _get_hour_pillar(day_stem, birth.hour, minute)
    else:
        hour_stem, hour_branch = "미", "상"
        hour_hanja = "未詳"

    return FourPillarsResult(
        year=f"{year_stem}{year_branch}",
        month=f"{month_stem}{month_branch}",
        day=f"{day_stem}{day_branch}",
        hour=f"{hour_stem}{hour_branch}" if hour_known else "미상",
        year_hanja=f"{HEAVENLY_STEMS_HANJA[HEAVENLY_STEMS.index(year_stem)]}{EARTHLY_BRANCHES_HANJA[EARTHLY_BRANCHES.index(year_branch)]}",
        month_hanja=f"{HEAVENLY_STEMS_HANJA[HEAVENLY_STEMS.index(month_stem)]}{EARTHLY_BRANCHES_HANJA[EARTHLY_BRANCHES.index(month_branch)]}",
        day_hanja=f"{HEAVENLY_STEMS_HANJA[HEAVENLY_STEMS.index(day_stem)]}{EARTHLY_BRANCHES_HANJA[EARTHLY_BRANCHES.index(day_branch)]}",
        hour_hanja=(
            f"{HEAVENLY_STEMS_HANJA[HEAVENLY_STEMS.index(hour_stem)]}{EARTHLY_BRANCHES_HANJA[EARTHLY_BRANCHES.index(hour_branch)]}"
            if hour_known
            else hour_hanja
        ),
        hour_known=hour_known,
        year_stem=year_stem,
        year_branch=year_branch,
        month_stem=month_stem,
        month_branch=month_branch,
        day_stem=day_stem,
        day_branch=day_branch,
        hour_stem=(hour_stem if hour_known else None),
        hour_branch=(hour_branch if hour_known else None),
    )


def _adjust_hour(marker: str | None, hour: int) -> int:
    if marker is None:
        return hour
    token = marker.lower()
    if token in {"오후", "pm", "저녁", "밤"} and hour < 12:
        return hour + 12
    if token in {"오전", "am", "새벽", "아침"} and hour == 12:
        return 0
    return hour


def _extract_birth_from_text(text: str) -> BirthInfoPartial:
    raw = text.strip()
    info = BirthInfoPartial()
    if not raw:
        return info

    lowered = raw.lower()
    if "음력" in raw:
        info.is_lunar = True
    if "양력" in raw:
        info.is_lunar = False
    if "윤달" in raw or "윤월" in raw:
        info.is_leap_month = True

    full_date = DATE_RE.search(raw) or COMPACT_DATE_RE.search(raw)
    if full_date:
        info.year = int(full_date.group("year"))
        info.month = int(full_date.group("month"))
        info.day = int(full_date.group("day"))
    else:
        compact_short = COMPACT_SHORT_DATE_RE.search(raw)
        if compact_short:
            info.year = _expand_two_digit_year(int(compact_short.group("year")))
            info.month = int(compact_short.group("month"))
            info.day = int(compact_short.group("day"))
        else:
            short_year_date = SHORT_YEAR_DATE_RE.search(raw)
            if short_year_date:
                info.year = _expand_two_digit_year(int(short_year_date.group("year")))
                info.month = int(short_year_date.group("month"))
                info.day = int(short_year_date.group("day"))
            else:
                month_day = MONTH_DAY_RE.search(raw)
                if month_day:
                    info.month = int(month_day.group("month"))
                    info.day = int(month_day.group("day"))

    meridiem_hour = MERIDIEM_HOUR_RE.search(raw)
    if meridiem_hour:
        hour = int(meridiem_hour.group("hour"))
        minute_raw = meridiem_hour.group("minute")
        info.hour = _adjust_hour(meridiem_hour.group("marker"), hour)
        info.minute = int(minute_raw) if minute_raw is not None else 0
    else:
        hour_minute = HOUR_MINUTE_RE.search(raw)
        if hour_minute:
            info.hour = int(hour_minute.group("hour"))
            minute_raw = hour_minute.group("minute")
            info.minute = int(minute_raw) if minute_raw is not None else 0
        else:
            for label, hour in SHICHEN_HOUR_MAP.items():
                if label in raw:
                    info.hour = hour
                    info.minute = 0
                    break
            if info.hour is None:
                hour_only = HOUR_ONLY_RE.search(raw)
                if hour_only:
                    info.hour = int(hour_only.group("hour"))
                    info.minute = 0
    if info.hour is None and ("생시모름" in raw or "생시 미상" in raw or UNKNOWN_HOUR_RE.search(raw)):
        info.minute = 0

    if info.is_lunar is None and "lunar" in lowered:
        info.is_lunar = True
    if info.is_lunar is None and "solar" in lowered:
        info.is_lunar = False

    return info


def _merge_birth(base: BirthInfoPartial, incoming: BirthInfoPartial) -> BirthInfoPartial:
    merged = BirthInfoPartial(
        year=base.year,
        month=base.month,
        day=base.day,
        hour=base.hour,
        minute=base.minute,
        is_lunar=base.is_lunar,
        is_leap_month=base.is_leap_month,
    )
    for key in ("year", "month", "day", "hour", "minute", "is_lunar", "is_leap_month"):
        value = getattr(incoming, key)
        if value is not None:
            setattr(merged, key, value)
    return merged


def _clean_question_text(text: str) -> str:
    cleaned = text
    cleaned = DATE_RE.sub(" ", cleaned)
    cleaned = SHORT_YEAR_DATE_RE.sub(" ", cleaned)
    cleaned = COMPACT_DATE_RE.sub(" ", cleaned)
    cleaned = COMPACT_SHORT_DATE_RE.sub(" ", cleaned)
    cleaned = MONTH_DAY_RE.sub(" ", cleaned)
    cleaned = MERIDIEM_HOUR_RE.sub(" ", cleaned)
    cleaned = HOUR_MINUTE_RE.sub(" ", cleaned)
    for token in (
        "양력",
        "음력",
        "윤달",
        "윤월",
        "생년월일",
        "생시",
        "생시모름",
        "생시 미상",
        "출생시간",
        "출생 시간",
        "시간모름",
        "시간 미상",
        "모름",
        "미상",
        "몰라요",
        "몰라",
        "년생",
    ):
        cleaned = cleaned.replace(token, " ")
    for label in SHICHEN_HOUR_MAP:
        cleaned = cleaned.replace(label, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.!?~")
    return cleaned


def _birth_summary(info: BirthInfoPartial) -> str:
    parts: list[str] = []
    if info.year is not None and info.month is not None and info.day is not None:
        parts.append(f"{info.year:04d}-{info.month:02d}-{info.day:02d}")
    if info.hour is not None:
        minute = info.minute or 0
        parts.append(f"{info.hour:02d}:{minute:02d}")
    elif info.year is not None and info.month is not None and info.day is not None:
        parts.append("생시 미상")
    if info.is_lunar is True:
        parts.append("음력")
    elif info.is_lunar is False:
        parts.append("양력")
    if info.is_leap_month:
        parts.append("윤달")
    return " / ".join(parts)


def _missing_fields(info: BirthInfoPartial) -> list[str]:
    missing: list[str] = []
    if info.year is None:
        missing.append("생년")
    if info.month is None:
        missing.append("생월")
    if info.day is None:
        missing.append("생일")
    if info.hour is None:
        missing.append("생시")
    return missing


def infer_saju_topic(question: str) -> str:
    text = question.replace(" ", "")
    if any(token in text for token in ("연애", "사랑", "결혼", "이별", "재회", "썸")):
        return "연애운"
    if any(token in text for token in ("금전", "재물", "돈", "투자", "수입", "지출")):
        return "금전운"
    if any(token in text for token in ("직장", "취업", "이직", "사업", "승진", "커리어")):
        return "직업운"
    if any(token in text for token in ("건강", "몸", "컨디션", "병원", "질병")):
        return "건강운"
    if any(token in text for token in ("학업", "시험", "공부", "입시")):
        return "학업운"
    return "종합운"


def build_saju_topic_fallback(topic: str, pillars_kor: str) -> str:
    by_topic = {
        "연애운": f"{pillars_kor} 기준 연애운은 서두르기보다 대화 속도를 맞추는 쪽이 유리합니다.",
        "금전운": f"{pillars_kor} 기준 금전운은 큰 베팅보다 지출 통제와 분산이 더 유리합니다.",
        "직업운": f"{pillars_kor} 기준 직업운은 방향 전환보다 현재 루틴 고도화가 성과에 유리합니다.",
        "건강운": f"{pillars_kor} 기준 건강운은 무리한 강도보다 수면·회복 리듬 관리가 더 중요합니다.",
        "학업운": f"{pillars_kor} 기준 학업운은 과목 확장보다 약점 한 과목 집중 보완이 유리합니다.",
        "종합운": f"{pillars_kor} 기준 종합운은 급한 결정 대신 순서 정리 후 실행하는 흐름이 유리합니다.",
    }
    return by_topic.get(topic, by_topic["종합운"])


def summarize_birth_info(info: BirthInfoPartial) -> str:
    return _birth_summary(info)


def list_missing_birth_fields(info: BirthInfoPartial) -> list[str]:
    return _missing_fields(info)


def _stem_hanja(stem: str) -> str:
    return HEAVENLY_STEMS_HANJA[HEAVENLY_STEMS.index(stem)]


def _branch_hanja(branch: str) -> str:
    return EARTHLY_BRANCHES_HANJA[EARTHLY_BRANCHES.index(branch)]


def _ten_god(day_stem: str, target_stem: str) -> str:
    day_element = STEM_ELEMENT[day_stem]
    target_element = STEM_ELEMENT[target_stem]
    same_polarity = STEM_YINYANG[day_stem] == STEM_YINYANG[target_stem]

    if target_element == day_element:
        return "비견" if same_polarity else "겁재"
    if ELEMENT_GENERATES[day_element] == target_element:
        return "식신" if same_polarity else "상관"
    if ELEMENT_CONTROLS[day_element] == target_element:
        return "편재" if same_polarity else "정재"
    if ELEMENT_GENERATES[target_element] == day_element:
        return "편인" if same_polarity else "정인"
    if ELEMENT_CONTROLS[target_element] == day_element:
        return "편관" if same_polarity else "정관"
    return "-"


def _describe_branch_hidden_stems(day_stem: str, branch: str) -> list[dict[str, str]]:
    stems = BRANCH_HIDDEN_STEMS.get(branch, [])
    result: list[dict[str, str]] = []
    for stem in stems:
        result.append(
            {
                "stem": stem,
                "hanja": _stem_hanja(stem),
                "element": STEM_ELEMENT[stem],
                "ten_god": _ten_god(day_stem, stem),
            }
        )
    return result


def _find_stem_relations(stems: list[str]) -> list[str]:
    items: list[str] = []
    for i in range(len(stems)):
        for j in range(i + 1, len(stems)):
            pair = frozenset({stems[i], stems[j]})
            if pair in HEAVENLY_STEM_HAP:
                items.append(f"{stems[i]}-{stems[j]} 합")
    return items


def _find_branch_relations(branches: list[str]) -> list[str]:
    items: list[str] = []
    for i in range(len(branches)):
        for j in range(i + 1, len(branches)):
            pair = frozenset({branches[i], branches[j]})
            if pair in EARTHLY_BRANCH_HAP:
                items.append(f"{branches[i]}-{branches[j]} 합")
            if pair in EARTHLY_BRANCH_CHUNG:
                items.append(f"{branches[i]}-{branches[j]} 충")
    return items


def build_four_pillars_details(pillars: FourPillarsResult) -> dict[str, object]:
    day_stem = pillars.day_stem
    columns_meta = [
        ("시", pillars.hour_stem, pillars.hour_branch, pillars.hour_known),
        ("일", pillars.day_stem, pillars.day_branch, True),
        ("월", pillars.month_stem, pillars.month_branch, True),
        ("년", pillars.year_stem, pillars.year_branch, True),
    ]

    columns: list[dict[str, object]] = []
    visible_stems: list[str] = []
    visible_branches: list[str] = []
    element_counts = {element: 0 for element in ELEMENT_ORDER}
    yin_count = 0
    yang_count = 0

    for label, stem, branch, known in columns_meta:
        if known and stem and branch:
            stem_hanja = _stem_hanja(stem)
            branch_hanja = _branch_hanja(branch)
            stem_element = STEM_ELEMENT[stem]
            branch_element = BRANCH_MAIN_ELEMENT[branch]
            stem_yinyang = STEM_YINYANG[stem]
            branch_yinyang = BRANCH_YINYANG[branch]
            stem_ten_god = "-" if label == "일" else _ten_god(day_stem, stem)
            hidden_stems = _describe_branch_hidden_stems(day_stem, branch)

            visible_stems.append(stem)
            visible_branches.append(branch)
            element_counts[stem_element] += 1
            element_counts[branch_element] += 1
            yin_count += 1 if stem_yinyang == "음" else 0
            yang_count += 1 if stem_yinyang == "양" else 0
            yin_count += 1 if branch_yinyang == "음" else 0
            yang_count += 1 if branch_yinyang == "양" else 0
        else:
            stem_hanja = "-"
            branch_hanja = "-"
            stem_element = "-"
            branch_element = "-"
            stem_yinyang = "-"
            branch_yinyang = "-"
            stem_ten_god = "-"
            hidden_stems = []

        columns.append(
            {
                "label": label,
                "known": known,
                "stem": stem if stem else "미상",
                "stem_hanja": stem_hanja,
                "stem_element": stem_element,
                "stem_yinyang": stem_yinyang,
                "stem_ten_god": stem_ten_god,
                "branch": branch if branch else "미상",
                "branch_hanja": branch_hanja,
                "branch_element": branch_element,
                "branch_yinyang": branch_yinyang,
                "hidden_stems": hidden_stems,
            }
        )

    return {
        "day_master": {
            "stem": day_stem,
            "hanja": _stem_hanja(day_stem),
            "element": STEM_ELEMENT[day_stem],
            "yinyang": STEM_YINYANG[day_stem],
        },
        "columns": columns,
        "element_counts": [{"element": element, "count": element_counts[element]} for element in ELEMENT_ORDER],
        "yin_count": yin_count,
        "yang_count": yang_count,
        "stem_relations": _find_stem_relations(visible_stems),
        "branch_relations": _find_branch_relations(visible_branches),
    }


def build_saju_reply_context(current_text: str, history_texts: list[str]) -> SajuReplyContext:
    merged = BirthInfoPartial()
    has_hint = False

    for text in history_texts:
        parsed = _extract_birth_from_text(text)
        if parsed.has_any():
            has_hint = True
            merged = _merge_birth(merged, parsed)

    current_parsed = _extract_birth_from_text(current_text)
    if current_parsed.has_any():
        has_hint = True
        merged = _merge_birth(merged, current_parsed)

    if merged.is_lunar is None:
        merged.is_lunar = False
    if merged.minute is None:
        merged.minute = 0

    question = _clean_question_text(current_text)
    missing = _missing_fields(merged)
    non_hour_missing = [item for item in missing if item != "생시"]
    if non_hour_missing:
        return SajuReplyContext(
            has_birth_hint=has_hint,
            is_complete=False,
            missing_fields=missing,
            birth=merged,
            question_text=question,
            birth_summary=_birth_summary(merged),
            four_pillars=None,
            hour_unknown=False,
            error_message=None,
        )

    hour_unknown = "생시" in missing
    try:
        pillars = calculate_four_pillars(merged, allow_unknown_hour=hour_unknown)
    except Exception as exc:  # noqa: BLE001
        return SajuReplyContext(
            has_birth_hint=True,
            is_complete=False,
            missing_fields=[],
            birth=merged,
            question_text=question,
            birth_summary=_birth_summary(merged),
            four_pillars=None,
            hour_unknown=False,
            error_message=f"생년월일 형식을 다시 확인해주세요. ({str(exc)[:80]})",
        )

    return SajuReplyContext(
        has_birth_hint=has_hint,
        is_complete=True,
        missing_fields=(["생시"] if hour_unknown else []),
        birth=merged,
        question_text=question,
        birth_summary=_birth_summary(merged),
        four_pillars=pillars,
        hour_unknown=hour_unknown,
        error_message=None,
    )
