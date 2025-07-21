import discord 
from discord.ext import commands, tasks
import logging 
from dotenv import load_dotenv
import os 
import requests
from datetime import datetime
from webserver import keep_alive
import json
import asyncio

# Load environment variables
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
comicvine_api_key = os.getenv('COMICVINE_API_KEY')
comics_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))

# Keep-alive (for Render hosting)
keep_alive()

# Configure logging
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)

# Log to file
file_handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
file_handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(file_handler)

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
    followed_series = {}

def save_followed_series():
    with open("followed_series.json", "w") as f:
        json.dump(followed_series, f, indent=2)

# -------------------- EVENTS --------------------

@bot.event
async def on_ready():
    logger.info(f"Bot is ready as {bot.user}")
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
    """Search ComicVine volumes by name and allow user to follow one with pagination."""
    user_id = str(ctx.author.id)
    headers = {"User-Agent": "MyComicBot/1.0"}

    url = f"https://comicvine.gamespot.com/api/volumes/?api_key={comicvine_api_key}&format=json&filter=name:{series_name}&sort=start_year:desc"
    response = requests.get(url, headers=headers).json()
    volumes = response.get("results", [])

    if not volumes:
        await ctx.send(f"❌ No series found with the name '{series_name}'.")
        return

    per_page = 5
    page = 0

    def make_page_content(page_index):
        start = page_index * per_page
        end = start + per_page
        page_volumes = volumes[start:end]
        return "\n".join(
            f"**{i+1}.** {v['name']} (ID: {v['id']}, start: {v.get('start_year', 'N/A')})"
            for i, v in enumerate(page_volumes)
        ), len(page_volumes)

    while True:
        content, count = make_page_content(page)
        await ctx.send(f"📚 Page {page + 1} of {((len(volumes)-1)//per_page)+1}\n" +
                       content + "\n\nReply with a number to follow, or `next`, `prev`, or `stop`.")

        def check_author(m): return m.author == ctx.author and m.channel == ctx.channel
        try:
            msg = await bot.wait_for('message', timeout=60, check=check_author)
            text = msg.content.strip().lower()

            if text == "stop":
                await ctx.send("❌ Selection canceled.")
                return
            elif text == "next":
                if (page + 1) * per_page < len(volumes):
                    page += 1
                else:
                    await ctx.send("🚫 You're on the last page.")
            elif text == "prev":
                if page > 0:
                    page -= 1
                else:
                    await ctx.send("🚫 You're already on the first page.")
            elif text.isdigit():
                index = int(text) - 1
                real_index = page * per_page + index
                if 0 <= real_index < len(volumes):
                    selected = volumes[real_index]
                    # Save
                    followed_series.setdefault(user_id, [])
                    already = any(s["volume_id"] == selected["id"] for s in followed_series[user_id])
                    if already:
                        await ctx.send(f"ℹ️ You are already following **{selected['name']}**.")
                    else:
                        followed_series[user_id].append({
                            "name": selected["name"],
                            "volume_id": selected["id"]
                        })
                        save_followed_series()
                        await ctx.send(f"✅ You are now following **{selected['name']}**.")
                    return
                else:
                    await ctx.send("❌ Invalid number.")
            else:
                await ctx.send("❓ Invalid command. Use number, `next`, `prev`, or `stop`.")

        except asyncio.TimeoutError:
            await ctx.send("⌛ Timed out. Please start over with `!follow`.")
            return

@bot.command()
async def unfollow(ctx, *, series_name):
    user_id = str(ctx.author.id)
    user_list = followed_series.get(user_id, [])
    new_list = [s for s in user_list if s["name"].lower() != series_name.lower()]

    if len(new_list) == len(user_list):
        await ctx.send(f"❌ You are not following **{series_name}**.")
    else:
        followed_series[user_id] = new_list
        save_followed_series()
        await ctx.send(f"🗑️ Unfollowed **{series_name}**.")


@bot.command()
async def myseries(ctx):
    user_id = str(ctx.author.id)
    series = followed_series.get(user_id, [])
    if not series:
        await ctx.send("📭 You are not following any series.")
        return

    msg = "\n".join(f"• {s['name']} (ID: {s['volume_id']})" for s in series)
    await ctx.send("📚 Your followed series:\n" + msg)



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

@bot.command()
async def lastissues(ctx):
    user_id = str(ctx.author.id)
    user_list = followed_series.get(user_id, [])
    if not user_list:
        await ctx.send("📭 You are not following any series. Use `!follow <series name>`.")
        return

    headers = {"User-Agent": "MyComicBot/1.0"}
    messages = []

    logger.info(f"🔍 Fetching last issues for user {ctx.author} ({user_id})")
    logger.info(f"Followed series: {user_list}")

    for series in user_list:
        logger.info(f"📚 Checking series: {series}")
        url = f"https://comicvine.gamespot.com/api/issues/?api_key={comicvine_api_key}&format=json&filter=name:{series}&sort=store_date:desc"
        logger.info(f"🔗 API URL: {url}")

        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            results = data.get("results", [])

            logger.info(f"✅ Found {len(results)} results for {series}")

            for issue in results:
                vol_name = issue.get("volume", {}).get("name", "N/A")
                store_date = issue.get("store_date", "N/A")
                logger.info(f"🔎 Issue found → Volume: {vol_name}, Store Date: {store_date}, Title: {issue.get('name')}")


            past_issues = [
                issue for issue in results
                if issue.get("store_date") and issue["store_date"] <= datetime.today().strftime('%Y-%m-%d')
                and issue.get("volume", {}).get("name", "").lower() == series.lower()
            ]

            logger.info(f"🕐 {len(past_issues)} past issues matched for {series}")

            if past_issues:
                issue = past_issues[0]
                title = issue.get("name") or series
                date = issue.get("store_date")
                messages.append(f"📘 **{title}** → 🗓️ {date}")
            else:
                messages.append(f"❓ No past issues found for **{series}**.")

        except Exception as e:
            logger.error(f"❌ Error fetching issues for {series}: {e}")
            messages.append(f"❌ Error fetching issues for **{series}**.")

    await ctx.send("🕐 Last released issues:\n" + "\n".join(messages))



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

bot.run(token)
