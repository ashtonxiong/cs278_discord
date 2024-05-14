import asyncio
from enum import Enum, auto
from datetime import datetime, timedelta
import discord
import json
import logging
import openai
from openai import OpenAI
import os
import pytz

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# Retrieve token
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    tokens = json.load(f)
    discord_token = tokens['discord']
    openai_api_key = tokens['openai']

class State(Enum):
    MOD_START = auto()
    AWAITING_MORE = auto()

class ModBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.openai_client = openai.OpenAI(api_key=openai_api_key)
        # self.state = State.MOD_START
        self.user_state = {}

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        trivia_channel = discord.utils.get(self.get_all_channels(), name='trivia')
        if trivia_channel:
            print(f"Found trivia channel: {trivia_channel.id}")
            self.scheduler = TriviaBot(trivia_channel, self.openai_client)
            asyncio.create_task(self.scheduler.start())
        else:
            print("Trivia channel not found. Make sure the bot is in the correct server and the channel exists.")

    async def on_message(self, message):
        # Ignore messages sent by bot to itself
        if message.author == self.user:
            return

        # Check if the message is a DM
        if message.guild is None: 
            if message.author in self.user_state and self.user_state[message.author]['state'] == State.AWAITING_MORE:
                if message.content.lower() == "learn more":
                    content, categories = self.user_state[message.author]['data']
                    categories = [category.replace('_', ' ').replace('/', ' ') for category in categories]
                    info_message = f"Your message\n`{content}`\nwas flagged due to: " + ', '.join(categories) + ".\n"
                    await message.author.send(info_message)
                if message.content.lower() == "report":
                    info_message = "Thank you for submitting a report.\n"
                    info_message += "Your message will be reviewed by our content moderation team.\n"
                    info_message += "You will be informed if your message is restored.\n\n"
                    await message.author.send(info_message)
                if message.content.lower() == "done":
                    info_message = "Thank you. Your interaction has ended.\n"
                    await message.author.send(info_message)
                    self.user_state[message.author]['state'] = State.MOD_START  # Reset state
            return  # Stop processing if it's a DM and no relevant state action


        response = self.openai_client.moderations.create(input=message.content)
        output = response.results[0]

        # Respond based on moderation resul
        if output.flagged:
            await message.delete()
            # Check which categories are flagged
            flagged_categories = [
                category for category, flagged in output.categories.dict().items() if flagged]
            self.user_state[message.author] = {'state': State.AWAITING_MORE, 'data': (message.content, flagged_categories)}
            print("user_state:", self.user_state)

            warning_message = f"Your message \n`{message.content}`\nwas flagged as potentially harmful and has been deleted.\n\n"
            warning_message += "Please remember to adhere to the community guidelines.\n\n\n"
            warning_message += "If you would like to know why your message was deleted, please respond with `learn more`.\n"
            warning_message += "If you believe your message was not harmful and should not have been deleted, please respond with `report`.\n"
            warning_message += "If you are done, please respond with `done`.\n"

            if message.author.dm_channel is None:
                await message.author.create_dm()
            await message.author.dm_channel.send(warning_message)
            self.State = State.AWAITING_MORE

        return None

class TriviaBot:
    def __init__(self, channel, openai_client, timezone='US/Pacific'):
        self.channel = channel
        self.timezone = timezone
        self.openai_client = openai_client

    async def generate_trivia_prompt(self):
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a music trivia bot, skilled in generating interesting musical trivia questions with diverse musical interests. Format the trivia question followed by four possible answers and indicate the correct answer at the end as 'Correct: A'."},
                    {"role": "user", "content": "Generate a trivia question with four possible answers, indicating which one is correct."}
                ])
            if response.choices and response.choices[0].message:
                trivia_data = response.choices[0].message.content.strip()
                if 'Correct:' not in trivia_data:
                    print("Unexpected format received:", trivia_data)
                    return None, None, None  # Returning None to indicate an error in format

                # Parse the trivia data into usable components
                question_part, answer_part = trivia_data.split('Correct:')
                question = question_part.strip()
                correct_answer = answer_part.strip()
                options = question.split('\n')[-4:]  # Get the last four lines as options
                correct_answer_letter = correct_answer[0]
                return question, options, correct_answer_letter
            else:
                raise ValueError("No valid response received from OpenAI.")
        except Exception as e:
            print(f"Failed to generate trivia prompt.")
            return None, None, None

    async def unpin_messages(self):
        pins = await self.channel.pins()
        if pins:
            for pin in pins:
                await pin.unpin()
            print("All previous pins unpinned.")
        else:
            return None

    async def start(self):
        while True:
            now = datetime.now(pytz.timezone(self.timezone))
            next_run = now.replace(hour=11, minute=16, second=0, microsecond=0)
            if now >= next_run:  # If it's past 12:00 PM PST today, schedule for the next day
                next_run += timedelta(days=1)
            wait_seconds = (next_run - now).total_seconds()
            print(f"Waiting {wait_seconds} seconds until the next message at 12:00 PM {self.timezone}.")
            await asyncio.sleep(wait_seconds)

            question, options, correct_answer_letter = await self.generate_trivia_prompt()
            if question and options and correct_answer_letter and self.channel:
                # Unpin all other messages in channel
                await self.unpin_messages()

                message = f"It's trivia time! 🎉\n`{question}`\n"
                message += "\nReact with 🎹 for A\nReact with 🎧 for B\nReact with 🎸 for C\nReact with 🎵 for D."
                sent_message = await self.channel.send(message)
                emojis = {'A': '🎹', 'B': '🎧', 'C': '🎸', 'D': '🎵'}
                for option in options:
                    emoji = emojis[option.strip()[0]]  # Ensure that we only get 'A', 'B', 'C', or 'D'
                    await sent_message.add_reaction(emoji)

                await sent_message.pin()
                # Create thread out of trivia question
                thread = await sent_message.create_thread(name="Trivia Question Discussion")
                await thread.send("Discuss today's trivia question here!")

            elif question and options and correct_answer_letter and not self.channel:
                print("Channel not found or missing. Check the configuration.\n")
            elif self.channel and not question and not options and not correct_answer_letter:
                print("Could not generate trivia question.\n.")
            else:
                print("Other error in start().\n")

client = ModBot()
client.run(discord_token)