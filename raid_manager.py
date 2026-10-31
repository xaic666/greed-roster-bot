"""Manually managed raid roster, independent of the guild-role roster."""
import json
import logging
import time
from pathlib import Path
import discord
from discord import app_commands

log = logging.getLogger("greed-raid-manager")
FILE = Path(__file__).with_name("raid_players.json")
CLASSES = ("Warrior","Paladin","Hunter","Rogue","Priest","Shaman","Mage","Warlock","Druid")
ROLES = ("Tank","Healer","DPS")
TARGET = 30
PAGE_SIZE = 12

def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"players": {}, "board": None, "control": None, "updated_at": None}

def save(data):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(FILE)

def permitted(i):
    return isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator

def guild_emoji(guild, name):
    """Resolve a custom server emoji by name without hardcoding its ID."""
    emoji = discord.utils.get(guild.emojis, name=name.lower())
    return str(emoji) if emoji is not None else ""

def board_embed(guild):
    data = load()
    players = data["players"]
    counts = {role: sum(v["main"] == role for v in players.values()) for role in ROLES}
    off_tanks = sum(v.get("designated_off_tank", False) for v in players.values())
    description = [
        f"**{len(players)}/{TARGET} Raiders**  |  "
        f"{guild_emoji(guild, 'tank')} {counts['Tank']} Tank  |  "
        f"{guild_emoji(guild, 'healer')} {counts['Healer']} Healer  |  "
        f"{guild_emoji(guild, 'dps')} {counts['DPS']} DPS",
        f"**Designated Off-Tanks:** {off_tanks}",
        "Browse players by role or class using the controls below.",
    ]
    if data.get("updated_at"):
        description.append(f"Updated <t:{data['updated_at']}:R>")
    embed = discord.Embed(
        title="⚔️ Greed | Confirmed Raid Roster",
        description="\n".join(description),
        color=0xC7A35B,
    )
    coverage = []
    for clazz in CLASSES:
        count = sum(p["class"] == clazz for p in players.values())
        emoji = guild_emoji(guild, clazz)
        coverage.append(f"{emoji} **{clazz}:** {count}" if emoji else f"**{clazz}:** {count}")
    for index in range(0, len(coverage), 3):
        embed.add_field(
            name="Class coverage" if index == 0 else "\u200b",
            value="\n".join(coverage[index:index + 3]),
            inline=True,
        )
    return embed

def browser_embed(guild, role=None, clazz=None, page=0):
    players = load()["players"]
    entries = [
        (int(uid), player) for uid, player in players.items()
        if (role is None or player["main"] == role)
        and (clazz is None or player["class"] == clazz)
    ]

    def sort_key(entry):
        uid, player = entry
        member = guild.get_member(uid)
        name = member.display_name if member else str(uid)
        return (ROLES.index(player["main"]), CLASSES.index(player["class"]), name.casefold())

    entries.sort(key=sort_key)
    page_count = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, page_count - 1))
    visible = entries[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    lines = []
    for uid, player in visible:
        details = [f"{guild_emoji(guild, player['class'])} {player['class']}".strip()]
        if player["off"] != "None":
            details.append(f"Off: {player['off']}")
        if player.get("designated_off_tank", False):
            details.append("🛡️ **Designated OT**")
        lines.append(f"<@{uid}> | {' | '.join(details)}")
    if not lines:
        empty = "No players match these filters." if players else "No Raiders have been confirmed yet."
        lines = [f"*{empty}*"]
    title_parts = ["⚔️ Greed | Raid Roster", role or "All roles"]
    if clazz:
        title_parts.append(clazz)
    embed = discord.Embed(title=" · ".join(title_parts), description="\n".join(lines), color=0xC7A35B)
    embed.set_footer(text=f"Page {page + 1}/{page_count} | {len(entries)} player{'s' if len(entries) != 1 else ''}")
    return embed, page, page_count

class BrowserFilterSelect(discord.ui.Select):
    def __init__(self, field_key, placeholder, values, row):
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            row=row,
            options=[discord.SelectOption(label="All", value="all")]
            + [discord.SelectOption(label=value, value=value) for value in values],
        )
        self.field_key = field_key

    async def callback(self, i):
        value = self.values[0]
        setattr(self.view, self.field_key, None if value == "all" else value)
        await self.view.refresh(i, reset_page=True)

class LoggedView(discord.ui.View):
    """Log component failures and give the user a useful response."""
    async def on_error(self, interaction, error, item):
        log.error(
            "Raid component failed: custom_id=%s user=%s interaction=%s responded=%s",
            getattr(item, "custom_id", None),
            getattr(interaction.user, "id", None),
            interaction.id,
            interaction.response.is_done(),
            exc_info=(type(error), error, error.__traceback__),
        )
        try:
            message = "Roster action failed. Please check the bot logs."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            log.exception("Could not deliver raid component error response")


class RosterBrowserView(LoggedView):
    def __init__(self, role=None, clazz=None):
        super().__init__(timeout=300)
        self.role = role
        self.clazz = clazz
        self.page = 0
        self.add_item(BrowserFilterSelect("role", "Filter by role", ROLES, 0))
        self.add_item(BrowserFilterSelect("clazz", "Filter by class", CLASSES, 1))

    def message(self, guild):
        embed, self.page, page_count = browser_embed(guild, self.role, self.clazz, self.page)
        self.previous.disabled = self.page == 0
        self.next.disabled = self.page == page_count - 1
        selected = {"role": self.role, "clazz": self.clazz}
        for item in self.children:
            if isinstance(item, BrowserFilterSelect):
                current = selected[item.field_key] or "all"
                for option in item.options:
                    option.default = option.value == current
        return embed

    async def refresh(self, i, reset_page=False):
        if reset_page:
            self.page = 0
        await i.response.edit_message(
            embed=self.message(i.guild),
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, row=2)
    async def previous(self, i, button):
        self.page -= 1
        await self.refresh(i)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary, row=2)
    async def next(self, i, button):
        self.page += 1
        await self.refresh(i)

async def show_browser(i, role=None, clazz=None):
    view = RosterBrowserView(role, clazz)
    await i.response.send_message(
        embed=view.message(i.guild),
        view=view,
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )

class PublicClassSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Browse by class",
            min_values=1,
            max_values=1,
            row=1,
            custom_id="greed:raid:browse-class",
            options=[discord.SelectOption(label=value, value=value) for value in CLASSES],
        )

    async def callback(self, i):
        await show_browser(i, clazz=self.values[0])

class PublicRosterView(LoggedView):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(PublicClassSelect())

    @discord.ui.button(label="Tank", style=discord.ButtonStyle.secondary, custom_id="greed:raid:browse:Tank", row=0)
    async def browse_tank(self, i, button):
        await show_browser(i, role="Tank")

    @discord.ui.button(label="Healer", style=discord.ButtonStyle.secondary, custom_id="greed:raid:browse:Healer", row=0)
    async def browse_healer(self, i, button):
        await show_browser(i, role="Healer")

    @discord.ui.button(label="DPS", style=discord.ButtonStyle.secondary, custom_id="greed:raid:browse:DPS", row=0)
    async def browse_dps(self, i, button):
        await show_browser(i, role="DPS")

async def refresh_setup_preview(bot, guild):
    """Mirror the public roster into the private admin control message."""
    state = load().get("control")
    if not state:
        return
    channel = guild.get_channel(state["channel_id"])
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        message = await channel.fetch_message(state["message_id"])
        if message.author.id == bot.user.id:
            await message.edit(
                content="**⚙️ Greed | Raid Roster Setup (Live Preview)**",
                embed=board_embed(guild),
                view=RosterView(bot),
                allowed_mentions=discord.AllowedMentions.none(),
            )
    except discord.NotFound:
        log.warning("Saved setup preview message was deleted; run /raid_roster to recreate it")
    except discord.HTTPException:
        log.exception("Could not refresh private setup preview")


async def refresh(bot, guild):
    data = load()
    board = data.get("board")
    if not board: return False
    channel = guild.get_channel(board["channel_id"])
    if not isinstance(channel, discord.TextChannel): return False
    try:
        msg = await channel.fetch_message(board["message_id"])
    except discord.NotFound:
        data["board"] = None
        save(data)
        return False
    if msg.author.id != bot.user.id: return False
    await msg.edit(embed=board_embed(guild), attachments=[], view=PublicRosterView(bot),
        allowed_mentions=discord.AllowedMentions.none())
    await refresh_setup_preview(bot, guild)
    return True

class MemberPicker(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Search for a Discord member", min_values=1, max_values=1, row=0)

    async def callback(self, i):
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        member = self.values[0]
        if not isinstance(member, discord.Member):
            await i.response.send_message("Choose a member of this server.", ephemeral=True)
            return
        self.view.member_id = member.id
        await i.response.defer()


class FieldPicker(discord.ui.Select):
    def __init__(self, key, label, options, row):
        super().__init__(
            placeholder=label, min_values=1, max_values=1, row=row,
            options=[discord.SelectOption(label=value, value=value) for value in options]
        )
        self.field_key = key

    async def callback(self, i):
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        setattr(self.view, self.field_key, self.values[0])
        await i.response.defer()


class EditRosterView(LoggedView):
    def __init__(self, bot, removing=False):
        super().__init__(timeout=300)
        self.bot = bot
        self.removing = removing
        self.member_id = None
        self.clazz = None
        self.main = None
        self.off = "None"
        self.designated_off_tank = False
        self.add_item(MemberPicker())
        if not removing:
            self.add_item(FieldPicker("clazz", "Select class", CLASSES, 1))
            self.add_item(FieldPicker("main", "Select main role", ROLES, 2))
            self.add_item(FieldPicker("off", "Select off-spec (optional)", ("None", *ROLES), 3))

    @discord.ui.button(label="Designated Off-Tank: NO", style=discord.ButtonStyle.secondary, row=4)
    async def toggle_off_tank(self, i, button):
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        if self.removing:
            await i.response.send_message("Not applicable when removing a player.", ephemeral=True)
            return
        self.designated_off_tank = not self.designated_off_tank
        button.label = "Designated Off-Tank: YES" if self.designated_off_tank else "Designated Off-Tank: NO"
        button.style = discord.ButtonStyle.success if self.designated_off_tank else discord.ButtonStyle.secondary
        await i.response.edit_message(view=self)

    @discord.ui.button(label="Save / Confirm",
                       style=discord.ButtonStyle.success, row=4)
    async def submit(self, i, button):
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        if self.member_id is None:
            await i.response.send_message("Select a Discord member first.", ephemeral=True)
            return
        if not self.removing and (self.clazz is None or self.main is None):
            await i.response.send_message("Select a class and main role.", ephemeral=True)
            return
        if not self.removing and self.designated_off_tank and (self.main not in ("DPS", "Healer") or self.off != "Tank"):
            await i.response.send_message("Designated Off-Tank requires DPS or Healer main role with Tank off-spec.", ephemeral=True)
            return
        if not self.removing and self.main == self.off:
            await i.response.send_message("Off-spec must differ from the main role.", ephemeral=True)
            return
        await i.response.defer(ephemeral=True)
        data = load()
        uid = str(self.member_id)
        if self.removing:
            existed = data["players"].pop(uid, None) is not None
            result = "Removed." if existed else "Member was not on the roster."
        else:
            data["players"][uid] = {"class": self.clazz, "main": self.main, "off": self.off,
                                    "designated_off_tank": self.designated_off_tank}
            result = "Roster entry saved."
        data["updated_at"] = int(time.time())
        save(data)
        updated = False
        try:
            updated = await refresh(self.bot, i.guild)
            if not updated:
                result += " Run /raid_roster to publish the roster."
        except discord.HTTPException:
            log.exception("Raid roster message refresh failed")
            result += " Saved locally, but the public message could not refresh."
        if updated:
            # The component interaction's original response is the private editor.
            # Never delete the public roster board.
            try:
                await i.delete_original_response()
            except discord.HTTPException:
                log.exception("Could not remove completed private roster editor")
                await i.followup.send(result, ephemeral=True)
        else:
            await i.followup.send(result, ephemeral=True)


class RosterView(PublicRosterView):
    def __init__(self, bot):
        super().__init__(bot)

    @discord.ui.button(label="Add / Edit", emoji="✏️", style=discord.ButtonStyle.primary, custom_id="greed:raid:edit", row=2)
    async def edit(self, i, button):
        log.info("Raid Add/Edit clicked: user=%s interaction=%s guild=%s latency=%.3fs", i.user.id, i.id, i.guild_id, self.bot.latency)
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        await i.response.send_message(
            "Choose a guild member, class, main role and optional off-spec, then click **Save / Confirm**.",
            view=EditRosterView(self.bot), ephemeral=True)
        log.info("Raid Add/Edit editor sent: interaction=%s", i.id)

    @discord.ui.button(label="Remove", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="greed:raid:remove", row=2)
    async def remove(self, i, button):
        log.info("Raid Remove clicked: user=%s interaction=%s guild=%s latency=%.3fs", i.user.id, i.id, i.guild_id, self.bot.latency)
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        await i.response.send_message(
            "Select the member to remove, then click **Save / Confirm**.",
            view=EditRosterView(self.bot, removing=True), ephemeral=True)
        log.info("Raid Remove editor sent: interaction=%s", i.id)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="greed:raid:refresh", row=2)
    async def reload(self, i, button):
        log.info("Raid Refresh clicked: user=%s interaction=%s guild=%s latency=%.3fs", i.user.id, i.id, i.guild_id, self.bot.latency)
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        await i.response.defer(ephemeral=True, thinking=True)
        log.info("Raid Refresh acknowledged: interaction=%s", i.id)
        try:
            updated = await refresh(self.bot, i.guild)
            await i.followup.send("Roster refreshed." if updated else "Use /raid_roster to publish.", ephemeral=True)
            log.info("Raid Refresh completed: interaction=%s updated=%s", i.id, updated)
        except discord.HTTPException:
            log.exception("Roster refresh failed")
            await i.followup.send("Roster refresh failed. Check bot logs.", ephemeral=True)

async def ensure_control(bot, guild, setup_id):
    channel = guild.get_channel(setup_id)
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Setup channel not found")
    perms = channel.permissions_for(guild.me)
    if not (perms.view_channel and perms.send_messages and perms.read_message_history):
        raise RuntimeError("Bot lacks View Channel, Send Messages or Read Message History in setup channel")
    data = load()
    state = data.get("control")
    if state and state.get("channel_id") == setup_id:
        try:
            message = await channel.fetch_message(state["message_id"])
            if message.author.id == bot.user.id:
                await message.edit(content="**⚙️ Greed | Raid Roster Setup (Live Preview)**", embed=board_embed(guild), view=RosterView(bot))
                return
        except discord.NotFound:
            pass
    message = await channel.send("**⚙️ Greed | Raid Roster Setup (Live Preview)**", embed=board_embed(guild), view=RosterView(bot), allowed_mentions=discord.AllowedMentions.none())
    data = load()
    data["control"] = {"channel_id": setup_id, "message_id": message.id}
    save(data)

def register_views(bot):
    """Register persistent views after login, binding the saved setup message."""
    view = RosterView(bot)
    bot.add_view(view)
    log.info("Registered persistent raid controls (fallback): %s",
             [(item.type.value, item.custom_id) for item in view.children])
    state = load().get("control")
    if state and state.get("message_id"):
        message_id = int(state["message_id"])
        bot.add_view(RosterView(bot), message_id=message_id)
        log.info("Bound raid admin controls to setup message %s", message_id)


def register(bot, guild_id, channel_id, setup_id):
    # Commands are registered at import time; views are bound in setup_hook().

    @bot.tree.command(name="raid_roster", description="Publish or refresh the raid roster and browser", guild=discord.Object(id=guild_id))
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def raid_roster(i):
        if i.guild_id != guild_id or not permitted(i):
            await i.response.send_message("Administrator permission required.", ephemeral=True)
            return
        started = time.monotonic()
        log.info("raid_roster invoked: guild=%s channel=%s bot_latency=%.3fs",
                 i.guild_id, channel_id, bot.latency)
        try:
            await i.response.defer(ephemeral=True)
        except discord.NotFound:
            log.exception("raid_roster interaction expired before acknowledgement (%.2fs elapsed; bot latency %.3fs). "
                          "Check network delays, clock synchronization and duplicate bot processes.",
                          time.monotonic() - started, bot.latency)
            return
        except discord.HTTPException:
            log.exception("raid_roster acknowledgement failed")
            return
        channel = i.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await i.followup.send("Roster channel not found.", ephemeral=True)
            return
        if await refresh(bot, i.guild):
            try:
                await ensure_control(bot, i.guild, setup_id)
            except (discord.HTTPException, RuntimeError) as exc:
                log.exception("Setup panel publish failed")
                await i.followup.send(f"Public roster updated, but setup panel failed: {exc}", ephemeral=True)
                return
            await i.delete_original_response()
            return
        permissions = channel.permissions_for(i.guild.me)
        if not permissions.view_channel or not permissions.send_messages or not permissions.embed_links:
            missing = [name for name, ok in (
                ("View Channel", permissions.view_channel),
                ("Send Messages", permissions.send_messages),
                ("Embed Links", permissions.embed_links)) if not ok]
            await i.followup.send(
                f"Cannot publish to <#{channel.id}>. Missing bot permissions: {', '.join(missing)}. "
                "Check channel and category overrides for the bot role.", ephemeral=True)
            return
        try:
            msg = await channel.send(embed=board_embed(i.guild), view=PublicRosterView(bot),
                allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden as exc:
            await i.followup.send(
                f"Discord denied access to <#{channel.id}> (HTTP {exc.status}, code {exc.code}). "
                "Verify this is the intended channel, and give the bot View Channel, Send Messages, "
                "Embed Links and Read Message History. Category overrides may also apply.",
                ephemeral=True)
            return
        data = load()
        data["board"] = {"channel_id": channel.id, "message_id": msg.id}
        save(data)
        try:
            await ensure_control(bot, i.guild, setup_id)
        except (discord.HTTPException, RuntimeError) as exc:
            log.exception("Setup panel publish failed")
            await i.followup.send(f"Public roster created, but setup panel failed: {exc}", ephemeral=True)
            return
        await i.delete_original_response()
