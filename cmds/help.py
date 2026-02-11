import discord
from discord.ext import commands
from discord import app_commands
from core.classes import Cog_Extension
from typing import Optional

# ✅ 每個 Cog 對應的 Emoji（可自行修改）
COG_EMOJI = {
    'Main': '🏠',
    'React': '🎭',
    'Event': '📡',
    'Task': '⏰',
    'Help': '❓',
}


class HelpView(discord.ui.View):
    def __init__(self, pages: list, author: discord.Member):
        super().__init__(timeout=120)
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

    # ========== 第一頁 ==========
    @discord.ui.button(label='⏪', style=discord.ButtonStyle.secondary)
    async def btn_first(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page = 0
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[0], view=self)

    # ========== 上一頁 ==========
    @discord.ui.button(label='◀', style=discord.ButtonStyle.primary)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    # ========== 頁碼顯示 ==========
    @discord.ui.button(label='1 / 1', style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

    # ========== 下一頁 ==========
    @discord.ui.button(label='▶', style=discord.ButtonStyle.primary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    # ========== 最後一頁 ==========
    @discord.ui.button(label='⏩', style=discord.ButtonStyle.secondary)
    async def btn_last(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_author(interaction):
            return
        self.current_page = len(self.pages) - 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[-1], view=self)

    # ========== 超時後禁用所有按鈕 ==========
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


class Help(Cog_Extension):
    def __init__(self, bot: commands.Bot):
        super().__init__(bot)
        # 移除 discord.py 內建的 help 指令
        self.bot.remove_command('help')

    @commands.hybrid_command(name='help', description='查看所有指令')
    async def help_command(self, ctx: commands.Context):
        pages = self._build_pages(ctx)

        if not pages:
            await ctx.send('❌ 目前沒有可用的指令！')
            return

        view = HelpView(pages, ctx.author)
        message = await ctx.send(embed=pages[0], view=view)
        view.message = message

    def _build_pages(self, ctx: commands.Context) -> list:
        pages = []
        cog_list = []

        # 蒐集所有有指令的 Cog
        for cog_name, cog in self.bot.cogs.items():
            cmds = cog.get_commands()
            if not cmds:
                continue
            cog_list.append((cog_name, cog, cmds))

        if not cog_list:
            return pages

        # ==========================================
        #  首頁：總覽所有分類
        # ==========================================
        home = discord.Embed(
            title='📖 指令幫助',
            description='使用下方按鈕切換不同分類的指令\n'
                        '支援前綴指令 `!` `！` 以及斜線指令 `/`',
            color=0x5865F2,
        )

        if self.bot.user and self.bot.user.avatar:
            home.set_thumbnail(url=self.bot.user.avatar.url)

        for cog_name, cog, cmds in cog_list:
            emoji = COG_EMOJI.get(cog_name, '📁')
            cmd_names = '、'.join(f'`{c.name}`' for c in cmds)
            home.add_field(
                name=f'{emoji} {cog_name}（{len(cmds)} 個指令）',
                value=cmd_names,
                inline=False,
            )

        total_cmds = sum(len(cmds) for _, _, cmds in cog_list)
        home.set_footer(text=f'共 {len(cog_list)} 個分類、{total_cmds} 個指令 • 首頁')
        pages.append(home)

        # ==========================================
        #  各分類頁面
        # ==========================================
        for i, (cog_name, cog, cmds) in enumerate(cog_list):
            emoji = COG_EMOJI.get(cog_name, '📁')

            embed = discord.Embed(
                title=f'{emoji} {cog_name}',
                description=cog.description or f'{cog_name} 的所有指令',
                color=0x5865F2,
            )

            for cmd in cmds:
                # 判斷是否支援斜線指令
                if isinstance(cmd, commands.HybridCommand):
                    cmd_type = '`/` `!`'
                else:
                    cmd_type = '`!`'

                # 指令說明
                desc = cmd.description or cmd.help or '沒有說明'

                # 指令用法（含參數）
                signature = cmd.signature
                if signature:
                    usage = f'{cmd.name} {signature}'
                else:
                    usage = cmd.name

                embed.add_field(
                    name=f'{cmd_type}  `{usage}`',
                    value=f'> {desc}',
                    inline=False,
                )

            embed.set_footer(
                text=f'第 {i + 2} / {len(cog_list) + 1} 頁 • {cog_name}'
            )
            pages.append(embed)

        return pages


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))