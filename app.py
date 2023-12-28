#https://discord.com/api/oauth2/authorize?client_id=1190002809685430437&permissions=139586776128&scope=bot
import os
import asyncio
import random
import math
import datetime
from copy import deepcopy
import json
import discord
from discord.ext import commands, tasks

client = commands.Bot(command_prefix="/",
                      intents=discord.Intents.all())

@tasks.loop(time=[datetime.time(hour=12, tzinfo=datetime.timezone.utc)])
async def dailyReset():
    # with open("./bot_status.txt", "r") as file:
    #     randomresponses = file.readlines()
    #     response = random.choice(randomresponses)
    # await client.change_presence(activity=discord.Game(response))
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    for user in user_info["users"]:
        user["quackedToday"] = False
    
    #Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)


@client.event
async def on_ready():
    await client.tree.sync()
    print("Bot is connected to Discord")
    dailyReset.start()


async def main():
    async with client:
        with open("config.json", "r") as file:
            config = json.load(file)

        await client.start(config['token'])


asyncio.run(main())