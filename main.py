import discord 
from discord.ext import commands, tasks
import logging 
from dotenv import load_dotenv
import os 
import requests
from datetime import datetime
from webserver import keep_alive

# Load environment variables from .env file
load_dotenv()
token = os.getenv('DISCORD_TOKEN')
comicvine_api_key = os.getenv('COMICVINE_API_KEY')
comics_channel_id = int(os.getenv('DISCORD_CHANNEL_ID'))
user_selected_series = {}  # user_id -> volume dict

keep_alive()


# Set up logging to a file
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')

# Set up Discord bot intents (permissions)
intents = discord.Intents.default()
intents.message_content = True  # Allow reading message content
intents.members = True          # Allow member join events

# Create bot instance with command prefix '!' and specified intents
bot = commands.Bot(command_prefix='!', intents=intents)

# Track if comics have been sent today
last_sent_date = None

@bot.event
async def on_ready():
    # Called when the bot is ready and connected
    print(f"We are ready to go in, {bot.user.name}")
    daily_comic_check.start()  # Start the daily comic check loop

@bot.event
async def on_member_join(member):
    # Send a welcome message to new members via DM
    await member.send(f"Welcome to the server {member.name}")

@bot.event
async def on_message(message):
    # Ignore messages sent by the bot itself
    if message.author == bot.user:
        return 
    # Delete messages containing a banned word and warn the user
    if "shit" in message.content.lower():
        await message.delete()
        await message.channel.send(f"{message.author.mention} - don't use that word!")
    # Allow commands to be processed
    await bot.process_commands(message)

@bot.command()
async def comics(ctx):
    # Respond to the !comics command by sending today's comics in the channel
    channel = bot.get_channel(comics_channel_id)
    if channel:
        await fetch_and_send_comics(channel)

@bot.command()
async def hello(ctx):
    # Respond to the !hello command
    await ctx.send(f"Hello {ctx.author.mention} !")

@bot.command()
async def choose(ctx):
    def check_author(m): return m.author == ctx.author and m.channel == ctx.channel

    await ctx.send("📝 Please enter a **publisher** (e.g. Marvel, DC Comics):")
    publisher_msg = await bot.wait_for('message', check=check_author, timeout=30)
    publisher_name = publisher_msg.content.strip().lower()

    await ctx.send("🦸 Now enter a **character name** (e.g. Spider-Man, Batman):")
    character_msg = await bot.wait_for('message', check=check_author, timeout=30)
    character_name = character_msg.content.strip().lower()

    await ctx.send("🔍 Searching for ongoing series matching your request...")

    # Step 1: Search for character
    character_search_url = f"https://comicvine.gamespot.com/api/characters/?api_key={comicvine_api_key}&format=json&filter=name:{character_name}"
    headers = {"User-Agent": "MyComicBot"}
    char_response = requests.get(character_search_url, headers=headers).json()
    characters = char_response.get("results", [])
    if not characters:
        await ctx.send(f"❌ Character '{character_name}' not found.")
        return

    character_id = characters[0]["id"]

    # Step 2: Search for volumes (series) with that character
    # ⚠️ ComicVine doesn't support direct volume-by-character search, so we use `/volumes/` with name and filter manually
    volumes_url = f"https://comicvine.gamespot.com/api/volumes/?api_key={comicvine_api_key}&format=json&filter=name:{character_name}&sort=name:asc"
    volumes_response = requests.get(volumes_url, headers=headers).json()
    volumes = volumes_response.get("results", [])

    # Filter by publisher and end_year
    matching = []
    for vol in volumes:
        if vol.get("publisher", {}).get("name", "").lower() != publisher_name:
            continue
        if vol.get("end_year") not in (None, 0):
            continue  # Not ongoing
        matching.append(vol)

    if not matching:
        await ctx.send(f"❌ No ongoing series found with character '{character_name}' from publisher '{publisher_name}'.")
        return

    # Show top 5 choices
    message_lines = [f"**{i+1}.** {v['name']} (start: {v.get('start_year', 'N/A')})" for i, v in enumerate(matching[:5])]
    await ctx.send("🎯 Please choose a series by typing the number:\n" + "\n".join(message_lines))

    try:
        response = await bot.wait_for('message', check=check_author, timeout=30)
        choice = int(response.content.strip()) - 1
        selected = matching[choice]
    except (ValueError, IndexError):
        await ctx.send("❌ Invalid selection.")
        return

    # Save user selection
    user_selected_series[ctx.author.id] = selected
    await ctx.send(f"✅ You selected: **{selected['name']}** (ID: {selected['id']})")


@tasks.loop(minutes=1)
async def daily_comic_check():
    """
    Checks every minute if it's 08:00 and comics haven't been sent today.
    If so, sends today's comics to the specified channel.
    """
    global last_sent_date

    now = datetime.now()
    current_time = now.strftime("%H:%M")
    today = now.date()

    # If it's 08:00 and comics haven't been sent today, send them
    if current_time == "08:00" and last_sent_date != today:
        channel = bot.get_channel(comics_channel_id)
        if channel:
            await fetch_and_send_comics(channel)
            last_sent_date = today

async def fetch_and_send_comics(channel):
    """
    Fetches today's comics from ComicVine API and sends them as embeds to the given channel.
    """
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
            # Extract comic details
            name = issue.get("name") or issue.get("volume", {}).get("name", "Unnamed")
            link = issue.get("site_detail_url", "")
            volume = issue.get("volume", {}).get("name", "Unknown Series")
            image = issue.get("image", {}).get("original_url")
            release_date = issue.get("store_date", date_today)

            # Create and send an embed for each comic
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
        # Send error message if fetching fails
        await channel.send(f"⚠️ Error fetching comics: {e}")

# Run the bot with logging enabled
bot.run(token, log_handler=handler, log_level=logging.DEBUG)
