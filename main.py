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
from datetime import datetime, timedelta, timezone

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

c.execute("""CREATE TABLE IF NOT EXISTS scheduled_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movie_name TEXT,
    event_datetime TEXT,
    organizer_id INTEGER,
    discord_event_id INTEGER,
    guild_id INTEGER
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
@bot.event
async def on_ready():
    print(f"🎬 Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()  # Global sync (works in all servers)
        print(f"✅ Synced {len(synced)} global slash commands across all servers.")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")
        
# ------------------------------
# WELCOME MESSAGE
# ------------------------------
@bot.event
async def on_member_join(member):
    channel = discord.utils.get(member.guild.text_channels, name="welcome")  # replace with your channel name
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
    # Remove all previous cinema bot roles
    for old_role_name in roles:
        old_role = discord.utils.get(guild.roles, name=old_role_name)
        if old_role and old_role in user.roles:
            await user.remove_roles(old_role)
    
    # Add the new role
    role_name = roles[min(new_level - 1, len(roles) - 1)]
    role = discord.utils.get(guild.roles, name=role_name)
    if not role:
        role = await guild.create_role(name=role_name)
    await user.add_roles(role)
    await user.send(f"🎉 Congrats {user.name}! You've been promoted to **{role_name}**!")


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
    await interaction.response.defer()
    
    try:
        async with aiohttp.ClientSession() as session:
            # Search for the movie
            search_url = f"https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={movie_name}"
            async with session.get(search_url) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"❌ Error connecting to TMDB API (status {resp.status}). Please try again later.")
                    return
                
                search_data = await resp.json()
                
                if not search_data.get("results"):
                    await interaction.followup.send(f"❌ Could not find movie '{movie_name}' on TMDB. Please check the spelling.")
                    return
                
                movie = search_data["results"][0]
                movie_id = movie["id"]
                title = movie["title"]
                
                # Get detailed movie information
                details_url = f"https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}"
                credits_url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits?api_key={TMDB_API_KEY}"
                
                async with session.get(details_url) as details_resp:
                    if details_resp.status != 200:
                        await interaction.followup.send(f"❌ Error fetching movie details from TMDB. Please try again later.")
                        return
                    details = await details_resp.json()
                
                async with session.get(credits_url) as credits_resp:
                    if credits_resp.status != 200:
                        await interaction.followup.send(f"❌ Error fetching movie credits from TMDB. Please try again later.")
                        return
                    credits = await credits_resp.json()
                
                # Extract information
                overview = details.get("overview", "No overview available.")
                if len(overview) > 300:
                    overview = overview[:300] + "..."
                imdb_rating = details.get("vote_average", "N/A")
                release_date = details.get("release_date", "Unknown")
                poster_path = details.get("poster_path")
                
                # Get director
                director = "Unknown"
                for crew_member in credits.get("crew", []):
                    if crew_member.get("job") == "Director":
                        director = crew_member.get("name", "Unknown")
                        break
                
                # Get lead actor
                lead_actor = "Unknown"
                if credits.get("cast") and len(credits["cast"]) > 0:
                    lead_actor = credits["cast"][0].get("name", "Unknown")
                
                # Create embed
                embed = discord.Embed(
                    title=f"🎬 {title}",
                    description=overview,
                    color=discord.Color.gold()
                )
                
                if poster_path:
                    poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                    embed.set_image(url=poster_url)
                
                embed.add_field(name="⭐ IMDB Rating", value=f"{imdb_rating}/10", inline=True)
                embed.add_field(name="📅 Release Date", value=release_date, inline=True)
                embed.add_field(name="🎬 Director", value=director, inline=True)
                embed.add_field(name="🎭 Lead Actor", value=lead_actor, inline=True)
                embed.set_footer(text=f"Recommended by {interaction.user.name}")
                
                # Save to database
                c.execute("INSERT INTO recommendations (movie_name, recommender_id) VALUES (?, ?)", (title, interaction.user.id))
                conn.commit()
                
                await interaction.followup.send(f"🎥 {interaction.user.mention} recommended **{title}**!", embed=embed)
    
    except aiohttp.ClientError as e:
        await interaction.followup.send(f"❌ Network error while connecting to TMDB. Please check your connection and try again.")
    except Exception as e:
        await interaction.followup.send(f"❌ An unexpected error occurred: {str(e)}")

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

@bot.tree.command(name="removerecommendations", description="Remove one of your own movie recommendations.")
@app_commands.describe(movie_name="Name of the movie you want to remove")
async def removerecommendations(interaction: discord.Interaction, movie_name: str):
    user_id = interaction.user.id

    try:
        # Check if the user has recommended this movie
        c.execute("SELECT * FROM recommendations WHERE recommender_id = ? AND movie_name = ?", (user_id, movie_name))
        result = c.fetchone()

        if not result:
            await interaction.response.send_message(
                f"❌ You haven’t recommended **{movie_name}** or it doesn’t exist.",
                ephemeral=True
            )
            return

        # Delete the movie recommendation
        c.execute("DELETE FROM recommendations WHERE recommender_id = ? AND movie_name = ?", (user_id, movie_name))
        conn.commit()

        await interaction.response.send_message(
            f"✅ Successfully removed your recommendation for **{movie_name}**.",
            ephemeral=True
        )

    except Exception as e:
        await interaction.response.send_message(f"❌ Error removing recommendation: {str(e)}", ephemeral=True)

@removerecommendations.autocomplete("movie_name")
async def remove_autocomplete(interaction: discord.Interaction, current: str):
    user_id = interaction.user.id
    cursor.execute("SELECT movie FROM recommendations WHERE user_id = ?", (user_id,))
    movies = [row[0] for row in cursor.fetchall()]
    return [
        app_commands.Choice(name=m, value=m)
        for m in movies if current.lower() in m.lower()
    ][:25]

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

@bot.tree.command(name="schedule", description="Schedule a movie night with automatic event creation.")
@app_commands.describe(
    movie_name="Name of the movie to watch",
    date="Date in format YYYY-MM-DD (e.g., 2025-11-15)",
    time="Time in 24-hour format HH:MM in UTC (e.g., 19:30)",
    duration="Duration in minutes (default: 120)"
)
async def schedule(interaction: discord.Interaction, movie_name: str, date: str, time: str, duration: int = 120):
    await interaction.response.defer()
    
    try:
        # Parse the date and time as UTC timezone-aware datetime
        event_datetime_str = f"{date} {time}"
        event_datetime_naive = datetime.strptime(event_datetime_str, "%Y-%m-%d %H:%M")
        event_datetime = event_datetime_naive.replace(tzinfo=timezone.utc)
        
        # Check if the date is in the future
        if event_datetime <= datetime.now(timezone.utc):
            await interaction.followup.send("❌ Please schedule a movie night for a future date and time.")
            return
        
        # Create Discord scheduled event
        guild = interaction.guild
        end_time = event_datetime + timedelta(minutes=duration)
        
        event = await guild.create_scheduled_event(
            name=f"🎬 Movie Night: {movie_name}",
            description=f"Join us for a screening of **{movie_name}**!\n\nOrganized by {interaction.user.name}",
            start_time=event_datetime,
            end_time=end_time,
            entity_type=discord.EntityType.external,
            location="Cinema Society Movie Night",
            privacy_level=discord.PrivacyLevel.guild_only
        )
        
        # Save to database (store as ISO format for proper parsing later)
        event_datetime_iso = event_datetime.isoformat()
        c.execute(
            "INSERT INTO scheduled_events (movie_name, event_datetime, organizer_id, discord_event_id, guild_id) VALUES (?, ?, ?, ?, ?)",
            (movie_name, event_datetime_iso, interaction.user.id, event.id, guild.id)
        )
        conn.commit()
        
        # Create response embed
        embed = discord.Embed(
            title="🎬 Movie Night Scheduled!",
            description=f"**{movie_name}**",
            color=discord.Color.green()
        )
        embed.add_field(name="📅 Date", value=event_datetime.strftime("%B %d, %Y"), inline=True)
        embed.add_field(name="⏰ Time", value=event_datetime.strftime("%I:%M %p UTC"), inline=True)
        embed.add_field(name="⏱️ Duration", value=f"{duration} minutes", inline=True)
        embed.add_field(name="👤 Organizer", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"Event ID: {event.id}")
        
        await interaction.followup.send(
            f"✅ Movie night scheduled! Check the server events to RSVP and get reminders.",
            embed=embed
        )
        
    except ValueError:
        await interaction.followup.send("❌ Invalid date or time format. Use YYYY-MM-DD for date and HH:MM for time (24-hour format).")
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to create events. Please give me the 'Manage Events' permission.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error creating event: {str(e)}")

@bot.tree.command(name="movieschedule", description="View upcoming scheduled movie nights.")
async def movieschedule(interaction: discord.Interaction):
    c.execute(
        "SELECT movie_name, event_datetime, organizer_id, discord_event_id FROM scheduled_events WHERE guild_id = ? ORDER BY event_datetime ASC",
        (interaction.guild.id,)
    )
    events = c.fetchall()
    
    if not events:
        await interaction.response.send_message("📅 No upcoming movie nights scheduled yet! Use `/schedule` to create one.")
        return
    
    embed = discord.Embed(
        title="🎬 Upcoming Movie Nights",
        description="Here are all the scheduled movie nights:",
        color=discord.Color.blue()
    )
    
    current_time = datetime.now(timezone.utc)
    upcoming_count = 0
    
    for movie_name, event_datetime_str, organizer_id, event_id in events:
        try:
            # Parse ISO format datetime string
            event_datetime = datetime.fromisoformat(event_datetime_str)
            
            # Only show future events
            if event_datetime > current_time:
                organizer = await bot.fetch_user(organizer_id)
                formatted_date = event_datetime.strftime("%B %d, %Y at %I:%M %p UTC")
                
                embed.add_field(
                    name=f"🎥 {movie_name}",
                    value=f"📅 {formatted_date}\n👤 Organized by {organizer.name}",
                    inline=False
                )
                upcoming_count += 1
        except:
            continue
    
    if upcoming_count == 0:
        await interaction.response.send_message("📅 No upcoming movie nights scheduled yet! Use `/schedule` to create one.")
    else:
        embed.set_footer(text=f"Total upcoming events: {upcoming_count}")
        await interaction.response.send_message(embed=embed)

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
    await run_webserver()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main()) 

