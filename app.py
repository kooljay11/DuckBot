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


@tasks.loop(time=[datetime.time(hour=17, minute=0, tzinfo=datetime.timezone.utc)])
async def dailyReset():
    print('Daily reset occurring')
    with open("./bot_status.txt", "r") as file:
        randomresponses = file.readlines()
        response = random.choice(randomresponses)
    await client.change_presence(activity=discord.CustomActivity(name=response, emoji='🦆'))
    # Requires that you do the following for this to work: pip install discord.py>=2.3.2

    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    with open("./data/lands.json", "r") as file:
        lands = json.load(file)

    for userId, user in user_info.items():
        if userId == "default":
            continue

        # Collect the income from each land
        for land_id in user["land_ids"]:
            land = lands[str(land_id)]

            species = await get_species(land["species"])

            income = land["quality"] + \
                int(species[global_info["current_season"]].get(
                    "bonusIncomePerQuality", species["all-season"]["bonusIncomePerQuality"]) * land["quality"])

            # Give the user extra income according to the support they gave/lands this user has
            if user["support"] > 0:
                support_used = int(
                    round(user["support"] / len(user["land_ids"])))
                user["support"] -= support_used
                income += income * support_used * \
                    global_info["supportIncomeBoostPercent"]

            # Adjust income if they have too many lands
            if len(user["land_ids"]) > global_info["landLimit"]:
                income -= income * \
                    global_info["landIncomePenaltyPercentPerLand"] * \
                    (len(user["land_ids"]) - global_info["landLimit"])
                income = max(0, int(income))

            # Adjust income if the land is being sieged by a superior foe
            if await is_surrounded(land):
                income -= income * species[global_info["current_season"]].get(
                    "incomePenaltyPercentInSiege", species["all-season"]["incomePenaltyPercentInSiege"])
                income = max(0, int(income))

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

        # Pay liege lord according to the tax rate set by them
        if user["liege_id"] != 0:
            liege = user_info[str(user["liege_id"])]
            tax = liege["taxPerVassalLand"] * len(user["land_ids"])

            if tax > user["quackerinos"]:
                liege["quackerinos"] += user["quackerinos"]
                user["quackerinos"] = 0
            else:
                liege["quackerinos"] += tax
                user["quackerinos"] -= tax

        # Reset streak counter if the streak is broken
        if not bool(user["quackedToday"]):
            user["quackStreak"] = 0

        user["quackedToday"] = False

        target_rank = await get_quack_rank(user["quacks"])

        if target_rank != user["quackRank"]:
            user["quackRank"] = target_rank

        # Reset support
        user["support"] = 0
        user["supportee_id"] = 0

        # Reduce safety counter
        if user["safety_count"] > 0 and user["homeland_id"] > 0:
            user["safety_count"] -= 1

    # Attempt to pay all the soldiers in each land
    for land_id, land in lands.items():
        if land_id == "default":
            continue

        garrison_disband_list = []
        siege_camp_disband_list = []

        # Pay the garrison
        for unit in land["garrison"]:
            user = user_info[str(unit["user_id"])]
            troop = await get_troop(unit["troop_name"])
            species = await get_species(troop["species"])

            cost = unit["amount"] * troop["upkeep"]
            cost -= cost * species[global_info["current_season"]
                                   ].get("upkeepDiscountPerTroop", species["all-season"]["upkeepDiscountPerTroop"])

            # If the user doesn't have enough money left then disband all, otherwise reduce the user's qq balance
            if user["quackerinos"] < cost:
                # Add unit to the list to be disbanded
                garrison_disband_list.append(unit)

                # DM user that units have been disbanded
                await dm(unit["user_id"], f'{unit["amount"]} {unit["troop_name"]} have been disbanded at {land["name"]} because you didn\'t have enough money to pay them.')
            else:
                user["quackerinos"] -= cost

        # Disband units from the garrison
        for unit in garrison_disband_list:
            land["garrison"].remove(unit)

        # Pay the siegecamp
        for unit in land["siegeCamp"]:
            user = user_info[str(unit["user_id"])]
            troop = await get_troop(unit["troop_name"])
            species = await get_species(troop["species"])

            cost = unit["amount"] * troop["upkeep"]
            cost -= cost * species[global_info["current_season"]
                                   ].get("upkeepDiscountPerTroop", species["all-season"]["upkeepDiscountPerTroop"])
            cost += unit["amount"] * species[global_info["current_season"]
                                             ].get("upkeepExtraPerTroopInOffensiveSiege", species["all-season"]["upkeepExtraPerTroopInOffensiveSiege"])

            # If the user doesn't have enough money left then disband all, otherwise reduce the user's qq balance
            if user["quackerinos"] < cost:
                # Add unit to the list to be disbanded
                siege_camp_disband_list.append(unit)

                # DM user that units have been disbanded
                await dm(unit["user_id"], f'{unit["amount"]} {unit["troop_name"]} have been disbanded at {land["name"]} because you didn\' have enough money to pay them.')
            else:
                user["quackerinos"] -= cost

        # Disband units from the siege camp
        for unit in siege_camp_disband_list:
            land["siegeCamp"].remove(unit)

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
                    await dm(task["user_id"], f'You don\'t have enough of {task["item"]} from {land["name"]} to send to the siege camp of {target_land["name"]}.')
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
                await dm(task["user_id"], f'You can\'t siege {client.get_user(int(target_land["owner_id"]))}\'s settlement {target_land["name"]} for one of the following reasons: they are your liege, fellow vassal, or your vassal.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Fail if the your land is already surrounded
            if await is_surrounded(land):
                await dm(task["user_id"], f'You cannot move {task["item"]} out of {land["name"]} because it is fully surrounded.')
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
                            await dm(action["user_id"], f'You don\'t have enough {action["item"]} from {land["name"]} to send on an attack against {target_land["name"]}.')
                            global_info["task_queue"].pop(
                                defend_index)  # Remove this task
                            continue

                    # Fail if they are both the same land
                    if target_land["owner_id"] == action["user_id"]:
                        await dm(action["user_id"], 'You don\'t need to use the defend command for troops in the garrison of a land being attacked.')
                        global_info["task_queue"].pop(
                            defend_index)  # Remove this task
                        continue

                    # Fail if the your land is already surrounded
                    if await is_surrounded(land):
                        await dm(task["user_id"], f'You cannot move {action["item"]} out of {land["name"]} because it is fully surrounded.')
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
                            await dm(action["user_id"], f'You don\'t have enough {action["item"]} from {land["name"]} to send on an attack against {target_land["name"]}.')
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
                        await dm(action["user_id"], f'You can\'t attack {client.get_user(int(target_land["owner_id"]))} for one of the following reasons: they are your liege, fellow vassal, or your vassal.')
                        global_info["task_queue"].pop(
                            attack_index)  # Remove this task
                        continue

                    # Fail if the your land is already surrounded
                    if await is_surrounded(land) and land != target_land:
                        await dm(task["user_id"], f'You cannot move {task["item"]} out of {land["name"]} because it is fully surrounded.')
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

            total_defenders = await get_total_troops(defender_army)
            total_attackers = await get_total_troops(attacker_army)
            # Only resolve combat if there are defenders and attackers
            if total_defenders > 0 and total_attackers > 0:
                # Resolve the combat
                message = await resolve_battle(attacker_army, defender_army, target_land)
            else:
                message = f'There were not enough troops for a battle at {
                    target_land["name"]}.'

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

                    total_destroy_percent += species[global_info["current_season"]].get(
                        "percentBuildingsDestroyedOnConquest", species["all-season"]["percentBuildingsDestroyedOnConquest"]) * company["amount"]
                    total_troops += company["amount"]

                total_buildings_destroyed = int(
                    round(len(target_land["buildings"]) * (total_destroy_percent/total_troops)))

                for x in range(total_buildings_destroyed):

                    building_name = target_land["buildings"].pop(random.randint(
                        0, len(target_land["buildings"])-1))

                    building = await get_building(building_name)

                    # Add the lower tier building if necessary
                    if building["demolishedTo"] != "":
                        target_land["buildings"].append(
                            building["demolishedTo"])

                # Change the land owner
                if highest_user_id != 0:
                    user_info[str(target_land["owner_id"])]["land_ids"].remove(
                        task["target_land_id"])
                    target_land["owner_id"] = int(highest_user_id)
                    user_info[str(target_land["owner_id"])]["land_ids"].append(
                        task["target_land_id"])
                    message += f'\n\n{target_land["name"]} has been taken by {
                        client.get_user(int(target_land["owner_id"]))}.'

                message += f'\n{total_buildings_destroyed} buildings were burned.'

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
            target_land = lands.get(str(task["target_land_id"]), "")

            while defend_index < len(global_info["task_queue"]):
                action = global_info["task_queue"][defend_index]
                if action["target_land_id"] == task["target_land_id"] and action["task"] == "sallyout":
                    land = lands.get(str(action["location_id"]), "")

                    unit = await get_unit(land["siegeCamp"], action["item"], action["user_id"])

                    # Fail if that troop isn't in that land or if there aren't as many as specified
                    if unit == "" or unit["amount"] < action["amount"]:
                        unit = await get_unit(land["garrison"], action["item"], action["user_id"])
                        if unit == "" or unit["amount"] < action["amount"]:
                            await dm(action["user_id"], f'You don\'t have enough {action["item"]} from {land["name"]} to send on an attack at {target_land["name"]}.')
                            global_info["task_queue"].pop(
                                defend_index)  # Remove this task
                            continue

                    # Fail if the your land is already surrounded
                    if await is_surrounded(land) and action["location_id"] != action["target_land_id"]:
                        await dm(task["user_id"], f'You cannot move {action["item"]} out of {land["name"]} because it is fully surrounded.')
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

            total_defenders = await get_total_troops(defender_army)
            total_attackers = await get_total_troops(attacker_army)

            # Only resolve combat if there are defenders and attackers
            if total_defenders > 0 and total_attackers > 0:
                # Resolve the combat
                message = await resolve_battle(attacker_army, defender_army)
            else:
                message = f'There were not enough troops for a battle at {
                    target_land["name"]}.'

            # DM the results to all the combatants
            for user_id in user_ids:
                await dm(user_id, message)
        else:
            index += 1

    index = 0

    # Execute all move commands.
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
                    await dm(task["user_id"], f'You don\'t have enough {task["item"]} from {land["name"]} to send to the siege camp of {target_land["name"]}.')
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
                    await dm(task["user_id"], f'You can\'t move {task["item"]} into {client.get_user(int(target_land["owner_id"]))}\'s settlement {target_land["name"]} for one of the following reasons: they are not your liege, fellow vassal, or your vassal.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue

            # Fail if the your land is already surrounded
            if await is_surrounded(land):
                await dm(task["user_id"], f'You cannot move {task["item"]} out of {land["name"]} because it is fully surrounded.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Fail if the target land is already surrounded unless taking troops out of the siege camp
            if await is_surrounded(target_land) and army != land["siegeCamp"]:
                await dm(task["user_id"], f'You cannot move {task["item"]} into the garrison of {target_land["name"]} because it is fully surrounded.')
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

    # Execute all upgrade commands in the following order: Tier 4 upgrades → Tier 3 upgrades → Tier 2 upgrades → Hire upgrades
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
                            await dm(action["user_id"], f'You cannot upgrade {action["item"]} at {land["name"]} because that land doesn\'t belong to you.')
                            global_info["task_queue"].pop(
                                troop_index)  # Remove this task
                            continue

                        unit = await get_unit(land["garrison"], action["item"], action["user_id"])

                        # Fail if that troop isn't in that land or if there aren't as many as specified
                        if unit == "" or unit["amount"] < action["amount"]:
                            await dm(action["user_id"], f'You don\'t have enough {action["item"]} to upgrade {action["amount"]} of them.')
                            global_info["task_queue"].pop(
                                troop_index)  # Remove this task
                            continue

                        new_troop = await get_troop(troop["upgradesTo"])
                        cost = new_troop["cost"] * action["amount"]

                        # Fail if not enough money
                        if int(user["quackerinos"]) < cost:
                            await dm(action["user_id"], f'You don\'t have enough quackerinos to upgrade {action["amount"]} {action["item"]}s.')
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
                await dm(task["user_id"], f'You cannot hire {action["item"]} at {land["name"]} because that land doesn\'t belong to you.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Get the amount that the land quality decreases by
            # troop_counter = 0
            # land_quality_penalty = 0

            # while troop_counter < task["amount"] and global_info["qualityPenaltyProbabilityPerTroop"] > 0:
            #     if random.random() < global_info["qualityPenaltyProbabilityPerTroop"]:
            #         land_quality_penalty += 1

            #     if land_quality_penalty >= land["quality"]:
            #         task["amount"] = troop_counter
            #         break
            #     troop_counter += 1

            cost = troop["cost"] * task["amount"]

            # Fail if not enough money
            if int(user["quackerinos"]) < cost:
                await dm(task["user_id"], f'You don\'t have enough quackerinos to upgrade {action["amount"]} {action["item"]}s.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Remove the money
            user["quackerinos"] -= cost

            # Remove the land quality
            # land["quality"] -= land_quality_penalty

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

    # Execute all build commands
    while index < len(global_info["task_queue"]):
        task = global_info["task_queue"][index]

        if task["task"] == "build":
            user = user_info[str(task["user_id"])]
            land = lands.get(str(task["location_id"]), "")
            building = await get_building(task["item"])

            # Fail if the specified land doesn't belong to that player
            if task["location_id"] not in user["land_ids"]:
                await dm(task["user_id"], f'You cannot build {task["item"]} because {land["name"]} doesn\'t belong to you.')
                global_info["task_queue"].pop(index)  # Remove this task
                continue

            # Fail if the building has already been built on that land
            if task["item"] in land["buildings"]:
                await dm(task["user_id"], f'{task["item"]} has already been built at {land["name"]}.')
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
                    await dm(task["user_id"], f'{task["item"]} needs to be built at {land["name"]} by upgrading a lower tier one.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    continue

            # Fail if there is an upper tier building of this already
            upgradesTo = deepcopy(building["upgradesTo"])
            skip = False
            while upgradesTo != "":
                if upgradesTo in land["buildings"]:
                    await dm(task["user_id"], f'There is already an upper tier equivalent of {task["item"]} at {land["name"]}.')
                    global_info["task_queue"].pop(index)  # Remove this task
                    skip = True
                    break
                else:
                    next_building = await get_building(upgradesTo)
                    upgradesTo = deepcopy(next_building["upgradesTo"])
            if skip:
                continue

            # Only make the user pay at the beginning of the construction
            if task["time"] == building["constructionTime"]:
                cost = building["cost"]

                # Fail if not enough money
                if int(user["quackerinos"]) < cost:
                    await dm(task["user_id"], f'You don\'t have enough quackerinos to build {task["item"]} at {land["name"]}.')
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

    # Update the quality of all the lands
    for land_id, land in lands.items():
        if land_id == "default":
            continue

        maxQuality = lands["default"]["maxQuality"]

        for building_name in land["buildings"]:
            building = await get_building(building_name)
            maxQuality += building["maxQualityBonus"]

        land["maxQuality"] = maxQuality

    # Randomize the q-qq exchange rate
    global_info["qqExchangeRate"] = random.randint(int(
        global_info["qqExchangeRateRange"][0]), int(global_info["qqExchangeRateRange"][1]))

    # Add to the day counter and cycle the season accordingly
    global_info["day_counter"] += 1
    global_info["current_season"] = await get_season(global_info["day_counter"])

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./data/global_info.json", "w") as file:
        json.dump(global_info, file, indent=4)

    with open("./data/lands.json", "w") as file:
        json.dump(lands, file, indent=4)

    # Tell the specified channel about the update
    try:
        destination_channel = int(global_info["new_day_channel_id"])
        await client.get_channel(destination_channel).send(
            f'A new day has arrived and the ducks feel refreshed from their slumber. The current season is: {global_info["current_season"]}')
    except:
        print('Error trying to execute the new day.')


@client.event
async def on_ready():
    await client.tree.sync()
    print("Bot is connected to Discord")
    dailyReset.start()


@client.tree.command(name="quack", description="Get your quack in for today.")
async def quack(interaction: discord.Interaction):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/global_info.json", "r") as file:
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
            # elif user_id == 712336169270116403:
            #     message = f'{username} did not deserve to quack today.'
            else:
                message = f'{username} quacked loudly.'

            if user["quackStreak"] >= global_info["maxQuackStreakLength"]:
                user["quackStreak"] -= global_info["maxQuackStreakLength"]
                user["quacks"] += global_info["quackStreakReward"]
                message += f'\n{username} finished a streak and got an extra {
                    global_info["quackStreakReward"]} quacks.'
        else:
            message = f'{
                username} tried to quack but their throat is too sore today.'
    except:
        new_user = deepcopy(user_info["default"])
        user_info[user_id] = new_user
        message = f'{username} quacked for the first time!'

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(message)


@client.tree.command(name="pay", description="Give a player some quackerinos.")
async def pay(interaction: discord.Interaction, target_user_id: str, number: int):
    with open("./data/user_info.json", "r") as file:
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
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You transferred {number} quackerinos to {client.get_user(int(target_user_id))}. They now have {target["quackerinos"]} qq and you now have {user["quackerinos"]} qq.')


@client.tree.command(name="buyqq", description="Trade in some of your quacks for quackerinos.")
async def buy_qq(interaction: discord.Interaction, quacks: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/global_info.json", "r") as file:
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
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    message = f'You bought {result} quackerinos using {quacks} quacks. You now have {
        user["quackerinos"]} qq and {user["quacks"]-user["spentQuacks"]} unspent quacks.'

    await interaction.response.send_message(message)


@client.tree.command(name="qqrate", description="Check the current quacks-quackerino exchange rate.")
async def qq_rate(interaction: discord.Interaction):
    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    await interaction.response.send_message(f'Currently 1 quack can buy {global_info["qqExchangeRate"]} quackerinos.')


@client.tree.command(name="quackery", description="Check out who are the top quackers.")
async def quackery(interaction: discord.Interaction, number: int = 10):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    top_list = "Top Quackers"

    for x in range(number):
        user_id = await get_max_quacks(user_info)

        if user_id == 0:
            break

        top_list += f'\n{client.get_user(int(user_id))} ({user_id}) --- {
            user_info[str(user_id)]["quacks"]}'
        user_info.pop(str(user_id))

    await interaction.response.send_message(top_list)


# Return user id of the user with the most quacks
async def get_max_quacks(users):
    quacks = 0
    top_user_id = 0

    # Find the userId with the max quacks
    for userId, user in users.items():
        if userId == "default":
            continue

        if int(user["quacks"]) > quacks:
            quacks = int(user["quacks"])
            top_user_id = int(userId)

    return top_user_id


@client.tree.command(name="quackinfo", description="Check out the quack info of a user.")
async def quack_info(interaction: discord.Interaction, user_id: str = ""):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/global_info.json", "r") as file:
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

        message += f' has quacked {user["quacks"]
                                   } times and is on a {user["quackStreak"]} day streak. '

        next_rank = await get_next_quack_rank(user["quackRank"])

        if next_rank != "":
            quacks = int(user["quacks"])
            next_quacks = int(global_info["quackRank"][next_rank])

            message += f'They are {next_quacks -
                                   quacks} quacks away from the next rank of {next_rank}. '

        message += f'They have spent {user.get("spentQuacks", 0)} quacks and have {
            user.get("quackerinos", 0)} quackerinos. '

        if user["homeland_id"] > 0:
            # homeland = await get_land(user["homeland_id"])

            # if homeland["owner_id"] == user_id:
            #     message += f'This user is in control of their homeland.'
            # else:
            #     message += f'This user is not in control of their homeland.'
            if user["homeland_id"] in user["land_ids"]:
                message += f'This user is in control of their homeland. '
            else:
                message += f'This user is not in control of their homeland. '

        if user["safety_count"] > 0:
            message += f'This user has {user["safety_count"]
                                        } turns left of safety protection. '

        if user["liege_id"] != 0:
            message += f'\nLiege: {client.get_user(int(user["liege_id"]))} (ID:{
                user["liege_id"]})'

        if len(user["ally_ids"]) > 0:
            message += f'\nAllies: '
            for ally_id in user["ally_ids"]:
                message += f'{client.get_user(int(ally_id))}, '
            message = message.rstrip()
            message = message.rstrip(",")

        has_vassals = False

        if user["taxPerVassalLand"] > 0:
            message += f'\nTax per vassal land: {user["taxPerVassalLand"]}'

        for target_id, target in user_info.items():
            if target["liege_id"] == user_id:
                if not has_vassals:
                    has_vassals = True
                    message += f'\nVassals: '
                message += f'{client.get_user(int(target_id))}, '
        message = message.rstrip()
        message = message.rstrip(",")

        if len(user["vassal_waitlist_ids"]) > 0:
            message += f'\Vassal waitlist: '
            for target_id in user["vassal_waitlist_ids"]:
                message += f'{client.get_user(int(target_id))}, '
        message = message.rstrip()
        message = message.rstrip(",")

        for land_id in user["land_ids"]:
            land = await get_land(land_id)

            message += f'\n\n**{land["name"]
                                } (ID:{land_id}) - {land["species"]}**'
            message += f'\nQuality: {land["quality"]}/{land["maxQuality"]}'
            message += f'\nBuildings: {land["buildings"]}'
            message += f'\nGarrison: '
            for unit in land["garrison"]:
                message += f'\n• {unit["amount"]} {unit["troop_name"]
                                                   } ({client.get_user(int(unit["user_id"]))})'

            if land["siegeCamp"] != []:
                message += f'\nSiege camp: '
                for unit in land["siegeCamp"]:
                    message += f'\n• {unit["amount"]} {unit["troop_name"]
                                                       } ({client.get_user(int(unit["user_id"]))})'

    except:
        message = 'Error while fetching user information.'

    await interaction.response.send_message(message)


@client.tree.command(name="rawquackinfo", description="Check out the raw quack info of a user.")
async def raw_quack_info(interaction: discord.Interaction, user_id: str = ""):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/global_info.json", "r") as file:
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
        message = f'{user}'
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
    message += f'\nOwner: {client.get_user(int(land["owner_id"]))} (ID: {
        land["owner_id"]})'
    message += f'\nQuality: {land["quality"]}/{land["maxQuality"]}'
    message += f'\nBuildings: {land["buildings"]}'
    message += f'\nGarrison: '
    for unit in land["garrison"]:
        message += f'\n• {unit["amount"]} {unit["troop_name"]
                                           } ({client.get_user(int(unit["user_id"]))})'

    if land["siegeCamp"] != []:
        message += f'\nSiege camp: '
        for unit in land["siegeCamp"]:
            message += f'\n• {unit["amount"]} {unit["troop_name"]
                                               } ({client.get_user(int(unit["user_id"]))})'

    await interaction.response.send_message(message)


@client.tree.command(name="taskqueue", description="Check out the task queue.")
async def view_task_queue(interaction: discord.Interaction):
    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    message = f'__**Task Queue**__'

    for task in global_info["task_queue"]:
        land = await get_land(task["location_id"])
        message += f'\n{client.get_user(int(task["user_id"]))} @ {
            land["name"]} ({task["location_id"]})'

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
    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    quack_rank = ""

    for rank, requirement in global_info["quackRank"].items():
        if int(quacks) >= int(requirement):
            quack_rank = rank

    return quack_rank


async def get_next_quack_rank(quack_rank):
    with open("./data/global_info.json", "r") as file:
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
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/global_info.json", "r") as file:
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

    with open("./data/lands.json", "r") as file:
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
        with open("./data/user_info.json", "w") as file:
            json.dump(user_info, file, indent=4)

        # Save to database
        with open("./data/global_info.json", "w") as file:
            json.dump(global_info, file, indent=4)

        # Save to database
        with open("./data/lands.json", "w") as file:
            json.dump(lands, file, indent=4)
    except:
        message = 'There was an error trying to add the new land.'

    await interaction.response.send_message(message)


@client.tree.command(name="species", description="View all the enabled species.")
async def list_species(interaction: discord.Interaction):
    with open("./data/species.json", "r") as file:
        species_list = json.load(file)

    message = f'**List of Playable Species**'

    for species_name, species in species_list.items():
        if bool(species.get("enabled", species_list["default"].get("enabled"))):
            message += f'\n{species_name}: {
                species.get("description", species)}'

    await interaction.response.send_message(message)


@client.tree.command(name="buildings", description="View all the buildings that can be built.")
async def list_buildings(interaction: discord.Interaction):
    with open("./data/buildings.json", "r") as file:
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
async def list_troops(interaction: discord.Interaction, species_name: str):
    with open("./data/troops.json", "r") as file:
        troops = json.load(file)

    message = f'__**All Troops**__'

    for troop_name, troop in troops.items():
        if troop["species"] == species_name or troop["species"] == "":
            message += f'\n**{troop_name}:** '
            for key, value in troop.items():
                if value != "":
                    message += f'{key}: {value}; '

    await interaction.response.send_message(message)


@client.tree.command(name="build", description="Build a new building in one of your lands (takes one month).")
async def build(interaction: discord.Interaction, location_id: int, building_name: str):
    with open("./data/user_info.json", "r") as file:
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
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/lands.json", "r") as file:
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
        message = f'The {building_name} was demolished into a {
            building["demolishedTo"]} and you were refunded {refund} qq.'
    else:
        message = f'The {
            building_name} was destroyed and you were refunded {refund} qq.'

    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./data/lands.json", "w") as file:
        json.dump(lands, file, indent=4)

    await interaction.response.send_message(message)


@client.tree.command(name="hire", description="Hire some troops (takes one month).")
async def hire(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/lands.json", "r") as file:
        lands = json.load(file)

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

    # Fail if the land quality is 0
    if land["quality"] <= 0 and bool(troop["requiresSpeciesMatch"]):
        await interaction.response.send_message('You cannot hire troops from a land that has zero quality.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "hire", troop_name, location_id, amount)

    await interaction.response.send_message(f'You have started to hire {amount} {troop_name}s in {land["name"]}.')


@client.tree.command(name="upgrade", description="Upgrade some troops (takes one month).")
async def upgrade(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int):
    with open("./data/user_info.json", "r") as file:
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
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/lands.json", "r") as file:
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

    message = f'{amount} {troop_name}s were disbanded. {
        refund} qq were refunded to the user.'

    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./data/lands.json", "w") as file:
        json.dump(lands, file, indent=4)

    await interaction.response.send_message(message)


@client.tree.command(name="attack", description="Launch an assault on someone's land/castle (takes one month).")
async def attack(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Prevent this player from using this action if they still are in the safety period
    if user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action during your safety period.")
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

    target_user = user_info[str(target_land["owner_id"])]

    # Prevent this player from attacking someone who is in their safety period
    if target_user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action against someone who is still in their safety period.")
        return

    # Prevent this player from using this action if they still are in the safety period
    if user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action during your safety period.")
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

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canAttack", species["all-season"].get("canAttack"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue and alert the defender
    await add_to_queue(user_id, "attack", troop_name, location_id, amount, target_land=target_land_id)
    await dm(target_land["owner_id"], f'{client.get_user(int(user_id))} has sent {amount} {troop_name}s to attack {target_land["name"]}!')

    message = f'{amount} {troop_name}s were sent to attack {
        target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="defend", description="Defend someone's land/castle from an incoming assault (takes one month).")
async def defend(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Prevent this player from using this action if they still are in the safety period
    if user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action during your safety period.")
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

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canAttack", species["all-season"].get("canAttack"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "defend", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to defend {
        target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="siege", description="Initiate or join a siege on someone's land (takes one month).")
async def siege(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Prevent this player from using this action if they still are in the safety period
    if user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action during your safety period.")
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

    target_user = user_info[str(target_land["owner_id"])]

    # Prevent this player from attacking someone who is in their safety period
    if target_user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action against someone who is still in their safety period.")
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

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canMove", species["all-season"].get("canMove"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "siege", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to siege {
        target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="sallyout", description="Launch an assault on a siege camp (takes one month).")
async def sallyout(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Prevent this player from using this action if they still are in the safety period
    if user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action during your safety period.")
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

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canMove", species["all-season"].get("canMove"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "sallyout", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to attack the siege camp at {
        target_land["name"]}.'

    await interaction.response.send_message(message)


@client.tree.command(name="move", description="Move troops to one of your or an ally's garrisons (takes one month).")
async def move(interaction: discord.Interaction, location_id: int, troop_name: str, amount: int, target_land_id: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Prevent this player from using this action if they still are in the safety period
    if user["safety_count"] > 0:
        await interaction.response.send_message("You cannot use this action during your safety period.")
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

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    troop = await get_troop(troop_name)
    species = await get_species(troop["species"])

    # Fail if the troop can't move during this season
    if not bool(species[global_info["current_season"]].get("canMove", species["all-season"].get("canMove"))):
        await interaction.response.send_message(f'You cannot move {troop["species"]} troops out of {land["name"]} during the {global_info["current_season"]}.')
        return

    # Add the task to the queue
    await add_to_queue(user_id, "move", troop_name, location_id, amount, target_land=target_land_id)

    message = f'{amount} {troop_name}s were sent to {
        target_land["name"]}\'s garrison.'

    await interaction.response.send_message(message)


@client.tree.command(name="support", description="Lend your support to another player to improve one of their land's income by 10%.")
async def support(interaction: discord.Interaction, target_user_id: str):
    with open("./data/user_info.json", "r") as file:
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
            await interaction.response.send_message("You can't give support to yourself.")
            return
        elif target_user_id == "default":
            await interaction.response.send_message("You can't give support to the default user.")
            return
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Make sure this user has already had a homeland
    if user["homeland_id"] == -1:
        await interaction.response.send_message("You cannot use this command without a homeland.")
        return

    # Make sure this user has no lands
    if len(user["land_ids"]) > 0:
        await interaction.response.send_message("You cannot use this command if you already have lands.")
        return

    # Make sure the user hasn't supported anyone yet
    if user["supportee_id"] == 0:
        await interaction.response.send_message("You can only use this command once per day.")
        return

    target["support"] += 1
    user["supportee_id"] = target_user_id

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You have lent your support to {client.get_user(int(target_user_id))}.')


@client.tree.command(name="giveland", description="Give your occupied land to another player.")
async def give_land(interaction: discord.Interaction, location_id: int, target_user_id: str):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/lands.json", "r") as file:
        lands = json.load(file)

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
            await interaction.response.send_message("You can't give support to yourself.")
            return
        elif target_user_id == "default":
            await interaction.response.send_message("You can't give support to the default user.")
            return
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    land = lands.get(str(location_id), "")

    # Fail if the specified land doesn't exist
    if land == "":
        await interaction.response.send_message('Land not found.')
        return

    # Fail if the specified land doesn't belong to that player
    if location_id not in user["land_ids"]:
        await interaction.response.send_message('That land doesn\'t belong to you.')
        return

    # Fail if this is the user's homeland
    if location_id == user["homeland_id"]:
        await interaction.response.send_message('You cannot give your homeland away.')
        return

    # Prevent this player from giving the land to someone who is in their safety period
    if target["safety_count"] > 0:
        await interaction.response.send_message("You cannot give lands to a protected user.")
        return

    # Give the land to the target user
    user["land_ids"].remove(location_id)
    target["land_ids"].append(location_id)
    land["owner_id"] = int(target_user_id)

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./data/lands.json", "w") as file:
        json.dump(lands, file, indent=4)

    await interaction.response.send_message(f'You have given control of {land["name"]} to {client.get_user(int(target_user_id))}.')


@client.tree.command(name="addally", description="Add a user to your ally list.")
async def add_ally(interaction: discord.Interaction, target_user_id: str):
    with open("./data/user_info.json", "r") as file:
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
            await interaction.response.send_message("You can't ally yourself.")
            return
        elif target_user_id == "default":
            await interaction.response.send_message("You can't ally with the default user.")
            return
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Fail if target user already is in your ally list
    if target_user_id in user["ally_ids"]:
        await interaction.response.send_message(f'You have already allied with that person. Your ally list is: {user["ally_ids"]}')
        return

    user["ally_ids"].append(target_user_id)

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You have added {client.get_user(int(target_user_id))} to your allylist. Your ally list is now: {user["ally_ids"]}')


@client.tree.command(name="removeally", description="Remove a user to your ally list.")
async def remmove_ally(interaction: discord.Interaction, target_user_id: str):
    with open("./data/user_info.json", "r") as file:
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
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Fail if target user is not in your ally list
    if target_user_id not in user["ally_ids"]:
        await interaction.response.send_message(f'You aren\'t allied with that person. Your ally list is: {user["ally_ids"]}')
        return

    user["ally_ids"].remove(target_user_id)

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You have removed {client.get_user(int(target_user_id))} from your allylist. Your ally list is now: {user["ally_ids"]}')


@client.tree.command(name="declareallegiance", description="Declare your allegiance to a user.")
async def declare_allegiance(interaction: discord.Interaction, target_user_id: str):
    with open("./data/user_info.json", "r") as file:
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
            await interaction.response.send_message("You can't declare allegiance to yourself.")
            return
        elif target_user_id == "default":
            await interaction.response.send_message("You can't declare allegiance to  the default user.")
            return
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Fail if target user already is in your ally list
    if target_user_id == user["liege_id"]:
        await interaction.response.send_message(f'This user is already your liege.')
        return

    # Fail if user already has a liege
    if user["liege_id"] != 0:
        await interaction.response.send_message(f'You already have a liege. You must renounce your oath before declaring your allegiance to someone else.')
        return

    # Fail if user already on the target user's vassal waitlist
    if user_id in target["vassal_waitlist_ids"]:
        await interaction.response.send_message(f'You already are on this person\'s vassal waitlist. You must wait until they accept your allegiance.')
        return

    target["vassal_waitlist_ids"].append(user_id)

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You have added yourself to {client.get_user(int(target_user_id))}\'s vassal waitlist. You must wait until they accept your allegiance.')


@client.tree.command(name="acceptallegiance", description="Accept an oath of allegiance from a user.")
async def accept_allegiance(interaction: discord.Interaction, target_user_id: str):
    with open("./data/user_info.json", "r") as file:
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
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Fail if target user has already been accepted as a vassal
    if user_id == target["liege_id"]:
        user["vassal_waitlist_ids"].remove(target_user_id)

        # Save to database
        with open("./data/user_info.json", "w") as file:
            json.dump(user_info, file, indent=4)

        await interaction.response.send_message(f'This user is already your vassal.')
        return

    # Fail if target user already has a liege
    if target["liege_id"] != 0:
        user["vassal_waitlist_ids"].remove(target_user_id)

        # Save to database
        with open("./data/user_info.json", "w") as file:
            json.dump(user_info, file, indent=4)

        await interaction.response.send_message(f'This user already has a liege. They must renounce your oath before declaring their allegiance to someone else.')
        return

    user["vassal_waitlist_ids"].remove(target_user_id)
    target["liege_id"] = user_id

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You have accepted {client.get_user(int(target_user_id))}\'s oath of allegiance.')


@client.tree.command(name="releasevassal", description="Release one of your vassals from their oath of allegiance.")
async def release_vassal(interaction: discord.Interaction, target_user_id: str):
    with open("./data/user_info.json", "r") as file:
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
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Fail if target user does not have this user as their liege
    if user_id != target["liege_id"]:
        await interaction.response.send_message("Target user is not your vassal.")
        return

    target["liege_id"] = 0

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You have released {client.get_user(int(target_user_id))} from their oath of allegiance.')


@client.tree.command(name="renounceallegiance", description="Renounce your allegiance to your liege. THERE WILL BE CONSEQUENCES.")
async def renounce_allegiance(interaction: discord.Interaction):
    with open("./data/user_info.json", "r") as file:
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
        target_user_id = user["liege_id"]
        target = user_info[str(target_user_id)]
    except:
        await interaction.response.send_message("Target has not quacked yet.")
        return

    # Fail if this user does not have a liege
    if user["liege_id"] == 0:
        await interaction.response.send_message("You don't have a liege.")
        return

    with open("./data/lands.json", "r") as file:
        lands = json.load(file)

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    # Fail if this user doesn't have the required money to renounce allegiance
    if user["quackerinos"] < global_info["qq_requirement_to_renounce"]:
        await interaction.response.send_message(f'You don\'t have the required funds ({global_info["qq_requirement_to_renounce"]}) to renounce allegiance.')
        return

    # Disband all deserting troops
    for land_id, land in lands.items():
        if land_id == "default":
            continue

        # Check the garrison for deserters
        for unit in land["garrison"]:
            user = user_info[str(unit["user_id"])]
            troop = await get_troop(unit["troop_name"])
            species = await get_species(troop["species"])

            percent_desert = species[global_info["current_season"]
                                     ].get("percentDesertsOnOathbreaker", species["all-season"]["percentDesertsOnOathbreaker"])
            total_amount = unit["amount"]
            num_desert = 0
            if percent_desert > 0:
                for x in range(unit["amount"]):
                    if random.random() > percent_desert:
                        num_desert += 1

                unit["amount"] -= num_desert

                # DM user that units have been disbanded
                await dm(unit["user_id"], f'{num_desert}/{total_amount} of {unit["troop_name"]} have been disbanded at {land["name"]} because of your oath breaking.')

        # Disband empty units from the garrison
        index = 0
        while index < len(land["garrison"]):
            if land["garrison"][index]["amount"] <= 0:
                land["garrison"].pop(index)
            else:
                index += 1

        # Check the siegecamp for deserters
        for unit in land["siegeCamp"]:
            user = user_info[str(unit["user_id"])]
            troop = await get_troop(unit["troop_name"])
            species = await get_species(troop["species"])

            percent_desert = species[global_info["current_season"]
                                     ].get("percentDesertsOnOathbreaker", species["all-season"]["percentDesertsOnOathbreaker"])
            total_amount = unit["amount"]
            num_desert = 0
            if percent_desert > 0:
                for x in range(unit["amount"]):
                    if random.random() > percent_desert:
                        num_desert += 1

                unit["amount"] -= num_desert

                # DM user that units have been disbanded
                print(
                    f'{num_desert}/{total_amount} of {unit["troop_name"]} have been disbanded at {land["name"]} because of your oath breaking.')
                await dm(unit["user_id"], f'{num_desert}/{unit["amount"]} of {unit["troop_name"]} have been disbanded at {land["name"]} because of your oath breaking.')

        # Disband empty units from the siegeCamp
        index = 0
        while index < len(land["siegeCamp"]):
            if land["siegeCamp"][index]["amount"] <= 0:
                land["siegeCamp"].pop(index)
            else:
                index += 1

    user["liege_id"] = 0
    user["quackerinos"] -= int(user["quackerinos"] *
                               global_info["percentPlunderedOnOathbreaker"])

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    with open("./data/lands.json", "w") as file:
        json.dump(lands, file, indent=4)

    await interaction.response.send_message(f'You have renounced your oath to {client.get_user(int(target_user_id))}. Half of all your troops have deserted and looted a quarter of your wealth.')


@client.tree.command(name="setvassaltax", description="Set a flat tax rate per land for all vassals.")
async def set_vassal_tax(interaction: discord.Interaction, amount: int):
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    with open("./data/global_info.json", "r") as file:
        global_info = json.load(file)

    user_id = interaction.user.id

    # Make sure this player exists in user_info
    try:
        user = user_info[str(user_id)]
    except:
        await interaction.response.send_message("You have not quacked yet.")
        return

    # Prevent the number from being lower than 0
    if amount < 0:
        await interaction.response.send_message("You cannot set a negative tax rate.")
        return

    # Prevent the number from being too high
    if amount > global_info["maxtaxPerVassalLand"]:
        await interaction.response.send_message(f'You cannot set a tax rate higher than the maximum ({global_info["maxtaxPerVassalLand"]}).')
        return

    user["taxPerVassalLand"] = amount

    # Save to database
    with open("./data/user_info.json", "w") as file:
        json.dump(user_info, file, indent=4)

    await interaction.response.send_message(f'You have set a tax rate of {amount} per land for all your vassals.')


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
    with open("./data/user_info.json", "r") as file:
        user_info = json.load(file)

    user = user_info.get(str(user_id), "")
    allies = user["ally_ids"]

    for ally_id, ally in user_info.items():
        if user["liege_id"] == ally["liege_id"] or user["liege_id"] == ally_id or ally["liege_id"] == user_id:
            allies.append(ally_id)

    return allies


async def get_troop(troop_name):
    with open("./data/troops.json", "r") as file:
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
    with open("./data/buildings.json", "r") as file:
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
    with open("./data/lands.json", "r") as file:
        lands = json.load(file)

    land = lands.get(str(land_id), "")

    return land


async def get_land_by_name(land_name):
    with open("./data/lands.json", "r") as file:
        lands = json.load(file)

    for land in lands:
        if land["name"] == land_name:
            return land

    return ""


async def get_land_id(query_land):
    with open("./data/lands.json", "r") as file:
        lands = json.load(file)

    for land_id, land in lands.items():
        if land == query_land:
            return land_id

    return -1


async def get_species(species_name):
    with open("./data/species.json", "r") as file:
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
    with open("./data/global_info.json", "r") as file:
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
    with open("./data/global_info.json", "r") as file:
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
        message += f'\n{company["amount"]} {company["unit"]["troop_name"]
                                            } ({client.get_user(int(company["unit"]["user_id"]))})'
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
    with open("./data/global_info.json", "r") as file:
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

    with open("./data/global_info.json", "w") as file:
        json.dump(global_info, file, indent=4)


# async def main():
#     async with client:
#         # Reading token from environment variable
#         discord_token = os.getenv('DISCORD_BOT_TOKEN')
#         if not discord_token:
#             raise ValueError(
#                 "No token provided. Set the DISCORD_BOT_TOKEN environment variable.")
#         await client.start(discord_token)
async def main():
    async with client:
        with open("config.json", "r") as file:
            config = json.load(file)

        await client.start(config['token'])

asyncio.run(main())
