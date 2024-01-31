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


# @tasks.loop(time=[datetime.time(hour=12, minute=0, tzinfo=datetime.timezone.utc)])
@tasks.loop(minutes=60)
# @tasks.loop(minutes=1)
async def dailyReset():
    print('Daily reset occurring')
    with open("./bot_status.txt", "r") as file:
        randomresponses = file.readlines()
        response = random.choice(randomresponses)
    await client.change_presence(activity=discord.CustomActivity(name=response, emoji='🦆'))
    # Requires that you do the following for this to work: pip install discord.py>=2.3.2

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

    index = 0

    # Execute all the siege commands first
    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "siege":
            user = user_info[str(task["user_id"])]
            land = lands.get(str(task["location_id"]), "")
            target_land = lands.get(str(task["target_land_id"]), "")
            unit = await get_unit(land["siegeCamp"], task["item"], task["user_id"])
            army = land["siegeCamp"]

            # Fail if that troop isn't in that land or if there aren't as many as specified
            if unit == "" or unit["amount"] < task["amount"]:
                unit = await get_unit(land["garrison"], task["item"], task["user_id"])
                army = land["garrison"]
                if unit == "" or unit["amount"] < task["amount"]:
                    await dm(task["user_id"], 'You don\'t have enough of that troop from that location to send to the siege camp.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue

            # Fail if the target land is yours
            if target_land["owner_id"] == task["user_id"]:
                await dm(task["user_id"], 'You can\'t siege yourself.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            ally_vassals = await get_allied_vassals(task["user_id"])

            # Fail if the target is the liege or vassal of your liege or your vassal
            if user["liege_id"] != 0 and (target_land["owner_id"] == user["liege_id"] or str(target_land["owner_id"]) in ally_vassals or user_info[str(target_land["owner_id"])]["liege_id"] == task["user_id"]):
                await dm(task["user_id"], 'You can\'t siege this person for one of the following reasons: they are your liege, fellow vassal, or your vassal.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Fail if the your land is already surrounded
            if await is_surrounded(land):
                await dm(task["user_id"], f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Remove the troops from the original land
            moved_unit = await remove_unit(army, unit, task["amount"])

            # Add them to the siege camp on the target land
            await add_unit(target_land["siegeCamp"], moved_unit)

            await dm(task["user_id"],
                     f'{task["amount"]} {task["item"]}s were sent to siege {target_land["name"]}.')
            global_info["task_queue"].pop(index)  # Remove this task
        else:
            index += 1

    index = 0

    # Execute each siege battle, including attack commands and garrison. Then also include the siege camp if there are any defend commands.
    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "attack":
            include_siege_camp = False
            user_ids = []
            attacker_army = []
            defender_army = []

            defend_index = 0
            target_land = lands.get(str(task["target_land_id"]), "")

            # Check for all other defend commands done to this target place and put them into an array
            while defend_index < len(global_info["task_queue"]):
                action = global_info["task_queue"][defend_index]
                if action["target_land_id"] == task["target_land_id"] and action["task"] == "defend":
                    user = user_info[str(action["user_id"])]
                    land = lands.get(str(action["location_id"]), "")

                    unit = await get_unit(land["siegeCamp"], action["item"], action["user_id"])

                    # Fail if that troop isn't in that land or if there aren't as many as specified
                    if unit == "" or unit["amount"] < action["amount"]:
                        unit = await get_unit(land["garrison"], action["item"], action["user_id"])
                        if unit == "" or unit["amount"] < action["amount"]:
                            await dm(action["user_id"], 'You don\'t have enough of that troop from that location to send on an attack.')
                            global_info["task_queue"].pop(
                                defend_index)  # Remove this task
                            continue

                    # Fail if they are both the same land
                    if target_land["owner_id"] == action["user_id"]:
                        await dm(action["user_id"], 'You don\'t need to use this command for troops in the garrison of a land being attacked.')
                        global_info["task_queue"].pop(
                            defend_index)  # Remove this task
                        continue

                    # Fail if the your land is already surrounded
                    if await is_surrounded(land):
                        await dm(task["user_id"], f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
                        global_info["task_queue"].pop(
                            defend_index)  # Remove this task
                        continue

                    # Add the troops to the defender army
                    defender_army.append(
                        {"unit": unit, "amount": action["amount"]})

                    # user_ids.append(action["user_id"])

                    global_info["task_queue"].pop(
                        defend_index)  # Remove this task

                    include_siege_camp = True
                else:
                    defend_index += 1

            # Add all garrison to the defend army
            for unit in target_land["garrison"]:
                defender_army.append({"unit": unit, "amount": unit["amount"]})

            if include_siege_camp:
                target_land = lands.get(str(task["target_land_id"]), "")

                # Add all siege camp to the attack army
                for unit in target_land["siegeCamp"]:
                    attacker_army.append(
                        {"unit": unit, "amount": unit["amount"]})

            attack_index = 0

            # Check for all other attack commands done to this target place and put them into an array
            while attack_index < len(global_info["task_queue"]):
                action = global_info["task_queue"][attack_index]

                if action["target_land_id"] == task["target_land_id"] and action["task"] == "attack":
                    user = user_info[str(action["user_id"])]
                    land = lands.get(str(action["location_id"]), "")
                    # target_land = lands.get(str(action["target_land_id"]), "")

                    unit = await get_unit(land["siegeCamp"], action["item"], action["user_id"])

                    # Fail if that troop isn't in that land or if there aren't as many as specified
                    if unit == "" or unit["amount"] < action["amount"]:
                        unit = await get_unit(land["garrison"], action["item"], action["user_id"])
                        if unit == "" or unit["amount"] < action["amount"]:
                            await dm(action["user_id"], 'You don\'t have enough of that troop from that location to send on an attack.')
                            global_info["task_queue"].pop(
                                attack_index)  # Remove this task
                            continue
                    # Fail if the siege camp has already been included in the battle
                    elif include_siege_camp and action["location_id"] == action["target_land_id"]:
                        global_info["task_queue"].pop(
                            attack_index)  # Remove this task
                        continue

                    # Fail if the target land is yours
                    if target_land["owner_id"] == action["user_id"]:
                        await dm(action["user_id"], 'You can\'t attack yourself.')
                        global_info["task_queue"].pop(
                            attack_index)  # Remove this task
                        continue

                    ally_vassals = await get_allied_vassals(action["user_id"])

                    # Fail if the target is the liege or vassal of your liege or your vassal
                    if user["liege_id"] != 0 and (target_land["owner_id"] == user["liege_id"] or str(target_land["owner_id"]) in ally_vassals or user_info[str(target_land["owner_id"])]["liege_id"] == action["user_id"]):
                        await dm(action["user_id"], 'You can\'t attack this person for one of the following reasons: they are your liege, fellow vassal, or your vassal.')
                        global_info["task_queue"].pop(
                            attack_index)  # Remove this task
                        continue

                    # Fail if the your land is already surrounded
                    if await is_surrounded(land) and land != target_land:
                        await dm(task["user_id"], f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
                        global_info["task_queue"].pop(
                            attack_index)  # Remove this task
                        continue

                    # Add the troops to the attacker army
                    attacker_army.append(
                        {"unit": unit, "amount": action["amount"]})

                    # user_ids.append(action["user_id"])

                    global_info["task_queue"].pop(
                        attack_index)  # Remove this task

                else:
                    attack_index += 1

            # Get the list of people to alert
            for unit in attacker_army:
                user_ids.append(unit["unit"]["user_id"])
            for unit in defender_army:
                user_ids.append(unit["unit"]["user_id"])

            # Resolve the combat
            message = await resolve_battle(attacker_army, defender_army, target_land)

            # If the defender army is empty then transfer the land to the attacking side (and add this to the message)
            total_defenders = await get_total_troops(defender_army)

            if total_defenders <= 0:
                troops_by_user = {}
                highest_user_id = 0

                # Find the person with the most troops currently left in the siegecamp
                for unit in land["siegeCamp"]:
                    troops_by_user[unit["user_id"]] = troops_by_user.get(
                        unit["user_id"], 0) + unit["amount"]

                for user_id, number in troops_by_user.items():
                    if troops_by_user.get(highest_user_id, 0) < number:
                        highest_user_id = user_id

                # Destroy buildings accordingly
                total_destroy_percent = 0
                total_troops = 0

                # Get the average percent building destruction
                for company in attacker_army:
                    troop = await get_troop(company["unit"]["troop_name"])
                    species = await get_species(troop["species"])
                    print(f'species: {species}')

                    total_destroy_percent += species[global_info["current_season"]].get(
                        "percentBuildingsDestroyedOnConquest", species["all-season"]["percentBuildingsDestroyedOnConquest"]) * company["amount"]
                    total_troops += company["amount"]

                print(f'total_destroy_percent: {total_destroy_percent}')
                print(f'total_troops: {total_troops}')

                total_buildings_destroyed = int(
                    round(len(target_land["buildings"]) * (total_destroy_percent/total_troops)))
                print(
                    f'total_buildings_destroyed: {total_buildings_destroyed}')

                for x in range(total_buildings_destroyed):
                    print(
                        f'target_land["buildings"]: {target_land["buildings"]}')

                    building_name = target_land["buildings"].pop(random.randint(
                        0, len(target_land["buildings"])-1))
                    print(f'building_name: {building_name}')

                    building = await get_building(building_name)

                    # Add the lower tier building if necessary
                    if building["demolishedTo"] != "":
                        target_land["buildings"].append(
                            building["demolishedTo"])

                print(f'target_land["buildings"]: {target_land["buildings"]}')

                # Change the land owner
                if highest_user_id != 0:
                    user_info[str(target_land["owner_id"])]["land_ids"].remove(
                        task["target_land_id"])
                    target_land["owner_id"] = int(highest_user_id)
                    user_info[str(target_land["owner_id"])]["land_ids"].append(
                        task["target_land_id"])
                    message += f'\n\n{target_land["name"]} has been taken by {client.get_user(int(target_land["owner_id"]))}.'

                message += f'\n{total_buildings_destroyed} buildings were burned.'

                print(f'highest_user_id: {highest_user_id}')

                # Move the siege camp troops into the garrison
                target_land["garrison"] = deepcopy(target_land["siegeCamp"])
                target_land["siegeCamp"] = []

            # DM the results to all the combatants
            for user_id in user_ids:
                await dm(user_id, message)
        else:
            index += 1

    index = 0

    # Execute each field battle, including sallyout commands and siege camp.
    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "sallyout":
            user_ids = []
            attacker_army = []
            defender_army = []

            defend_index = 0

            while defend_index < len(global_info["task_queue"]):
                action = global_info["task_queue"][defend_index]
                if action["target_land_id"] == task["target_land_id"] and action["task"] == "sallyout":
                    land = lands.get(str(action["location_id"]), "")
                    target_land = lands.get(str(action["target_land_id"]), "")

                    unit = await get_unit(land["siegeCamp"], action["item"], action["user_id"])

                    # Fail if that troop isn't in that land or if there aren't as many as specified
                    if unit == "" or unit["amount"] < action["amount"]:
                        unit = await get_unit(land["garrison"], action["item"], action["user_id"])
                        if unit == "" or unit["amount"] < action["amount"]:
                            await dm(action["user_id"], 'You don\'t have enough of that troop from that location to send on an attack.')
                            global_info["task_queue"].pop(
                                defend_index)  # Remove this task
                            continue

                    # Fail if the your land is already surrounded
                    if await is_surrounded(land) and action["location_id"] != action["target_land_id"]:
                        await dm(task["user_id"], f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
                        global_info["task_queue"].pop(
                            defend_index)  # Remove this task
                        continue

                    # Add the troops to the defender army
                    defender_army.append(
                        {"unit": unit, "amount": action["amount"]})

                    user_ids.append(action["user_id"])

                    global_info["task_queue"].pop(
                        defend_index)  # Remove this task
                else:
                    defend_index += 1

            # Add all siege camp to the attack army
            for unit in target_land["siegeCamp"]:
                attacker_army.append(
                    {"unit": unit, "amount": unit["amount"]})

            # Resolve the combat
            target_land = lands.get(str(task["target_land_id"]), "")
            message = await resolve_battle(attacker_army, defender_army, target_land)

            # DM the results to all the combatants
            for user_id in user_ids:
                await dm(user_id, message)
        else:
            index += 1

    index = 0

    # Execute all move commands
    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "move":
            user = user_info[str(task["user_id"])]
            land = lands.get(str(task["location_id"]), "")
            target_land = lands.get(str(task["target_land_id"]), "")
            unit = await get_unit(land["siegeCamp"], task["item"], task["user_id"])
            army = land["siegeCamp"]

            # Fail if that troop isn't in that land or if there aren't as many as specified
            if unit == "" or unit["amount"] < task["amount"]:
                unit = await get_unit(land["garrison"], task["item"], task["user_id"])
                army = land["garrison"]
                if unit == "" or unit["amount"] < task["amount"]:
                    await dm(task["user_id"], 'You don\'t have enough of that troop from that location to send to the siege camp.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue
                # Fail if they are both the same land
                elif task["location_id"] == task["target_land_id"]:
                    await dm(task["user_id"], 'The developers stopped you from taking a useless action.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue

            ally_vassals = await get_allied_vassals(task["user_id"])

            # Fail if the target land isn't yours, your liege's, vassal of your liege, or your vassal
            if target_land["owner_id"] != task["user_id"]:
                if not (user["liege_id"] != 0 and (target_land["owner_id"] == user["liege_id"] or str(target_land["owner_id"]) in ally_vassals or user_info[str(target_land["owner_id"])]["liege_id"] == user_id)):
                    await dm(task["user_id"], 'You can only move troops to lands that belong to you, your liege, a vassal of your liege, or your vassal.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue

            # Fail if the your land is already surrounded
            if await is_surrounded(land):
                await dm(task["user_id"], f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Fail if the target land is already surrounded unless taking troops out of the siege camp
            if await is_surrounded(target_land) and army != land["siegeCamp"]:
                await dm(task["user_id"], f'You cannot move troops into the garrison of {target_land["name"]} because it is fully surrounded.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Remove the troops from the original land
            moved_unit = await remove_unit(army, unit, task["amount"])

            # Add them to the garrison on the target land
            await add_unit(target_land["siegeCamp"], moved_unit)

            # DM the results to the player
            await dm(task["user_id"], f'{task["amount"]} {task["item"]}s were sent to {target_land["name"]}\'s garrison.')

            global_info["task_queue"].pop(index)  # Remove this task
        else:
            index += 1

    index = 0

    # Execute all hire/upgrade commands in the following order: Tier 4 upgrades → Tier 3 upgrades → Tier 2 upgrades → Hire upgrades
    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "upgrade":
            top_tier = 1

            # Get the top tier upgrade troop
            for action in global_info["task_queue"]:
                if action["task"] == "upgrade":
                    troop = await get_troop(action["item"])

                    if troop["tier"] > top_tier:
                        top_tier = troop["tier"]

            # Execute all the upgrade commands going from top to bottom tiers
            while top_tier > 0:
                troop_index = 0
                while troop_index < len(global_info["task_queue"]):
                    action = global_info["task_queue"][troop_index]
                    troop = await get_troop(action["item"])

                    if action["task"] == "upgrade" and troop["tier"] == top_tier:
                        user = user_info[str(action["user_id"])]
                        land = lands.get(str(action["location_id"]), "")
                        # Fail if the specified land doesn't belong to that player
                        if action["location_id"] not in user["land_ids"]:
                            await dm(action["user_id"], 'That land doesn\'t belong to you.')
                            global_info["task_queue"].pop(
                                troop_index)  # Remove this task
                            continue

                        unit = await get_unit(land["garrison"], action["item"], action["user_id"])

                        # Fail if that troop isn't in that land or if there aren't as many as specified
                        if unit == "" or unit["amount"] < action["amount"]:
                            await dm(action["user_id"], f'You don\'t have enough of that troop to upgrade {action["amount"]} of them.')
                            global_info["task_queue"].pop(
                                troop_index)  # Remove this task
                            continue

                        new_troop = await get_troop(troop["upgradesTo"])
                        cost = new_troop["cost"] * action["amount"]

                        # Fail if not enough money
                        if int(user["quackerinos"]) < cost:
                            await dm(action["user_id"], "You don't have enough quackerinos for that.")
                            global_info["task_queue"].pop(
                                troop_index)  # Remove this task
                            continue

                        # Remove the money
                        user["quackerinos"] -= cost

                        # Remove the troops from the garrison
                        await remove_unit(land["garrison"], unit, action["amount"])

                        # Add the upgraded troop to the garrison
                        new_unit = {
                            "troop_name": troop["upgradesTo"], "amount": action["amount"], "user_id": action["user_id"]}
                        await add_unit(land["garrison"], new_unit)

                        # DM the results to the player
                        await dm(action["user_id"], f'{action["amount"]} {action["item"]}s were upgraded to {troop["upgradesTo"]}s at {land["name"]}\'s garrison.')

                        global_info["task_queue"].pop(
                            troop_index)  # Remove this task

                    else:
                        troop_index += 1
                top_tier -= 1
        else:
            index += 1

    index = 0

    # Execute all hire commands
    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "hire":
            user = user_info[str(task["user_id"])]
            troop = await get_troop(task["item"])
            land = lands.get(str(task["location_id"]), "")

            # Fail if the specified land doesn't belong to that player
            if task["location_id"] not in user["land_ids"]:
                await dm(task["user_id"], 'That land doesn\'t belong to you.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            cost = troop["cost"] * task["amount"]

            # Fail if not enough money
            if int(user["quackerinos"]) < cost:
                await dm(task["user_id"], "You don't have enough quackerinos for that.")
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Remove the money
            user["quackerinos"] -= cost

            # Add the troops to the garrison
            new_unit = {
                "troop_name": task["item"], "amount": task["amount"], "user_id": task["user_id"]}
            await add_unit(land["garrison"], new_unit)

            # DM the results to the player
            await dm(task["user_id"], f'You hired {task["amount"]} {task["item"]}s at {land["name"]}\'s garrison.')

            global_info["task_queue"].pop(index)  # Remove this task
        else:
            index += 1

    index = 0

    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "build":
            user = user_info[str(task["user_id"])]
            land = lands.get(str(task["location_id"]), "")
            building = await get_building(task["item"])

            # Fail if the specified land doesn't belong to that player
            if task["location_id"] not in user["land_ids"]:
                await dm(task["user_id"], 'That land doesn\'t belong to you.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Fail if the building has already been built on that land
            if task["item"] in land["buildings"]:
                await dm(task["user_id"], 'That building has already been built there.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Fail if the building has to be upgraded to and is missing their requirement
            if bool(building["fromUpgradeOnly"]):
                requirement = False
                for building_x_name in land["buildings"]:
                    building_x = await get_building(building_x_name)
                    if building_x["upgradesTo"] == task["item"]:
                        requirement = True
                        break
                if not requirement:
                    await dm(task["user_id"], 'That building needs to be built by upgrading a lower tier one.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue

            # Fail if there is an upper tier building of this already
            upgradesTo = deepcopy(building["upgradesTo"])
            skip = False
            while upgradesTo != "":
                if upgradesTo in land["buildings"]:
                    await dm(task["user_id"], 'There is already an upper tier equivalent of that building in that location.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    skip = True
                    break
                else:
                    next_building = await get_building(building["upgradesTo"])
                    upgradesTo = deepcopy(next_building["upgradesTo"])
            if skip:
                continue

            # Only make the user pay at the beginning of the construction
            if task["time"] == building["constructionTime"]:
                cost = building["cost"]

                # Fail if not enough money
                if int(user["quackerinos"]) < cost:
                    await dm(task["user_id"], "You don't have enough quackerinos for that.")
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue

                # Remove the money
                user["quackerinos"] -= cost

                await dm(task["user_id"], f'The labourers have started building {task["item"]} at {land["name"]}, costing {cost}')

            task["time"] -= 1

            if task["time"] <= 0:
                # Build the new building
                land["buildings"].append(task["item"])

                # Destroy the lower tier one if applicable
                if bool(building["fromUpgradeOnly"]):
                    for building_x_name in land["buildings"]:
                        building_x = await get_building(building_x_name)
                        if building_x["upgradesTo"] == task["item"]:
                            land["buildings"].remove(building_x_name)
                            break

                await dm(task["user_id"], f'{task["item"]} has been built at {land["name"]}.')
                global_info["task_queue"].pop(index)  # Remove this task
            else:
                index += 1
        else:
            index += 1

    # Execute all build commands

    # 1) Siege commands
    # 2) Resolve attack+defend battles
    # 3) Resolve sallyout battles
    # 4) move commands
    # 5) Hire/upgrade troops
    # 6) Increase building progress or build the queued building

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
            return
        elif target_user_id == "default":
            await interaction.response.send_message("You can't give quackerinos to the default user.")
            return

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
            message += f'\nGarrison: '
            for unit in land["garrison"]:
                message += f'\n• {unit["amount"]} {unit["troop_name"]} ({client.get_user(int(unit["user_id"]))})'

            if land["siegeCamp"] != []:
                message += f'\nSiege camp: '
                for unit in land["siegeCamp"]:
                    message += f'\n• {unit["amount"]} {unit["troop_name"]} ({client.get_user(int(unit["user_id"]))})'

    except:
        message = 'Error while fetching user information.'

    await interaction.response.send_message(message)


@client.tree.command(name="landinfo", description="Check out the info on a certain land.")
async def land_info(interaction: discord.Interaction, land_id: int = 0, land_name: str = ""):
    # Fail if both fields are empty
    if land_id == 0 and land_name == "":
        await interaction.response.send_message("You need to put in either a land id or land name.")
        return

    land = await get_land(land_id)

    # Fail if land id is wrong/empty and land name is wrong/empty
    if land == "":
        land = await get_land_by_name(land_name)
        print(f'land: {land}')
        if land == "":
            await interaction.response.send_message("Land not found.")
            return

    land_id = await get_land_id(land)

    # Display the land info
    message = f'**{land["name"]} (ID: {land_id}) - {land["species"]}**'
    message += f'\nOwner: {client.get_user(int(land["owner_id"]))} (ID: {land["owner_id"]})'
    message += f'\nQuality: {land["quality"]}/{land["maxQuality"]}'
    message += f'\nBuildings: {land["buildings"]}'
    message += f'\nGarrison: '
    for unit in land["garrison"]:
        message += f'\n• {unit["amount"]} {unit["troop_name"]} ({client.get_user(int(unit["user_id"]))})'

    if land["siegeCamp"] != []:
        message += f'\nSiege camp: '
        for unit in land["siegeCamp"]:
            message += f'\n• {unit["amount"]} {unit["troop_name"]} ({client.get_user(int(unit["user_id"]))})'

    await interaction.response.send_message(message)


@client.tree.command(name="taskqueue", description="Check out the task queue.")
async def view_task_queue(interaction: discord.Interaction):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    message = f'__**Task Queue**__'

    for task in global_info["task_queue"]:
        land = await get_land(task["location_id"])
        message += f'\n{client.get_user(int(task["user_id"]))} @ {land["name"]} ({task["location_id"]})'

        if task["target_land_id"] > 0:
            target = await get_land(task["target_land_id"])
            message += f' → {target["name"]} ({task["target_land_id"]})'

        message += f': {task["task"]}'

        if task["amount"] > 1:
            message += f' {task["amount"]} {task["item"]}s'
        else:
            message += f' {task["item"]}'

        if task["time"] > 1:
            message += f' (turns remaining: {task["time"]})'

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
    if building == "" or not bool(building["enabled"]):
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

    # Fail if the building has to be upgraded to and is missing their requirement
    if bool(building["fromUpgradeOnly"]):
        requirement = False
        for building_x_name in land["buildings"]:
            building_x = await get_building(building_x_name)
            if building_x["upgradesTo"] == building_name:
                requirement = True
                break
        if not requirement:
            await interaction.response.send_message('That building needs to be built by upgrading a lower tier one.')
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

    # Add the lower tier building if necessary
    if building["demolishedTo"] != "":
        land["buildings"].append(building["demolishedTo"])
        message = f'The {building_name} was demolished into a {building["demolishedTo"]} and you were refunded {refund} qq.'
    else:
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
    if troop == "" or troop == "default_tier1":
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

    # Fail if that troop can't be upgraded
    if troop["upgradesTo"] == "":
        await interaction.response.send_message('That troop can\'t be upgraded.')
        return

    unit = await get_unit(land["garrison"], troop_name, user_id)

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

    unit = await get_unit(land["garrison"], troop_name, user_id)

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


@client.tree.command(name="attack", description="Launch an assault on someone's land/castle (takes one month).")
async def attack(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    land = await get_land(location_id)
    target_land = await get_land(target_land_id)

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the other land doesn't exist
    if target_land == "":
        await interaction.response.send_message('Target land doesn\'t exist.')
        return

    unit = await get_unit(land["siegeCamp"], troop_name, user_id)

    # Fail if that troop isn't in that land or if there aren't as many as specified
    if unit == "" or unit["amount"] < amount:
        unit = await get_unit(land["garrison"], troop_name, user_id)
        if unit == "" or unit["amount"] < amount:
            await interaction.response.send_message(f'You don\'t have enough of that troop from that location to send on an attack.')
            return

    # Fail if the target land is yours
    if target_land["owner_id"] == user_id:
        await interaction.response.send_message(f'You can\'t attack yourself.')
        return

    ally_vassals = await get_allied_vassals(user_id)

    # Fail if the target is the liege or vassal of your liege or your vassal
    if user["liege_id"] != 0 and (target_land["owner_id"] == user["liege_id"] or str(target_land["owner_id"]) in ally_vassals or user_info[str(target_land["owner_id"])]["liege_id"] == user_id):
        await interaction.response.send_message(f'You can\'t attack this person for one of the following reasons: they are your liege, fellow vassal, or your vassal.')
        return

    # Fail if the your land is already surrounded
    if await is_surrounded(land) and land != target_land:
        await interaction.response.send_message(f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
        return

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canAttack", species["all-season"].get("canAttack"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "attack", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to attack {target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="defend", description="Defend someone's land/castle from an incoming assault (takes one month).")
async def defend(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    land = await get_land(location_id)
    target_land = await get_land(target_land_id)

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    unit = await get_unit(land["siegeCamp"], troop_name, user_id)

    # Fail if that troop isn't in that land or if there aren't as many as specified
    if unit == "" or unit["amount"] < amount:
        unit = await get_unit(land["garrison"], troop_name, user_id)
        if unit == "" or unit["amount"] < amount:
            await interaction.response.send_message(f'You don\'t have enough of that troop from that location to send on an attack.')
            return

    # Fail if the other land doesn't exist
    if target_land == "":
        await interaction.response.send_message('Target land doesn\'t exist.')
        return

    # Fail if they are both the same land
    if location_id == target_land_id:
        await interaction.response.send_message('You don\'t need to use this command for troops in the garrison of a land being attacked.')
        return

    # Fail if the your land is already surrounded
    if await is_surrounded(land):
        await interaction.response.send_message(f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
        return

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canAttack", species["all-season"].get("canAttack"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "defend", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to defend {target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="siege", description="Initiate or join a siege on someone's land (takes one month).")
async def siege(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    land = await get_land(location_id)
    target_land = await get_land(target_land_id)

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the other land doesn't exist
    if target_land == "":
        await interaction.response.send_message('Target land doesn\'t exist.')
        return

    unit = await get_unit(land["siegeCamp"], troop_name, user_id)

    # Fail if that troop isn't in that land or if there aren't as many as specified
    if unit == "" or unit["amount"] < amount:
        unit = await get_unit(land["garrison"], troop_name, user_id)
        if unit == "" or unit["amount"] < amount:
            await interaction.response.send_message(f'You don\'t have enough of that troop from that location to send to the siege camp.')
            return

    # Fail if the target land is yours
    if target_land["owner_id"] == user_id:
        await interaction.response.send_message(f'You can\'t siege yourself.')
        return

    ally_vassals = await get_allied_vassals(user_id)

    # Fail if the target is the liege or vassal of your liege or your vassal
    if user["liege_id"] != 0 and (target_land["owner_id"] == user["liege_id"] or str(target_land["owner_id"]) in ally_vassals or user_info[str(target_land["owner_id"])]["liege_id"] == user_id):
        await interaction.response.send_message(f'You can\'t siege this person for one of the following reasons: they are your liege, fellow vassal, or your vassal.')
        return

    # Fail if the your land is already surrounded
    if await is_surrounded(land):
        await interaction.response.send_message(f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
        return

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canMove", species["all-season"].get("canMove"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "siege", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to siege {target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="sallyout", description="Launch an assault on a siege camp (takes one month).")
async def sallyout(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    land = await get_land(location_id)
    target_land = await get_land(target_land_id)

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the other land doesn't exist
    if target_land == "":
        await interaction.response.send_message('Target land doesn\'t exist.')
        return

    unit = await get_unit(land["siegeCamp"], troop_name, user_id)

    # Fail if that troop isn't in that land or if there aren't as many as specified
    if unit == "" or unit["amount"] < amount:
        unit = await get_unit(land["garrison"], troop_name, user_id)
        if unit == "" or unit["amount"] < amount:
            await interaction.response.send_message(f'You don\'t have enough of that troop from that location to send on an attack.')
            return

    # Fail if the your land is already surrounded
    if await is_surrounded(land) and land != target_land:
        await interaction.response.send_message(f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
        return

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canMove", species["all-season"].get("canMove"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "sallyout", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to attack the siege camp at {target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="move", description="Move troops to one of your or an ally's garrisons (takes one month).")
async def move(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    land = await get_land(location_id)
    target_land = await get_land(target_land_id)

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the other land doesn't exist
    if target_land == "":
        await interaction.response.send_message('Target land doesn\'t exist.')
        return

    unit = await get_unit(land["siegeCamp"], troop_name, user_id)

    # Fail if that troop isn't in that land or if there aren't as many as specified
    if unit == "" or unit["amount"] < amount:
        unit = await get_unit(land["garrison"], troop_name, user_id)
        if unit == "" or unit["amount"] < amount:
            await interaction.response.send_message(f'You don\'t have enough of that troop from that location to send to {target_land["name"]}.')
            return

    # Fail if they are both the same land
    if location_id == target_land_id:
        await interaction.response.send_message('The developers stopped you from taking a useless action.')
        return

    ally_vassals = await get_allied_vassals(user_id)

    # Fail if the target land isn't yours, your liege's, vassal of your liege, or your vassal
    if target_land["owner_id"] != user_id:
        if not (user["liege_id"] != 0 and (target_land["owner_id"] == user["liege_id"] or str(target_land["owner_id"]) in ally_vassals or user_info[str(target_land["owner_id"])]["liege_id"] == user_id)):
            await interaction.response.send_message(f'You can only move troops to lands that belong to you, your liege, a vassal of your liege, or your vassal.')
            return

    # Fail if the your land is already surrounded
    if await is_surrounded(land):
        await interaction.response.send_message(f'You cannot move troops out of {land["name"]} because it is fully surrounded.')
        return

    # Fail if the target land is already surrounded
    if await is_surrounded(target_land):
        await interaction.response.send_message(f'You cannot move troops into the garrrison of {target_land["name"]} because it is fully surrounded.')
        return

    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canMove", species["all-season"].get("canMove"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "move", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to {target_land["name"]}\'s garrison.'

    await interaction.response.send_message(message)


async def is_surrounded(land):
    defender_score = 0
    sieger_score = 0

    num_defenders = 0
    num_siegers = 0

    # 1 troop = +1 score
    for unit in land["garrison"]:
        num_defenders += unit["amount"]
    for unit in land["siegeCamp"]:
        num_siegers += unit["amount"]

    defender_score += num_defenders
    sieger_score += num_siegers

    # HP and DEF bonuses of buildings increase the defender score
    for building_name in land["buildings"]:
        building = await get_building(building_name)
        defender_score += min(building["maxAPbonus"], building["APbonus"] + building["APbonusPerTroop"] * num_defenders) + min(
            building["maxHPbonus"], building["HPbonus"] + building["HPbonusPerTroop"] * num_defenders)

    if sieger_score > defender_score:
        return True
    else:
        return False


async def remove_unit(army, unit, amount):
    moved_unit = deepcopy(unit)
    moved_unit["amount"] = amount
    unit["amount"] -= amount
    if unit["amount"] == 0:
        army.remove(unit)

    return moved_unit


async def add_unit(army, unit, amount=-1):
    target_unit = await get_unit(army, unit["troop_name"], unit["user_id"])
    if target_unit == "":
        army.append(unit)
    else:
        if amount < 0:
            target_unit["amount"] += unit["amount"]
        else:
            target_unit["amount"] += amount


async def get_allied_vassals(user_id):
    with open("./user_info.json", "r") as file:
        user_info = json.load(file)

    user = user_info.get(str(user_id), "")
    allies = []

    for ally_id, ally in user_info.items():
        if user["liege_id"] == ally["liege_id"] or user["liege_id"] == ally_id or ally["liege_id"] == user_id:
            allies.append(ally_id)

    return allies


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


async def get_land_by_name(land_name):
    with open("./lands.json", "r") as file:
        lands = json.load(file)

    for land in lands:
        if land["name"] == land_name:
            return land

    return ""


async def get_land_id(query_land):
    with open("./lands.json", "r") as file:
        lands = json.load(file)

    for land_id, land in lands.items():
        if land == query_land:
            return land_id

    return -1


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
            if dayx <= length:
                return season_name
            else:
                dayx -= length


async def get_unit(army, troop_name, user_id):
    for unit in army:
        if unit["troop_name"] == troop_name and str(unit["user_id"]) == str(user_id):
            return unit

    return ""


async def resolve_battle(attack_army, defend_army, land=""):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    percent_casualties_attackers = 0
    percent_casualties_defenders = 0
    total_attackers = await get_total_troops(attack_army)
    total_defenders = await get_total_troops(defend_army)

    round = 0

    message = f'__**Battle Report @ {land.get("name")}**__'
    message += f'\n**Round {round}**'
    message += f'\nAttackers:'
    message += f'{await print_army(attack_army)}'
    message += f'\nDefenders:'
    message += f'{await print_army(defend_army)}'

    attacker_HP = 0
    defender_HP = 0

    for unit in attack_army:
        troop = await get_troop(unit["unit"]["troop_name"])
        species = await get_species(troop["species"])
        attacker_HP += (troop["HP"] + species[global_info["current_season"]].get(
            "bonusHPPerTroop", species["all-season"].get("bonusHPPerTroop", 0))) * unit["amount"]

    for unit in defend_army:
        troop = await get_troop(unit["unit"]["troop_name"])
        species = await get_species(troop["species"])
        defender_HP += (troop["HP"] + species[global_info["current_season"]].get(
            "bonusHPPerTroop", species["all-season"].get("bonusHPPerTroop", 0))) * unit["amount"]

    if land != "":
        for building_name in land["buildings"]:
            building = await get_building(building_name)
            hpbonus = building["HPbonus"] + \
                building["HPbonusPerTroop"] * total_defenders
            hpbonus = min(hpbonus, building["maxHPbonus"])
            defender_HP += hpbonus

    while percent_casualties_attackers < global_info["max_casualties_attackers"] and percent_casualties_defenders < global_info["max_casualties_defenders"]:
        updated_total_attackers = await get_total_troops(attack_army)
        updated_total_defenders = await get_total_troops(defend_army)
        attacker_ATK = 0
        defender_ATK = 0
        attacker_DEF = 0
        defender_DEF = 0

        for unit in attack_army:
            troop = await get_troop(unit["unit"]["troop_name"])
            species = await get_species(troop["species"])
            attacker_ATK += int(troop["ATK"] + species[global_info["current_season"]].get(
                "bonusATKPerTroop", species["all-season"].get("bonusATKPerTroop", 0))) * unit["amount"]
            attacker_DEF += (troop["AP"] + species[global_info["current_season"]].get(
                "bonusDEFPerTroop", species["all-season"].get("bonusDEFPerTroop", 0))) * unit["amount"]
            # attacker_HP += (troop["HP"] + species[global_info["current_season"]].get("bonusHPPerTroop", species["all-season"].get("bonusHPPerTroop", 0))) * unit["amount"]

        for unit in defend_army:
            troop = await get_troop(unit["unit"]["troop_name"])
            species = await get_species(troop["species"])
            defender_ATK += (troop["ATK"] + species[global_info["current_season"]].get(
                "bonusATKPerTroop", species["all-season"].get("bonusATKPerTroop", 0))) * unit["amount"]
            defender_DEF += (troop["AP"] + species[global_info["current_season"]].get(
                "bonusDEFPerTroop", species["all-season"].get("bonusDEFPerTroop", 0))) * unit["amount"]
            # defender_HP += (troop["HP"] + species[global_info["current_season"]].get("bonusHPPerTroop", species["all-season"].get("bonusHPPerTroop", 0))) * unit["amount"]

        if land != "":
            for building_name in land["buildings"]:
                building = await get_building(building_name)
                atkbonus = building["ATKbonus"] + \
                    building["ATKbonusPerTroop"] * updated_total_defenders
                atkbonus = min(atkbonus, building["maxATKbonus"])
                defender_ATK += atkbonus
                defbonus = building["APbonus"] + \
                    building["APbonusPerTroop"] * updated_total_defenders
                defbonus = min(defbonus, building["maxAPbonus"])
                defender_DEF += defbonus
                # hpbonus = building["HPbonus"] + building["HPbonusPerTroop"] * total_defenders
                # hpbonus = min(hpbonus, building["maxHPbonus"])
                # defender_HP += hpbonus

        attacker_score = await get_battle_score(attacker_ATK)
        defender_score = await get_battle_score(defender_ATK)

        # attacker_score["score"] -= defender_DEF + defender_HP
        # defender_score["score"] -= attacker_DEF + attacker_HP
        # print(f'attacker_score["spite"]: {attacker_score["spite"]}')
        # print(f'defender_score["spite"]: {defender_score["spite"]}')
        attack_spite = deepcopy(attacker_score["spite"])
        defend_spite = deepcopy(defender_score["spite"])
        attacker_score["spite"] -= defender_DEF + defender_HP
        defender_score["spite"] -= attacker_DEF + attacker_HP
        defender_HP -= attack_spite
        defender_HP = max(0, defender_HP)
        attacker_HP -= defend_spite
        attacker_HP = max(0, attacker_HP)
        # print(f'attacker_score["spite"]: {attacker_score["spite"]}')
        # print(f'defender_score["spite"]: {defender_score["spite"]}')
        # print(f'defender_HP: {defender_HP}')
        # print(f'attacker_HP: {attacker_HP}')

        for x in range(attacker_score["spite"]):
            await remove_casualty(defend_army)
        for x in range(defender_score["spite"]):
            await remove_casualty(attack_army)
        # for x in range(attacker_score["score"]):
        #     await remove_casualty(defend_army)
        # for x in range(defender_score["score"]):
        #     await remove_casualty(attack_army)

        percent_casualties_attackers = 1 - await get_total_troops(attack_army) / total_attackers
        percent_casualties_defenders = 1 - await get_total_troops(defend_army) / total_defenders

        round += 1
        message += f'\n\n\n**Round {round}**'
        message += f'\nAttackers:'
        message += f'{await print_army(attack_army)}'
        message += f'\n\nDefenders:'
        message += f'{await print_army(defend_army)}'

    return message


async def print_army(army_collection):
    message = ""
    for company in army_collection:
        message += f'\n{company["amount"]} {company["unit"]["troop_name"]} ({client.get_user(int(company["unit"]["user_id"]))})'
    return message


async def remove_casualty(army_collection):
    try:
        target_index = random.randint(0, len(army_collection) - 1)
    except:
        return

    army_collection[target_index]["amount"] -= 1
    army_collection[target_index]["unit"]["amount"] -= 1

    if army_collection[target_index]["amount"] <= 0:
        army_collection.pop(target_index)


async def get_total_troops(army_collection):
    total = 0

    for company in army_collection:
        total += company["amount"]

    return total


async def get_battle_score(num):
    score = 0
    spite = 0

    for x in range(num):
        a = random.randint(1, 6)
        score += a
        if a >= 5:
            spite += 1

    return {"score": score, "spite": spite}


async def dm(user_id, message):
    try:
        user = await client.fetch_user(int(user_id))
        await user.send(message)
    except:
        print(f'{user_id} not found. Message: {message}')
        return


async def add_to_queue(user_id, action, item, location_id, amount=1, time=1, target_land=0):
    with open("./global_info.json", "r") as file:
        global_info = json.load(file)

    task = {
        "user_id": user_id,
        "task": action,
        "item": item,
        "location_id": location_id,
        "amount": amount,
        "time": time,
        "target_land_id": target_land
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
