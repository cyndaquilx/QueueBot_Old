# QueueBot

This is the bot used in MK8DX 150cc Lounge to run Squad Queue events, where teams of 2, 3, or 4 queue up and are placed into rooms based on their average MMR.

You will need [discord.py](https://discordpy.readthedocs.io/en/latest/intro.html#installing) and [python-dateutil](https://pypi.org/project/python-dateutil/) to run the bot, and [gspread](https://gspread.readthedocs.io/en/latest/) if you get your MMR from a spreadsheet.

If you get your MMR from a spreadsheet, make a Google Sheet with sheet name "search" that functions the same as [this sample.](https://docs.google.com/spreadsheets/d/1ts17B2k8Hv5wnHB-4kCE3PNFL1EXEJ01lx-s8zPpECE/edit?usp=sharing) Make sure that you have a `credentials.json` file in your bot directory, instructions [here.](https://gspread.readthedocs.io/en/latest/oauth2.html)

If you don't get your MMR from a spreadsheet, the **mmr** function in `cogs/Sheet.py` will have to be rewritten. The provided file should give you a general idea of how the function should work.

Make sure that you edit `config.json` so that the following fields have a value:
- token: replace "insert token here" with your bot's token
- roles: list containing the roles that should have mogi powers
- mogichannel: ID of the channel where players can join the mogi
- roles_for_channels: ID of any roles that you want to see the room channels
- queue_messages: Either true or false. If true, sends messages every `sec_between_queue_msgs` seconds, otherwise sends messages instantly
- sec_between_queue_msgs: Number of seconds between queue msgs
- TIME_ADJUSTMENT: Number of hours behind EST that the bot owner's system is (ex. 3 for PST, -6 for CET)
- QUEUE_OPEN_TIME: Number of minutes before the scheduled time that the queue should open (default: 60)
- JOINING_TIME: Number of minutes after QUEUE_OPEN_TIME that the queue is open (default: 45)
- EXTENSION_TIME: Number of minutes after JOINING_TIME for any potential extra teams to join (default: 5)

Once you have everything set up, run `lounge.py` from the command line

Report any bugs to Cynda#1979 on Discord
