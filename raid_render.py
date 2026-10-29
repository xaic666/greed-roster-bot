"""Render the confirmed raid roster with authentic WoW class text colours."""
import io
from PIL import Image, ImageDraw, ImageFont

CLASS_COLOURS = {
    "Warrior": "#C79C6E", "Paladin": "#F58CBA", "Hunter": "#ABD473",
    "Rogue": "#FFF569", "Priest": "#FFFFFF", "Shaman": "#0070DE",
    "Mage": "#69CCF0", "Warlock": "#9482C9", "Druid": "#FF7D0A",
}
ROLES = ("Tank", "Healer", "DPS")


def _font(size, bold=False):
    paths = (
        ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def make_roster_image(players, guild):
    """Return a PNG stream; no Discord requests, no side effects."""
    ordered = sorted(players.items(), key=lambda item: (
        ROLES.index(item[1]["main"]) if item[1]["main"] in ROLES else 3,
        (guild.get_member(int(item[0])).display_name if guild.get_member(int(item[0])) else item[0]).casefold()
    ))
    regular, bold, heading = _font(22), _font(23, True), _font(32, True)
    width, row_height = 1000, 42
    sections = {role: [(uid, player) for uid, player in ordered if player["main"] == role] for role in ROLES}
    height = 106 + sum(48 + max(1, len(items)) * row_height + 12 for items in sections.values())
    canvas = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(canvas)
    draw.text((24, 18), "GREED  |  CONFIRMED RAID ROSTER", font=heading, fill="#F1E6CA")
    draw.text((24, 63), f"{len(players)}/30 Raiders", font=regular, fill="#AAB6C7")
    y = 106
    for role, entries in sections.items():
        draw.rectangle((20, y, width-20, y+43), fill="#2B3445")
        draw.text((34, y+9), role.upper(), font=bold, fill="#E5E7EB")
        y += 48
        if not entries:
            draw.text((36, y+7), "Open", font=regular, fill="#718096")
            y += row_height
        for index, (uid, player) in enumerate(entries):
            member = guild.get_member(int(uid))
            name = member.display_name if member else str(uid)
            if len(name) > 28:
                name = name[:27] + "…"
            draw.rectangle((20, y, width-20, y+row_height), fill="#1A2231" if index % 2 == 0 else "#151C29")
            draw.text((36, y+8), name, font=regular, fill="#EDF2F7")
            clazz = player["class"]
            draw.text((380, y+8), clazz, font=bold, fill=CLASS_COLOURS.get(clazz, "#EDF2F7"))
            off = player.get("off", "None")
            draw.text((585, y+8), f"Off-spec: {off}", font=regular, fill="#AFBBD0")
            if player.get("designated_off_tank", False):
                draw.text((805, y+8), "DESIGNATED OT", font=bold, fill="#7DB8FF")
            y += row_height
        y += 12
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    output.seek(0)
    return output
