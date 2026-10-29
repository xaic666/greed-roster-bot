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

def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"players": {}, "board": None}

def save(data):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(FILE)

def permitted(i):
    return isinstance(i.user, discord.Member) and i.user.guild_permissions.administrator

def board_embed(guild):
    data = load()["players"]
    counts = {role: sum(v["main"] == role for v in data.values()) for role in ROLES}
    off_tanks = sum(v.get("designated_off_tank", False) for v in data.values())
    embed = discord.Embed(title="⚔️ Greed | Confirmed Raid Roster",
        description=f"**{len(data)}/{TARGET} Raiders** | 🛡️ {counts['Tank']} Tank | 💚 {counts['Healer']} Healer | ⚔️ {counts['DPS']} DPS\n**Designated Off-Tanks:** {off_tanks}",
        color=0xC7A35B)
    for role in ROLES:
        entries = sorted(((int(uid), p) for uid, p in data.items() if p["main"] == role), key=lambda x: x[0])
        lines = [f"<@{uid}> | {p['class']} | off-spec: {p['off']}" + (" | 🛡️ **Designated OT**" if p.get("designated_off_tank", False) else "") for uid, p in entries]
        if not lines: lines = ["*Open*"]
        # Split field values to respect Discord's 1024-char limit.
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 950:
                embed.add_field(name=role, value=chunk, inline=False)
                chunk = ""
            chunk += line + "\n"
        if chunk: embed.add_field(name=role, value=chunk, inline=False)
    embed.set_footer(text="Administrator permission required to edit | No Discord roles are changed")
    return embed

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
    await msg.edit(embed=board_embed(guild), view=RosterView(bot),
        allowed_mentions=discord.AllowedMentions.none())
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


class EditRosterView(discord.ui.View):
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
        if not self.removing and self.designated_off_tank and (self.main != "DPS" or self.off != "Tank"):
            await i.response.send_message("Designated Off-Tank requires main role DPS and Tank off-spec.", ephemeral=True)
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


class RosterView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Add / Edit", emoji="✏️", style=discord.ButtonStyle.primary, custom_id="greed:raid:edit")
    async def edit(self, i, button):
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        await i.response.send_message(
            "Choose a guild member, class, main role and optional off-spec, then click **Save / Confirm**.",
            view=EditRosterView(self.bot), ephemeral=True)

    @discord.ui.button(label="Remove", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="greed:raid:remove")
    async def remove(self, i, button):
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        await i.response.send_message(
            "Select the member to remove, then click **Save / Confirm**.",
            view=EditRosterView(self.bot, removing=True), ephemeral=True)

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="greed:raid:refresh")
    async def reload(self, i, button):
        if not permitted(i):
            await i.response.send_message("Administrators only.", ephemeral=True)
            return
        await i.response.defer(ephemeral=True)
        try:
            updated = await refresh(self.bot, i.guild)
            await i.followup.send("Roster refreshed." if updated else "Use /raid_roster to publish.", ephemeral=True)
        except discord.HTTPException:
            log.exception("Roster refresh failed")
            await i.followup.send("Roster refresh failed. Check bot logs.", ephemeral=True)

def register(bot, guild_id, channel_id):
    bot.add_view(RosterView(bot))

    @bot.tree.command(name="raid_roster", description="Publish or refresh the editable raid roster", guild=discord.Object(id=guild_id))
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
            msg = await channel.send(embed=board_embed(i.guild), view=RosterView(bot),
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
        await i.delete_original_response()
