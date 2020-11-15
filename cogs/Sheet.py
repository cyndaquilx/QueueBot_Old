# every lounge is different so this file will probably
# have to be completely rewritten for each server.
# my implementation is here as an example; gspread is only
# needed if you get MMR from a spreadsheet.

# The important part is that the function returns False
# if a player's MMR can't be found,
# and returns the player's MMR otherwise

import discord
from discord.ext import commands

import gspread
gc = gspread.service_account(filename='credentials.json')

#opens a lookup worksheet so MMR is retrieved quickly
sh = gc.open_by_key('1ts17B2k8Hv5wnHB-4kCE3PNFL1EXEJ01lx-s8zPpECE')
mmrs = sh.worksheet("search")

class Sheet(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    async def mmr(self, member: discord.Member):
        name = member.display_name
        #updates cell B3 of the lookup sheet with the member name
        mmrs.update_cell(3, 2, name)
        #cell C3 of the lookup sheet returns the member's MMR,
        #if found, otherwise returns "N"
        check_value = mmrs.acell('C3').value
        #if player has placement mmr, sets it to 1000
        #for the sake of getting a team mmr average
        if check_value == "Placement":
            check_value = 1000
        #if player isn't found in sheet/database, return False
        if check_value == "N":
            check_value = False
        return check_value

def setup(bot):
    bot.add_cog(Sheet(bot))
