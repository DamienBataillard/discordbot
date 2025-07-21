import discord 
from discord.ext import commands, tasks
import logging 
from dotenv import load_dotenv
import os 
import requests
from datetime import datetime
from webserver import keep_alive
import json

# Load environment variables
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
comicvine_api_key = os.getenv('COMICVINE_API_KEY')
comics_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))

# Keep-alive (for Render hosting)
keep_alive()

# Logging
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Track if comics have been sent today
last_sent_date = None

# Load followed series (saved across restarts)
if os.path.exists("followed_series.json"):
    with open("followed_series.json", "r") as f:
        followed_series = json.load(f)
else:
    followed_series = []

def save_followed_series():
    with open("followed_series.json", "w") as f:
        json.dump(followed_series, f, indent=2)

# -------------------- EVENTS --------------------

@bot.event
async def on_ready():
    print(f"✅ Bot is online: {bot.user.name}")
    daily_comic_check.start()

@bot.event
async def on_member_join(member):
    await member.send(f"Welcome to the server {member.name}")

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return 
    if "shit" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} - don't use that word!")
    await bot.process_commands(message)

# -------------------- COMMANDS --------------------

@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention} !")

@bot.command()
async def follow(ctx, *, series_name):
    """Add a series to the followed list"""
    if series_name not in followed_series:
        followed_series.append(series_name)
        save_followed_series()
        await ctx.send(f"✅ You are now following **{series_name}**.")
    else:
        await ctx.send(f"ℹ️ You're already following **{series_name}**.")

@bot.command()
async def unfollow(ctx, *, series_name):
    """Remove a series from the followed list"""
    lowered = series_name.lower()
    matches = [s for s in followed_series if s.lower() == lowered]
    if matches:
        followed_series.remove(matches[0])
        save_followed_series()
        await ctx.send(f"🗑️ Unfollowed **{series_name}**.")
    else:
        await ctx.send(f"❌ Series **{series_name}** is not in your followed list.")

@bot.command()
async def comics(ctx):
    """Show next issues for followed series"""
    headers = {"User-Agent": "MyComicBot/1.0"}
    upcoming = []

    for series in followed_series:
        url = f"https://comicvine.gamespot.com/api/issues/?api_key={comicvine_api_key}&format=json&filter=name:{series}&sort=store_date:asc"
        response = requests.get(url, headers=headers).json()
        results = response.get("results", [])

        future_issues = [
            i for i in results 
            if i.get("store_date") and i["store_date"] >= datetime.today().strftime('%Y-%m-%d')
            and i.get("volume", {}).get("name", "").lower() == series.lower()
        ]

        if future_issues:
            issue = future_issues[0]
            title = issue.get("name") or series
            date = issue.get("store_date")
            upcoming.append(f"• **{title}** → 📅 {date}")

    if upcoming:
        await ctx.send("📬 Upcoming issues:\n" + "\n".join(upcoming))
    else:
        await ctx.send("📭 No upcoming issues found.")

# -------------------- DAILY CHECK --------------------

@tasks.loop(minutes=1)
async def daily_comic_check():
    global last_sent_date
    now = datetime.now()
    current_time = now.strftime("%H:%M")
    today = now.date()

    if current_time == "08:00" and last_sent_date != today:
        headers = {"User-Agent": "MyComicBot/1.0"}
        date_today = today.strftime('%Y-%m-%d')
        url = f"https://comicvine.gamespot.com/api/issues/?api_key={comicvine_api_key}&format=json&filter=store_date:{date_today}"
        response = requests.get(url, headers=headers).json()
        issues = response.get("results", [])

        if not issues:
            return

        for issue in issues:
            volume_name = issue.get("volume", {}).get("name", "").lower()
            if any(s.lower() == volume_name for s in followed_series):
                title = issue.get("name") or volume_name
                link = issue.get("site_detail_url", "")
                image = issue.get("image", {}).get("original_url")

                embed = discord.Embed(
                    title=title,
                    url=link,
                    description=f"📅 Released today!\n📚 Series: *{volume_name}*",
                    color=0x00ffcc
                )
                if image:
                    embed.set_thumbnail(url=image)
                embed.set_footer(text="Powered by ComicVine")

                channel = bot.get_channel(comics_channel_id)
                await channel.send(embed=embed)

        last_sent_date = today

# -------------------- RUN --------------------

bot.run(token, log_handler=handler, log_level=logging.DEBUG)
