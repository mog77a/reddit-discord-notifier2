# For hosting on Heroku we'll need to use the OS library to pull the Token
# from the Enviroment Variables

import os
import asyncio
import asyncpraw
import discord
import aiohttp
import psycopg2
import datetime
import urllib.parse
from discord.ext import commands
import random

from dotenv import load_dotenv
load_dotenv()


# Add subreddits to check. Make sure the API calls don't exceed 1/sec
subs = ['hardwareswap', 'buildapcsales']

# global filter enable. Turn off to grab every post
global_filter_enable = True

# Add in an entry to the filter for each subreddit if applicable and an icon as it is used in the embed to help glancability
keyword_filter = {'buildapcsales': {'enabled': False,
                                    'filter': ['Nvidia', 'AMD', 'Intel', 'ssd'],
                                    'icon': "https://styles.redditmedia.com/t5_2s3dh/styles/communityIcon_bf4ya2rtdaz01.png?width=256&s=76feb45fa3beb2c72b1ce635a0cd311dfb5d1cd3"},
                  'hardwareswap': {'enabled': True,
                                   'filter': ['nvidia', 'RTX', 'RX', 'AMD', 'ryzen', 'Intel', 'Apple', 'ip', 'i7', 'i9', 'laptop', 'macbook'],
                                   'icon': "https://styles.redditmedia.com/t5_2skrs/styles/communityIcon_pgwod7arn6a41.png?width=256&s=41d29ecd84c93b91b3cdf992ba43262d51aef410"}}

# lowercase everything for easy comparison
for k, v in keyword_filter.items():
    keyword_filter[k]['filter'] = [x.lower()
                                   for x in keyword_filter[k]['filter']]

PAYPAL_EMAIL = os.environ['PAYPAL_EMAIL']
token = os.environ['DISCORDBOT_TOKEN']
DATABASE_URL = os.environ['DATABASE_URL']
channelid = os.environ['CHANNEL_ID']
bot = commands.Bot(command_prefix="!")
username = os.environ['BOTONE_USERNAME']
password = os.environ['BOTONE_PASSWORD']
client_id = os.environ['BOTONE_ID']
client_secret = os.environ['BOTONE_SECRET']
user_agent = os.environ['BOTONE_AGENT']


reddit = asyncpraw.Reddit(client_id=client_id,
                          client_secret=client_secret,
                          password=password,
                          username=username,
                          user_agent=user_agent,
                          read_only=True,)


async def webhook_coroutine(post):
    async with aiohttp.ClientSession() as session:
        # create an async session with a webhook
        webhook = discord.Webhook.from_url(
            os.environ['DISCORD_WEBHOOK'], adapter=discord.AsyncWebhookAdapter(session))

        sub = f"{post.subreddit}"
        title = f"{post.title}"
        title = title[0:100]
        title = urllib.parse.quote(title)
        message = f"Hello!\nI am interested in buying delete_and_type_inquiry_here_dont_forget_title\n\nMy Paypal for an invoice request through [Paypal goods and services](https://www.paypal.com/myaccount/transfer/homepage/request) is:\n{PAYPAL_EMAIL}\n\n\nShipping address is handled through Paypal.\n\nThanks!"
        message = urllib.parse.quote(message)
        icon_url = keyword_filter[sub]['icon']

        url = f"https://reddit.com/message/compose/?to={post.author}&subject={title}&message={message}"
        # random color
        randColor = random.randint(0, 0xFFFFFF)
        # Create a discord embed
        post_url = f"https://reddit.com{post.permalink}"

        # descriptions length handling
        description = f"{post_url}\n\n{post.selftext}"
        if len(description) > 4096:
            description = description[0:4096]

        if (sub == 'hardwareswap'):
            embed = discord.Embed(title=post.title, url=url,
                                  color=randColor, description=description, timestamp=datetime.datetime.now())
        else:
            embed = discord.Embed(title=post.title, url=post.url,
                                  color=randColor, description=description, timestamp=datetime.datetime.now())

        embed.set_thumbnail(url=icon_url)
        embed.set_author(name=f"r/{post.subreddit}")
        embed.set_footer(text=f"u/{post.author}")
        await webhook.send(embed=embed)
        print("[NEW POST]r/{0}: {1}\n".format(post.subreddit, post.title))


async def reddit_channel(subreddits, reddit):
    channel = bot.get_channel(channelid)

    num_subreddits = 0
    while True:
        # create the subreddit string for asyncpraw
        if num_subreddits != len(subreddits):
            s = '+'.join(subreddits)
            num_subreddits = len(subreddits)
            print("Scraping subreddits: {0}".format(s))

        # grab the top posts
        posts = await ScrapePosts(s, reddit)
        # check the posts if a new post has been made and it matches the keywords
        await check_posts(posts)

        await asyncio.sleep(random.randint(len(subs)*3, len(subs)*4))


async def check_posts(posts):
    # Look through posts and check if they contain the keywords
    for p in posts:
        # check if post exists in the database
        post_exists = await database_post_check(p)
        if post_exists is False:
            # check global filter enable
            if global_filter_enable:
                sub = f"{p.subreddit}"
                # check the individual subreddit filter enable
                if keyword_filter[sub]['enabled']:
                    # check if the post contains any of the keywords
                    if any(x in p.title.lower() for x in keyword_filter[sub]['filter']):
                        print(f"Match found in r/{sub}: {p.title})")
                        await webhook_coroutine(p)
                    elif any(x in p.selftext.lower() for x in keyword_filter[sub]['filter']):
                        print(f"Match found in r/{sub}: {p.title})")
                        await webhook_coroutine(p)

                else:
                    await webhook_coroutine(p)

            else:
                await webhook_coroutine(p)
        else:
            print(F"{datetime.datetime.now()}: No new posts found")


async def database_post_check(post):

    ''' Checks if the post is already in the database, if not it will add it to the database and send a notification'''
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    # Creating a cursor (a DB cursor is an abstraction, meant for data set traversal)
    cur = conn.cursor()
    # Executing your PostgreSQL query
    select_query = "SELECT EXISTS (SELECT 1 from redditpostalerts WHERE post_id = '" + str(
        post.id) + "');"
    cur.execute(select_query)

    post_id = cur.fetchone()[0]
    if post_id is False:

        insert_query = "INSERT INTO redditpostalerts (post_id) VALUES ('" + str(
            post.id) + "');"
        cur.execute(insert_query)

        delete_older_than_1_day_query = "DELETE FROM redditpostalerts WHERE timestamp < NOW() - INTERVAL '1 DAY';"
        cur.execute(delete_older_than_1_day_query)

        # In order to make the changes to the database permanent, we now commit our changes
        conn.commit()

    # We have committed the necessary changes and can now close out our connection
    cur.close()
    conn.close()
    return post_id


async def ScrapePosts(subreddits, reddit, num_posts_toLoad=len(subs) * 1):
    posts = []

    try:

        reddits = await reddit.subreddit(subreddits)

        # checks for any new post
        async for submission in reddits.new(limit=num_posts_toLoad):
            posts.append(submission)

    except Exception as e:
        print("ScrapeError, Function input: {0} | {1}".format(subs, e))
    return posts


channel = bot.get_channel(channelid)


@ bot.event
async def on_ready():
    global reddit
    global subs
    print(f'{bot.user} has connected to Discord!')

    channel = bot.get_channel(channelid)
    print("Connected to channel: {0}".format(channel))

    channel_array = []
    for guild in bot.guilds:
        for channel in guild.channels:

            channel_array.append(channel)
    await reddit_channel(subs, reddit)


bot.run(token)
