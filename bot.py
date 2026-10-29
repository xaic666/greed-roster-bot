"""Greed live roster: read-only Discord role aggregation, split into Tank/Healer/DPS panels."""
import asyncio
import io
import sys
import json
import logging
import os
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from raid_manager import register as register_raid_manager

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('greed-roster')


def required_int(name):
    val = os.environ.get(name, '')
    if not val.isdigit():
        raise RuntimeError(f'Set numeric {name} in .env')
    return int(val)


TOKEN = os.environ.get('DISCORD_TOKEN', '')
GUILD_ID = required_int('GUILD_ID')
CHANNEL_ID = required_int('ROSTER_CHANNEL_ID')
CONFIG = json.loads((BASE / 'config.json').read_text(encoding='utf-8'))
STATE_FILE = BASE / 'roster_state.json'
RANKS = list(CONFIG['guild_ranks'])
COMBAT = list(CONFIG['combat_roles'])
CLASSES = list(CONFIG['classes'])
DELAY = max(1, int(CONFIG.get('refresh_delay_seconds', 5)))

CLASS_COLORS = {
    'Warrior': '#C79C6E', 'Paladin': '#F58CBA', 'Hunter': '#ABD473',
    'Rogue': '#FFF569', 'Priest': '#FFFFFF', 'Shaman': '#0070DE',
    'Mage': '#69CCF0', 'Warlock': '#9482C9', 'Druid': '#FF7D0A'
}
ROLE_COLORS = {'Tank': '#7DB8FF', 'Healer': '#7EDC8E', 'DPS': '#F0D27A'}


def role_matches(member, categories):
    role_names = {r.name.casefold() for r in member.roles}
    return [key for key, aliases in categories.items()
            if any(a.casefold() in role_names for a in aliases)]


def build_roster(members):
    roster = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    issues = []
    totals = {'Raider': 0, 'Recruit': 0, 'Social': 0,
              'Tank': 0, 'Healer': 0, 'DPS': 0}
    for member in members:
        if member.bot:
            continue
        rank = role_matches(member, CONFIG['guild_ranks'])
        if not rank:
            continue
        clazz = role_matches(member, CONFIG['classes'])
        combat = role_matches(member, CONFIG['combat_roles'])
        if len(rank) != 1 or len(clazz) != 1 or len(combat) != 1:
            issues.append((member, rank, clazz, combat))
            continue
        roster[clazz[0]][combat[0]][rank[0]].append(member)
        totals[rank[0]] += 1
        totals[combat[0]] += 1
    return roster, totals, issues


def persist_config():
    """Atomically save mapping changes selected through Discord."""
    dest = (BASE / 'config.json').with_suffix('.tmp')
    dest.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    dest.replace(BASE / 'config.json')


def update_config_mapping(section, key, roles):
    CONFIG[section][key] = [role.name for role in roles]
    persist_config()
    schedule_update()


def short_name(member):
    return discord.utils.escape_markdown(member.display_name).replace('@', '@\u200b')


def describe_issue(rank_matches, class_matches, combat_matches):
    problems = []
    if len(class_matches) == 0:
        problems.append('missing Class')
    elif len(class_matches) > 1:
        problems.append('multiple Classes: ' + ', '.join(class_matches))

    if len(combat_matches) == 0:
        problems.append('missing Role')
    elif len(combat_matches) > 1:
        problems.append('multiple Roles: ' + ', '.join(combat_matches))

    if len(rank_matches) == 0:
        problems.append('missing Guild Rank')
    elif len(rank_matches) > 1:
        problems.append('multiple Guild Ranks: ' + ', '.join(rank_matches))

    return '; '.join(problems) if problems else 'check configuration'


def _font_candidates(size, bold=False):
    if sys.platform == 'win32':
        if bold:
            return [
                r'C:\Windows\Fonts\segoeuib.ttf',
                r'C:\Windows\Fonts\arialbd.ttf',
            ]
        return [
            r'C:\Windows\Fonts\segoeui.ttf',
            r'C:\Windows\Fonts\arial.ttf',
            r'C:\Windows\Fonts\tahoma.ttf',
        ]
    return [
        '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]


def font(size, bold=False):
    for name in _font_candidates(size, bold=bold):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _measure(draw, text, use_font):
    left, top, right, bottom = draw.textbbox((0, 0), text, font=use_font)
    return right - left, bottom - top


def wrap_text(draw, value, max_width, use_font):
    if not value or value == '—':
        return ['—']
    items = value.split(', ')
    lines = []
    line = ''
    for item in items:
        item = item.strip()
        while item and _measure(draw, item, use_font)[0] > max_width:
            item = item[:-2] + '…'
        proposed = f'{line}, {item}' if line else item
        if line and _measure(draw, proposed, use_font)[0] > max_width:
            lines.append(line)
            line = item
        else:
            line = proposed
    if line:
        lines.append(line)
    return lines or ['—']


def render_role_panel(roster, totals, issues, combat_role, panel_index, panel_count):
    regular = font(28)
    bold = font(29, True)
    heading = font(42, True)
    small = font(21)

    # Fixed readable size; one panel per combat role.
    columns = [('CLASS', 165), ('RAIDER', 235), ('RECRUIT', 245), ('SOCIAL', 235)]
    padding = 22
    width = sum(w for _, w in columns) + padding * 2

    test = Image.new('RGB', (width, 200), '#111827')
    measure = ImageDraw.Draw(test)

    rows = []
    for clazz in CLASSES:
        ranks = roster.get(clazz, {}).get(combat_role, {})
        if not any(ranks.values()):
            continue
        cell_values = []
        for rank in RANKS:
            players = sorted(ranks.get(rank, []), key=lambda m: m.display_name.casefold())
            cell_values.append(', '.join(short_name(m) for m in players) or '—')
        wrapped = [wrap_text(measure, value, columns[i + 1][1] - 18, regular)
                   for i, value in enumerate(cell_values)]
        line_count = max(len(lines) for lines in wrapped) if wrapped else 1
        row_height = max(58, 16 + 32 * line_count)
        rows.append((clazz, wrapped, row_height))

    header_height = 165
    table_header_h = 48
    body_height = sum(r[2] for r in rows) if rows else 60

    issue_entries = []
    if panel_index == panel_count - 1 and issues:
        for member, rank_matches, class_matches, combat_matches in sorted(issues, key=lambda x: x[0].display_name.casefold()):
            issue_entries.append(f'{short_name(member)}: {describe_issue(rank_matches, class_matches, combat_matches)}')

    wrapped_issues = []
    issue_area_height = 0
    if issue_entries:
        issue_wrap_font = small
        max_issue_width = width - padding * 2 - 12
        for text in issue_entries:
            # wrap based on words this time, to keep diagnostics readable
            words = text.split(' ')
            line = ''
            lines = []
            for word in words:
                proposed = f'{line} {word}'.strip()
                if line and _measure(measure, proposed, issue_wrap_font)[0] > max_issue_width:
                    lines.append(line)
                    line = word
                else:
                    line = proposed
            if line:
                lines.append(line)
            wrapped_issues.append(lines)
        issue_area_height = 52 + sum(28 * len(lines) + 8 for lines in wrapped_issues)

    height = header_height + table_header_h + body_height + issue_area_height + 28
    image = Image.new('RGB', (width, height), '#111827')
    d = ImageDraw.Draw(image)

    y = 18
    d.text((padding, y), f'GREED | {combat_role.upper()} ROSTER', fill='#F1E6CA', font=heading)
    y += 52
    total_members = sum(totals.get(rank, 0) for rank in RANKS)
    summary = f'{total_members} members  |  {totals["Tank"]} tanks  |  {totals["Healer"]} healers  |  {totals["DPS"]} DPS'
    d.text((padding, y), summary, fill='#E5E7EB', font=bold)
    y += 35
    role_total = totals.get(combat_role, 0)
    sub = f'{combat_role}: {role_total} total  |  Raiders {totals.get("Raider", 0)}  |  Recruits {totals.get("Recruit", 0)}  |  Socials {totals.get("Social", 0)}'
    d.text((padding, y), sub, fill=ROLE_COLORS.get(combat_role, '#B8C0CF'), font=small)
    y += 42

    x = padding
    for label, col_width in columns:
        d.rectangle((x, y, x + col_width, y + table_header_h), fill='#2B3445')
        d.text((x + 10, y + 10), label, fill='#F9FAFB', font=small)
        x += col_width
    y += table_header_h

    if rows:
        for row_idx, (clazz, wrapped, row_height) in enumerate(rows):
            bg = '#1A2231' if row_idx % 2 == 0 else '#151C29'
            d.rectangle((padding, y, width - padding, y + row_height), fill=bg)
            x = padding
            for col_idx, (_, col_width) in enumerate(columns):
                if col_idx == 0:
                    d.text((x + 10, y + 12), clazz, fill=CLASS_COLORS.get(clazz, '#FFFFFF'), font=bold)
                else:
                    lines = wrapped[col_idx - 1]
                    for line_idx, line in enumerate(lines):
                        fill = '#E5E7EB' if line != '—' else '#667085'
                        d.text((x + 10, y + 9 + line_idx * 30), line, fill=fill, font=regular)
                x += col_width
                d.line((x, y, x, y + row_height), fill='#314056', width=1)
            d.line((padding, y + row_height, width - padding, y + row_height), fill='#314056', width=1)
            y += row_height
    else:
        d.rectangle((padding, y, width - padding, y + 60), fill='#1A2231')
        d.text((padding + 10, y + 16), f'No {combat_role.lower()}s classified yet.', fill='#E5E7EB', font=regular)
        y += 60

    if wrapped_issues:
        y += 12
        d.text((padding, y), 'NEEDS ATTENTION', fill='#FFC27A', font=bold)
        y += 36
        for lines in wrapped_issues:
            for line in lines:
                d.text((padding, y), line, fill='#EAB0B5', font=small)
                y += 28
            y += 8

    output = io.BytesIO()
    image.save(output, format='PNG', optimize=True)
    output.seek(0)
    file_name = f'greed-roster-{combat_role.lower()}.png'
    embed = discord.Embed(
        title='GREED | Live Guild Roster' if panel_index == 0 else f'GREED | Live Guild Roster ({combat_role})',
        color=0xC7A35B,
        description='Automatically updated from Discord roles.' if panel_index == 0 else None,
    )
    embed.set_image(url=f'attachment://{file_name}')
    if panel_index == panel_count - 1:
        embed.set_footer(text='The same message is edited whenever roles change')
    return embed, discord.File(output, filename=file_name)


def render_panels(roster, totals, issues):
    embeds = []
    files = []
    for idx, combat_role in enumerate(COMBAT):
        embed, file = render_role_panel(roster, totals, issues, combat_role, idx, len(COMBAT))
        embeds.append(embed)
        files.append(file)
    return embeds, files


intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)
refresh_task = None
update_lock = asyncio.Lock()


def read_state():
    try:
        data = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return [int(mid) for mid in data.get(str(CHANNEL_ID), [])]
    except (OSError, ValueError, TypeError):
        return []


def save_state(ids):
    dest = STATE_FILE.with_suffix('.tmp')
    dest.write_text(json.dumps({str(CHANNEL_ID): ids}, indent=2), encoding='utf-8')
    dest.replace(STATE_FILE)


async def update_roster():
    async with update_lock:
        guild = bot.get_guild(GUILD_ID)
        if guild is None:
            raise RuntimeError('Bot is not installed in configured guild')
        channel = guild.get_channel(CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError('ROSTER_CHANNEL_ID must refer to a text channel')

        members = [m async for m in guild.fetch_members(limit=None)]
        embeds, attachments = render_panels(*build_roster(members))

        previous = read_state()
        msg = None
        for mid in previous:
            try:
                candidate = await channel.fetch_message(mid)
                if candidate.author.id == bot.user.id and msg is None:
                    msg = candidate
            except discord.NotFound:
                pass

        if msg:
            await msg.edit(content=None, embeds=embeds, attachments=attachments,
                           allowed_mentions=discord.AllowedMentions.none())
        else:
            msg = await channel.send(embeds=embeds, files=attachments,
                                     allowed_mentions=discord.AllowedMentions.none())

        save_state([msg.id])
        for mid in previous:
            if mid == msg.id:
                continue
            try:
                old = await channel.fetch_message(mid)
                if old.author.id == bot.user.id:
                    await old.delete()
            except discord.NotFound:
                pass
        log.info('Roster updated: %d members, %d panel(s)', len(members), len(embeds))


async def deferred_update():
    await asyncio.sleep(DELAY)
    try:
        await update_roster()
    except Exception:
        log.exception('Roster auto-refresh failed')


def schedule_update():
    global refresh_task
    if refresh_task and not refresh_task.done():
        refresh_task.cancel()
    refresh_task = asyncio.create_task(deferred_update())


@bot.event
async def on_ready():
    log.info('Logged in as %s', bot.user)
    try:
        await update_roster()
    except Exception:
        log.exception('Startup roster update failed')


@bot.event
async def on_member_update(before, after):
    if after.guild.id == GUILD_ID and (before.roles != after.roles or before.display_name != after.display_name):
        schedule_update()


@bot.event
async def on_member_join(member):
    if member.guild.id == GUILD_ID:
        schedule_update()


@bot.event
async def on_member_remove(member):
    if member.guild.id == GUILD_ID:
        schedule_update()


class MappingPicker(discord.ui.RoleSelect):
    def __init__(self, section, key):
        super().__init__(placeholder=f'Add Discord roles to {key}', min_values=1, max_values=25)
        self.section = section
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
            return
        existing = CONFIG[self.section][self.key]
        additions = [role.name for role in self.values]
        new_names = list(existing)
        for name in additions:
            if name.casefold() not in {x.casefold() for x in new_names}:
                new_names.append(name)
        CONFIG[self.section][self.key] = new_names
        persist_config()
        schedule_update()
        await interaction.response.edit_message(
            content=f'**{self.key}** now maps to: {", ".join(new_names)}\n'
                    'New selections are ADDED, not substituted. Use the buttons below to add/remove other roles.',
            view=MappingPickerView(self.section, self.key)
        )


class RoleNameModal(discord.ui.Modal):
    def __init__(self, section, key, operation):
        super().__init__(title=f'{operation.title()} {key} role mapping')
        self.section, self.key, self.operation = section, key, operation
        self.names = discord.ui.TextInput(
            label='Discord role names or IDs (comma-separated)',
            style=discord.TextStyle.paragraph,
            placeholder='Raider, Officer, 123456789012345678',
            max_length=1500,
            required=True
        )
        self.add_item(self.names)

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
            return
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message('This works only inside a server.', ephemeral=True)
            return
        tokens = [x.strip() for x in str(self.names.value).split(',') if x.strip()]
        if not tokens:
            await interaction.response.send_message('No role names were entered.', ephemeral=True)
            return
        resolved, unknown = [], []
        for item in tokens:
            matches = ([r for r in guild.roles if r.id == int(item)] if item.isdecimal()
                       else [r for r in guild.roles if r.name.casefold() == item.casefold()])
            if len(matches) == 1:
                role = matches[0]
                if role.is_default():
                    unknown.append(item + ' (everyone role)')
                else:
                    resolved.append(role.name)
            elif len(matches) > 1:
                unknown.append(item + ' (ambiguous, use role ID)')
            else:
                unknown.append(item)
        if unknown:
            await interaction.response.send_message(
                'No changes saved. Could not uniquely resolve: ' + ', '.join(unknown) +
                '. Check the exact role names or use Copy Role ID (Developer Mode).', ephemeral=True)
            return
        previous = CONFIG[self.section][self.key]
        if self.operation == 'add':
            updated = list(previous)
            for name in resolved:
                if name.casefold() not in {x.casefold() for x in updated}:
                    updated.append(name)
        else:
            removing = {name.casefold() for name in resolved}
            updated = [name for name in previous if name.casefold() not in removing]
        CONFIG[self.section][self.key] = updated
        persist_config()
        schedule_update()
        await interaction.response.send_message(
            f'Updated **{self.key}**. Mapping: {", ".join(updated) or "(none)"}', ephemeral=True)


class MappingPickerView(discord.ui.View):
    def __init__(self, section, key):
        super().__init__(timeout=300)
        self.section, self.key = section, key
        self.add_item(MappingPicker(section, key))

    @discord.ui.button(label='Add by name / ID', style=discord.ButtonStyle.primary, row=1)
    async def add_names(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
            return
        await interaction.response.send_modal(RoleNameModal(self.section, self.key, 'add'))

    @discord.ui.button(label='Remove by name / ID', style=discord.ButtonStyle.secondary, row=1)
    async def remove_names(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
            return
        await interaction.response.send_modal(RoleNameModal(self.section, self.key, 'remove'))


class SettingCategorySelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder='Choose mapping category', options=[
            discord.SelectOption(label='Combat roles', value='combat_roles', description='Tank, Healer, DPS'),
            discord.SelectOption(label='Guild ranks', value='guild_ranks', description='Raider, Recruit, Social'),
            discord.SelectOption(label='Classes', value='classes', description='WoW class roles'),
        ])

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
            return
        section = self.values[0]
        await interaction.response.edit_message(
            content=f'**{section.replace("_", " ").title()}**: choose which roster category to configure. Each category can map to multiple Discord roles.',
            view=SettingKeyView(section)
        )


class SettingsHome(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(SettingCategorySelect())


class SettingKeySelect(discord.ui.Select):
    def __init__(self, section):
        self.section = section
        super().__init__(placeholder='Choose roster category', options=[
            discord.SelectOption(label=key, value=key, description=', '.join(aliases)[:100] or 'Not mapped')
            for key, aliases in CONFIG[section].items()
        ])

    async def callback(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
            return
        key = self.values[0]
        current = ', '.join(CONFIG[self.section][key]) or '(none)'
        await interaction.response.edit_message(
            content=f'**{key}** currently maps to: {current}\nSelect Discord roles to **add** to **{key}**, or use Add/Remove by name or ID. Nothing here changes members\' real roles.',
            view=MappingPickerView(self.section, key)
        )


class SettingKeyView(discord.ui.View):
    def __init__(self, section):
        super().__init__(timeout=180)
        self.add_item(SettingKeySelect(section))


@bot.tree.command(name='settings', description='Configure how Discord roles map to the guild roster', guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def settings(interaction: discord.Interaction):
    if interaction.guild_id != GUILD_ID or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
        return
    await interaction.response.send_message(
        '**GREED ROSTER SETTINGS**\n'
        'Map existing Discord roles to **Combat roles**, **Guild ranks**, and **Classes** using the menus below. '
        'You may assign multiple server roles to one roster category. Changes are saved to `config.json` and automatically refresh the roster.\n\n'
        '**Maintenance:** For Windows startup, use `Greed_Bot_Toggle.bat` locally. '
        'Stopping the bot makes Discord slash commands unavailable, so it cannot enable itself again.',
        view=SettingsHome(), ephemeral=True
    )


@bot.tree.command(name='roster_refresh', description='Rebuild the live guild roster now', guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def roster_refresh(interaction: discord.Interaction):
    if interaction.guild_id != GUILD_ID or not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message('Manage Server permission required.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        await update_roster()
    except Exception as exc:
        log.exception('Manual refresh failed')
        await interaction.followup.send(f'Refresh failed. Check the bot logs ({type(exc).__name__}).', ephemeral=True)
    else:
        await interaction.followup.send('Roster synchronized.', ephemeral=True)


async def setup_hook():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))


register_raid_manager(bot, GUILD_ID, 1552992202966306926)
bot.setup_hook = setup_hook
if not TOKEN or TOKEN == 'replace_with_your_bot_token':
    raise RuntimeError('Set DISCORD_TOKEN in .env')
bot.run(TOKEN, log_handler=None)
