import discord
from discord.ext import commands, tasks
import json
from dateutil.parser import parse
from datetime import datetime, timedelta
import collections
import time

with open('./config.json', 'r') as cjson:
            config = json.load(cjson)

CHECKMARK_ADDITION = "-\U00002713"
CHECKMARK_ADDITION_LEN = 2
time_print_formatting = "%B %d, %Y at %I:%M%p EST"
#There are two timezones: the timezone your staff schedules events in, and your server's timezone
#Set this to the number of hours ahead (or behind) your staff's timezone is from your server's timezone
#This is so that you don't have to adjust your machine clock to accomodate for your staff

#For example, if my staff is supposed to schedule events in EST and my machine is PST, this number would be 3 since EST is 3 hours ahead of my machine's PST
TIME_ADJUSTMENT = timedelta(hours=config["TIME_ADJUSTMENT"])

#number of minutes before scheduled time that queue should open
QUEUE_OPEN_TIME = timedelta(minutes=config["QUEUE_OPEN_TIME"])

#number of minutes after QUEUE_OPEN_TIME that teams can join the mogi
JOINING_TIME = timedelta(minutes=config["JOINING_TIME"])

#number of minutes after JOINING_TIME for any potential extra teams to join
EXTENSION_TIME = timedelta(minutes=config["EXTENSION_TIME"])

Scheduled_Event = collections.namedtuple('Scheduled_Event', 'size time started mogi_channel')

class Mogi(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
            
        # no commands should work when self.started or self.gathering is False, 
        # except for start, which initializes each of these values.
        self.started = False
        self.gathering = False
        self.making_rooms_run = False
        
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
        self.categories = []
        self.channels = []
        
        self.scheduled_events = []

        self.is_automated = False

        self.mogi_channel = None

        self.start_time = None

        self._scheduler_task = self.sqscheduler.start()

        self._msgqueue_task = self.send_queued_messages.start()

        self.msg_queue = []

    async def lockdown(self, channel:discord.TextChannel):
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)
        await channel.send("Locked down " + channel.mention)

    async def unlockdown(self, channel:discord.TextChannel):
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(channel.guild.default_role, overwrite=overwrite)
        await channel.send("Unlocked " + channel.mention)

    async def scheduler_mogi_start(self):
        """Functions that tries to launch scheduled mogis - Note that it won't launch any sscheduled mogis
        if an there is already a mogi ongoing, instead it will send an error message and delete that event from the schedule"""

        cur_time = datetime.now()

        to_remove = [] #Keep a list of indexes to remove - can't remove while iterating
        for ind, event in enumerate(self.scheduled_events):
            if (event.time - QUEUE_OPEN_TIME) < cur_time:
                #if self.started or self.gathering: #We can't start a new event while the current event is already going
                if self.gathering:
                    to_remove.append(ind)
                    await event.mogi_channel.send(f"Because there is an ongoing event right now, the following event has been removed: {self.get_event_str(event)}\n")
                else:
                    if self.started:
                        await self.endMogi()
                    to_remove.append(ind)
                    await self.launch_mogi(event.mogi_channel, event.size, True, event.time)
                    await self.unlockdown(event.mogi_channel)

        for ind in reversed(to_remove):
            del self.scheduled_events[ind]

    async def ongoing_mogi_checks(self):
            #If it's not automated, not started, we've already started making the rooms, don't run this
            if not self.is_automated or not self.started or self.making_rooms_run:
                return

            cur_time = datetime.now()
            if (self.start_time - QUEUE_OPEN_TIME + JOINING_TIME + EXTENSION_TIME) <= cur_time:
                await self.makeRoomsLogic(self.mogi_channel, (self.start_time.minute)%60, True)
                return

            if self.start_time - QUEUE_OPEN_TIME + JOINING_TIME <= cur_time:
                #check if there are an even amount of teams since we are past the queue time
                numLeftoverTeams = len(self.list) % int((12/self.size))
                if numLeftoverTeams == 0:
                    await self.makeRoomsLogic(self.mogi_channel, (self.start_time.minute)%60, True)
                    return
                else:
                    if int(cur_time.second / 20) == 0:
                        force_time = self.start_time - QUEUE_OPEN_TIME + JOINING_TIME + EXTENSION_TIME
                        minutes_left = int((force_time - cur_time).seconds/60)
                        x_teams = int(int(12/self.size) - numLeftoverTeams)
                        await self.mogi_channel.send(f"Need {x_teams} more team(s) to start immediately. Starting in {minutes_left} minute(s) regardless.")

    

    @tasks.loop(seconds=20.0)
    async def sqscheduler(self):
        """Scheduler that checks if it should start mogis and close them"""
        #It may seem silly to do try/except Exception, but this coroutine **cannot** fail
        #This coroutine *silently* fails and stops if exceptions aren't caught - an annoying abtraction of asyncio
        #This is unacceptable considering people are relying on these mogis to run, so we will not allow this routine to stop
        try:
            await self.scheduler_mogi_start()
        except Exception as e:
            print(e)

        try:
            await self.ongoing_mogi_checks()
        except Exception as e:
            print(e)

    async def queue_or_send(self, ctx, msg, delay=0):
        if config["queue_messages"] is True:
            self.msg_queue.append(msg)
        else:
            sentmsg = await ctx.send(msg)
            if delay > 0:
                await sentmsg.delete(delay=delay)

    @tasks.loop(seconds=config["sec_between_queue_msgs"])
    async def send_queued_messages(self):
        mogi_channel = self.get_mogi_channel()
        if mogi_channel is not None:
            if len(self.msg_queue) > 0:
                sentmsgs = []
                sentmsg = ""
                for i in range(len(self.msg_queue)-1, -1, -1):
                    sentmsg = self.msg_queue.pop(i) + "\n" + sentmsg
                    if len(sentmsg) > 1500:
                        #await mogi_channel.send(sentmsg)
                        sentmsgs.append(sentmsg)
                        sentmsg = ""
                #else:
                if len(sentmsg) > 0:
                    #await mogi_channel.send(sentmsg)
                    sentmsgs.append(sentmsg)
                for i in range(len(sentmsgs)-1, -1, -1):
                    await mogi_channel.send(sentmsgs[i])

    def get_mogi_channel(self):
        mogi_channel_id = config["mogichannel"]
        return self.bot.get_channel(mogi_channel_id)

    

    # the 4 functions below act as various checks for each of the bot commands.
    # if any of these are false, sends a message to the channel
    # and throws an exception to force the command to stop

    async def hasroles(self, ctx):
        for rolename in config["roles"]:
            for role in ctx.author.roles:
                if role.name == rolename:
                    return
        raise commands.MissingAnyRole(config["roles"])

    async def is_mogi_channel(self, ctx):
        if ctx.channel.id != config["mogichannel"]:
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
            await self.queue_or_send(ctx, "%s didn't tag the correct number of people for this format (%d)"
                            % (ctx.author.display_name, self.size-1), delay=5)
            return

        sheet = self.bot.get_cog('Sheet')

        # checking if message author is already in the mogi
        checkWait = await Mogi.check_waiting(self, ctx.author)
        checkList = await Mogi.check_list(self, ctx.author)
        if checkWait is not False:
            if self.waiting[checkWait][ctx.author][0] == True:
                await self.queue_or_send(ctx, "%s has already confirmed for this event; type `!d` to drop"
                                         % (ctx.author.display_name), delay=5)  
                return
        if checkList is not False:
            await self.queue_or_send(ctx, "%s has already confirmed for this event; type `!d` to drop"
                                     % (ctx.author.display_name), delay=5)  
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
                string = ("%s has confirmed for their squad [%d/%d]\n"
                          % (ctx.author.display_name, len(confirmedPlayers), self.size))
                if len(missingPlayers) > 0:
                          string += "Missing players: "
                          string += ", ".join([player.display_name for player in missingPlayers])
                
                #if player is the last one to confirm for their squad,
                #add them to the mogi list
                if len(missingPlayers) == 0:
                    squad = self.waiting[checkWait]
                    squad2 = {}
                    teamMsg = ""
                    totalMMR = 0
                    playerCount = 1
                    for player in squad.keys():
                        playerMMR = int(squad[player][1])
                        squad2[player] = playerMMR
                        totalMMR += playerMMR
                        teamMsg += "`%d.` %s (%d MMR)\n" % (playerCount, player.display_name, int(playerMMR))
                        playerCount += 1
                    self.avgMMRs.append(int(totalMMR/self.size))
                    self.waiting.pop(checkWait)
                    self.list.append(squad2)
                    if len(self.list) > 1:
                        s = "s"
                    else:
                        s = ""
                    string += ("`Squad successfully added to mogi list [%d team%s]`:\n%s"
                                   % (len(self.list), s, teamMsg))
                await self.queue_or_send(ctx, string)
                await self.ongoing_mogi_checks()
                return

            await self.queue_or_send(ctx, "%s didn't tag the correct number of people for this format (%d)"
                            % (ctx.author.display_name, self.size-1), delay=5)
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
                await self.queue_or_send(ctx, msg)
                return
            if member == ctx.author:
                await self.queue_or_send(ctx, "%s, Duplicate players are not allowed for a squad, please try again"
                                         % (ctx.author.mention))
                return
        if len(set(members)) < len(members):
            await self.queue_or_send(ctx, "%s, Duplicate players are not allowed for a squad, please try again"
                                     % (ctx.author.mention))
            return
            
        # logic for when the correct number of arguments are supplied
        # (self.size - 1)
        players = {ctx.author: [True]}
        lookupMembers = [ctx.author.display_name]
        lookupMembers += [member.display_name for member in members]
        #playerMMR = await sheet.mmr(ctx.author)
        playerMMRs = await sheet.mmr(lookupMembers)
        if playerMMRs[0] is False:
            await self.queue_or_send(ctx, "Error: MMR for player %s cannot be found! Please contact a staff member for help"
                                     % ctx.author.display_name, delay=10)
            return
        players[ctx.author].append(playerMMRs[0])
        for i in range(self.size-1):
            players[members[i]] = [False]
            #playerMMR = await sheet.mmr(members[i])
            if playerMMRs[i+1] is False:
                await self.queue_or_send(ctx, "Error: MMR for player %s cannot be found! Please contact a staff member for help"
                                         % members[i].display_name, delay=10)
                return
            players[members[i]].append(playerMMRs[i+1])
        self.waiting.append(players)
        
        msg = "%s has created a squad with " % ctx.author.display_name
        msg += ", ".join([player.display_name for player in members])
        msg += "; each player must type `!c` to join the queue [1/%d]\n" % (self.size)
        await self.queue_or_send(ctx, msg, delay=10)


           
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
            await self.queue_or_send(ctx, "%s is not currently in a squad for this event; type `!c @partnerNames`"
                                     % (ctx.author.display_name), delay=5)
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
        await self.queue_or_send(ctx, string, delay=5)

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

    #The caller is responsible to make sure the paramaters are correct
    async def launch_mogi(self, mogi_channel:discord.TextChannel, size: int, is_automated=False, start_time=None):       
        self.started = True
        self.gathering = True
        self.making_rooms_run = False
        self.is_automated = is_automated
        self.size = size
        self.waiting = []
        self.list = []
        self.avgMMRs = []

        if not is_automated:
            self.is_automated = False
            self.mogi_channel = None
            self.start_time = None
        else:
            self.is_automated = True
            self.mogi_channel = mogi_channel
            self.start_time = start_time

        await mogi_channel.send("A %dv%d mogi has been started - @here Type `!c`, `!d`, or `!list`" % (size, size))

    @commands.command()
    @commands.guild_only()
    async def start(self, ctx, size: int):
        """Start a mogi in the channel defined by the config file"""
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
        except:
            return
        if not await Mogi.start_input_validation(ctx, size):
            return False
        self.is_automated = False
        await self.launch_mogi(ctx.channel, size)

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
        self.is_automated = False
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
        self.is_automated = False
        await ctx.send("Mogi is now open; players can join and drop from the event")

    async def deleteChannels(self):
        for i in range(len(self.channels)-1, -1, -1):
            try:
                await self.channels[i][0].delete()
                self.channels.pop(i)
            except:
                pass
        for i in range(len(self.categories)-1, -1, -1):
            try:
                await self.categories[i].delete()
                self.categories.pop(i)
            except:
                pass  

    async def endMogi(self):
        await self.deleteChannels()
        self.started = False
        self.gathering = False
        self.making_rooms_run = False
        self.is_automated = False
        self.mogi_channel = None
        self.start_time = None
        self.waiting = []
        self.list = []
        self.avgMMRs = []

    @commands.command()
    async def remakeRooms(self, ctx, openTime:int):
        self.making_rooms_run = False
        await self.deleteChannels()
        await self.makeRooms(self, ctx, openTime)

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
        await self.endMogi()
        await ctx.send("%s has ended the mogi" % ctx.author.display_name)
            

    @commands.command(aliases=['l'])
    @commands.cooldown(1, 120)
    @commands.guild_only()
    async def list(self, ctx, mmrorder=""):
        """Display the list of confirmed squads for a mogi; sends 15 at a time to avoid
           reaching 2000 character limit"""
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        mogilist = self.list
        avgMMRs = self.avgMMRs
        if mmrorder.lower() == "mmr":
            indexes = range(len(self.avgMMRs))
            sortTeamsMMR = sorted(zip(self.avgMMRs, indexes), reverse=True)
            avgMMRs = [x for x, _ in sortTeamsMMR]
            mogilist = [self.list[i] for i in (x for _, x in sortTeamsMMR)]
        if len(mogilist) == 0:
            await(await ctx.send("There are no squads in the mogi - confirm %d players to join" % (self.size))).delete(delay=5)
            return
        msg = "`Mogi List`\n"
        for i in range(len(mogilist)):
            #safeguard against potentially reaching 2000-char msg limit
            if len(msg) > 1500:
                await ctx.send(msg)
                msg = ""
            msg += "`%d.` " % (i+1)
            msg += ", ".join([player.display_name for player in mogilist[i].keys()])
            msg += " (%d MMR)\n" % (avgMMRs[i])
        if(len(self.list) % (12/self.size) != 0):
            msg += ("`[%d/%d] teams for %d full rooms`"
                    % ((len(mogilist) % (12/self.size)), (12/self.size), int(len(mogilist) / (12/self.size))+1))
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
            await self.queue_or_send(ctx, "%s is not currently in a squad for this event; type `!c @partnerNames`"
                                     % (ctx.author.display_name), delay=5)
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

            await self.queue_or_send(ctx, msg, delay=30)
        else:
            myTeam = self.list[checkList]
            msg += ("`%s's squad [registered]`\n" % (ctx.author.display_name))
            for player in myTeam.keys():
                msg += ("`%d.` %s (%d MMR)\n"
                        % (playerNum, player.display_name, int(myTeam[player])))
                playerNum += 1
            await self.queue_or_send(ctx, msg, delay=30)

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

    async def makeRoomsLogic(self, mogi_channel:discord.TextChannel, openTime:int, startedViaAutomation=False):
        """Sorts squads into rooms based on average MMR, creates room channels and adds players to each room channel"""
        if self.making_rooms_run and startedViaAutomation: #Reduce race condition, but also allow manual !makeRooms
            return
        if startedViaAutomation:
            await self.lockdown(mogi_channel)
        
        self.making_rooms_run = True
        catNum = config["channels_per_category"]
        if self.gathering:
            self.gathering = False
            await mogi_channel.send("Mogi is now closed; players can no longer join or drop from the event")

        numRooms = int(len(self.list) / (12/self.size))
        if numRooms == 0:
            await mogi_channel.send("Not enough players to fill a room! Try this command with at least %d teams" % int(12/self.size))
            return

        if openTime >= 60 or openTime < 0:
            await mogi_channel.send("Please specify a valid time (in minutes) for rooms to open (00-59)")
            return
        penTime = openTime + 5
        startTime = openTime + 10
        while penTime >= 60:
            penTime -= 60
        while startTime >= 60:
            startTime -= 60
            
        numTeams = int(numRooms * (12/self.size))
        finalList = self.list[0:numTeams]
        finalMMRs = self.avgMMRs[0:numTeams]

        indexes = range(len(finalMMRs))
        sortTeamsMMR = sorted(zip(finalMMRs, indexes), reverse=True)
        sortedMMRs = [x for x, _ in sortTeamsMMR]
        sortedTeams = [finalList[i] for i in (x for _, x in sortTeamsMMR)]
        for i in range(int(numRooms/catNum)+1):
            cat = await mogi_channel.guild.create_category_channel(name="Rooms %d" % (i+1),
                                                                   position=config["channel_category_position"])
            self.categories.append(cat)
        for i in range(numRooms):

            #creating room roles and channels
            roomName = "Room %d" % (i+1)
            #category = mogi_channel.category
            category = self.categories[int(i/catNum)]
            overwrites = {
                mogi_channel.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                mogi_channel.guild.me: discord.PermissionOverwrite(read_messages=True)
            }
            
            #tries to retrieve all these roles, and add them to the
            #channel overwrites if the role specified in the config file exists
            for bot_role_id in config["roles_for_channels"]:
                bot_role = mogi_channel.guild.get_role(bot_role_id)
                if bot_role is not None:
                    overwrites[bot_role] = discord.PermissionOverwrite(read_messages=True)
            

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
                scoreboard += ",".join([player.display_name for player in sortedTeams[index].keys()])
                if j+1 < int(12/self.size):
                    scoreboard += ","
            
            roomMsg += "%s`\n" % scoreboard
            roomMsg += ("\nDecide a host amongst yourselves; room open at :%02d, penalty at :%02d, start by :%02d. Good luck!\n\n"
                        % (openTime, penTime, startTime))
            roomMsg += mentions
            try:
                roomChannel = await category.create_text_channel(name=roomName, overwrites=overwrites)
                self.channels.append([roomChannel, False])
                await roomChannel.send(roomMsg)
            except Exception as e:
                errMsg = f"\nAn error has occurred while creating the room channel; please contact your opponents in DM or another channel\n"
                errMsg += mentions
                msg += errMsg
            await mogi_channel.send(msg)
            
        if numTeams < len(self.list):
            missedTeams = self.list[numTeams:len(self.list)]
            missedMMRs = self.avgMMRs[numTeams:len(self.list)]
            msg = "`Late teams:`\n"
            for i in range(len(missedTeams)):
                msg += "`%d.` " % (i+1)
                msg += ", ".join([player.display_name for player in missedTeams[i].keys()])
                msg += " (%d MMR)\n" % missedMMRs[i]
            await mogi_channel.send(msg)

    @commands.command()
    @commands.bot_has_guild_permissions(manage_channels=True)
    @commands.guild_only()
    async def makeRooms(self, ctx, openTime: int):
        await Mogi.hasroles(self, ctx)
        try:
            await Mogi.is_mogi_channel(self, ctx)
            await Mogi.is_started(self, ctx)
        except:
            return
        await self.makeRoomsLogic(ctx.channel, openTime)


    @commands.command()
    @commands.bot_has_guild_permissions(manage_channels=True)
    @commands.guild_only()
    async def finish(self, ctx):
        """Finishes the room by adding a checkmark to the channel. Anyone in the room can call this command."""
        current_channel = ctx.channel
        for index, (channel, isFinished) in enumerate(self.channels):
            if current_channel == channel:
                if not isFinished:
                    await current_channel.edit(name=current_channel.name + CHECKMARK_ADDITION)
                    self.channels[index] = [current_channel, True]
       
       
    @staticmethod
    async def start_input_validation(ctx, size:int):
        valid_sizes = [2, 3, 4, 6]
        if size not in valid_sizes:
            await(await ctx.send("The size you entered is invalid; proper values are: 2, 3, 4")).delete(delay=5)
            return False
        
        return True 
                   
                                      
    @commands.command()
    @commands.guild_only()
    async def schedule(self, ctx, size: int, *, schedule_time:str):
        """Schedules a room in the future so that the staff doesn't have to be online to open the mogi and make the rooms"""
        
        await Mogi.hasroles(self, ctx)
        
        if not await Mogi.start_input_validation(ctx, size):
            return False
              
        try:
            actual_time = parse(schedule_time)
            actual_time = actual_time - TIME_ADJUSTMENT
            mogi_channel = self.get_mogi_channel()
            if mogi_channel == None:
                ctx.send("I can't see the mogi channel, so I can't schedule this event.")
                return
            event = Scheduled_Event(size, actual_time, False, mogi_channel)
            
            self.scheduled_events.append(event)
            self.scheduled_events.sort(key=lambda data:data.time)
            await ctx.send(f"Scheduled {Mogi.get_event_str(event)}")
        except (ValueError, OverflowError):
            await ctx.send("I couldn't figure out the date and time for your event. Try making it a bit more clear for me.")

    @commands.command(aliases=['pt'])
    async def parsetime(self, ctx, *, schedule_time:str):
        try:
            actual_time = parse(schedule_time)
            await ctx.send("```<t:" + str(int(time.mktime(actual_time.timetuple()))) + ":F>```")
        except (ValueError, OverflowError):
            await ctx.send("I couldn't figure out the date and time for your event. Try making it a bit more clear for me.")
        
    @commands.command()
    @commands.guild_only()
    async def view_schedule(self, ctx):
        """Displays the schedule"""
        await Mogi.hasroles(self, ctx)
        
        if len(self.scheduled_events) == 0:
            await ctx.send("There are currently no schedule events. Do `!schedule` to schedule a future event.")
        else:
            event_str = ""
            for ind, this_event in enumerate(self.scheduled_events, 1):
                event_str += f"`{ind}.` {Mogi.get_event_str(this_event)}\n"
            event_str += "\nDo `!remove_event` to remove that event from the schedule."
            await ctx.send(event_str)
            
    @commands.command()
    @commands.guild_only()
    @commands.max_concurrency(number=1,wait=True)
    async def remove_event(self, ctx, event_num: int):
        """Removes an event from the schedule"""
        await Mogi.hasroles(self, ctx)
        
        if event_num < 1 or event_num > len(self.scheduled_events):
            await ctx.send("This event number isn't in the schedule. Do `!view_schedule` to see the scheduled events.")
        else:
            removed_event = self.scheduled_events.pop(event_num-1)
            await ctx.send(f"Removed `{event_num}.` {self.get_event_str(removed_event)}")
    
        
    @staticmethod
    def get_event_str(this_event):
        event_size, event_time = this_event.size, this_event.time
        timezone_adjusted_time = event_time + TIME_ADJUSTMENT
        event_time_str = timezone_adjusted_time.strftime(time_print_formatting)
        return f"{event_size}v{event_size} on {event_time_str}"
                  

def setup(bot):
    bot.add_cog(Mogi(bot))
