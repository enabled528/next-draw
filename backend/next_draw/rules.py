from dataclasses import dataclass
from datetime import date, datetime
import re
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Game:
    id: str
    name: str
    front_count: int
    front_max: int
    back_count: int
    back_max: int


GAMES = {
    "ssq": Game("ssq", "双色球", 6, 33, 1, 16),
    "dlt": Game("dlt", "大乐透", 5, 35, 2, 12),
    "qlc": Game("qlc", "七乐彩", 7, 30, 1, 30),
}


def validate_numbers(game, front, back):
    spec = GAMES[game]
    for values, count, maximum in [(front, spec.front_count, spec.front_max), (back, spec.back_count, spec.back_max)]:
        if not isinstance(values, list) or len(values) != count:
            raise ValueError("号码数量不符")
        if any(type(n) is not int or not 1 <= n <= maximum for n in values):
            raise ValueError("号码超出范围")
        if len(set(values)) != count:
            raise ValueError("同一区域号码重复")
    if game == "qlc" and set(front) & set(back):
        raise ValueError("七乐彩特别号不能与基本号码重复")


def validate_draw(game, record):
    if game not in GAMES or not isinstance(record, dict):
        raise ValueError("不支持的彩种或记录")
    if not isinstance(record.get("issue"), str) or not re.fullmatch(r"\d{5,7}", record["issue"]):
        raise ValueError("期号必须是保留前导零的字符串")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["draw_date"]): raise ValueError("开奖日期格式不符")
    if date.fromisoformat(record["draw_date"]) > datetime.now(ZoneInfo("Asia/Shanghai")).date():
        raise ValueError("开奖日期不能在未来")
    retrieved = datetime.fromisoformat(record["retrieved_at"])
    if retrieved.utcoffset() is None:
        raise ValueError("采集时间必须包含时区")
    validate_numbers(game, record["front"], record["back"])
    return record


def validate_chronology(records):
    for previous, current in zip(records, records[1:]):
        if previous["draw_date"] >= current["draw_date"] or int(previous["issue"]) >= int(current["issue"]):
            raise ValueError("开奖日期和期号必须严格递增")
