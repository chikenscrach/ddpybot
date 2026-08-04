import pytest

from cmds.ptt import (
    ArticleNotFoundError,
    normalize_ptt_url,
    parse_ptt,
    parse_pttweb,
    ptt_to_pttweb_url,
)

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
    # 404 需為 ArticleNotFoundError 才會觸發 pttweb 備份 fallback
    with pytest.raises(ArticleNotFoundError):
        parse_ptt("<html><head><title>404 - Not Found</title></head><body></body></html>", URL)


# ── ptt_to_pttweb_url ──

def test_pttweb_url_strips_html_suffix():
    assert (
        ptt_to_pttweb_url("https://www.ptt.cc/bbs/C_Chat/M.1782889510.A.9DF.html")
        == "https://www.pttweb.cc/bbs/C_Chat/M.1782889510.A.9DF"
    )


def test_pttweb_url_ignores_query_string():
    assert (
        ptt_to_pttweb_url("https://www.ptt.cc/bbs/Gossiping/M.123.A.456.html?from=share")
        == "https://www.pttweb.cc/bbs/Gossiping/M.123.A.456"
    )


def test_pttweb_url_rejects_non_article():
    with pytest.raises(ValueError):
        ptt_to_pttweb_url("https://www.ptt.cc/index.html")


# ── parse_pttweb ──

PTTWEB_URL = "https://www.pttweb.cc/bbs/C_Chat/M.test"

PTTWEB_FIXTURE_HTML = '''<html><head><title>[閒聊] 備份測試 - 看板C_Chat - PTT網頁版</title></head><body>
<h1 class="title"><span itemprop="headline">
    [閒聊] 備份測試<span class="e7-full-title-appended-part"></span></span></h1>
<div class="e7-head">
<div><div class="e7-head-label">看板</div><div class="e7-head-content">C_Chat</div></div>
<div><div class="e7-head-label">作者</div><div class="e7-head-content">tester(測試員)</div></div>
<div><div class="e7-head-label">時間</div><div class="e7-head-content">4周前發表(2026/07/01 15:05),編輯</div></div>
<div><div class="e7-head-label">推噓</div><div class="e7-head-content">19(19推0噓4→)</div></div>
</div>
<div class="e7-main-content" itemprop="articleBody"><span>備份內文第一行</span></div>
<div></div>
<div class="e7-main-content" itemprop="articleBody"><span>第二行
※ 發信站: 批踢踢實業坊(ptt.cc), 來自: 1.2.3.4</span></div>
<div class="e7-container pt-1 pb-1"><div class="e7-left"><div>推</div></div>
<div class="e7-right ml-2"><div class="e7-right-top">
<div class="e7-author"><span itemprop="name"><a><span>alice</span></a></span></div>
<div class="ml-2 e7-ipdatetime1"><span>07/01 15:06, </span>4周前<span class="e7-floor e7-xs">, 1<sup>F</sup></span></div>
</div><div class="e7-right-bottom">
<div class="e7-recommend-message"><div><span>推推</span></div></div>
<div class="e7-ipdatetime2"><span>07/01 15:06</span><span class="e7-floor">, 1<sup>F</sup></span></div>
</div></div></div>
<div class="e7-container pt-1 pb-1"><div class="e7-left"><div>噓</div></div>
<div class="e7-right ml-2"><div class="e7-right-top">
<div class="e7-author"><span itemprop="name"><a><span>bob</span></a></span></div>
</div><div class="e7-right-bottom">
<div class="e7-recommend-message"><div><span>噓</span></div></div>
<div class="e7-ipdatetime2"><span>07/01 15:07</span><span class="e7-floor">, 2<sup>F</sup></span></div>
</div></div></div>
<div class="e7-container pt-1 pb-1"><div class="e7-left"><div>→</div></div>
<div class="e7-right ml-2"><div class="e7-right-top">
<div class="e7-author"><span itemprop="name"><a><span>carol</span></a></span></div>
</div><div class="e7-right-bottom">
<div class="e7-recommend-message"><div><span>路過</span></div></div>
<div class="e7-ipdatetime2"><span>07/01 15:08</span><span class="e7-floor">, 3<sup>F</sup></span></div>
</div></div></div>
</body></html>'''


def test_pttweb_parse_metadata():
    data = parse_pttweb(PTTWEB_FIXTURE_HTML, PTTWEB_URL)
    assert data["title"] == "[閒聊] 備份測試"
    assert data["board"] == "C_Chat"
    assert data["author"] == "tester(測試員)"
    assert data["time"] == "2026/07/01 15:05"
    assert data["backup"] is True


def test_pttweb_parse_body_cut_before_signature():
    data = parse_pttweb(PTTWEB_FIXTURE_HTML, PTTWEB_URL)
    assert data["body"] == "備份內文第一行\n第二行"
    assert "發信站" not in data["body"]


def test_pttweb_counts_from_header():
    # 推噓統計以頁首數字為準（pttweb 長文只會先渲染部分推文）
    data = parse_pttweb(PTTWEB_FIXTURE_HTML, PTTWEB_URL)
    assert data["push_count"] == 19
    assert data["boo_count"] == 0
    assert data["arrow_count"] == 4
    assert data["total"] == 23


def test_pttweb_counts_fallback_to_rendered_pushes():
    html = PTTWEB_FIXTURE_HTML.replace("19(19推0噓4→)", "尚無統計")
    data = parse_pttweb(html, PTTWEB_URL)
    assert data["push_count"] == 1
    assert data["boo_count"] == 1
    assert data["arrow_count"] == 1
    assert data["total"] == 3


def test_pttweb_parse_pushes():
    data = parse_pttweb(PTTWEB_FIXTURE_HTML, PTTWEB_URL)
    assert len(data["pushes"]) == 3
    assert data["pushes"][0] == {"tag": "推", "userid": "alice", "content": "推推", "datetime": "07/01 15:06"}
    assert data["pushes"][1]["userid"] == "bob"
    assert data["pushes"][2]["tag"] == "→"


def test_pttweb_missing_article_raises():
    with pytest.raises(ArticleNotFoundError):
        parse_pttweb("<html><head><title>404</title></head><body>找不到頁面</body></html>", PTTWEB_URL)
