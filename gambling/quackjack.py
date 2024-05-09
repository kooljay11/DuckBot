from __future__ import annotations

import asyncio
import collections
import dataclasses
import enum
import json
import pathlib
import random
import typing
from textwrap import dedent

import discord
from discord import Interaction
from discord.ext import commands
from discord.utils import utcnow

USER_INFO_PATH = pathlib.Path(__file__).absolute().parent.parent / "data" / "user_info.json"

T_RANKS = typing.Literal["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
T_SUITS = typing.Literal["♠️", "♦️", "♣️", "♥️"]
_RANKS: typing.Final[tuple[T_RANKS, ...]] = typing.get_args(T_RANKS)
_SUITS: typing.Final[tuple[_SUITS, ...]] = typing.get_args(T_SUITS)

MAX_BET: typing.Final[int] = 500
MIN_BET: typing.Final[int] = 2


@dataclasses.dataclass(slots=True, frozen=True, kw_only=True)
class Card:
    """
    This class represents a single card (rank + suit).

    :param rank: The rank of the card.
    :param suit: The suit of the card.
    """

    rank: T_RANKS
    suit: T_SUITS

    def __str__(self) -> str:
        """
        Formats the card to string as <suit><rank>.

        :return: The string representation of the card.
        """
        return f"{self.suit}{self.rank}"

    @property
    def value(self) -> int:
        """
        Gets the card's face value.
        :return: The face value of the card, returns 1 for aces.
        """
        if self.rank in {"2", "3", "4", "5", "6", "7", "8", "9"}:
            return int(self.rank)
        elif self.rank in {"10", "J", "Q", "K"}:
            return 10
        return 1  # For aces


class Shoe:
    """
    This class contains operations pertaining to Quackjack shoe.
    """

    _CARD_DECK: typing.Final[set[Card]] = {Card(rank=rank, suit=suit) for rank in _RANKS for suit in _SUITS}

    def __init__(self, *, num_decks: int = 6, penetration: float = 0.75):
        """
        Initializes the shoe with the number of decks.

        The penetration value can be set to specify when the cards should be reshuffled to counter card counting.
        When set to 1, all the cards will be dealt before a reshuffle.

        :param num_decks: The number of decks the shoe can hold.
        :param penetration: The ratio of cards (0.0 - 1.0) used in game before a reshuffle.
        """
        self._num_decks: int = num_decks
        self.cards_dealt: int = 0
        total_cards: int = num_decks * len(self._CARD_DECK)
        self.penetration_card: int = int(total_cards * penetration)
        self.deck: collections.deque[Card] = collections.deque()
        self.reset()  # Populates the deck

    def reset(self) -> None:
        """
        Resets the shoe a randomly shuffled N-decks shoe.
        """
        _deck = [card for card in self._CARD_DECK for _ in range(self._num_decks)]
        random.shuffle(_deck)
        self.deck = collections.deque(_deck)
        self.cards_dealt = 0

    def draw_card(self) -> Card:
        """
        Draws the next card from the shoe.

        If there's no more cards in the shoe (or stopped by penetration), the shoe will first be reshuffled.

        :return: The top card of the shoe.
        """
        if self.cards_dealt >= self.penetration_card:
            self.reset()
        self.cards_dealt += 1
        return self.deck.popleft()  # The shoe should never be out of cards


class HandValue(int):
    """
    An implementation of card value to take account that values > 21 should be invalidated in comparisons.
    """

    def __gt__(self, other: HandValue | int) -> bool:
        """
        Compare the card's value to another card's.

        :param other: Another card's value.
        :return: If the value is greater than the other value.
        """
        if isinstance(other, HandValue):  # If comparing to another value
            if int(other) > 21 and int(self) > 21:  # If both > 21, then they are equal
                return False
            if int(self) > 21:  # If self is busted and other is not
                return False
            if int(other) > 21:
                return True  # If other is busted and self is not
        return super().__gt__(int(other))

    def __lt__(self, other: HandValue | int) -> bool:
        """
        Compare the card's value to another card's.

        :param other: Another card's value.
        :return: If the value is lesser than the other value.
        """
        if isinstance(other, HandValue):  # If comparing to another value
            if int(other) > 21 and int(self) > 21:  # If both > 21, then they are equal
                return False
            if int(self) > 21:  # If self is busted and other is not
                return True
            if int(other) > 21:
                return False  # If other is busted and self is not
        return super().__lt__(int(other))

    # The following two methods are necessary to override the default int behaviours.
    def __ge__(self, other: HandValue | int) -> bool:
        """
        Checks >= while taking account of >= 21 rule.
        :param other: Another card's value.
        :return: If the value is greater or equals to the other value.
        """
        return self.__gt__(other) or self.__eq__(other)

    def __le__(self, other: HandValue | int) -> bool:
        """
        Checks <= while taking account of >= 21 rule.
        :param other: Another card's value.
        :return: If the value is lesser or equals to the other value.
        """
        return self.__lt__(other) or self.__eq__(other)


class Hand:
    """
    This class represents a Quackjack hand.
    """

    def __init__(self, shoe: Shoe, *, bet: int | None, cards: list[Card] | None = None):
        """
        Creates a Quackjack hand.

        :param shoe: The current active shoe.
        :param bet: The bet for this hand, set to None if it's the dealer's hand.
        :param cards: Pre-existing cards that are part of this hand.
        """
        self.shoe: Shoe = shoe
        self.bet: int | None = bet
        self.cards: list[Card] = [] if cards is None else cards

    def draw_card(self) -> Card:
        """
        Draw a card from the shoe.

        :return: The Card drew.
        """
        card = self.shoe.draw_card()
        self.cards += [card]
        return card

    def split(self) -> Hand:
        """
        Split the current hand into two.

        :return: The newly split hand.
        """
        new_hand = Hand(self.shoe, bet=self.bet, cards=[self.cards.pop(1)])
        return new_hand

    @property
    def is_busted(self) -> bool:
        """
        Check if this hand is busted.

        :return: True if the hand is busted, False otherwise.
        """
        return self.value > 21

    @property
    def value(self) -> HandValue:
        """
        Get total cards' value.

        :return: The cards' value that's closest to 21.
        """
        value: int = 0  # Initially with no cards, the value is 0
        num_aces: int = 0

        for card in self.cards:
            if card.rank == "A":  # Add 11 (if too high, we will reduce later)
                value += 11
                num_aces += 1
            else:
                value += card.value

        while value > 21 and (num_aces := num_aces - 1) >= 0:
            value -= 10

        # Returns the maximum possible value under 21 if possible.
        return HandValue(value)

    def __getitem__(self, item: int) -> Card:
        """
        Get a Card by its index position.

        :param item: The Card's index.
        :return: The Card at the specified index.
        :raise IndexError: When the index is out of bounds.
        """
        return self.cards[item]

    def __iter__(self) -> typing.Iterator[Card]:
        """
        Get an iterator of cards.

        :return: An iterator of the cards in the Hand.
        """
        return iter(self.cards)

    def __len__(self) -> int:
        """
        Get the number of cards in the Hand.

        :return: The size of the Hand.
        """
        return len(self.cards)

    def __str__(self) -> str:
        """
        Get a string representation of the Hand.

        :return: A string formatted Hand.
        """
        return " ".join(map(str, self.cards))


class GameState(enum.Enum):
    """
    The state of the Quackjack game.
    """

    pre_game: int = enum.auto()
    in_game: int = enum.auto()


class QuackjackError(Exception):
    """
    An exception class used when something went wrong with Quackjack.
    """

    pass


class PlayAgainBetModal(discord.ui.Modal, title="Quackjack"):
    """
    Modal to prompt the user to input a bet to play again.
    """

    bet = discord.ui.TextInput(
        label="Bet",
        placeholder="How much do you want to bet?",
        min_length=len(str(MIN_BET)),
        max_length=len(str(MAX_BET)),
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """
        Callback function for when the user submits the bet form.

        :param interaction: The current discord.py interaction.
        """

        # If the bet is not a valid number.
        if not self.bet.value.isdigit():
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                "It doesn't look like that's a valid bet! "
                f"Play again using </{Quackjack.play.qualified_name}:{Quackjack.quackjack.id}> command.",
                ephemeral=True,
            )
            return

        bet = int(self.bet.value)

        # If the bet is out of bounds.
        if bet > MAX_BET or bet < MIN_BET:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                f"Bets must be between {MIN_BET} and {MAX_BET}. Play again using "
                f"</{Quackjack.play.qualified_name}:{Quackjack.quackjack.id}>.",
                ephemeral=True,
            )
            return

        with USER_INFO_PATH.open("r") as file:
            all_users_info: dict = json.load(file)

        user_balance = int(all_users_info[str(interaction.user.id)]["quackerinos"])

        # Check if user can afford the bet.
        if bet > user_balance:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(f"You don't have enough quackerinos to bet {bet}.", ephemeral=True)
            return

        if interaction.guild is not None:
            guild_id = interaction.guild.id
        else:  # If this command is invoked in DM, use the user ID instead.
            guild_id = interaction.user.id

        game = QuackjackGame.get_game(user_id=interaction.user.id, guild_id=guild_id)
        if game._state != GameState.pre_game:  # Check if the game is in the idle state (pre-game)
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                "You are currently still in a round. Finish it first!", ephemeral=True
            )
            return

        await game.start_round(interaction, bet)
        await interaction.message.edit(view=None)  # Remove the Play Again button


class PlayAgainView(discord.ui.View):
    """
    A view to prompt user to play again.
    """

    def __init__(self, game: QuackjackGame):
        """
        Create an instance of the view.
        """
        super().__init__(timeout=QuackjackGame.TIMEOUT_SECS)
        self.game: QuackjackGame = game

    async def interaction_check(self, interaction: Interaction) -> bool:
        """
        Check if the interaction is performed by the same user in the same guild.

        :param interaction: The discord.py interaction.
        :return: True or False depending on the check.
        """
        if interaction.guild is not None:
            guild_id = interaction.guild.id
        else:  # If this command is invoked in DM, use the user ID instead.
            guild_id = interaction.user.id

        return self.game.user_id == interaction.user.id and self.game.guild_id == guild_id

    # noinspection PyUnusedLocal
    @discord.ui.button(label="Play Again?", style=discord.ButtonStyle.green)
    async def play_again(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        """
        Callback function for when the play again button is clicked.

        :param interaction: The current discord.py interaction.
        :param button: The button clicked.
        """
        # noinspection PyUnresolvedReferences
        await interaction.response.send_modal(PlayAgainBetModal())  # Prompt the user to enter a bet


class UserActionView(discord.ui.View):
    """
    A view to display actions that the user can perform during the Quackjack game.
    """

    def __init__(self, game: QuackjackGame):
        """
        Create an instance of the view, add components as needed.

        :param game: The ongoing Quackjack game.
        """
        super().__init__(timeout=QuackjackGame.TIMEOUT_SECS)
        self.game: QuackjackGame = game

    async def interaction_check(self, interaction: Interaction) -> bool:
        """
        Check if the interaction is performed by the same user in the same guild.

        :param interaction: The discord.py interaction.
        :return: True or False depending on the check.
        """
        if interaction.guild is not None:
            guild_id = interaction.guild.id
        else:  # If this command is invoked in DM, use the user ID instead.
            guild_id = interaction.user.id

        return self.game.user_id == interaction.user.id and self.game.guild_id == guild_id

    async def on_timeout(self) -> None:
        """
        When the view times out, terminate the game.
        """
        self.game.terminate()


class QuackjackGame:
    """
    A multi-round game of Quackjack with a user in a guild.
    """

    # A mapping of (user_id, guild_id) -> QuackjackGame
    _on_going_games: dict[tuple[int, int], QuackjackGame] = {}
    # The number of seconds after the last user action to terminate the game.
    TIMEOUT_SECS: typing.Final[int] = 3 * 60  # 3 minutes timeout

    _winning_phrases: typing.Final[tuple[str]] = (
        "Well played!",
        "Nice job! You've got it!",
        "Well done!",
        "Nicely played!",
        "You're on a roll! Keep it up!",
        "You're on fire! Ready for another round?",
        "Impressive! Up for a rematch?",
        "Excellent play! How about another hand?",
        "Fantastic job! Want to keep the streak going?",
        "Ready for another hand?",
        "Want to keep playing?",
    )

    _losing_phrases: typing.Final[tuple[str]] = (
        "Tough luck, but there's always the next round.",
        "Unlucky break, but keep your spirits high.",
        "It slipped away this time, but stay focused.",
        "A close one, but no worries, let's play again.",
        "Better luck next time!",
        "Don't worry, there's always another round.",
        "Tough break, but keep at it!",
        "It happens, better luck on the next hand.",
        "Chin up, there's still plenty of game to go!",
        "Close call. Want to try again?",
        "Just missed it this time, but next round's yours.",
        "A tough loss, but there's more game to be had.",
        "Ready for another hand?",
        "Want to keep playing?",
    )

    _neutral_phrases: typing.Final[tuple[str]] = (
        "Well played, ready for another round?",
        "Thanks for the game, want to go again?",
        "Great game, shall we shuffle up for another?",
        "Good hand, up for another go?",
        "Enjoyed that, want to keep playing?",
        "Nice round, how about another?",
        "Well matched, care for another round?",
        "Solid game, up for another deal?",
        "Well done, fancy another hand?",
        "Good play, ready for the next round?",
        "Good game all around, ready to play again?",
        "Well played, shall we shuffle up for another deal?",
        "Ready for another hand?",
        "Want to keep playing?",
    )

    def __init__(self, *, user_id: int, guild_id: int):
        """
        Create a new multi-round Quackjack game, will override existing games.

        :param user_id: The ID of the user.
        :param guild_id: The ID of the guild, or the user ID if not in guild.
        """
        self.user_id = user_id
        self.guild_id = guild_id
        self.expires_at: float = 0
        self._on_going_games[(user_id, guild_id)] = self
        self._state: GameState = GameState.pre_game
        self.shoe: Shoe = Shoe()
        self.dealer_hand: Hand | None = None
        self.player_hands: list[Hand] = []  # using [Hand,...] since the player can split
        self.active_player_hand_idx: int = 0  # The current playing hand of the player
        self.main_message: discord.Message | None = None  # The main interaction message
        self.last_action_text: str | None = None  # The text of the last user-performed action
        self.can_double_down: bool = True  # If the user is still allowed to double down
        self.refresh_expiry()  # Sets the initial expiry time

    @classmethod
    def get_game(cls, *, user_id: int, guild_id: int) -> QuackjackGame:
        """
        Get or create a Quackjack game for the user of the guild.

        :param user_id: The ID of the user.
        :param guild_id: The ID of the guild.
        :return: The current / new Quackjack game for the user.
        """
        game = cls._on_going_games.get((user_id, guild_id))
        if game is None:
            # If there's no current ongoing game for this user in this guild, start a new game.
            return QuackjackGame(user_id=user_id, guild_id=guild_id)
        if game.expires_at < utcnow().timestamp():
            game.terminate()
            # If the game has already expired, end the current game and start a new game.
            return QuackjackGame(user_id=user_id, guild_id=guild_id)
        return game

    def refresh_expiry(self) -> None:
        """
        Refreshes the expiry time of this game to now + timeout.
        """
        self.expires_at = utcnow().timestamp() + self.TIMEOUT_SECS

    def terminate(self) -> None:
        """
        Mark the game as terminated and remove from the ongoing games cache.
        """
        self.expires_at = 0
        self._on_going_games.pop((self.user_id, self.guild_id), None)

    def modify_quackerinos(self, amount: int) -> int:
        """
        Modify the amount of quackerinos in the user's balance.

        :param amount: The relative amount to modify. Use a negative amount to subtract.
        :return: The new balance of the user.
        """
        with USER_INFO_PATH.open("r") as file:
            all_users_info: dict = json.load(file)
        if amount != 0:  # If there's actually a change
            all_users_info[str(self.user_id)]["quackerinos"] += amount
            with USER_INFO_PATH.open("w") as file:
                json.dump(all_users_info, file, indent=4)
        return all_users_info[str(self.user_id)]["quackerinos"]

    def get_game_board(self, dealer_hidden: bool, *, show_hand_conclusion: bool = False) -> str:
        """
        Get the current game board formatted as a discord code block.

        :param dealer_hidden: If the second dealer card is hidden.
        :param show_hand_conclusion: Should win/lose/tie for the player hand be shown.
        :return: The formatted game board text.
        """
        if dealer_hidden:  # Dealer has only two cards, second is hidden
            dealer_cards_text = f"{self.dealer_hand[0]}  ?"
        else:
            dealer_cards_text = str(self.dealer_hand)
            if show_hand_conclusion and self.dealer_hand.is_busted:
                dealer_cards_text += " [2;30m(Busted)[0m"

        dealer_value = self.dealer_hand.value
        extra_dealer_padding: int = 0  # Extra space padding for the dealer's text

        def get_extra_info(hand: Hand) -> str:
            """
            Get the status text of the hand.
            """
            nonlocal dealer_value
            if hand.is_busted:
                _extra_info = "Busted"
            else:
                _value = hand.value
                if show_hand_conclusion:
                    if _value > dealer_value:
                        _extra_info = "Win"
                    elif _value < dealer_value:
                        _extra_info = "Lose"
                    else:
                        _extra_info = "Tie"
                else:
                    _extra_info = "Stay"

            return f" [2;30m({_extra_info})[0m"

        if len(self.player_hands) == 1:
            if self.active_player_hand_idx == 1:  # The player chose to stay or has busted
                extra_info: str = get_extra_info(self.player_hands[0])
            else:
                extra_info = ""
            player_cards_text = str(self.player_hands[0]) + extra_info
        else:
            # Format into "[Hand #1] C1 C2 (Stayed), [Hand #2] C3 C4 C5, ..."
            player_cards_texts = []
            for hand_idx, player_hand in enumerate(self.player_hands):
                if hand_idx < self.active_player_hand_idx:  # Already actioned on
                    extra_info = get_extra_info(player_hand)
                elif hand_idx == self.active_player_hand_idx:
                    extra_info = f" [2;30m(Current)[0m"
                else:
                    extra_info = ""
                extra_dealer_padding = len(f"[Hand #{hand_idx + 1}] ")
                player_cards_texts += [f"[2;33m[Hand #{hand_idx + 1}][0m {player_hand}{extra_info}"]

            player_cards_text = ", ".join(player_cards_texts)  # Join multiple hands with ","

        total_bet = sum(hand.bet for hand in self.player_hands)
        return (
            dedent(
                f"""
                    Playing Quackjack with <@{self.user_id}> 
                    ```ansi
                    [1;2m[1;35mTotal Bet: {total_bet} {self._format_plural("quackerino", total_bet)}[0m
                    [1;2m[1;32mDealer's cards:[0m  {' ' * extra_dealer_padding}{dealer_cards_text}
                    [1;2m[1;34m    Your cards:[0m  {player_cards_text}```
            """
            ).rstrip()
            + (f"\n{self.last_action_text}" if self.last_action_text is not None else "")
        )

    def get_ending_message(self, amount_diff: int, msg: str) -> str:
        """
        Get the ending message of the game based on cards played.

        :param amount_diff: The earning / loss of the player.
        :param msg: The message to show in the ending.
        :return: A string ending message.
        """
        # Add a random ending phrase depending on win/lose/tie.
        if amount_diff > 0:
            random_ending_phrase = random.choice(self._winning_phrases)
        elif amount_diff < 0:
            random_ending_phrase = random.choice(self._losing_phrases)
        else:
            random_ending_phrase = random.choice(self._neutral_phrases)

        balance = self.modify_quackerinos(0)  # Get the balance by modifying 0
        extra_newline = "\n" if self.last_action_text else ""  # If there's an action text, add an extra newline here
        return (
            self.get_game_board(False, show_hand_conclusion=True)
            + f"\n{extra_newline}{msg} {random_ending_phrase} ({'+' if amount_diff >= 0 else ''}{amount_diff} qq)\n"
            f"You now have {balance} {self._format_plural('quackerino', balance)}."
        )

    async def start_round(self, ctx: commands.Context | discord.Interaction, initial_bet: int) -> None:
        """
        Start a new Quackjack round.

        :param ctx: The discord.py context or interaction of the invoked command.
        :param initial_bet: The amount of initial bet.
        :raise QuackjackError: Trying to start a round when the previous one is still ongoing.
        """
        if self._state != GameState.pre_game:
            raise QuackjackError("Unable to start a round as the previous round hasn't finished yet.")

        self._state = GameState.in_game
        self.refresh_expiry()

        # Reset states.
        self.active_player_hand_idx = 0
        self.main_message = None
        self.last_action_text = None
        self.can_double_down = True

        # First, take away the bet from the user's balance.
        self.modify_quackerinos(-initial_bet)

        # Create the first player hand and dealer's hand.
        self.player_hands += [Hand(self.shoe, bet=initial_bet)]
        self.dealer_hand = Hand(self.shoe, bet=None)

        # Alternatively deal two cards to the player and the dealer.
        self.player_hands[0].draw_card()
        self.dealer_hand.draw_card()
        self.player_hands[0].draw_card()
        self.dealer_hand.draw_card()

        game_board = self.get_game_board(True)
        if isinstance(ctx, discord.Interaction):
            # noinspection PyUnresolvedReferences
            if ctx.response.is_done():
                self.main_message = await ctx.followup.send(game_board, wait=True)
            else:
                # noinspection PyUnresolvedReferences
                await ctx.response.send_message(content=game_board)
                self.main_message = await ctx.original_response()
        else:
            self.main_message = await ctx.reply(game_board)

        player_value = self.player_hands[0].value
        dealer_value = self.dealer_hand.value

        if player_value == 21 and dealer_value == 21:  # Both got 21 (a draw)
            await asyncio.sleep(1)  # Wait 1 second to let the user process the message.
            self.active_player_hand_idx = 1  # Increment the active player hand since the game is over
            self.modify_quackerinos(initial_bet)  # Add back the user's quackerinos
            final_message: str = "You and the dealer both got a Quackjack!"
            ending_message: str = self.get_ending_message(0, final_message)
            await self.main_message.edit(content=ending_message)
            await self.end_round()
            return

        if player_value == 21:
            await asyncio.sleep(1)  # Wait 1 second to let the user process the message.
            self.active_player_hand_idx = 1  # Increment the active player hand since the game is over
            earnings = int(initial_bet * 1.5)  # Natural 21 gets 2:1 winnings
            self.modify_quackerinos(initial_bet + earnings)  # Add back the user's quackerinos and winnings
            final_message = "You got a Quackjack!"
            ending_message = self.get_ending_message(earnings, final_message)
            await self.main_message.edit(content=ending_message)
            await self.end_round()
            return

        if dealer_value == 21:
            await asyncio.sleep(1)  # Wait 1 second to let the user process the message.
            self.active_player_hand_idx = 1  # Increment the active player hand since the game is over
            final_message = "The dealer got a Quackjack!"
            ending_message = self.get_ending_message(-initial_bet, final_message)
            await self.main_message.edit(content=ending_message)
            await self.end_round()
            return

        await self.ask_for_user_action()  # Starts the main game

    async def end_round(self) -> None:
        """
        Ask to play again and perform some cleanup actions to end the round.
        """
        self._state = GameState.pre_game
        await self.main_message.edit(view=PlayAgainView(self))
        self.active_player_hand_idx = 0
        self.main_message = None
        self.last_action_text = None
        self.can_double_down = True
        self.dealer_hand = None
        self.player_hands.clear()
        self.refresh_expiry()

    async def ask_for_user_action(self) -> None:
        """
        Prompt the player to choose an available game action.
        """

        if self.expires_at < utcnow().timestamp():  # If the game already timed out
            self.terminate()
            return

        self.refresh_expiry()
        view = UserActionView(self)

        async def hit_callback(interaction: discord.Interaction) -> None:
            """
            Callback function for the discord.ui.Button view when the player choose to hit.

            :param interaction: The discord.py interaction.
            """
            view.stop()
            for button in view.children:
                if isinstance(button, discord.ui.Button):
                    button.disabled = True

            if len(self.player_hands) == 1:
                self.last_action_text = "You choose to hit."
            else:
                self.last_action_text = f"You choose to hit hand #{self.active_player_hand_idx + 1}."

            await self.main_message.edit(content=self.get_game_board(True), view=view)
            await asyncio.sleep(1)  # Add slight delay
            await self.hit(interaction)

        # Add the hit button.
        hit_button = discord.ui.Button(label="Hit", style=discord.ButtonStyle.green)
        hit_button.callback = hit_callback
        view.add_item(hit_button)

        async def stay_callback(interaction: discord.Interaction) -> None:
            """
            Callback function for the discord.ui.Button view when the player choose to stay.

            :param interaction: The discord.py interaction.
            """
            view.stop()
            for button in view.children:
                if isinstance(button, discord.ui.Button):
                    button.disabled = True

            if len(self.player_hands) == 1:
                self.last_action_text = "You choose to stay."
            else:
                self.last_action_text = f"You choose to stay hand #{self.active_player_hand_idx + 1}."

            await self.main_message.edit(content=self.get_game_board(True), view=view)
            await asyncio.sleep(1)  # Add slight delay
            await self.stay(interaction)

        # Add the stay button.
        stay_button = discord.ui.Button(label="Stay", style=discord.ButtonStyle.red)
        stay_button.callback = stay_callback
        view.add_item(stay_button)

        if self.can_double_down:
            # You're only allowed to double down at the start of the game.

            async def doubling_down_callback(interaction: discord.Interaction) -> None:
                """
                Callback function for the discord.ui.Button view when the player choose to double down.

                :param interaction: The discord.py interaction.
                """
                for button in view.children:
                    # Don't disable Double Down button in case user pressed "cancel".
                    if isinstance(button, discord.ui.Button) and button.label != "Double Down":
                        button.disabled = True

                self.last_action_text = "You choose to double down."
                await self.main_message.edit(content=self.get_game_board(True), view=view)
                await asyncio.sleep(1)  # Add slight delay
                await self.doubling_down(interaction, view)

            # Add the doubling down button.
            doubling_down_button = discord.ui.Button(label="Double Down", style=discord.ButtonStyle.gray)
            doubling_down_button.callback = doubling_down_callback
            view.add_item(doubling_down_button)

        # If player have two of the same cards, then it's splittable.
        if (
            len(self.player_hands[self.active_player_hand_idx]) == 2
            and self.player_hands[self.active_player_hand_idx][0].value
            == self.player_hands[self.active_player_hand_idx][1].value
        ):

            async def split_callback(interaction: discord.Interaction) -> None:
                """
                Callback function for the discord.ui.Button view when the player choose to split.

                :param interaction: The discord.py interaction.
                """
                view.stop()
                for button in view.children:
                    if isinstance(button, discord.ui.Button):
                        button.disabled = True

                if len(self.player_hands) == 1:
                    self.last_action_text = "You choose to split."
                else:
                    self.last_action_text = f"You choose to split hand #{self.active_player_hand_idx + 1}."

                await self.main_message.edit(content=self.get_game_board(True), view=view)
                await asyncio.sleep(1)  # Add slight delay
                await self.split(interaction)

            # Add the split button.
            split_button = discord.ui.Button(label="Split", style=discord.ButtonStyle.gray)
            split_button.callback = split_callback
            view.add_item(split_button)

        await self.main_message.edit(content=self.get_game_board(True) + "\nWhat do you want to do?", view=view)

    async def hit(self, interaction: discord.Interaction) -> None:
        """
        When the player choose to hit.

        :param interaction: The discord.py interaction.
        """
        # noinspection PyUnresolvedReferences
        await interaction.response.defer()

        self.can_double_down = False  # Can no longer double down after the first action

        card = self.player_hands[self.active_player_hand_idx].draw_card()

        # Show the card to the player.
        self.last_action_text = f"You drew `{card}`."
        await self.main_message.edit(content=self.get_game_board(True))
        await asyncio.sleep(1)

        if self.player_hands[self.active_player_hand_idx].is_busted:  # Player busted
            self.active_player_hand_idx += 1
            if self.active_player_hand_idx >= len(self.player_hands):
                # End of the game, process dealer's turn.
                await self.dealer_turn()
                return

        await self.ask_for_user_action()

    async def stay(self, interaction: discord.Interaction) -> None:
        """
        When the player choose to stay.

        :param interaction: The discord.py interaction.
        """
        # noinspection PyUnresolvedReferences
        await interaction.response.defer()

        self.can_double_down = False  # Can no longer double down after the first action

        self.active_player_hand_idx += 1  # Stay moves the active hand to the next hand

        if self.active_player_hand_idx >= len(self.player_hands):
            # End of the game, process dealer's turn.
            await self.dealer_turn()
            return

        # There's still more hands to play, ask for next action.
        await self.ask_for_user_action()

    async def doubling_down(self, interaction: discord.Interaction, view: discord.ui.View) -> None:
        """
        When the player choose to double down.

        :param interaction: The discord.py interaction.
        :param view: The view where the doubling down button got triggered.
        """

        class DoublingDownModal(discord.ui.Modal, title="Double Down"):
            """
            Modal to prompt the user to input a bet for double down.
            """

            bet = discord.ui.TextInput(
                label=f"Bet (Up to {self.player_hands[0].bet})",
                placeholder="How much do you want to bet?",
                min_length=len(str(MIN_BET)),
                max_length=len(str(self.player_hands[0].bet)),
                default=str(self.player_hands[0].bet),
            )

            # noinspection PyMethodParameters
            def __init__(self_):
                """
                Create a doubling down modal with default timeout.
                """
                super().__init__(timeout=self.TIMEOUT_SECS)

            # noinspection PyShadowingNames,PyMethodParameters
            async def on_submit(self_, interaction: discord.Interaction) -> None:
                """
                Callback function for when the user submits the bet form.

                :param interaction: THe current discord.py interaction.
                """
                view.stop()
                for button in view.children:
                    if isinstance(button, discord.ui.Button):
                        button.disabled = True

                await self.main_message.edit(view=view)

                # If the bet is not a valid number.
                if not self_.bet.value.isdigit():
                    # noinspection PyUnresolvedReferences
                    await interaction.response.send_message(
                        "It doesn't look like that's a valid bet!",
                        ephemeral=True,
                        delete_after=5,
                    )
                    await self.ask_for_user_action()
                    return

                bet = int(self_.bet.value)

                # If the bet is out of bounds.
                if bet > self.player_hands[0].bet or bet < MIN_BET:
                    # noinspection PyUnresolvedReferences
                    await interaction.response.send_message(
                        f"Double down bets must be between {MIN_BET} and {self.player_hands[0].bet}.",
                        ephemeral=True,
                        delete_after=5,
                    )
                    await self.ask_for_user_action()
                    return

                user_balance = self.modify_quackerinos(0)  # Get the balance using 0 change

                # Check if user can afford the bet.
                if bet > user_balance:
                    # noinspection PyUnresolvedReferences
                    await interaction.response.send_message(
                        f"You don't have enough quackerinos to bet {bet} for double down.",
                        ephemeral=True,
                        delete_after=5,
                    )
                    await self.ask_for_user_action()
                    return

                self.can_double_down = False  # Can no longer double down after the first action

                # noinspection PyUnresolvedReferences
                await interaction.response.defer()

                # Update bets.
                self.modify_quackerinos(-bet)
                self.player_hands[0].bet += bet

                # Draw card.
                card = self.player_hands[0].draw_card()

                # Show the card to the player.
                self.last_action_text = f"You drew `{card}`."
                await self.main_message.edit(content=self.get_game_board(True))
                await asyncio.sleep(2)

                # Finish the game.
                self.active_player_hand_idx += 1  # Stay moves the active hand to the next hand
                await self.dealer_turn()

            # noinspection PyShadowingNames,PyMethodParameters
            async def on_error(self_, *args: typing.Any, **kwargs: typing.Any) -> None:
                """
                Callback for when there's an error.
                """
                view.stop()
                await self.ask_for_user_action()  # Disregard the error and re-ask for input
                return

            # noinspection PyMethodParameters
            async def on_timeout(self_) -> None:
                """
                Callback for when the modal times out.
                """
                view.stop()
                self.terminate()
                return

        # noinspection PyUnresolvedReferences
        await interaction.response.send_modal(DoublingDownModal())

    async def split(self, interaction: discord.Interaction) -> None:
        """
        When the player choose to split.

        :param interaction: The discord.py interaction.
        """

        user_balance = self.modify_quackerinos(0)  # Get the balance using 0 change
        bet = self.player_hands[self.active_player_hand_idx].bet

        # Check if user can afford the bet.
        if bet > user_balance:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                "You don't have enough quackerinos to split.",
                ephemeral=True,
                delete_after=5,
            )
            await self.ask_for_user_action()
            return

        # noinspection PyUnresolvedReferences
        await interaction.response.defer()

        self.can_double_down = False  # Can no longer double down after the first action

        # Update bets.
        self.modify_quackerinos(-bet)

        self.player_hands.insert(
            self.active_player_hand_idx + 1, self.player_hands[self.active_player_hand_idx].split()
        )

        card1 = self.player_hands[self.active_player_hand_idx].draw_card()
        card2 = self.player_hands[self.active_player_hand_idx + 1].draw_card()

        # Show the card to the player.
        self.last_action_text = f"You drew `{card1}` and `{card2}`."
        await self.main_message.edit(content=self.get_game_board(True))
        await asyncio.sleep(1)

        if self.player_hands[self.active_player_hand_idx][0].rank == "A":  # Splitting aces cannot draw anymore
            self.active_player_hand_idx += 1
            # End of the game, process dealer's turn.
            await self.dealer_turn()
            return

        await self.ask_for_user_action()

    @staticmethod
    def _format_hand_indexes(indexes: list[tuple[int, Hand]]) -> str:
        """
        Format a list of indexes into an "and"-joined string.

        :param indexes: A list of indexes and their hands to concat.
        :return: The formatted string.
        """
        items = [f"#{i + 1} ({hand.value})" for i, hand in indexes]
        if len(items) == 0:
            return ""
        elif len(items) == 1:
            return items[0]
        elif len(items) == 2:
            return f"{items[0]} and {items[1]}"
        else:
            # Join all but the last item with ", ".
            formatted_items = ", ".join(items[:-1])
            # Add "and" before the last item.
            formatted_items += f", and {items[-1]}"
            return formatted_items

    @staticmethod
    def _format_plural(word: str, items_or_count: typing.Sized | int) -> str:
        """
        Add a plural "s" to the end of the word if the items / count is not 1.

        :param word: The word to modify.
        :param items_or_count: A sized container or integer count.
        :return: A formatted string with "s" appended when necessary.
        """
        if isinstance(items_or_count, int):
            return f"{word}{'s' if abs(items_or_count) != 1 else ''}"
        else:
            return f"{word}{'s' if len(items_or_count) != 1 else ''}"

    async def dealer_turn(self) -> None:
        """
        After the player cannot make another action, it's the dealer's turn.

        This is also the ending of the game, since the game ends after the dealer's turn.
        """

        self.refresh_expiry()

        if all(hand.is_busted for hand in self.player_hands):  # All player hands are busted
            if len(self.player_hands) == 1:
                ending_message: str = f"Your hand busted with {self.player_hands[0].value}."
            else:
                ending_message = "All your hands busted."

            final_message: str = self.get_ending_message(-sum(hand.bet for hand in self.player_hands), ending_message)
            await self.main_message.edit(content=final_message)
            await self.end_round()
            return

        await self.main_message.edit(content=self.get_game_board(False), view=None)

        # Dealer draws card when total value is < 17, and stops when it's >= 17 or busted.
        while self.dealer_hand.value < 17 and not self.dealer_hand.is_busted:
            card = self.dealer_hand.draw_card()
            await asyncio.sleep(1)
            self.last_action_text = f"The dealer drew a `{card}`."
            await self.main_message.edit(content=self.get_game_board(False))

        if self.dealer_hand.is_busted:  # Dealer busted
            if len(self.player_hands) == 1:  # Player has only one hand, and it's not busted, they win
                earnings = self.player_hands[0].bet  # Winning to dealer busted earns 1:1
                self.modify_quackerinos(self.player_hands[0].bet + earnings)
                ending_message = f"The dealer busted with {self.dealer_hand.value}."

            else:  # Some player hands are busted, but some are winning
                earnings: int = 0
                quackerinos_return: int = 0
                winning_hand_indexes: list[tuple[int, Hand]] = []  # format: [(index, Hand), ...]
                losing_hand_indexes: list[tuple[int, Hand]] = []
                for hand_idx, player_hand in enumerate(self.player_hands):  # Separate the winning / losing hands
                    if not player_hand.is_busted:
                        winning_hand_indexes += [(hand_idx, player_hand)]
                        earnings += player_hand.bet
                        quackerinos_return += player_hand.bet
                    else:
                        losing_hand_indexes += [(hand_idx, player_hand)]

                self.modify_quackerinos(quackerinos_return + earnings)

                if len(winning_hand_indexes) == len(self.player_hands):
                    ending_message = f"The dealer busted with {self.dealer_hand.value}, you won with all your hands."
                else:
                    ending_message = (
                        f"The dealer busted with {self.dealer_hand.value}. You won with "
                        f"{self._format_plural('hand', winning_hand_indexes)} "
                        f"{self._format_hand_indexes(winning_hand_indexes)} but your "
                        f"{self._format_plural('hand', losing_hand_indexes)} "
                        f"{self._format_hand_indexes(losing_hand_indexes)} busted."
                    )

            final_message = self.get_ending_message(earnings, ending_message)
            await self.main_message.edit(content=final_message)
            await self.end_round()
            return

        # Time to compare player to dealer values.
        # There are many redundancies in this section of code and this is by-design for the verboseness.

        # First case, if player wins with all hands.
        if all(hand.value > self.dealer_hand.value for hand in self.player_hands):
            earnings = sum(hand.bet for hand in self.player_hands)
            quackerinos_return = earnings  # Winning payout is 1:1
            self.modify_quackerinos(quackerinos_return + earnings)
            if len(self.player_hands) == 1:
                ending_message = (
                    f"Your hand of {self.player_hands[0].value} beats the dealer's {self.dealer_hand.value}."
                )
            else:
                ending_message = f"All your hands beat the dealer's {self.dealer_hand.value}."
            final_message = self.get_ending_message(earnings, ending_message)
            await self.main_message.edit(content=final_message)
            await self.end_round()
            return

        # Second case, if player loses with all hands.
        if all(hand.value < self.dealer_hand.value for hand in self.player_hands):
            if len(self.player_hands) == 1:
                ending_message = (
                    f"Your hand of {self.player_hands[0].value} loses to the dealer's {self.dealer_hand.value}."
                )
            else:
                ending_message = f"All your hands loses to the dealer's {self.dealer_hand.value}."

            final_message = self.get_ending_message(-sum(hand.bet for hand in self.player_hands), ending_message)
            await self.main_message.edit(content=final_message)
            await self.end_round()
            return

        # Third case, if player has 1 hand and tied with the dealer.
        if len(self.player_hands) == 1 and self.player_hands[0].value == self.dealer_hand.value:
            quackerinos_return = self.player_hands[0].bet
            self.modify_quackerinos(quackerinos_return)
            ending_message = f"You and the dealer both got {self.dealer_hand.value}."
            final_message = self.get_ending_message(0, ending_message)
            await self.main_message.edit(content=final_message)
            await self.end_round()
            return

        # Remaining case, if player has > 1 hands, and is a combination of win / lose / tie.
        earnings: int = 0
        quackerinos_return: int = 0
        winning_hand_indexes: list[tuple[int, Hand]] = []  # format: [(index, Hand), ...]
        losing_hand_indexes: list[tuple[int, Hand]] = []
        tie_hand_indexes: list[tuple[int, Hand]] = []
        for hand_idx, player_hand in enumerate(self.player_hands):  # Separate the winning / losing / tied hands
            if player_hand.is_busted or player_hand.value < self.dealer_hand.value:  # Busted or losing hands
                losing_hand_indexes += [(hand_idx, player_hand)]
            elif player_hand.value > self.dealer_hand.value:  # Winning hands
                winning_hand_indexes += [(hand_idx, player_hand)]
                earnings += player_hand.bet  # Winning payout is 1:1
                quackerinos_return += player_hand.bet
            else:  # Tied hands
                tie_hand_indexes += [(hand_idx, player_hand)]
                quackerinos_return += player_hand.bet

        self.modify_quackerinos(quackerinos_return + earnings)

        ending_message = f"The dealer got {self.dealer_hand.value}."
        if winning_hand_indexes:
            ending_message += (
                f"You won with {self._format_plural('hand', winning_hand_indexes)} "
                f"{self._format_hand_indexes(winning_hand_indexes)}."
            )
        if losing_hand_indexes:
            ending_message += (
                f"You lost with {self._format_plural('hand', losing_hand_indexes)} "
                f"{self._format_hand_indexes(losing_hand_indexes)}."
            )
        if tie_hand_indexes:
            ending_message += (
                f"You tied with {self._format_plural('hand', tie_hand_indexes)} "
                f"{self._format_hand_indexes(tie_hand_indexes)}."
            )
        final_message = self.get_ending_message(earnings, ending_message)
        await self.main_message.edit(content=final_message)
        await self.end_round()


class Quackjack(commands.Cog):
    """
    A full implementation of the game Blackjack ("Quackjack").
    """

    def __init__(self, bot: commands.Bot):
        """
        Initiates the Quackjack cog, load using bot.add_cog().

        :param bot: The active discord.py Bot.
        """
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """
        An on_ready listener for the bot.
        """
        all_commands = await self.bot.tree.fetch_commands()
        Quackjack.quackjack.id = next(x.id for x in all_commands if self.quackjack.name == x.name)

    async def cog_load(self) -> None:
        """
        Hook for calling on_ready when the bot was already ready.
        """
        if self.bot.is_ready():
            await self.on_ready()  # If the bot is already ready when loading the cog, call on_ready manually

    @commands.hybrid_group()
    async def quackjack(self, ctx: commands.Context) -> None:
        """
        Gamble your quackerinos and play a fun game of Quackjack.

        :param ctx: The interaction context.
        """
        await ctx.reply(f"To start a game of Quackjack, type `{ctx.prefix + self.play.qualified_name}`.")

    @quackjack.command()
    async def play(self, ctx: commands.Context, bet: commands.Range[int, MIN_BET, MAX_BET]) -> None:
        """
        Start a Quackjack game.

        :param ctx: The interaction context.
        :param bet: The starting bet you want to place for the round.
        """
        # This is definitely *NOT* a great way of keeping balance,
        # but given the rest of the code, it is what it is...
        with USER_INFO_PATH.open("r") as file:
            all_users_info: dict = json.load(file)

        # Make sure this player exists in user_info.
        try:
            user: dict = all_users_info[str(ctx.author.id)]
        except KeyError:
            await ctx.reply("You have not quacked yet.")
            return

        try:
            user_balance: int = int(user["quackerinos"])
        except (TypeError, KeyError):
            user_balance = 0

        # Check if user can afford the bet.
        if bet > user_balance:
            await ctx.reply(f"You don't have enough quackerinos to bet {bet}.")
            return

        if ctx.guild is not None:
            guild_id = ctx.guild.id
        else:  # If this command is invoked in DM, use the user ID instead.
            guild_id = ctx.author.id

        game = QuackjackGame.get_game(user_id=ctx.author.id, guild_id=guild_id)
        if game._state != GameState.pre_game:  # Check if the game is in the idle state (pre-game)
            await ctx.reply("You are currently still in a round. Finish it first!")
            return

        await game.start_round(ctx, bet)


async def setup(bot: commands.Bot) -> None:
    """
    Setup hook for discord.py extensions.

    :param bot: The active discord.py bot.
    """
    await bot.add_cog(Quackjack(bot))
