# https://discord.com/api/oauth2/authorize?client_id=1190002809685430437&permissions=139586776128&scope=bot
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

    for userId, user in user_info["users"].items():
        if not bool(user["quackedToday"]):
            user["quackStreak"] = 0

        user["quackedToday"] = False

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)


@client.event
async def on_ready():
    await client.tree.sync()
    print("Bot is connected to Discord")
    dailyReset.start()


@client.tree.command(name="quack", description="Get your quack in for today.")
async def quack(interaction: discord.Interaction):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    user = interaction.user.id
    # print(f'{user} trying to quack')

    try:
        if not bool(user_info[str(user)]["quackedToday"]):
            user_info[user]["quackedToday"] = True
            user_info[user]["quacks"] += 1
            user_info[user]["quackStreak"] += 1
            # print(f'{user} quacked loudly.')
            message = f'User {user} quacked loudly.'

            if user_info[user]["quackStreak"] >= global_info["maxQuackStreakLength"]:
                user_info[user]["quackStreak"] -= global_info["maxQuackStreakLength"]
                user_info[user]["quacks"] += global_info["quackStreakReward"]
                # print(f'{user} finished a streak and got an extra {global_info["quackStreakReward"]} quacks.')
                message += f'\nUser {user} finished a streak and got an extra {global_info["quackStreakReward"]} quacks.'
        else:
            print(
                f'User {user} tried to quack but your throat is too sore today.')
    except:
        new_user = {
            "quacks": 1,
            "quackStreak": 1,
            "quackedToday": True
        }
        user_info[user] = new_user
        print(f'User {user} quacked for the first time!')

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message("Command executed")


@client.tree.command(name="quackery", description="Check out who are the top quackers.")
async def quackery(interaction: discord.Interaction, number: int = 10):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    top_list = "Top Quackers"

    for x in range(number):
        user_id = await get_max_quacks(user_info)
        print(f'user_id: {user_id}')

        if user_id == 0:
            break

        top_list += f'\n{client.get_user(user_id)} --- {user_info[str(user_id)]["quacks"]}'
        user_info.pop(str(user_id))

    await interaction.response.send_message(top_list)


# Return user id of the user with the most quacks
async def get_max_quacks(users):
    quacks = 0
    top_user_id = 0

    # Find the userId with the max quacks
    for userId, user in users.items():
        if int(user["quacks"]) > quacks:
            quacks = int(user["quacks"])
            top_user_id = int(userId)

    return top_user_id


async def main():
    async with client:
        with open("config.json", "r") as file:
            config = json.load(file)

        await client.start(config['token'])


asyncio.run(main())
