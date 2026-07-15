import pytest

from cmds.ptt import normalize_ptt_url, parse_ptt

FIXTURE_HTML = '''<html><head><title>Re: [閒聊] 測試 - 看板 C_Chat - 批踢踢實業坊</title></head>
<body><div id="main-content">
<div class="article-metaline"><span class="article-meta-tag">作者</span><span class="article-meta-value">tester (測試員)</span></div>
<div class="article-metaline"><span class="article-meta-tag">標題</span><span class="article-meta-value">Re: [閒聊] 測試</span></div>
<div class="article-metaline-right"><span class="article-meta-tag">看板</span><span class="article-meta-value">C_Chat</span></div>
<div class="article-metaline"><span class="article-meta-tag">時間</span><span class="article-meta-value">Mon Jul 13 12:00:00 2026</span></div>
這是內文第一行
第二行
※ 發信站: 批踢踢實業坊(ptt.cc), 來自: 1.2.3.4
<div class="push"><span class="push-tag">推 </span><span class="push-userid">alice</span><span class="push-content">: 推推</span><span class="push-ipdatetime">07/13 12:01</span></div>
<div class="push"><span class="push-tag">噓 </span><span class="push-userid">bob</span><span class="push-content">: 噓</span><span class="push-ipdatetime">07/13 12:02</span></div>
<div class="push"><span class="push-tag">→ </span><span class="push-userid">carol</span><span class="push-content">: 路過</span><span class="push-ipdatetime">07/13 12:03</span></div>
</div></body></html>'''

URL = "https://www.ptt.cc/bbs/C_Chat/M.test.html"


# ── normalize_ptt_url ──

def test_normalize_full_https():
    assert normalize_ptt_url(URL) == URL


def test_normalize_upgrades_http():
    assert normalize_ptt_url(URL.replace("https://", "http://")) == URL


def test_normalize_adds_scheme():
    assert normalize_ptt_url("www.ptt.cc/bbs/C_Chat/M.test.html") == URL


def test_normalize_rejects_non_ptt():
    with pytest.raises(ValueError):
        normalize_ptt_url("https://example.com/bbs/whatever")


def test_normalize_rejects_non_article():
    with pytest.raises(ValueError):
        normalize_ptt_url("https://www.ptt.cc/index.html")


# ── parse_ptt ──

def test_parse_metadata():
    data = parse_ptt(FIXTURE_HTML, URL)
    assert data["author"] == "tester (測試員)"
    assert data["board"] == "C_Chat"
    assert data["title"] == "Re: [閒聊] 測試"


def test_parse_body_cut_before_signature():
    data = parse_ptt(FIXTURE_HTML, URL)
    assert data["body"] == "這是內文第一行\n第二行"
    assert "發信站" not in data["body"]


def test_parse_push_counts():
    data = parse_ptt(FIXTURE_HTML, URL)
    assert data["push_count"] == 1
    assert data["boo_count"] == 1
    assert data["arrow_count"] == 1
    assert data["total"] == 3
    assert data["pushes"][0]["userid"] == "alice"
    assert data["pushes"][0]["content"] == "推推"


def test_parse_404_page():
    with pytest.raises(ValueError):
        parse_ptt("<html><head><title>404 - Not Found</title></head><body></body></html>", URL)
