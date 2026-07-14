# ──────────────────────────────────────────────
#  通用分頁器 View（翻頁按鈕）
# ──────────────────────────────────────────────
import discord
from typing import Optional


class PaginationView(discord.ui.View):
    """
    通用分頁 View，支援 ⏪◀ 頁碼 ▶⏩ 按鈕。

    Parameters
    ----------
    pages : list[discord.Embed]
        所有頁面的 Embed 列表。
    author : discord.Member | discord.User
        觸發此指令的使用者（只有此人可翻頁）。
    timeout : float
        View 超時秒數，預設 120。
    """

    def __init__(
        self,
        pages: list[discord.Embed],
        author: discord.Member | discord.User,
        timeout: float = 120,
    ):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.current_page = 0
        self.author = author
        self.message: Optional[discord.Message] = None
        self._update_buttons()

    def _update_buttons(self):
        self.btn_first.disabled = self.current_page == 0
        self.btn_prev.disabled = self.current_page == 0
        self.btn_next.disabled = self.current_page == len(self.pages) - 1
        self.btn_last.disabled = self.current_page == len(self.pages) - 1
        self.btn_page.label = f'{self.current_page + 1} / {len(self.pages)}'

    async def _check_author(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                '❌ 這不是你的指令面板！', ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label='⏪', style=discord.ButtonStyle.secondary)
    async def btn_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

    @discord.ui.button(label='◀', style=discord.ButtonStyle.primary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label='1 / 1', style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    @discord.ui.button(label='▶', style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label='⏩', style=discord.ButtonStyle.secondary)
    async def btn_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page = len(self.pages) - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[-1], view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass
