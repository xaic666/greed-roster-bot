"""Greed live roster: read-only Discord role aggregation, split into Tank/Healer/DPS panels."""
import asyncio
import json
import logging
import os
from collections import defaultdict
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from raid_manager import register as register_raid_manager, register_views as register_raid_views, ensure_control as ensure_raid_control

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
RAID_CHANNEL_ID = int(os.environ.get('RAID_ROSTER_CHANNEL_ID', '1552992208850919465'))
SETUP_CHANNEL_ID = int(os.environ.get('SETUP_CHANNEL_ID', '1565392826152263680'))
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


# Discord-native roster embeds. Three inline class fields per row on desktop.
# These replace the old Pillow screenshots without changing role classifications.
CLASS_ICONS = {
    "Warrior": "⚔️", "Paladin": "🔆", "Hunter": "🏹",
    "Rogue": "🗡️", "Priest": "✨", "Shaman": "⚡",
    "Mage": "🔮", "Warlock": "🔥", "Druid": "🌿",
}
ROLE_ICONS = {"Tank": "🛡️", "Healer": "💚", "DPS": "⚔️"}
ROLE_EMBED_COLORS = {"Tank": 0x528CC4, "Healer": 0x54A878, "DPS": 0xC7A35B}


def class_icon(guild, clazz):
    # Prefer a server's existing class emoji, just like Raid-Helper.
    emoji = discord.utils.get(guild.emojis, name=clazz.lower())
    return str(emoji) if emoji else CLASS_ICONS.get(clazz, "⚔️")


def chunk_lines(lines, limit=900):
    """Split on line boundaries to stay comfortably below Discord's 1024-char field limit."""
    chunks = []
    current = []
    length = 0
    for line in lines:
        # Discord names are capped at 32 chars, but issue descriptions can be longer.
        if len(line) > limit:
            line = line[:limit - 1] + "…"
        if current and length + len(line) + 1 > limit:
            chunks.append("\n".join(current))
            current = []
            length = 0
        current.append(line)
        length += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def render_panels(roster, totals, issues, guild):
    """Return native Discord embeds, grouped by combat role then class."""
    total_members = sum(totals.get(rank, 0) for rank in RANKS)
    embeds = []
    for combat_role in COMBAT:
        role_count = totals.get(combat_role, 0)
        description = (
            f"**{total_members} classified members**  |  "
            f"🛡️ {totals.get('Tank', 0)} Tanks  |  "
            f"💚 {totals.get('Healer', 0)} Healers  |  "
            f"⚔️ {totals.get('DPS', 0)} DPS\n"
            f"**{combat_role}: {role_count}**  |  "
            + "  ·  ".join(f"{rank}: {totals.get(rank, 0)}" for rank in RANKS)
        )
        fields = []
        for clazz in CLASSES:
            ranks = roster.get(clazz, {}).get(combat_role, {})
            class_count = sum(len(ranks.get(rank, [])) for rank in RANKS)
            if class_count == 0:
                continue
            lines = []
            for rank in RANKS:
                players = sorted(ranks.get(rank, []), key=lambda m: m.display_name.casefold())
                if players:
                    lines.append(f"**{rank}**")
                    lines.extend(f"• <@{member.id}>" for member in players)
            for index, chunk in enumerate(chunk_lines(lines)):
                name = f"{class_icon(guild, clazz)} {clazz} ({class_count})"
                if index:
                    name += f" ({index + 1})"
                fields.append((name, chunk))

        # Discord caps embeds at 25 fields and 6000 characters. Keep each page
        # below both limits instead of losing players as the guild grows.
        page = 1
        while fields or page == 1:
            embed = discord.Embed(
                title=f"{ROLE_ICONS.get(combat_role, '⚔️')} GREED | {combat_role.upper()} ROSTER"
                + (f" · {page}" if page > 1 else ""),
                description=description if page == 1 else f"**{combat_role}: {role_count}** (continued)",
                color=ROLE_EMBED_COLORS.get(combat_role, 0xC7A35B),
            )
            remaining = 5500 - len(embed.title) - len(embed.description)
            while fields and len(embed.fields) < 24:
                name, value = fields[0]
                if len(name) + len(value) + 2 > remaining:
                    break
                embed.add_field(name=name[:256], value=value, inline=True)
                remaining -= len(name) + len(value) + 2
                fields.pop(0)
            if not embed.fields:
                if fields:
                    raise ValueError("A roster field exceeds Discord's embed character limit")
                embed.add_field(name="No players", value=f"No {combat_role.lower()}s classified yet.", inline=False)
            embed.set_footer(text="Live guild roles · Automatically refreshed")
            embeds.append(embed)
            page += 1

    if issues:
        # Misconfigured members still remain visible to officers, rather than
        # silently disappearing from the original roster.
        lines = [
            f"• {short_name(member)}: {describe_issue(ranks, classes, roles)}"
            for member, ranks, classes, roles in sorted(
                issues, key=lambda item: item[0].display_name.casefold()
            )
        ]
        chunks = chunk_lines(lines)
        for offset in range(0, len(chunks), 5):
            embed = discord.Embed(
                title="⚠️ GREED | NEEDS ATTENTION",
                description="Members with missing or conflicting class, combat role, or rank mappings.",
                color=0xD39A56,
            )
            for index, chunk in enumerate(chunks[offset:offset + 5], start=offset + 1):
                embed.add_field(name=f"Unclassified members {index}", value=chunk, inline=False)
            embeds.append(embed)
    if len(embeds) > 10:
        raise ValueError("Roster exceeds Discord's ten-embed message limit")
    return embeds


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
        embeds = render_panels(*build_roster(members), guild)

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
            await msg.edit(content=None, embeds=embeds, attachments=[],
                           allowed_mentions=discord.AllowedMentions.none())
        else:
            msg = await channel.send(embeds=embeds,
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
async def on_socket_response(payload):
    # Raw gateway logging lets us distinguish routing failures from callback errors.
    if payload.get('t') != 'INTERACTION_CREATE':
        return
    data = payload.get('d') or {}
    component = data.get('data') or {}
    log.info(
        'Gateway interaction: type=%s custom_id=%s message=%s guild=%s app=%s user=%s',
        data.get('type'), component.get('custom_id'),
        (data.get('message') or {}).get('id'), data.get('guild_id'),
        data.get('application_id'),
        ((data.get('member') or {}).get('user') or data.get('user') or {}).get('id')
    )


@bot.event
async def on_interaction(interaction: discord.Interaction):
    # This should appear for a received interaction even when its view is not found.
    log.info(
        'Parsed interaction: type=%s custom_id=%s message=%s guild=%s user=%s',
        interaction.type, (interaction.data or {}).get('custom_id'),
        interaction.message.id if interaction.message else None,
        interaction.guild_id, interaction.user.id
    )


@bot.event
async def on_ready():
    log.info('Logged in as %s (bot_id=%s guild_id=%s setup_channel=%s)',
             bot.user, bot.user.id, GUILD_ID, SETUP_CHANNEL_ID)
    log.info('Registered persistent views: %s', len(bot.persistent_views))
    for view in bot.persistent_views:
        log.info('Persistent view %s: %s', type(view).__name__,
                 [getattr(item, 'custom_id', None) for item in view.children])

    try:
        await update_roster()
    except Exception:
        log.exception('Startup roster update failed')
    # Refresh the saved admin message and attach a live view to this exact message.
    # A missing/forbidden setup channel must not prevent the rest of the bot running.
    guild = bot.get_guild(GUILD_ID)
    if guild is not None:
        try:
            await ensure_raid_control(bot, guild, SETUP_CHANNEL_ID)
            log.info('Raid setup controls verified on startup')
        except (discord.HTTPException, RuntimeError, KeyError, ValueError):
            log.exception('Raid setup controls could not be restored')


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
    register_raid_views(bot)
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))


register_raid_manager(bot, GUILD_ID, RAID_CHANNEL_ID, SETUP_CHANNEL_ID)
bot.setup_hook = setup_hook
if not TOKEN or TOKEN == 'replace_with_your_bot_token':
    raise RuntimeError('Set DISCORD_TOKEN in .env')
bot.run(TOKEN, log_handler=None)
