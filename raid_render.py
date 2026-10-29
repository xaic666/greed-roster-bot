"""Wide visual raid roster, rendered alongside the clickable Discord roster."""
import io
from PIL import Image, ImageDraw, ImageFont

COLORS = {
    "Warrior": "#C79C6E", "Paladin": "#F58CBA", "Hunter": "#ABD473",
    "Rogue": "#FFF569", "Priest": "#FFFFFF", "Shaman": "#0070DE",
    "Mage": "#69CCF0", "Warlock": "#9482C9", "Druid": "#FF7D0A",
}
ROLES = ("Tank", "Healer", "DPS")


def font(size, bold=False):
    candidates = (
        ["C:/Windows/Fonts/segoeuib.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
        if bold else
        ["C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render(players, guild):
    """Return a seekable PNG stream for the current confirmed raid roster."""
    sections = {}
    for role in ROLES:
        rows = [(uid, details) for uid, details in players.items() if details["main"] == role]
        rows.sort(key=lambda x: (guild.get_member(int(x[0])).display_name if guild.get_member(int(x[0])) else x[0]).casefold())
        sections[role] = rows

    width = 1240
    row_h = 60
    height = 160 + sum(66 + max(1, len(rows)) * row_h + 16 for rows in sections.values()) + 30
    image = Image.new("RGB", (width, height), "#111827")
    draw = ImageDraw.Draw(image)
    title, header, regular = font(40, True), font(27, True), font(26)
    draw.text((38, 24), "GREED  |  RAID ROSTER", font=title, fill="#F0DFAF")
    count = len(players)
    designated = sum(bool(p.get("designated_off_tank")) for p in players.values())
    draw.text((40, 88), f"{count}/30 Raiders   |   {designated} designated off-tanks", font=regular, fill="#B9C5D6")
    y = 160
    for role, rows in sections.items():
        draw.rounded_rectangle((24, y, width - 24, y + 52), radius=10, fill="#2B3445")
        draw.text((44, y + 9), f"{role.upper()}  ({len(rows)})", font=header, fill="#F1E6CA")
        y += 66
        if not rows:
            draw.text((48, y + 12), "Open", font=regular, fill="#8290A3")
            y += row_h
        for index, (uid, p) in enumerate(rows):
            draw.rounded_rectangle((30, y, width - 30, y + row_h - 4), radius=7,
                                   fill="#1D283A" if index % 2 == 0 else "#172131")
            member = guild.get_member(int(uid))
            name = member.display_name if member else str(uid)
            if len(name) > 22:
                name = name[:21] + "…"
            clazz = p.get("class", "Unknown")
            draw.text((52, y + 12), name, font=regular, fill="#F7F9FD")
            draw.text((450, y + 12), clazz, font=header, fill=COLORS.get(clazz, "#FFFFFF"))
            off = p.get("off", "None")
            draw.text((690, y + 12), f"Off-spec: {off}", font=regular, fill="#C2CEDF")
            if p.get("designated_off_tank"):
                draw.text((995, y + 12), "OFF-TANK", font=header, fill="#7DB8FF")
            y += row_h
        y += 16
    stream = io.BytesIO()
    image.save(stream, format="PNG", optimize=True)
    stream.seek(0)
    return stream
