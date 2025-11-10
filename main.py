import discord
from discord.ext import commands, tasks
from discord import app_commands
import sqlite3
import random
import aiohttp
from aiohttp import web
import asyncio
import os
from dotenv import load_dotenv

# ------------------------------
# CONFIGURATION
# ------------------------------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------------
# DATABASE SETUP
# ------------------------------
conn = sqlite3.connect("cinema.db")
c = conn.cursor()

# Create tables
c.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    xp INTEGER DEFAULT 0,
    level INTEGER DEFAULT 1
)""")

c.execute("""CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_name TEXT,
    recommender_id INTEGER,
    rating REAL DEFAULT 0
)""")
conn.commit()

# ------------------------------
# ROLE LEVELS
# ------------------------------
roles = [
    "🎬 Side Actor",
    "🧑‍🎤 Supporting Actor",
    "⭐ Lead Actor",
    "🎭 Script Writer",
    "🎥 Cinematographer",
    "🎞️ Editor",
    "🎬 Director",
    "💰 Executive Producer",
    "🏛️ Studio Head",
    "🌟 Legendary Producer"
]
level_thresholds = [0, 50, 120, 200, 300, 450, 650, 900, 1200, 1600]

# ------------------------------
# ON READY
# ------------------------------
@bot.event
async def on_ready():
    print(f"🎬 Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")

# ------------------------------
# WELCOME MESSAGE
# ------------------------------
@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel
    if channel:
        await channel.send(
            f"🎥 **Welcome to the Cinema Society, {member.mention}!**\nGrab your popcorn 🍿 and join the show!"
        )

# ------------------------------
# XP SYSTEM
# ------------------------------
last_xp = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    now = asyncio.get_event_loop().time()

    if user_id not in last_xp or now - last_xp[user_id] >= 60:  # XP_COOLDOWN
        xp_gain = random.randint(10, 20)
        last_xp[user_id] = now

        c.execute("SELECT xp, level FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()

        if result:
            xp, level = result
            xp += xp_gain
        else:
            xp = xp_gain
            level = 1

        # Check level up
        new_level = level
        for i, threshold in enumerate(level_thresholds):
            if xp >= threshold:
                new_level = i + 1

        if new_level > level:
            await level_up(message.author, message.guild, new_level)

        c.execute("INSERT OR REPLACE INTO users (user_id, xp, level) VALUES (?, ?, ?)", (user_id, xp, new_level))
        conn.commit()

    await bot.process_commands(message)

async def level_up(user, guild, new_level):
    role_name = roles[min(new_level - 1, len(roles) - 1)]
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name)
    await user.add_roles(role)
    await user.send(f"🎉 Congrats {user.name}! You’ve been promoted to **{role_name}**!")

# ------------------------------
# SLASH COMMANDS
# ------------------------------
@bot.tree.command(name="level", description="Check your current XP and level.")
async def level(interaction: discord.Interaction):
    user_id = interaction.user.id
    c.execute("SELECT xp, level FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()

    if result:
        xp, level = result
        await interaction.response.send_message(f"🎬 {interaction.user.mention}, you're level **{level}** with **{xp} XP**!")
    else:
        await interaction.response.send_message("You don’t have any XP yet. Start chatting to earn some!")

@bot.tree.command(name="recommend", description="Recommend a movie to others.")
@app_commands.describe(movie_name="Name of the movie to recommend")
async def recommend(interaction: discord.Interaction, movie_name: str):
    c.execute("INSERT INTO recommendations (movie_name, recommender_id) VALUES (?, ?)", (movie_name, interaction.user.id))
    conn.commit()
    await interaction.response.send_message(f"🎥 {interaction.user.mention} recommended **{movie_name}**!")

@bot.tree.command(name="recommendations", description="Show recent movie recommendations.")
async def recommendations(interaction: discord.Interaction):
    c.execute("SELECT movie_name, recommender_id, rating FROM recommendations ORDER BY id DESC LIMIT 10")
    rows = c.fetchall()
    if not rows:
        await interaction.response.send_message("No movie recommendations yet!")
        return

    embed = discord.Embed(title="🎬 Movie Recommendations", color=discord.Color.gold())
    for movie, uid, rating in rows:
        user = await bot.fetch_user(uid)
        embed.add_field(name=movie, value=f"By: {user.name} | ⭐ {rating if rating > 0 else 'Not rated'}", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="rate", description="Rate a recommended movie.")
@app_commands.describe(movie_name="Movie to rate", rating="Your rating (1-10)")
async def rate(interaction: discord.Interaction, movie_name: str, rating: int):
    if rating < 1 or rating > 10:
        await interaction.response.send_message("Please rate between 1 and 10.")
        return

    c.execute("UPDATE recommendations SET rating = ? WHERE movie_name = ?", (rating, movie_name))
    conn.commit()
    await interaction.response.send_message(f"⭐ You rated **{movie_name}** {rating}/10!")

@bot.tree.command(name="randommovie", description="Get a random movie suggestion.")
async def randommovie(interaction: discord.Interaction):
    async with aiohttp.ClientSession() as session:
        url = f"https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&language=en-US&page={random.randint(1, 10)}"
        async with session.get(url) as resp:
            data = await resp.json()
            movie = random.choice(data["results"])
            title = movie["title"]
            overview = movie["overview"][:200] + "..."
            embed = discord.Embed(title=title, description=overview, color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)

@bot.tree.command(name="randomgenre", description="Suggest a random movie genre.")
async def randomgenre(interaction: discord.Interaction):
    genres = [
        "Action", "Comedy", "Drama", "Horror", "Sci-Fi", "Romance",
        "Thriller", "Fantasy", "Documentary", "Animation"
    ]
    genre = random.choice(genres)
    await interaction.response.send_message(f"🎞️ Random genre: **{genre}**")

# ------------------------------
# MOVIE CHAIN GAME
# ------------------------------
used_movies = []
current_last_letter = None

@bot.command(name="moviechain")
async def moviechain(ctx, *, movie_name: str):
    global current_last_letter, used_movies
    movie_name = movie_name.strip().title()

    if movie_name in used_movies:
        await ctx.send("❌ That movie has already been used!")
        return

    if current_last_letter and not movie_name.startswith(current_last_letter.upper()):
        await ctx.send(f"⚠️ Movie must start with **{current_last_letter.upper()}**!")
        return

    used_movies.append(movie_name)
    current_last_letter = movie_name[-1]
    await ctx.send(f"🎬 Nice! Next movie should start with **{current_last_letter.upper()}**!")

# ------------------------------
# WEB SERVER TO KEEP RAILWAY HAPPY
# ------------------------------
async def handle(request):
    return web.Response(text="OK")

async def run_webserver():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

# ------------------------------
# MAIN ASYNC ENTRYPOINT
# ------------------------------
async def main():
    await site.start()

# ------------------------------
# MAIN ASYNC ENTRYPOINT
# ------------------------------
async def main():
    await run_webserver()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main()) 
