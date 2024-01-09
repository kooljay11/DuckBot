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
# @tasks.loop(minutes=60)
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

    with open("./lands.json", "r") as file:
        lands = json.load(file)

    for userId, user in user_info.items():

        # Collect the income from each land
        for land_id in user["land_ids"]:
            # print(f'lands[land_id]: {lands[land_id]}')
            land = lands[str(land_id)]

            species = await get_species(land["species"])
            income = land["quality"] + \
                int(species[global_info["current_season"]].get(
                    "bonusIncomePerQuality", species["all-season"]["bonusIncomePerQuality"]) * land["quality"])

            # Remove income if they have too many lands
            if len(user["land_ids"]) > global_info["landLimit"]:
                income -= income * \
                    global_info["landIncomePenaltyPercentPerLand"]
                income = min(0, income)

            # Don't collect if the land is being sieged by a superior foe
            # Count total number of HP+DEF for both sides

            # Add the income to the user
            user["quackerinos"] += income

            # Roll for increase land quality if the user quacked
            if bool(user["quackedToday"]):
                if land["quality"] < land["maxQuality"]:
                    if random.random() < global_info["qualityImprovementProbability"]:
                        land["quality"] += 1
            else:
                # Roll for decrease land quality of the user didn't quack
                if land["quality"] > 0 and random.random() < global_info["qualityDecayProbability"]:
                    land["quality"] -= 1

        # Reset streak counter if the streak is broken
        if not bool(user["quackedToday"]):
            user["quackStreak"] = 0

        user["quackedToday"] = False

        target_rank = await get_quack_rank(user["quacks"])

        if target_rank != user["quackRank"]:
            user["quackRank"] = target_rank

        # Attempt to pay all the soldiers in the party and garrisoned in each land

        # If no money is left then disband all the soldiers that cant be paid

    # Execute the task queue
    for task in global_info["task_queue"]:
        # 1) Do attacks/lay siege
        # 2) Build queued buildings
        # 3) Hire/upgrade troops
        print("")

    global_info["task_queue"] = []

    # Randomize the q-qq exchange rate
    global_info["qqExchangeRate"] = random.randint(int(
        global_info["qqExchangeRateRange"][0]), int(global_info["qqExchangeRateRange"][1]))

    # Add to the day counter and cycle the season accordingly
    global_info["day_counter"] += 1
    global_info["current_season"] = await get_season(global_info["day_counter"])

    # Save to database
    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./global_info.json", "w") as file:
        json.dump(global_info, file, indent=4)

    with open("./lands.json", "w") as file:
        json.dump(lands, file, indent=4)

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

            if user["species"] == "penguin":
                message = f'{username}: noot noot!'
            else:
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
            "mischief": False,
            "species": "",
            "party": [],
            "siege_location_ids": []
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

    # Make sure the player can't give negative quackerinos
    if number < 1:
        await interaction.response.send_message("Nice try.")
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

    message = f'You bought {result} quackerinos using {quacks} quacks. You now have {user["quackerinos"]} qq and {user["quacks"]-user["spentQuacks"]} unspent quacks.'

    await interaction.response.send_message(message)


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
async def quack_info(interaction: discord.Interaction, user_id: str = ""):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    if user_id == "":
        user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("That user has not quacked yet.")
        return

    try:
        message = f'{client.get_user(int(user_id))}'
        if user["quackRank"] != "":
            message += f' the {user["quackRank"]}'

        message += f' has quacked {user["quacks"]} times and is on a {user["quackStreak"]} day streak. '

        next_rank = await get_next_quack_rank(user["quackRank"])

        if next_rank != "":
            quacks = int(user["quacks"])
            next_quacks = int(global_info["quackRank"][next_rank])

            message += f'They are {next_quacks-quacks} quacks away from the next rank of {next_rank}. '

        message += f'They have spent {user.get("spentQuacks", 0)} quacks and have {user.get("quackerinos", 0)} quackerinos. '

        if user["homeland_id"] > 0:
            homeland = await get_land(user["homeland_id"])

            if homeland["owner_id"] == user_id:
                message += f'This user is in control of their homeland.'
            else:
                message += f'This user is not in control of their homeland.'

        for land_id in user["land_ids"]:
            land = await get_land(land_id)

            message += f'\n\n**{land["name"]} (ID:{land_id}) - {land["species"]}**'
            message += f'\nQuality: {land["quality"]}/{land["maxQuality"]}'
            message += f'\nBuildings: {land["buildings"]}'
            message += f'\nGarrison: {land["garrison"]}'

            if land["siegeCamp"] != []:
                message += f'\nSiege camp: {land["siegeCamp"]}'

    except:
        message = 'Error while fetching user information.'

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
async def establish_homeland(interaction: discord.Interaction, name: str, species_name: str):
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

    # Make sure the species exists and is enabled
    species = await get_species(species_name)
    if species != "":
        if not bool(species["enabled"]):
            await interaction.response.send_message("This species is not enabled.")
            return
    else:
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
        new_land["species"] = species_name

        lands[global_info["landCounter"]] = new_land

        user["homeland_id"] = global_info["landCounter"]
        user["species"] = species_name
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


@client.tree.command(name="species", description="View all the enabled species.")
async def list_species(interaction: discord.Interaction):
    with open("./species.json", "r") as file:
        species_list = json.load(file)

    message = f'**List of Playable Species**'

    for species_name, species in species_list.items():
        if bool(species.get("enabled", species_list["default"].get("enabled"))):
            message += f'\n{species_name}: {species.get("description", species)}'

    await interaction.response.send_message(message)


@client.tree.command(name="buildings", description="View all the buildings that can be built.")
async def list_buildings(interaction: discord.Interaction):
    with open("./buildings.json", "r") as file:
        buildings = json.load(file)

    message = f'__**All Buildings**__'

    for building_name, building in buildings.items():
        if bool(building.get("enabled", buildings["default"].get("enabled"))):
            # message += f'\n{building_name}: {building.get("description", building)}'
            message += f'\n**{building_name}:** '
            for key, value in building.items():
                if key != "enabled":
                    message += f'{key}: {value}; '

    await interaction.response.send_message(message)


@client.tree.command(name="troops", description="View all the troops that can be hired.")
async def list_troops(interaction: discord.Interaction):
    with open("./troops.json", "r") as file:
        troops = json.load(file)

    message = f'__**All Troops**__'

    for troop_name, troop in troops.items():
        message += f'\n**{troop_name}:** '
        for key, value in troop.items():
            if value != "":
                message += f'{key}: {value}; '

    await interaction.response.send_message(message)


@client.tree.command(name="build", description="Build a new building in one of your lands (takes one month).")
async def build(interaction: discord.Interaction, location_id: int, building_name: str):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    building = await get_building(building_name)
    land = await get_land(location_id)

    # Fail if building doesn't exist
    if building == "":
        await interaction.response.send_message('Building not found.')
        return

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the specified land doesn't belong to that player
    if location_id not in user["land_ids"]:
        await interaction.response.send_message('That land doesn\'t belong to you.')
        return

    # Fail if the building has already been built on that land
    if building_name in land["buildings"]:
        await interaction.response.send_message('That building has already been built there.')
        return

    # Add it to the queue
    await add_to_queue(user_id, "build", building_name, location_id, time=building["constructionTime"])

    await interaction.response.send_message(f'{client.get_user(user_id)} has started building a {building_name} at {land["name"]}.')


@client.tree.command(name="demolish", description="Destroy a building in one of your lands.")
async def demolish(interaction: discord.Interaction, location_id: int, building_name: str):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./lands.json", "r") as file:
        lands = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    building = await get_building(building_name)
    land = lands.get(str(location_id), "")

    # Fail if building doesn't exist
    if building == "":
        await interaction.response.send_message('Building not found.')
        return

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the specified land doesn't belong to that player
    if location_id not in user["land_ids"]:
        await interaction.response.send_message('That land doesn\'t belong to you.')
        return

    # Fail if that building has not been built on that land yet
    if building_name not in land["buildings"]:
        await interaction.response.send_message('That building has not been built there yet.')
        return

    # Remove the building from that land and give the user a percent of the money
    land["buildings"].remove(building_name)
    refund = building["refundPercent"] * building["cost"]
    user["quackerinos"] += refund
    message = f'The {building_name} was destroyed and you were refunded {refund} qq.'

    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./lands.json", "w") as file:
        json.dump(lands, file, indent=4)

    await interaction.response.send_message(message)


@client.tree.command(name="hire", description="Hire some troops (takes one month).")
async def hire(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    troop = await get_troop(troop_name)
    # land = lands.get("location_id", "")
    land = await get_land(location_id)

    # Fail if troop doesn't exist
    if troop == "":
        await interaction.response.send_message('Troop not found.')
        return

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the specified land doesn't belong to that player
    if location_id not in user["land_ids"]:
        await interaction.response.send_message('That land doesn\'t belong to you.')
        return

    # Fail if that troop doesn't match the species of the land
    if bool(troop["requiresSpeciesMatch"]) and troop["species"] != land["species"]:
        await interaction.response.send_message('You can\'t hire that troop there.')
        return

    # Fail if that troop requires upgrading and can't be hired directly
    if bool(troop["fromUpgradeOnly"]):
        await interaction.response.send_message('That troop requires that you upgrade from a lower tier.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "hire", troop_name, location_id, amount)

    await interaction.response.send_message(f'You have started to hire {amount} {troop_name}s in {land["name"]}.')


@client.tree.command(name="upgrade", description="Upgrade some troops (takes one month).")
async def upgrade(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    troop = await get_troop(troop_name)
    # land = lands.get("location_id", "")
    land = await get_land(location_id)

    # Fail if troop doesn't exist
    if troop == "":
        await interaction.response.send_message('Troop not found.')
        return

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the specified land doesn't belong to that player
    if location_id not in user["land_ids"]:
        await interaction.response.send_message('That land doesn\'t belong to you.')
        return

    # Fail if that troop requires upgrading and can't be hired directly
    if bool(troop["fromUpgradeOnly"]):
        await interaction.response.send_message('That troop requires that you upgrade from a lower tier.')
        return

    unit = await get_unit(land["garrison"], troop_name)

    # Fail if that troop isn't in that land or if there aren't as many as specified
    if unit == "" or unit["amount"] < amount:
        await interaction.response.send_message(f'You don\'t have enough of that troop to upgrade {amount} of them.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "upgrade", troop_name, location_id, amount)

    await interaction.response.send_message(f'You have started to upgrade {amount} {troop_name}s in {land["name"]}.')


@client.tree.command(name="disband", description="Disband some of your troops.")
async def disband(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./lands.json", "r") as file:
        lands = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    troop = await get_troop(troop_name)
    land = lands.get(str(location_id), "")

    # Fail if troop doesn't exist
    if troop == "":
        await interaction.response.send_message('Troop not found.')
        return

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the specified land doesn't belong to that player
    if location_id not in user["land_ids"]:
        await interaction.response.send_message('That land doesn\'t belong to you.')
        return

    # Fail if that troop doesn't match the species of the land
    if bool(troop["requiresSpeciesMatch"]) and troop["species"] != land["species"]:
        await interaction.response.send_message('You can\'t hire that troop there.')
        return

    unit = await get_unit(land["garrison"], troop_name)

    # Fail if that troop isn't in that land or if there aren't as many as specified
    if unit == "" or unit["amount"] < amount:
        await interaction.response.send_message(f'You don\'t have enough of that troop to disband {amount} of them.')
        return

    # Remove troops from that user's land
    unit["amount"] -= amount

    if unit["amount"] == 0:
        land["garrison"].remove(unit)

    # Give refund to user if necessary
    refund = troop["refundPercentOnDisband"] * troop["cost"] * amount
    user["quackerinos"] += refund

    message = f'{amount} {troop_name}s were disbanded. {refund} qq were refunded to the user.'

    with open("./user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./lands.json", "w") as file:
        json.dump(lands, file, indent=4)

    await interaction.response.send_message(message)


async def get_troop(troop_name):
    with open("./troops.json", "r") as file:
        troops = json.load(file)

    try:
        overrides = troops[troop_name]
    except:
        return ""

    troop = troops.get(f'default_tier{overrides["tier"]}', {})

    # Replace the attributes with the troop specific overrides
    for attr, value in overrides.items():
        troop[attr] = value

    return troop


async def get_building(building_name):
    with open("./buildings.json", "r") as file:
        buildings = json.load(file)

    try:
        overrides = buildings[building_name]
    except:
        return ""

    building = buildings.get("default", "")

    # Replace the attributes with the building specific overrides
    for attr, value in overrides.items():
        building[attr] = value

    return building


async def get_land(land_id):
    with open("./lands.json", "r") as file:
        lands = json.load(file)

    land = lands.get(str(land_id), "")

    return land


async def get_species(species_name):
    with open("./species.json", "r") as file:
        species_list = json.load(file)

    try:
        overrides = species_list[species_name]
    except:
        return ""

    # species = species_list.get(species_name, "")
    species = species_list.get("default", "")

    # Replace the attributes with the species specific overrides
    species["enabled"] = overrides.get("enabled", species["enabled"])
    species["mischief"] = overrides.get("mischief", species["mischief"])

    for attr, value in overrides["all-season"].items():
        species["all-season"][attr] = value

    for attr, value in overrides["spring"].items():
        species["spring"][attr] = value

    for attr, value in overrides["summer"].items():
        species["summer"][attr] = value

    for attr, value in overrides["fall"].items():
        species["fall"][attr] = value

    for attr, value in overrides["winter"].items():
        species["winter"][attr] = value

    return species


async def get_season(day):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    dayx = deepcopy(day)

    while True:
        for season_name, length in global_info["seasons"].items():
            print(f'[{dayx}]: {season_name}, {length}')
            if dayx <= length:
                return season_name
            else:
                dayx -= length


async def get_unit(army, troop_name):
    for unit in army:
        if unit["troop_name"] == troop_name:
            return unit

    return ""


async def add_to_queue(user_id, action, item, location_id, amount=1, time=1):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    task = {
        "user_id": user_id,
        "task": action,
        "item": item,
        "location_id": location_id,
        "amount": amount,
        "time": time
    }

    global_info["task_queue"].append(task)

    with open("./global_info.json", "w") as file:
        json.dump(global_info, file, indent=4)


async def main():
    async with client:
        with open("config.json", "r") as file:
            config = json.load(file)

        await client.start(config['token'])


asyncio.run(main())
