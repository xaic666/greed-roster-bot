"""Manually managed raid roster, independent of the guild-role roster."""
import json
from pathlib import Path
import discord
from discord import app_commands

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
    return isinstance(i.user, discord.Member) and i.user.guild_permissions.manage_guild

def board_embed(guild):
    data = load()["players"]
    counts = {role: sum(v["main"] == role for v in data.values()) for role in ROLES}
    off_tanks = sum(v["off"] == "Tank" for v in data.values())
    embed = discord.Embed(title="⚔️ Greed | Confirmed Raid Roster",
        description=f"**{len(data)}/{TARGET} Raiders** | 🛡️ {counts['Tank']} Tank | 💚 {counts['Healer']} Healer | ⚔️ {counts['DPS']} DPS\n**Designated Off-Tanks:** {off_tanks}",
        color=0xC7A35B)
    for role in ROLES:
        entries = sorted(((int(uid), p) for uid, p in data.items() if p["main"] == role), key=lambda x: x[0])
        lines = [f"<@{uid}> | {p['class']} | off-spec: {p['off']}" for uid, p in entries]
        if not lines: lines = ["*Open*"]
        # Split field values to respect Discord's 1024-char limit.
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 950:
                embed.add_field(name=role, value=chunk, inline=False)
                chunk = ""
            chunk += line + "\n"
        if chunk: embed.add_field(name=role, value=chunk, inline=False)
    embed.set_footer(text="Manage Server permission required to edit | No Discord roles are changed")
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

class RosterModal(discord.ui.Modal):
    def __init__(self, bot, removing=False):
        super().__init__(title="Remove Raider" if removing else "Add or Edit Raider")
        self.bot, self.removing = bot, removing
        self.player = discord.ui.TextInput(label="Discord user ID or mention", max_length=80)
        self.add_item(self.player)
        if not removing:
            self.clazz = discord.ui.TextInput(label="Class", placeholder="Druid")
            self.main = discord.ui.TextInput(label="Main role (Tank / Healer / DPS)")
            self.off = discord.ui.TextInput(label="Off-spec (Tank / Healer / DPS / None)", default="None")
            for field in (self.clazz, self.main, self.off): self.add_item(field)

    async def on_submit(self, i):
        if not permitted(i):
            await i.response.send_message("Manage Server permission required.", ephemeral=True)
            return
        uid = str(self.player.value).strip().strip("<@!>")
        if not uid.isdecimal():
            await i.response.send_message("Enter a valid Discord user ID or mention.", ephemeral=True)
            return
        uid = int(uid)
        try:
            await i.guild.fetch_member(uid)
        except discord.NotFound:
            await i.response.send_message("This user is not in the server.", ephemeral=True)
            return
        entry = None
        if not self.removing:
            clazz = next((x for x in CLASSES if x.lower() == str(self.clazz.value).strip().lower()), None)
            main = next((x for x in ROLES if x.lower() == str(self.main.value).strip().lower()), None)
            off = next((x for x in (*ROLES,"None") if x.lower() == str(self.off.value).strip().lower()), None)
            if not clazz or not main or not off or main == off:
                await i.response.send_message("Invalid class or main/off-spec combination.", ephemeral=True)
                return
            entry = {"class": clazz, "main": main, "off": off}
        await i.response.defer(ephemeral=True)
        data = load()
        if self.removing: data["players"].pop(str(uid), None)
        else: data["players"][str(uid)] = entry
        save(data)
        try:
            await refresh(self.bot, i.guild)
            await i.followup.send("Roster saved. " + ("Removed" if self.removing else "Updated") + f" <@{uid}>.",
                ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            await i.followup.send("Saved locally, but failed to refresh the public roster. Use /raid_roster.", ephemeral=True)

class RosterView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Add / Edit", emoji="✏️", style=discord.ButtonStyle.primary, custom_id="greed:raid:edit")
    async def edit(self, i, button):
        if not permitted(i):
            await i.response.send_message("Officers only.", ephemeral=True)
            return
        await i.response.send_modal(RosterModal(self.bot))

    @discord.ui.button(label="Remove", emoji="🗑️", style=discord.ButtonStyle.secondary, custom_id="greed:raid:remove")
    async def remove(self, i, button):
        if not permitted(i):
            await i.response.send_message("Officers only.", ephemeral=True)
            return
        await i.response.send_modal(RosterModal(self.bot, removing=True))

    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, custom_id="greed:raid:refresh")
    async def reload(self, i, button):
        if not permitted(i):
            await i.response.send_message("Officers only.", ephemeral=True)
            return
        await i.response.defer(ephemeral=True)
        await refresh(self.bot, i.guild)
        await i.followup.send("Roster refreshed.", ephemeral=True)

def register(bot, guild_id, channel_id):
    bot.add_view(RosterView(bot))

    @bot.tree.command(name="raid_roster", description="Publish or refresh the editable raid roster", guild=discord.Object(id=guild_id))
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def raid_roster(i):
        if i.guild_id != guild_id or not permitted(i):
            await i.response.send_message("Manage Server permission required.", ephemeral=True)
            return
        await i.response.defer(ephemeral=True)
        channel = i.guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await i.followup.send("Roster channel not found.", ephemeral=True)
            return
        if await refresh(bot, i.guild):
            await i.followup.send("Raid roster refreshed.", ephemeral=True)
            return
        msg = await channel.send(embed=board_embed(i.guild), view=RosterView(bot),
            allowed_mentions=discord.AllowedMentions.none())
        data = load()
        data["board"] = {"channel_id": channel.id, "message_id": msg.id}
        save(data)
        await i.followup.send("Raid roster published.", ephemeral=True)
