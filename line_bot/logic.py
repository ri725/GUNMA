from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlencode

import store

MEDIA = store.ROOT / "media"
VIDEOS = {
    "shinbure": {
        "file": "shinbure.mp4",
        "poster": "shinbure.jpg",
        "title": "ドリルの芯振れの確認",
    },
}
_VIDEO_LINE = re.compile(r"^動画:[ \t]*([A-Za-z0-9_-]+)[ \t]*$", re.MULTILINE)

MENUS = ("よくある質問", "機械が止まった", "合否の判断", "その他")
PROMPTS = {
    "よくある質問": "どの分類ですか",
    "機械が止まった": "どれを見ますか",
    "合否の判断": "どの製品ですか",
}


def handle_text(text: str) -> dict:
    text = text.strip()
    if text in MENUS:
        return open_menu(text)
    found = _unique_kind(text)
    if found:
        category, kind = found
        return _answer_message(category, kind, text)
    matched = _search(text)
    if matched is None:
        _safe_log(text, result="本人待ち")
        return _text("表にない質問なので、担当に確認します。")
    _safe_log(text, matched.category, matched.kind, "返した", str(matched.number))
    return _text(_render(matched))


def handle_postback(data: str) -> dict:
    parsed = parse_qs(data)
    category = (parsed.get("cat") or [""])[0]
    kind = (parsed.get("item") or [""])[0]
    if not category or not kind:
        return _text("選択を読み取れませんでした。もう一度ボタンを押してください。")
    return _answer_message(category, kind, kind)


def open_menu(name: str) -> dict:
    if name == "その他":
        return _text("その他は保留です。")
    items = store.menu_items(name)
    if name == "機械が止まった" and items == ["対応方法"]:
        return _answer_message(name, "対応方法", name)
    if not items:
        return _text("まだ項目がありません。")
    return {
        "type": "text",
        "text": PROMPTS.get(name, "選んでください"),
        "quickReply": {"items": [_quick(name, item) for item in items[:13]]},
    }


def _answer_message(category: str, kind: str, source_text: str) -> dict:
    found = store.answers_for(category, kind)
    if not found:
        _safe_log(source_text, category, kind, "未対応")
        return _text("まだ登録されていません。担当に確認します。")
    _safe_log(source_text, category, kind, "返した", str(found[0].number))
    body = "\n\n".join(_render(item) for item in found)
    return _text(body)


def public_base() -> str:
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base:
        return base
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if domain:
        return f"https://{domain}"
    return "http://localhost:8000"


def video_files() -> set[str]:
    names = set()
    for video in VIDEOS.values():
        names.add(video["file"])
        poster = video.get("poster", "")
        if poster:
            names.add(poster)
    return names


def _render(item: store.Item) -> str:
    text = _attach_video_links(item.answer)
    if item.after == "送ったあと本人に知らせる":
        text += "\n\n最終判断は担当者に確認してください。"
    return text


def _attach_video_links(text: str) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key not in VIDEOS:
            return match.group(0)
        return f"動画\n{public_base()}/v/{key}"

    return _VIDEO_LINE.sub(replace, text)


def _unique_kind(text: str) -> tuple[str, str] | None:
    found = []
    for category in MENUS:
        if text in store.menu_items(category):
            found.append((category, text))
    if len(found) == 1:
        return found[0]
    return None


def _search(text: str):
    hits = []
    for item in store.questions():
        if not item.active:
            continue
        words = [part.strip() for part in item.aliases.replace("，", ",").replace("、", ",").split(",")]
        if item.question:
            words.append(item.question)
        score = 0
        for word in words:
            if len(word) < 2:
                continue
            if word in text or text in word:
                score += len(word)
        if score:
            hits.append((score, item))
    if not hits:
        return None
    hits.sort(key=lambda pair: pair[0], reverse=True)
    if len(hits) > 1 and hits[0][0] == hits[1][0]:
        return None
    return hits[0][1]


def _quick(category: str, label: str) -> dict:
    return {
        "type": "action",
        "action": {
            "type": "postback",
            "label": label[:20],
            "data": urlencode({"cat": category, "item": label}),
            "displayText": label[:20],
        },
    }


def _text(text: str) -> dict:
    return {"type": "text", "text": text[:5000]}


def _safe_log(text: str, category: str = "", kind: str = "", result: str = "本人待ち", used_number: str = "") -> None:
    try:
        store.log_incoming(text, category, kind, result, used_number)
    except OSError:
        return
