import discord
from discord.ext import commands
import json

class Mogi(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        with open('./config.json', 'r') as cjson:
            self.config = json.load(cjson)
            
        # no commands should work when self.started or self.gathering is False, 
        # except for start, which initializes each of these values.
        self.started = False
        self.gathering = False
        
        # can either be 2, 3, or 4, representing the respective mogi sizes
        self.size = 2
        
        # self.waiting is a list of dictionaries, with the keys each corresponding to a
        # Discord member class, and the values being a list with 2 values:
        # index 0 being the player's confirmation status, and index 1 being the player's MMR.
        self.waiting = []
        
        # self.list is also a list of dictionaries, with the keys each corresponding to a
        # Discord member class, and the values being the player's MMR.
        self.list = []
        
        # contains the avg MMR of each confirmed team
        self.avgMMRs = []

        #list of Channel objects created by the bot for easy deletion
        self.channels = []


    # the 4 functions below act as various checks for each of the bot commands.
    # if any of these are false, sends a message to the channel
    # and throws an exception to force the command to stop

    async def hasroles(self, ctx):
        for rolename in self.config["roles"]:
            for role in ctx.author.roles:
                if role.name == rolename:
                    return
        raise commands.MissingAnyRole(self.config["roles"])

    async def is_mogi_channel(self, ctx):
        if ctx.channel.id != self.config["mogichannel"]:
            await(await ctx.send("You cannot use this command in this channel!")).delete(delay=5)
            raise Exception()

    async def is_started(self, ctx):
        if self.started == False:
            await(await ctx.send("Mogi has not been started yet.. type !start")).delete(delay=5)
            raise Exception()

    async def is_gathering(self, ctx):
        if self.gathering == False:
            await(await ctx.send("Mogi is closed; players cannot join or drop from the event")).delete(delay=5)
            raise Exception()
        
            

    # Checks if a user is in a squad currently gathering players;
    # returns False if not found, and returns the squad index in
    # self.waiting if found
    async def check_waiting(self, member: discord.Member):
        if(len(self.waiting) == 0):
            return False
        for i in range(len(self.waiting)):
            for player in self.waiting[i].keys():
                # for testing, it's convenient to change player.id
                # and member.id to player.display_name
                # and member.display_name respectively
                # (lets you test with only 2 accounts and changing
                #  nicknames)
                if player.id == member.id:
                    return i
        return False

    # Checks if a user is in a full squad that has joined the mogi;
    # returns False if not found, and returns the squad index in
    # self.list if found
    async def check_list(self, member: discord.Member):
        if (len(self.list) == 0):
            return False
        for i in range(len(self.list)):
            for player in self.list[i].keys():
                # for testing, it's convenient to change player.id
                # and member.id to player.display_name
                # and member.display_name respectively
                # (lets you test with only 2 accounts and changing
                #  nicknames)
                if player.id == member.id:
                    return i
        return False
        
    @commands.command(aliases=['c'])
    @commands.max_concurrency(number=1,wait=True)
    @commands.guild_only()
    async def can(self, ctx, members: commands.Greedy[discord.Member]):
        """Tag your partners to invite them to a mogi or accept a invitation to join a mogi"""
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
            await Mogi.is_gathering(self, ctx)
        except:
            return

        if (len(members) > 0 and len(members) < self.size - 1):
            await ctx.send("You didn't tag the correct number of people for this format (%d)"
                           % (self.size-1))
            return

        sheet = self.bot.get_cog('Sheet')

        # checking if message author is already in the mogi
        checkWait = await Mogi.check_waiting(self, ctx.author)
        checkList = await Mogi.check_list(self, ctx.author)
        if checkWait is not False:
            if self.waiting[checkWait][ctx.author][0] == True:
                    await ctx.send("You have already confirmed for this event; type `!d` to drop")
                    return
        if checkList is not False:
            await ctx.send("You have already confirmed for this event; type `!d` to drop")
            return

        # logic for when no players are tagged
        if len(members) == 0:
            #runs if message author has been invited to squad
            #but hasn't confirmed
            if checkWait is not False:
                self.waiting[checkWait][ctx.author][0] = True
                confirmedPlayers = []
                missingPlayers = []
                for player in self.waiting[checkWait].keys():
                    if self.waiting[checkWait][player][0] == True:
                        confirmedPlayers.append(player)
                    else:
                        missingPlayers.append(player)
                string = ("Successfully confirmed for your squad [%d/%d]\n"
                          % (len(confirmedPlayers), self.size))
                if len(missingPlayers) > 0:
                          string += "Missing players: "
                          string += ", ".join([player.display_name for player in missingPlayers])
                await ctx.send(string)
                
                #if player is the last one to confirm for their squad,
                #add them to the mogi list
                if len(missingPlayers) == 0:
                    squad = self.waiting[checkWait]
                    squad2 = {}
                    teamMsg = ""
                    totalMMR = 0
                    for player in squad.keys():
                        playerMMR = int(squad[player][1])
                        squad2[player] = playerMMR
                        totalMMR += playerMMR
                        teamMsg += "%s (%d MMR)\n" % (player.display_name, int(playerMMR))
                    self.avgMMRs.append(int(totalMMR/self.size))
                    self.waiting.pop(checkWait)
                    self.list.append(squad2)
                    if len(self.list) > 1:
                        s = "s"
                    else:
                        s = ""
                    await ctx.send("Squad successfully added to mogi list `[%d team%s]`:\n%s"
                                   % (len(self.list), s, teamMsg))
                return
            
            await ctx.send("You didn't tag the correct number of people for this format (%d)"
                           % (self.size-1))
            return

        # Input validation for tagged members; checks if each tagged member is already
        # in a squad, as well as checks if any of them are duplicates
        for member in members:
            checkWait = await Mogi.check_waiting(self, member)
            checkList = await Mogi.check_list(self, member)
            if checkWait is not False or checkList is not False:
                msg = ("%s is already confirmed for a squad for this event `("
                               % (member.display_name))
                if checkWait is not False:
                    msg += ", ".join([player.display_name for player in self.waiting[checkWait].keys()])
                else:
                    msg += ", ".join([player.display_name for player in self.list[checkList].keys()])
                msg += ")` They should type `!d` if this is in error."
                await ctx.send(msg)
                return
            if member == ctx.author:
                await ctx.send("Duplicate players are not allowed for a squad, please try again")
                return
        if len(set(members)) < len(members):
            await ctx.send("Duplicate players are not allowed for a squad, please try again")
            return
            
        # logic for when the correct number of arguments are supplied
        # (self.size - 1)
        players = {ctx.author: [True]}
        playerMMR = await sheet.mmr(ctx.author)
        if playerMMR is False:
            await(await ctx.send("Error: MMR for player %s cannot be found! Please contact a staff member for help"
                           % ctx.author.display_name)).delete(delay=10)
            return
        players[ctx.author].append(playerMMR)
        for i in range(self.size-1):
            players[members[i]] = [False]
            playerMMR = await sheet.mmr(members[i])
            if playerMMR is False:
                await(await ctx.send("Error: MMR for player %s cannot be found! Please contact a staff member for help"
                               % members[i].display_name)).delete(delay=10)
                return
            players[members[i]].append(playerMMR)
        self.waiting.append(players)
        
        msg = "%s has created a squad with " % ctx.author.display_name
        msg += ", ".join([player.display_name for player in members])
        msg += "; each player must type `!c` to join the queue [1/%d]" % (self.size)
        await(await ctx.send(msg)).delete(delay=10)


           
    @commands.command(aliases=['d'])
    @commands.max_concurrency(number=1,wait=True)
    @commands.guild_only()
    @commands.cooldown(1, 15, commands.BucketType.member)
    async def drop(self, ctx):
        """Remove your squad from a mogi"""
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
            await Mogi.is_gathering(self, ctx)
        except:
            return

        checkWait = await Mogi.check_waiting(self, ctx.author)
        checkList = await Mogi.check_list(self, ctx.author)
        # "is" instead of "==" is essential here, otherwise if
        # i=0 is returned, it will think it's False
        if checkWait is False and checkList is False:
            await(await ctx.send("You are not currently in a squad for this event; type `!c @partnerNames`")).delete(delay=5)
            return
        if checkWait is not False:
            droppedTeam = self.waiting.pop(checkWait)
            fromStr = " from unfilled squads"
        else:
            droppedTeam = self.list.pop(checkList)
            self.avgMMRs.pop(checkList)
            fromStr = " from mogi list"
        string = "Removed team "
        string += ", ".join([player.display_name for player in droppedTeam.keys()])
        string += fromStr
        await(await ctx.send(string)).delete(delay=5)

    @commands.command(aliases=['r'])
    @commands.max_concurrency(number=1,wait=True)
    @commands.guild_only()
    async def remove(self, ctx, num: int):
        """Removes the given squad ID from the mogi list"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        if num > len(self.list) or num < 1:
            await(await ctx.send("Invalid squad ID; there are %d squads in the mogi"
                                 % len(self.list))).delete(delay=10)
            return
        squad = self.list.pop(num-1)
        self.avgMMRs.pop(num-1)
        await ctx.send("Removed squad %s from mogi list"
                       % (", ".join([player.display_name for player in squad.keys()])))

    @commands.command()
    @commands.guild_only()
    async def start(self, ctx, size: int):
        """Start a mogi in the channel defined by the config file"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
        except:
            return
        valid_sizes = [2, 3, 4]
        if size not in valid_sizes:
            await(await ctx.send("The size you entered is invalid; proper values are: 2, 3, 4")).delete(delay=5)
            return
        self.started = True
        self.gathering = True
        self.size = size
        self.waiting = []
        self.list = []
        self.avgMMRs = []
        await ctx.send("A %dv%d mogi has been started - @here Type `!c`, `!d`, or `!list`" % (size, size))

    @commands.command()
    @commands.guild_only()
    async def close(self, ctx):
        """Close the mogi so players can't join or drop"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
            await Mogi.is_gathering(self, ctx)
        except:
            return
        self.gathering = False
        await ctx.send("Mogi is now closed; players can no longer join or drop from the event")

    @commands.command()
    @commands.guild_only()
    async def open(self, ctx):
        """Reopen the mogi so that players can join and drop"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        if self.gathering is True:
            await(await ctx.send("Mogi is already open; players can join and drop from the event")
                  ).delete(delay=5)
            return
        self.gathering = True
        await ctx.send("Mogi is now open; players can join and drop from the event")

    @commands.command()
    @commands.guild_only()
    async def end(self, ctx):
        """End the mogi"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        try:
            for i in range(len(self.channels)-1, -1, -1):
                await self.channels[i].delete()
                self.channels.pop(i)
        except:
            pass
        self.started = False
        self.gathering = False
        self.waiting = []
        self.list = []
        self.avgMMRs = []
        await ctx.send("%s has ended the mogi" % ctx.author.display_name)
            

    @commands.command(aliases=['l'])
    @commands.cooldown(1, 40)
    @commands.guild_only()
    async def list(self, ctx):
        """Display the list of confirmed squads for a mogi; sends 15 at a time to avoid
           reaching 2000 character limit"""
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        if len(self.list) == 0:
            await(await ctx.send("There are no squads in the mogi - confirm %d players to join" % (self.size))).delete(delay=5)
            return
        msg = "`Mogi List`\n"
        for i in range(len(self.list)):
            #safeguard against potentially reaching 2000-char msg limit
            if i > 0 and i % 15 == 0:
                await ctx.send(msg)
                msg = ""
            msg += "`%d.` " % (i+1)
            msg += ", ".join([player.display_name for player in self.list[i].keys()])
            msg += " (%d MMR)\n" % (self.avgMMRs[i])
        if(len(self.list) % (12/self.size) != 0):
            msg += ("`[%d/%d] teams for %d full rooms`"
                    % ((len(self.list) % (12/self.size)), (12/self.size), int(len(self.list) / (12/self.size))+1))
        await ctx.send(msg)

    @commands.command()
    @commands.cooldown(1, 30, commands.BucketType.member)
    @commands.guild_only()
    async def squad(self, ctx):
        """Displays information about your squad for a mogi"""
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        checkWait = await Mogi.check_waiting(self, ctx.author)
        checkList = await Mogi.check_list(self, ctx.author)
        if checkWait is False and checkList is False:
            await(await ctx.send("You are not currently in a squad for this event; type `!c @partnerNames`")
                  ).delete(delay=5)
            return
        msg = ""
        playerNum = 1
        if checkWait is not False:
            myTeam = self.waiting[checkWait]
            listString = ""
            confirmCount = 0
            for player in myTeam.keys():
                listString += ("`%d.` %s (%d MMR)" % (playerNum, player.display_name, int(myTeam[player][1])))
                if myTeam[player][0] is False:
                    listString += " `✘ Unconfirmed`\n"
                else:
                    listString += " `✓ Confirmed`\n"
                    confirmCount += 1
                playerNum += 1
            msg += ("`%s's squad [%d/%d confirmed]`\n%s"
                    % (ctx.author.display_name, confirmCount, self.size, listString))
            await(await ctx.send(msg)).delete(delay=30)
        else:
            myTeam = self.list[checkList]
            msg += ("`%s's squad [registered]`\n" % (ctx.author.display_name))
            for player in myTeam.keys():
                msg += ("`%d.` %s (%d MMR)\n"
                        % (playerNum, player.display_name, int(myTeam[player])))
                playerNum += 1
            await(await ctx.send(msg)).delete(delay=30)

    @commands.command()
    @commands.guild_only()
    async def sortTeams(self, ctx):
        """Backup command if !makerooms doesn't work; doesn't make channels, just sorts teams in MMR order"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        indexes = range(len(self.avgMMRs))
        sortTeamsMMR = sorted(zip(self.avgMMRs, indexes), reverse=True)
        sortedMMRs = [x for x, _ in sortTeamsMMR]
        sortedTeams = [self.list[i] for i in (x for _, x in sortTeamsMMR)]
        msg = "`Sorted list`\n"
        for i in range(len(sortedTeams)):
            if i > 0 and i % 15 == 0:
                await ctx.send(msg)
                msg = ""
            msg += "`%d.` " % (i+1)
            msg += ", ".join([player.display_name for player in sortedTeams[i].keys()])
            msg += " (%d MMR)\n" % sortedMMRs[i]
        await ctx.send(msg)

    @commands.command()
    @commands.bot_has_guild_permissions(manage_channels=True)
    @commands.guild_only()
    async def makeRooms(self, ctx, openTime: int):
        """Sorts squads into rooms based on average MMR, creates room channels and adds players to each room channel"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return

        numRooms = int(len(self.list) / (12/self.size))
        if numRooms == 0:
            await ctx.send("Not enough players to fill a room! Try this command with at least %d teams" % int(12/self.size))
            return

        if openTime >= 60 or openTime < 0:
            await ctx.send("Please specify a valid time (in minutes) for rooms to open (00-59)")
            return
        startTime = openTime + 10
        while startTime >= 60:
            startTime -= 60
            
        numTeams = int(numRooms * (12/self.size))
        finalList = self.list[0:numTeams]
        finalMMRs = self.avgMMRs[0:numTeams]

        indexes = range(len(finalMMRs))
        sortTeamsMMR = sorted(zip(finalMMRs, indexes), reverse=True)
        sortedMMRs = [x for x, _ in sortTeamsMMR]
        sortedTeams = [finalList[i] for i in (x for _, x in sortTeamsMMR)]
        for i in range(numRooms):

            #creating room roles and channels
            roomName = "Room %d" % (i+1)
            category = ctx.channel.category
            overwrites = {
                ctx.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                ctx.guild.me: discord.PermissionOverwrite(read_messages=True)
                }
            
            #tries to retrieve RandomBot and BooBot's roles, and adds them to the
            #channel overwrites if the role specified in the config file exists
            randombot = ctx.guild.get_role(self.config["randombot_role"])
            boobot = ctx.guild.get_role(self.config["boobot_role"])
            if randombot is not None:
                overwrites[randombot] = discord.PermissionOverwrite(read_messages=True)
            if boobot is not None:
                overwrites[boobot] = discord.PermissionOverwrite(read_messages=True)

            msg = "`%s`\n" % roomName
            for j in range(int(12/self.size)):
                index = int(i * 12/self.size + j)
                msg += "`%d.` " % (j+1)
                msg += ", ".join([player.display_name for player in sortedTeams[index].keys()])
                msg += " (%d MMR)\n" % sortedMMRs[index]
                for player in sortedTeams[index].keys():
                    overwrites[player] = discord.PermissionOverwrite(read_messages=True)
            roomMsg = msg
            mentions = ""
            scoreboard = "Table: `!scoreboard %d " % (12/self.size)
            for j in range(int(12/self.size)):
                index = int(i * 12/self.size + j)
                mentions += " ".join([player.mention for player in sortedTeams[index].keys()])
                mentions += " "
                for player in sortedTeams[index].keys():
                    scoreboard += player.display_name.replace(" ", "")
                    scoreboard += " "
            
            roomMsg += "%s`\n" % scoreboard
            roomMsg += ("\nDecide a host amongst yourselves; room open at :%02d, start at :%02d. Good luck!\n\n"
                        % (openTime, startTime))
            roomMsg += mentions
            roomChannel = await category.create_text_channel(name=roomName, overwrites=overwrites)
            self.channels.append(roomChannel)
            await roomChannel.send(roomMsg)
            await ctx.send(msg)
            
        if numTeams < len(self.list):
            missedTeams = self.list[numTeams:len(self.list)]
            missedMMRs = self.avgMMRs[numTeams:len(self.list)]
            msg = "`Late teams:`\n"
            for i in range(len(missedTeams)):
                msg += "`%d.` " % (i+1)
                msg += ", ".join([player.display_name for player in missedTeams[i].keys()])
                msg += " (%d MMR)\n" % missedMMRs[i]
            await ctx.send(msg)
                  

def setup(bot):
    bot.add_cog(Mogi(bot))
