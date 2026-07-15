import discord
from discord.ext import commands

from core.classes import CogExtension
from utils.constants import COG_EMOJI, COLOR_BLURPLE
from views.pagination import PaginationView


class Help(CogExtension):
    # main.py 已設定 help_command=None，這裡不需要再 remove_command('help')

    @commands.hybrid_command(name='help', description='查看所有指令')
    async def help_command(self, ctx: commands.Context):
        pages = self._build_pages(ctx)

        if not pages:
            await ctx.send('❌ 目前沒有可用的指令！')
            return

        view = PaginationView(pages, ctx.author)
        message = await ctx.send(embed=pages[0], view=view)
        view.message = message

    def _build_pages(self, ctx: commands.Context) -> list:
        pages = []
        cog_list = []

        for cog_name, cog in self.bot.cogs.items():
            # 同時蒐集 prefix/hybrid 指令 和 純 app_commands
            prefix_cmds = cog.get_commands()      # !cmd / hybrid
            slash_cmds  = cog.get_app_commands()  # /cmd (純斜線)

            # hybrid_command 會同時出現在兩邊，只保留 prefix 那側避免重複顯示
            hybrid_names = {
                c.name for c in prefix_cmds
                if isinstance(c, commands.HybridCommand)
            }
            pure_slash = [
                c for c in slash_cmds
                if c.name not in hybrid_names
            ]

            if not prefix_cmds and not pure_slash:
                continue

            cog_list.append((cog_name, cog, prefix_cmds, pure_slash))

        if not cog_list:
            return pages

        # ==========================================
        #  首頁：總覽所有分類
        # ==========================================
        home = discord.Embed(
            title='📖 指令幫助',
            description='使用下方按鈕切換不同分類的指令\n'
                        '支援前綴指令 `!` `！` 以及斜線指令 `/`',
            color=COLOR_BLURPLE,
        )

        if self.bot.user and self.bot.user.avatar:
            home.set_thumbnail(url=self.bot.user.avatar.url)

        for cog_name, _cog, prefix_cmds, pure_slash in cog_list:
            emoji = COG_EMOJI.get(cog_name, '📁')

            all_names = [f'`{c.name}`' for c in prefix_cmds]
            all_names += [f'`/{c.name}`' for c in pure_slash]
            total = len(prefix_cmds) + len(pure_slash)

            home.add_field(
                name=f'{emoji} {cog_name}（{total} 個指令）',
                value='、'.join(all_names),
                inline=False,
            )

        total_cmds = sum(
            len(p) + len(s) for _, _, p, s in cog_list
        )
        home.set_footer(
            text=f'共 {len(cog_list)} 個分類、{total_cmds} 個指令 • 首頁'
        )
        pages.append(home)

        # ==========================================
        #  各分類頁面
        # ==========================================
        for i, (cog_name, cog, prefix_cmds, pure_slash) in enumerate(cog_list):
            emoji = COG_EMOJI.get(cog_name, '📁')

            embed = discord.Embed(
                title=f'{emoji} {cog_name}',
                description=cog.description or f'{cog_name} 的所有指令',
                color=COLOR_BLURPLE,
            )

            # ── prefix / hybrid 指令 ──
            for cmd in prefix_cmds:
                if isinstance(cmd, commands.HybridCommand):
                    cmd_type = '`/` `!`'
                else:
                    cmd_type = '`!`'

                desc = cmd.description or cmd.help or '沒有說明'
                signature = cmd.signature
                usage = f'{cmd.name} {signature}' if signature else cmd.name

                embed.add_field(
                    name=f'{cmd_type}  `{usage}`',
                    value=f'> {desc}',
                    inline=False,
                )

            # ── 純 app_commands（斜線指令）──
            for cmd in pure_slash:
                cmd_type = '`/`'
                desc = cmd.description or '沒有說明'

                if cmd.parameters:
                    params = ' '.join(
                        f'<{p.name}>' if p.required else f'[{p.name}]'
                        for p in cmd.parameters
                    )
                    usage = f'{cmd.name} {params}'
                else:
                    usage = cmd.name

                embed.add_field(
                    name=f'{cmd_type}  `{usage}`',
                    value=f'> {desc}',
                    inline=False,
                )

            total = len(prefix_cmds) + len(pure_slash)
            embed.set_footer(
                text=f'第 {i + 2} / {len(cog_list) + 1} 頁 • '
                     f'{cog_name}（{total} 個指令）'
            )
            pages.append(embed)

        return pages


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
