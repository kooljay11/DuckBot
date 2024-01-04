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


@tasks.loop(time=[datetime.time(hour=12, minute=0, tzinfo=datetime.timezone.utc)])
# @tasks.loop(minutes=1)
async def dailyReset():
    print('Daily reset occurring')
    # with open("./bot_status.txt", "r") as file:
    #     randomresponses = file.readlines()
    #     response = random.choice(randomresponses)
    # await client.change_presence(activity=discord.Game(response))
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    # Reset streak counter if the streak is broken
    for userId, user in user_info.items():
        if not bool(user["quackedToday"]):
            user["quackStreak"] = 0

        user["quackedToday"] = False

        target_rank = await get_quack_rank(user["quacks"])

        if target_rank != user["quackRank"]:
            user["quackRank"] = target_rank

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    # Tell the specified channel about the update
    try:
        with open("./global_info.json", "r") as file:
            global_info = json.load(file)

        destination_channel = int(global_info["new_day_channel_id"])
        await client.get_channel(destination_channel).send(
            "A new day has arrived and the ducks feel refreshed from their slumber.")
    except:
        print('Error trying to execute the new day.')


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

    user_id = interaction.user.id
    username = client.get_user(user_id)

    try:
        user = user_info[str(user_id)]

        if not bool(user["quackedToday"]):
            user["quackedToday"] = True
            user["quacks"] += 1
            user["quackStreak"] += 1
            message = f'{username} quacked loudly.'

            if user["quackStreak"] >= global_info["maxQuackStreakLength"]:
                user["quackStreak"] -= global_info["maxQuackStreakLength"]
                user["quacks"] += global_info["quackStreakReward"]
                message += f'\n{username} finished a streak and got an extra {global_info["quackStreakReward"]} quacks.'
        else:
            message = f'{username} tried to quack but their throat is too sore today.'
    except:
        new_user = {
            "quacks": 1,
            "quackStreak": 1,
            "quackedToday": True,
            "quackRank": ""
        }
        user_info[user_id] = new_user
        message = f'{username} quacked for the first time!'

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(message)


@client.tree.command(name="quackery", description="Check out who are the top quackers.")
async def quackery(interaction: discord.Interaction, number: int = 10):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    top_list = "Top Quackers"

    for x in range(number):
        user_id = await get_max_quacks(user_info)

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


@client.tree.command(name="quackinfo", description="Check out the quack info of a user.")
async def quack_info(interaction: discord.Interaction, user_id: int = 0):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    if user_id == 0:
        user_id = interaction.user.id

    try:
        message = f'{client.get_user(user_id)}'
        if user_info[str(user_id)]["quackRank"] != "":
            message += f' the {user_info[str(user_id)]["quackRank"]}'

        message += f' has quacked {user_info[str(user_id)]["quacks"]} times and is on a {user_info[str(user_id)]["quackStreak"]} day streak. '

        next_rank = await get_next_quack_rank(user_info[str(user_id)]["quackRank"])

        if next_rank != "":
            quacks = int(user_info[str(user_id)]["quacks"])
            next_quacks = int(global_info["quackRank"][next_rank])

            message += f'They are {next_quacks-quacks} quacks away from the next rank of {next_rank}.'

    except:
        message = 'That user has not quacked yet.'

    await interaction.response.send_message(message)


async def get_quack_rank(quacks):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    quack_rank = ""

    for rank, requirement in global_info["quackRank"].items():
        if int(quacks) >= int(requirement):
            quack_rank = rank

    return quack_rank


async def get_next_quack_rank(quack_rank):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    next_quack_rank = ""

    try:
        current_quacks = int(global_info["quackRank"][quack_rank])
    except:
        current_quacks = 0

    for rank, requirement in global_info["quackRank"].items():
        # Check greater than current quack rank requirement but lower/eq to target quack rank
        if requirement > current_quacks and (next_quack_rank == "" or requirement < int(global_info["quackRank"][next_quack_rank])):
            next_quack_rank = rank

    return next_quack_rank


async def main():
    async with client:
        with open("config.json", "r") as file:
            config = json.load(file)

        await client.start(config['token'])


asyncio.run(main())
