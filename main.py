import discord 
from discord.ext import commands, tasks
import logging 
from dotenv import load_dotenv
import os 
import requests
from datetime import datetime

# Load environment variables
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
comicvine_api_key = os.getenv('COMICVINE_API_KEY')
comics_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))

# Logging
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Bot instance
bot = commands.Bot(command_prefix='!', intents=intents)

# Track if comics have been sent today
last_sent_date = None

@bot.event
async def on_ready():
    print(f"We are ready to go in, {bot.user.name}")
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

@bot.command()
async def comics(ctx):
    channel = bot.get_channel(comics_channel_id)
    if channel:
        await fetch_and_send_comics(channel)

@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention} !")

@tasks.loop(minutes=1)
async def daily_comic_check():
    global last_sent_date

    now = datetime.now()
    current_time = now.strftime("%H:%M")
    today = now.date()

    if current_time == "08:00" and last_sent_date != today:
        channel = bot.get_channel(comics_channel_id)
        if channel:
            await fetch_and_send_comics(channel)
            last_sent_date = today

async def fetch_and_send_comics(channel):
    date_today = datetime.today().strftime('%Y-%m-%d')
    url = f"https://comicvine.gamespot.com/api/issues/?api_key={comicvine_api_key}&format=json&filter=store_date:{date_today}"
    headers = {"User-Agent": "MyComicBot/1.0"}

    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        results = data.get("results", [])

        if not results:
            await channel.send("📭 No comics released today.")
            return

        for issue in results:
            name = issue.get("name") or issue.get("volume", {}).get("name", "Unnamed")
            link = issue.get("site_detail_url", "")
            volume = issue.get("volume", {}).get("name", "Unknown Series")
            image = issue.get("image", {}).get("original_url")
            release_date = issue.get("store_date", date_today)

            embed = discord.Embed(
                title=name,
                url=link,
                description=f"📅 Release date: **{release_date}**\n📚 Series: *{volume}*",
                color=0x00ffcc
            )
            if image:
                embed.set_thumbnail(url=image)
            embed.set_footer(text="Powered by ComicVine")
            await channel.send(embed=embed)

    except Exception as e:
        await channel.send(f"⚠️ Error fetching comics: {e}")

# Run bot
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
