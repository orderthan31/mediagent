"""Bounded UTF-8 timed subtitle import shared by originals and workflow inputs."""
from copy import deepcopy
from html.parser import HTMLParser
import re
from video_service.timed_subtitles import MAX_TRANSCRIPT_BYTES, timed_segments as validate_timed

MAX_TEXT = MAX_TRANSCRIPT_BYTES
STAMP = r"(\d{2,5}):([0-5]\d):([0-5]\d),(\d{3})"

def timed_segments(rows, *, maximum=MAX_TEXT):
    validate_timed(rows, maximum=maximum)
    return deepcopy(rows)


def parse_srt(text, *, maximum=MAX_TEXT):
    """Strict bounded SRT reader; shared native segment validators own the timeline."""
    if not isinstance(text, str) or not 1 <= len(text.encode("utf-8")) <= maximum:
        raise ValueError(f"SRT 파일은 UTF-8 {maximum // 1024}KiB 이내여야 합니다. 자막을 나누거나 출력 설정을 변경하세요.")
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    rows = []
    for block in re.split(r"\n[ \t]*\n", normalized.rstrip("\n")):
        lines = block.split("\n")
        if len(lines) < 3 or not re.fullmatch(r"\d{1,128}", lines[0]):
            raise ValueError("번호·시각·문구가 있는 SRT 파일을 선택하세요.")
        clock = re.fullmatch(STAMP + r" --> " + STAMP, lines[1])
        if not clock:
            raise ValueError("SRT 시각은 HH:MM:SS,mmm 형식이어야 합니다.")
        if any(re.fullmatch(STAMP + r" --> " + STAMP, line) for line in lines[2:]):
            raise ValueError("SRT 구간 사이에는 빈 줄이 필요합니다.")
        values = list(map(int, clock.groups()))
        seconds = lambda v: v[0] * 3600 + v[1] * 60 + v[2] + v[3] / 1000
        rows.append({"id": lines[0], "start": seconds(values[:4]), "end": seconds(values[4:]), "text": "\n".join(lines[2:])})
        if len(rows) > 10000:
            raise ValueError("선택 자막은 10000구간 이내로 나눈 뒤 다시 선택하세요.")
    return timed_segments(rows, maximum=maximum)


class _SamiParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.seen = False
        self.ignore = 0
        self.in_paragraph = False
        self.stamp = None
        self.parts = []
        self.rows = []
        self.classes = set()
        self.paragraph_seen = False
        self.body_seen = False

    def _text(self):
        value = re.sub(r"^\x01+|\x01+$", "", "".join(self.parts))
        value = re.sub(r"\x01*\x00\x01*", "\n", value)
        return re.sub(r"\x01+", " ", value)

    def _visible(self):
        return bool(self._text().replace("\u00a0", " ").strip())

    def handle_starttag(self, tag, attrs):
        allowed = {"sami": set(), "head": set(), "title": set(), "body": set(),
                   "style": {"type"}, "meta": {"charset", "http-equiv", "content", "name"},
                   "sync": {"start"}, "p": {"class"}, "br": set(),
                   "b": set(), "i": set(), "u": set(), "font": {"color", "size", "face"}}
        if tag not in allowed or len({k for k, _ in attrs}) != len(attrs) or any(k not in allowed[tag] for k, _ in attrs):
            raise ValueError("단순 SYNC/P/BR 형식의 SMI 자막을 선택하세요.")
        if tag == "body":
            if self.body_seen:
                raise ValueError("SMI에는 BODY 하나만 사용하세요.")
            self.body_seen = True
        if tag in {"head", "style"}:
            self.ignore += 1
        if tag == "sami":
            if self.seen:
                raise ValueError("SMI에는 SAMI 문서 하나만 사용하세요.")
            self.seen = True
        if self.ignore:
            return
        if tag == "sync":
            starts = [v for k, v in attrs if k == "start"]
            if len(starts) != 1 or not isinstance(starts[0], str) or not re.fullmatch(r"\d{1,12}", starts[0]):
                raise ValueError("SMI 구간의 Start 시각을 확인하세요.")
            stamp = int(starts[0])
            if self.stamp is not None:
                if stamp <= self.stamp:
                    raise ValueError("SMI 구간 시각은 순서대로 증가해야 합니다.")
                if self._visible():
                    self.rows.append({"id": str(len(self.rows) + 1), "start": self.stamp / 1000,
                                      "end": stamp / 1000, "text": self._text()})
            if len(self.rows) > 10000:
                raise ValueError("SMI 자막은 10000구간 이내여야 합니다.")
            self.stamp, self.parts, self.in_paragraph = stamp, [], False
            self.paragraph_seen = False
        elif tag == "p" and self.stamp is not None:
            if self.paragraph_seen:
                raise ValueError("SMI 한 시각에는 한 언어의 문단 하나만 사용하세요.")
            self.paragraph_seen = True
            classes = [v for k, v in attrs if k == "class"]
            if len(classes) > 1 or any(not isinstance(v, str) for v in classes):
                raise ValueError("SMI 자막 언어 표기를 확인하세요.")
            if classes and isinstance(classes[0], str) and classes[0]:
                self.classes.add(classes[0].casefold())
            if len(self.classes) > 1:
                raise ValueError("SMI는 단일 언어 자막으로 나누어 등록하세요.")
            if self.parts:
                self.parts.append("\x00")
            self.in_paragraph = True
        elif tag == "br" and self.in_paragraph:
            self.parts.append("\x00")

    def handle_endtag(self, tag):
        if tag in {"head", "style"}:
            self.ignore = max(0, self.ignore - 1)
        if tag == "p":
            self.in_paragraph = False

    def handle_data(self, data):
        if not self.ignore and self.in_paragraph:
            if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", data):
                raise ValueError("SMI에 지원하지 않는 제어 문자가 있습니다.")
            self.parts.append(re.sub(r"[ \t]*(?:\r\n|\r|\n)[ \t]*", "\x01", data))


def parse_sami(text, *, maximum=MAX_TEXT):
    """Import single-language SAMI with explicit end markers; invent no duration."""
    if not isinstance(text, str) or not 1 <= len(text.encode("utf-8")) <= maximum:
        raise ValueError("SMI 파일은 입력 크기 한도 이내의 UTF-8 자막이어야 합니다.")
    parser = _SamiParser()
    parser.feed(text.removeprefix("\ufeff"))
    parser.close()
    if not parser.seen or not parser.body_seen or not parser.rows:
        raise ValueError("시각과 문구가 있는 SAMI 자막을 선택하세요.")
    if parser._visible():
        raise ValueError("SMI 마지막 구간의 종료 시각을 빈 Sync 구간으로 지정하세요.")
    return timed_segments(parser.rows, maximum=maximum)
