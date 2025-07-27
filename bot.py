# bot.py
import discord
from discord.ext import commands
import yt_dlp
import asyncio
import threading
import sys
import os

from flask import Flask, request, jsonify
from dotenv import load_dotenv

# Load .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
bot = commands.Bot(command_prefix='!', intents=intents)

app = Flask(__name__)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Voice clients map per guild
voice_clients = {}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ydl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'default_search': 'ytsearch',
}

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')

@app.route('/play', methods=['POST'])
def play_from_api():
    data = request.get_json()
    song = data.get('song')
    channel_id = int(data.get('channel_id'))

    if not song or not channel_id:
        return jsonify({"error": "Missing 'song' or 'channel_id'"}), 400

    asyncio.run_coroutine_threadsafe(play_song(song, channel_id), loop)
    return jsonify({"status": "playing", "song": song}), 200

async def play_song(song, channel_id):
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"Channel {channel_id} not found.")
            return

        guild_id = channel.guild.id

        if not channel.permissions_for(channel.guild.me).connect:
            print("No permission to connect to the voice channel.")
            return

        if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
            voice_clients[guild_id] = await channel.connect()

        vc = voice_clients[guild_id]
        if vc.is_playing():
            vc.stop()

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(song, download=False)
            url = info['url'] if 'url' in info else info['entries'][0]['url']

        audio = await discord.FFmpegOpusAudio.from_probe(url, **FFMPEG_OPTIONS)
        vc.play(audio)

    except Exception as e:
        print(f"Error playing song: {e}")

@app.route('/pause', methods=['POST'])
def pause_audio():
    data = request.get_json()
    guild_id = int(data.get("guild_id"))

    vc = voice_clients.get(guild_id)
    if vc and vc.is_playing():
        loop.call_soon_threadsafe(vc.pause)
        return jsonify({"status": "paused"}), 200
    return jsonify({"error": "Nothing is playing."}), 400

@app.route('/resume', methods=['POST'])
def resume_audio():
    data = request.get_json()
    guild_id = int(data.get("guild_id"))

    vc = voice_clients.get(guild_id)
    if vc and vc.is_paused():
        loop.call_soon_threadsafe(vc.resume)
        return jsonify({"status": "resumed"}), 200
    return jsonify({"error": "Nothing to resume."}), 400

@app.route('/stop', methods=['POST'])
def stop_audio():
    data = request.get_json()
    guild_id = int(data.get("guild_id"))

    vc = voice_clients.get(guild_id)
    if vc and vc.is_playing():
        loop.call_soon_threadsafe(vc.stop)
        return jsonify({"status": "stopped"}), 200
    return jsonify({"error": "Nothing to stop."}), 400

@app.route('/leave', methods=['POST'])
def leave_voice():
    data = request.get_json()
    guild_id = int(data.get("guild_id"))

    vc = voice_clients.get(guild_id)
    if vc:
        loop.call_soon_threadsafe(asyncio.create_task, vc.disconnect())
        voice_clients.pop(guild_id, None)
        return jsonify({"status": "disconnected"}), 200
    return jsonify({"error": "Bot not in a voice channel."}), 400

def run_flask():
    app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    try:
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()

        loop.run_until_complete(bot.start(TOKEN))

    except KeyboardInterrupt:
        print("\n[!] Detected exit signal. Shutting down...")

        future = asyncio.run_coroutine_threadsafe(bot.close(), loop)
        future.result(timeout=10)
        loop.stop()
        sys.exit(0)
