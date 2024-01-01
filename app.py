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

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    for userId, user in user_info.items():
        # Reset streak counter if the streak is broken
        if not bool(user["quackedToday"]):
            user["quackStreak"] = 0

        user["quackedToday"] = False

        target_rank = await get_quack_rank(user["quacks"])

        if target_rank != user["quackRank"]:
            user["quackRank"] = target_rank

        # Collect the income from each land
        for land_id in user["land_ids"]:
            land = await get_land(land_id)

            # Don't collect if the land is being sieged by a superior foe

        # Attempt to pay all the soldiers in the party and garrisoned in each land

        # If no money is left then disband all the soldiers that cant be paid

    # Execute the task queue
    # 1) Do attacks/lay siege
    # 2) Build queued buildings
    # 3) Hire/upgrade troops
    # 4)

    # Randomize the q-qq exchange rate
    global_info["qqExchangeRate"] = random.randint(int(
        global_info["qqExchangeRateRange"][0]), int(global_info["qqExchangeRateRange"][1]))

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./global_info.json", "w") as file:
        json.dump(global_info, file, indent=4)

    # Tell the specified channel about the update
    try:
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
            "quackRank": "",
            "spentQuacks": 0,
            "quackerinos": 0,
            "renown": 0,
            "liege_id": 0,
            "taxPerVassalLand": 0,
            "homeland_id": -1,
            "land_ids": [],
            "mischief": false,
            "species": "",
            "party": []
        }
        user_info[user_id] = new_user
        message = f'{username} quacked for the first time!'

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(message)


@client.tree.command(name="pay", description="Give a player some quackerinos.")
async def pay(interaction: discord.Interaction, target_user_id: str, number: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Make sure the target player exists in user_info
    try:
        target = user_info[target_user_id]
        if user == target:
            await interaction.response.send_message("You can't give quackerinos to yourself.")
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Make sure the player can't give more quackerinos than they have
    try:
        if int(user["quackerinos"]) < number:
            await interaction.response.send_message("You don't have enough quackerinos for that.")
            return
    except:
        await interaction.response.send_message("You don't have enough quackerinos for that.")
        return

    # Give the other player quackerinos, but check if they have the quackerinos attribute yet
    target["quackerinos"] = target.get("quackerinos", 0) + number
    user["quackerinos"] -= number

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You transferred {number} quackerinos to {client.get_user(int(target_user_id))}. They now have {target["quackerinos"]} qq and you now have {user["quackerinos"]} qq.')


@client.tree.command(name="buyqq", description="Trade in some of your quacks for quackerinos.")
async def buy_qq(interaction: discord.Interaction, quacks: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Make sure the player has enough quacks
    if int(user["quacks"]) - int(user["spentQuacks"]) < quacks:
        await interaction.response.send_message("You don't have enough quacks for that.")
        return

    user["spentQuacks"] += quacks
    result = int(global_info["qqExchangeRate"]) * quacks
    user["quackerinos"] = user.get("quackerinos", 0) + result

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You bought {result} quackerinos using {quacks} quacks. You now have {user["quackerinos"]} qq and {user["quacks"]} quacks.')


@client.tree.command(name="qqrate", description="Check the current quacks-quackerino exchange rate.")
async def qq_rate(interaction: discord.Interaction):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    await interaction.response.send_message(f'Currently 1 quack can buy {global_info["qqExchangeRate"]} quackerinos.')


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

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    try:
        message = f'{client.get_user(user_id)}'
        if user["quackRank"] != "":
            message += f' the {user["quackRank"]}'

        message += f' has quacked {user["quacks"]} times and is on a {user["quackStreak"]} day streak. '

        next_rank = await get_next_quack_rank(user["quackRank"])

        if next_rank != "":
            quacks = int(user["quacks"])
            next_quacks = int(global_info["quackRank"][next_rank])

            message += f'They are {next_quacks-quacks} quacks away from the next rank of {next_rank}. '

        message += f'They have spent {user.get("spentQuacks", 0)} quacks and have {user.get("quackerinos", 0)} quackerinos.'

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


@client.tree.command(name="homeland", description="Establish a new homeland for you and your people.")
async def establish_homeland(interaction: discord.Interaction, name: str, species: str):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    with open("./species.json", "r") as file:
        species_list = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Make sure the species exists and is enabled
    try:
        if not bool(species_list[species]["enabled"]):
            await interaction.response.send_message("This species is not enabled.")
            return
    except:
        await interaction.response.send_message("Species not found.")
        return

    # Make sure this player hasn't made a homeland already
    if user.get("homeland_id", -1) >= 0:
        await interaction.response.send_message("You already have a homeland.")
        return

    with open("./lands.json", "r") as file:
        lands = json.load(file)

    # Create the new land
    try:
        new_land = deepcopy(lands["default"])
        new_land["name"] = name
        new_land["owner_id"] = user_id
        new_land["species"] = species

        lands[global_info["landCounter"]] = new_land

        user["homeland_id"] = global_info["landCounter"]
        user["species"] = species
        user["land_ids"] = [global_info["landCounter"]]

        global_info["landCounter"] += 1
        message = 'New land created'

        # Save to database
        with open("./user_info.json", "w") as file:
            json.dump(user_info, file, indent=4)

        # Save to database
        with open("./global_info.json", "w") as file:
            json.dump(global_info, file, indent=4)

        # Save to database
        with open("./lands.json", "w") as file:
            json.dump(lands, file, indent=4)
    except:
        message = 'There was an error trying to add the new land.'

    await interaction.response.send_message(message)


async def get_land(land_id):
    with open("./lands.json", "r") as file:
        lands = json.load(file)

    land = lands.get(land_id, "")

    return land


async def get_species(species_name):
    with open("./species.json", "r") as file:
        species_list = json.load(file)

    species = species_list.get(species_name, "")

    return species


async def main():
    async with client:
        with open("config.json", "r") as file:
            config = json.load(file)

        await client.start(config['token'])


asyncio.run(main())
