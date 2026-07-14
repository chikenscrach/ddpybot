import re
import io
import asyncio
import logging
from typing import List, Dict

import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

from core.classes import Cog_Extension

log = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
    # 優先用 lxml，未安裝則用內建 html.parser (import 時偵測一次即可)
    try:
        BeautifulSoup("", "lxml")
        PARSER = "lxml"
    except Exception:
        PARSER = "html.parser"
except ImportError:
    HAS_BS4 = False
    PARSER = "html.parser"

EXAMPLE_URL = "https://www.ptt.cc/bbs/C_Chat/M.1782889510.A.9DF.html"

# Embed description 上限 4096，保留緩衝
BODY_DISPLAY_LIMIT = 3800


def normalize_ptt_url(url: str) -> str:
    """驗證並補全 PTT 文章網址，回傳含 https:// 的完整網址"""
    url = url.strip()
    if not re.match(r"^https?://", url):
        # 支援使用者只貼 ptt.cc 開頭
        if url.startswith(("www.ptt.cc", "ptt.cc")):
            url = "https://" + url
        else:
            raise ValueError(f"網址需為 PTT 文章連結，例如 {EXAMPLE_URL}")

    if "ptt.cc" not in url or "/bbs/" not in url:
        raise ValueError("請提供正確的 PTT 文章網址 (需包含 ptt.cc 與 /bbs/)")

    # PTT 一律強制 https（http 會被 301 轉回 https，先升級可省一次來回）
    return re.sub(r"^http://", "https://", url)


def parse_ptt(html: str, url: str) -> Dict:
    """
    解析 PTT 文章 HTML
    回傳 dict 包含:
    - author, board, title, time
    - body (完整內文,不含推文與meta, 已去除發信站之後)
    - full_raw (去除 push/meta 後的原始 main-content 文字)
    - push_count, boo_count, arrow_count, total
    - pushes: List[{tag, userid, content, datetime}]
    """
    if not HAS_BS4:
        raise RuntimeError("缺少 beautifulsoup4，請執行 pip install beautifulsoup4 lxml")

    soup = BeautifulSoup(html, PARSER)

    # 判斷是否為 404 / 被刪除
    title_tag = soup.find("title")
    if title_tag and "404" in title_tag.text:
        raise ValueError("文章不存在或已被刪除 (404)")

    main = soup.find(id="main-content")
    if not main:
        # 有可能是 over18 攔截頁
        if "over18" in html.lower() or "年滿十八歲" in html:
            raise ValueError("此為限制級看板，驗證失敗。請確認網址正確或稍後再試 (已自動帶 over18=1)")
        raise ValueError("找不到文章主體，可能是已被刪除或網址錯誤")

    # === Meta 萃取，取完即移除，之後取內文才乾淨 ===
    author = board = title = time_str = ""
    for div in main.select("div.article-metaline, div.article-metaline-right"):
        tag_span = div.find("span", class_="article-meta-tag")
        val_span = div.find("span", class_="article-meta-value")
        if tag_span and val_span:
            t = tag_span.get_text(strip=True)
            v = val_span.get_text(strip=True)
            if t == "作者":
                author = v
            elif t == "看板":
                board = v
            elif t == "標題":
                title = v
            elif t == "時間":
                time_str = v
        div.decompose()

    # === 推文萃取，同樣取完即移除 ===
    pushes: List[Dict] = []
    push_count = boo_count = arrow_count = 0

    for push_div in main.find_all("div", class_="push"):
        tag_span = push_div.find("span", class_="push-tag")
        if tag_span:
            userid_span = push_div.find("span", class_="push-userid")
            content_span = push_div.find("span", class_="push-content")
            datetime_span = push_div.find("span", class_="push-ipdatetime")

            tag_raw = tag_span.get_text(strip=True)  # "推", "噓", "→"
            userid = userid_span.get_text(strip=True) if userid_span else "?"
            ipdatetime = datetime_span.get_text(strip=True) if datetime_span else ""

            # push-content 格式通常是 ": 內容"，移除前導冒號
            content = ""
            if content_span:
                c_text = content_span.get_text()
                content = (c_text[1:] if c_text.startswith(":") else c_text).strip()

            if "推" in tag_raw:
                push_count += 1
            elif "噓" in tag_raw:
                boo_count += 1
            else:
                # → 箭頭或其他
                arrow_count += 1

            pushes.append({
                "tag": tag_raw,
                "userid": userid,
                "content": content,
                "datetime": ipdatetime
            })
        push_div.decompose()

    # 此時 main-content 內剩餘的是內文 + 簽名 + ※ 發信站 等
    full_raw = main.get_text().strip()

    # 切出純內文 (去掉 ※ 發信站之後)
    split_markers = ["※ 發信站:", "※ 文章網址:", "※ 編輯:"]
    cut = min((full_raw.find(m) for m in split_markers if m in full_raw), default=len(full_raw))
    body = full_raw[:cut].strip()

    total = push_count + boo_count + arrow_count

    return {
        "url": url,
        "author": author,
        "board": board,
        "title": title or (title_tag.text if title_tag else "PTT 文章"),
        "time": time_str,
        "body": body,
        "full_raw": full_raw,
        "push_count": push_count,
        "boo_count": boo_count,
        "arrow_count": arrow_count,
        "total": total,
        "pushes": pushes
    }


def build_main_embed(data: Dict, url: str) -> discord.Embed:
    # 顏色邏輯: 推多綠色，噓多紅色
    if data["boo_count"] > data["push_count"]:
        color = 0xE74C3C
    elif data["push_count"] > data["boo_count"]:
        color = 0x2ECC71
    else:
        color = 0x3498DB

    body = data["body"] or "(無內文或僅有圖片連結)"
    truncated = len(body) > BODY_DISPLAY_LIMIT
    if truncated:
        display_body = body[:BODY_DISPLAY_LIMIT] + "\n\n...（內文過長，已截斷，完整版請看附檔）"
    else:
        display_body = body

    embed = discord.Embed(
        title=data["title"][:256],  # title limit 256
        url=url,
        description=display_body,
        color=color
    )
    embed.add_field(name="看板", value=data["board"] or "未知", inline=True)
    embed.add_field(name="作者", value=data["author"][:1024] or "未知", inline=True)
    embed.add_field(name="時間", value=data["time"] or "未知", inline=True)

    embed.add_field(
        name="📊 推噓統計",
        value=(
            f"👍 推: **{data['push_count']}**\n"
            f"👎 噓: **{data['boo_count']}**\n"
            f"➡️ →: **{data['arrow_count']}**\n"
            f"💬 總留言: **{data['total']}**"
        ),
        inline=False
    )

    footer_text = f"PTT {data['board']} | 推:{data['push_count']} 噓:{data['boo_count']} →:{data['arrow_count']}"
    if truncated:
        footer_text += " | 內文已截斷"
    embed.set_footer(text=footer_text)

    return embed


def build_full_file(data: Dict, url: str) -> discord.File:
    """組出完整內文 txt 附檔 (指令自動附檔與「完整內文檔」按鈕共用)"""
    pushes_text = "\n".join(
        f"{p['tag']} {p['userid']}: {p['content']} {p['datetime']}" for p in data["pushes"]
    )
    sep = "-" * 30
    combined = (
        f"標題: {data['title']}\n"
        f"看板: {data['board']}\n"
        f"作者: {data['author']}\n"
        f"時間: {data['time']}\n"
        f"網址: {url}\n"
        f"{sep}\n"
        f"推: {data['push_count']} 噓: {data['boo_count']} →: {data['arrow_count']} 總計: {data['total']}\n"
        f"{sep}\n"
        f"【內文】\n{data['body']}\n"
        f"{sep}\n"
        f"【完整原始內文(含簽名等)】\n{data['full_raw']}\n"
        f"{sep}\n"
        f"【推文列表 ({data['total']}則)】\n{pushes_text}\n"
    )
    filename = re.sub(r'[\\/:*?"<>|\s]+', "_", f"ptt_{data['board']}_{data['title'][:20]}") + ".txt"
    return discord.File(io.BytesIO(combined.encode("utf-8")), filename=filename)


class AutoDisableView(discord.ui.View):
    """timeout 後自動停用按鈕並更新訊息 (連結按鈕不停用)"""

    def __init__(self, timeout: float):
        super().__init__(timeout=timeout)
        self.message: discord.Message | None = None

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.style == discord.ButtonStyle.link:
                continue
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class PushPaginatorView(AutoDisableView):
    PER_PAGE = 15

    def __init__(self, data: Dict, author_id: int):
        super().__init__(timeout=180)
        self.data = data
        self.pushes = data["pushes"]
        self.author_id = author_id
        self.page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("只有開啟這份推文列表的人可以翻頁。", ephemeral=True)
            return False
        return True

    def get_total_pages(self):
        if not self.pushes:
            return 1
        return (len(self.pushes) - 1) // self.PER_PAGE + 1

    def get_embed(self) -> discord.Embed:
        total_pages = self.get_total_pages()
        start = self.page * self.PER_PAGE
        slice_pushes = self.pushes[start:start + self.PER_PAGE]

        lines = []
        for p in slice_pushes:
            tag = p["tag"]
            if "推" in tag:
                prefix = "⭕ 推"
            elif "噓" in tag:
                prefix = "❌ 噓"
            else:
                prefix = "➡️ →"
            # 避免內容過長
            content = p["content"]
            if len(content) > 80:
                content = content[:80] + "…"
            lines.append(f"`{prefix}` **{p['userid']}**: {content}\n   {p['datetime']}")

        desc = "\n\n".join(lines) if lines else "無推文"
        # Discord description limit 4096
        if len(desc) > 4000:
            desc = desc[:4000] + "\n..."

        embed = discord.Embed(
            title=f"💬 推文列表 - {self.data['title'][:50]}",
            description=desc,
            color=0x95A5A6
        )
        embed.set_footer(
            text=f"第 {self.page+1}/{total_pages} 頁 | 總計 {len(self.pushes)} 則"
                 f" | 推:{self.data['push_count']} 噓:{self.data['boo_count']} →:{self.data['arrow_count']}"
        )
        return embed

    @discord.ui.button(label="上一頁", style=discord.ButtonStyle.secondary, emoji="⬅️")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="下一頁", style=discord.ButtonStyle.secondary, emoji="➡️")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.get_total_pages() - 1:
            self.page += 1
        await interaction.response.edit_message(embed=self.get_embed(), view=self)


class PTTMainView(AutoDisableView):
    def __init__(self, article_data: Dict, url: str):
        super().__init__(timeout=300)
        self.article_data = article_data
        self.url = url

        # 連結按鈕 (Link Button 必須用 add_item)
        self.add_item(discord.ui.Button(label="開啟原文", url=url, style=discord.ButtonStyle.link, emoji="🔗"))

    @discord.ui.button(label="推文列表", style=discord.ButtonStyle.primary, emoji="💬")
    async def show_pushes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.article_data["pushes"]:
            return await interaction.response.send_message("此文章目前沒有任何推文。", ephemeral=True)

        paginator = PushPaginatorView(self.article_data, interaction.user.id)
        await interaction.response.send_message(embed=paginator.get_embed(), view=paginator)
        paginator.message = await interaction.original_response()

    @discord.ui.button(label="完整內文檔", style=discord.ButtonStyle.secondary, emoji="📄")
    async def show_full(self, interaction: discord.Interaction, button: discord.ui.Button):
        file = build_full_file(self.article_data, self.url)
        await interaction.response.send_message(f"📄 **{self.article_data['title']}** 完整內文", file=file, ephemeral=True)


class PTT(Cog_Extension):
    """PTT 文章抓取"""

    # 連線層暫時性錯誤（DNS 失敗、TLS 握手瞬斷等）的最大嘗試次數
    FETCH_RETRIES = 3

    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        self.session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        timeout = aiohttp.ClientTimeout(total=20)
        self.session = aiohttp.ClientSession(timeout=timeout, cookie_jar=aiohttp.CookieJar())

    async def cog_unload(self):
        if self.session:
            await self.session.close()

    async def _fetch_html(self, url: str) -> str:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8"
        }
        cookies = {"over18": "1"}

        last_err: Exception | None = None
        for attempt in range(1, self.FETCH_RETRIES + 1):
            try:
                async with self.session.get(url, headers=headers, cookies=cookies) as resp:
                    if resp.status == 404:
                        raise ValueError("找不到此文章 (404)，可能已被刪除或網址錯誤")
                    if resp.status != 200:
                        raise ValueError(f"抓取失敗，HTTP狀態碼: {resp.status}")
                    html = await resp.text()
                    # 如果被導到 over18 驗證頁，但我們已帶 cookie，若還是驗證頁代表看板可能有問題
                    if 'id="over18-modal"' in html or ("ask/over18" in str(resp.url) and "main-content" not in html):
                        # 多數情況帶 cookie 就過，若仍失敗，拋錯
                        if "main-content" not in html:
                            raise ValueError("過18驗證失敗，可能是 PTT 暫時阻擋或網址錯誤")
                    return html
            except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
                # 連線層的暫時性錯誤（DNS、TLS 握手瞬斷）重試幾次再放棄
                last_err = e
                if attempt < self.FETCH_RETRIES:
                    log.warning("PTT 連線失敗 (第 %d/%d 次): %s，稍後重試", attempt, self.FETCH_RETRIES, e)
                    await asyncio.sleep(attempt)  # 1s、2s 漸進等待
            except aiohttp.ClientError as e:
                log.warning(f"PTT fetch ClientError: {e}")
                raise ValueError(f"網路連線錯誤: {e}")

        if isinstance(last_err, asyncio.TimeoutError):
            raise ValueError(f"連線逾時（已嘗試 {self.FETCH_RETRIES} 次），請稍後再試")
        raise ValueError(f"網路連線錯誤（已嘗試 {self.FETCH_RETRIES} 次）: {last_err}")

    @app_commands.command(name="ptt", description="抓取PTT文章完整內文與推噓統計")
    @app_commands.describe(url=f"PTT 文章網址，例如 {EXAMPLE_URL}")
    async def ptt(self, interaction: discord.Interaction, url: str):
        if not HAS_BS4:
            return await interaction.response.send_message(
                "❌ 機器人缺少 `beautifulsoup4`，請先安裝：`pip install beautifulsoup4 lxml`",
                ephemeral=True
            )

        # 網址驗證在 defer 之前完成，錯誤訊息才能維持 ephemeral
        try:
            url = normalize_ptt_url(url)
        except ValueError as ve:
            return await interaction.response.send_message(f"❌ {ve}", ephemeral=True)

        await interaction.response.defer(thinking=True)

        try:
            html = await self._fetch_html(url)
            # 爆文的 HTML 解析可能耗時，丟到 thread 避免卡住 event loop
            data = await asyncio.to_thread(parse_ptt, html, url)
        except ValueError as ve:
            return await interaction.followup.send(f"❌ {ve}")
        except Exception:
            log.exception("PTT 解析失敗")
            return await interaction.followup.send("❌ 解析文章時發生未知錯誤，請通知管理員。")

        embed = build_main_embed(data, url)
        view = PTTMainView(data, url)

        files = []
        # 若內文超過顯示上限，自動附上完整文字檔
        if len(data["body"]) > BODY_DISPLAY_LIMIT or len(data["full_raw"]) > BODY_DISPLAY_LIMIT:
            files.append(build_full_file(data, url))

        if files:
            msg = await interaction.followup.send(embed=embed, view=view, files=files)
        else:
            msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(PTT(bot))
