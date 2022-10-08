# For hosting on Heroku we'll need to use the OS library to pull the Token
# from the Enviroment Variables

from asyncio.windows_events import NULL
from dotenv import load_dotenv
import os
import asyncio
import asyncpraw
import discord
import aiohttp
import psycopg2
import datetime
import urllib.parse
from discord.ext import commands
import logging
import random

root = logging.getLogger()
root.setLevel(logging.INFO)

load_dotenv()


# Add subreddits to check. Make sure the API calls don't exceed 1/sec
subs = ['hardwareswap', 'buildapcsales', 'appleswap']

# global filter enable. Turn off to grab every post
global_filter_enable = True

# Add in an entry to the filter for each subreddit if applicable and an icon as it is used in the embed to help glancability
keyword_filter = {'buildapcsales': {'enabled': False,
                                    'filter': ['Nvidia', 'AMD', 'Intel', 'ssd'],
                                    'icon': "https://styles.redditmedia.com/t5_2s3dh/styles/communityIcon_bf4ya2rtdaz01.png?width=256&s=76feb45fa3beb2c72b1ce635a0cd311dfb5d1cd3"},
                  'hardwareswap': {'enabled': True,
                                   'filter': ['nvidia', 'RTX', 'RX', 'AMD', 'ryzen', 'Intel', 'Apple', 'ip', 'i7', 'i9', 'laptop', 'macbook'],
                                   'icon': "https://styles.redditmedia.com/t5_2skrs/styles/communityIcon_pgwod7arn6a41.png?width=256&s=41d29ecd84c93b91b3cdf992ba43262d51aef410"},
                  'appleswap': {'enabled': False,
                                'filter': [],
                                'icon': "https://a.thumbs.redditmedia.com/a3ssBgNxKSiiSdelZRriwweMNZXKZwt-rwZgz-oUA98.png"}}

# lowercase everything for easy comparison
for k, v in keyword_filter.items():
    keyword_filter[k]['filter'] = [x.lower()
                                   for x in keyword_filter[k]['filter']]

PAYPAL_EMAIL = os.environ['PAYPAL_EMAIL']
token = os.environ['DISCORDBOT_TOKEN']
DATABASE_URL = os.environ['DATABASE_URL']
channelid = os.environ['CHANNEL_ID']
bot = commands.Bot(command_prefix="!")
client_id = os.environ['BOTONE_ID']
client_secret = os.environ['BOTONE_SECRET']
user_agent = os.environ['BOTONE_AGENT']


reddit = asyncpraw.Reddit(client_id=client_id,
                          client_secret=client_secret,
                          refresh_token=os.environ['BOTONE_REFRESH'],
                          user_agent=user_agent)


async def webhook_coroutine(post):
    async with aiohttp.ClientSession() as session:
        # create an async session with a webhook
        webhook = discord.Webhook.from_url(
            os.environ['DISCORD_WEBHOOK'], adapter=discord.AsyncWebhookAdapter(session))

        sub = f"{post.subreddit}"
        discord_title = f"(r/{sub}){post.title}"
        discord_title = discord_title[0:100]
        parsed_title = post.title[0:100]
        parsed_title = urllib.parse.quote(parsed_title)
        message = f"Hello!\nI am interested in buying delete_and_type_inquiry_here_dont_forget_title\n\nMy Paypal for an invoice request through [Paypal goods and services](https://www.paypal.com/myaccount/transfer/homepage/request) is:\n{PAYPAL_EMAIL}\n\n\nShipping address is handled through Paypal.\n\nThanks!"
        message = urllib.parse.quote(message)
        icon_url = keyword_filter[sub]['icon']

        url = f"https://reddit.com/message/compose/?to={post.author}&subject={parsed_title}&message={message}"
        # random color
        randColor = random.randint(0, 0xFFFFFF)
        # Create a discord embed
        post_url = f"https://reddit.com{post.permalink}"

        # descriptions length handling
        description = f"{post_url}\n\n{post.selftext}"
        if len(description) > 4096:
            description = description[0:4096]

        if (sub in ['hardwareswap', 'appleswap']):
            embed = discord.Embed(title=discord_title, url=url,
                                  color=randColor, description=description, timestamp=datetime.datetime.utcnow())
        else:
            embed = discord.Embed(title=discord_title, url=post.url,
                                  color=randColor, description=description, timestamp=datetime.datetime.utcnow())

        embed.set_thumbnail(url=icon_url)
        embed.set_author(name=f"r/{post.subreddit}")
        embed.set_footer(text=f"u/{post.author}")
        await webhook.send(embed=embed)
        # print("[NEW POST]r/{0}: {1}\n".format(post.subreddit, post.title))


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
        print(F"{datetime.datetime.now()}: Scraping new posts")
        posts = await ScrapePosts(s, reddit)
        # check the posts if a new post has been made and it matches the keywords
        await check_posts(posts)
        print('\n')

        await asyncio.sleep(random.randint(len(subs)*3, len(subs)*4))


async def check_posts(posts):
    # Look through posts and check if they contain the keywords
    try:
        print(F"{datetime.datetime.now()}: Checking for posts in database")
        post_ids_exist = await database_multiple_post_check(posts)
        for p in posts:
           # check if post exists in the database
            if post_ids_exist[p.id] is False:
                # check global filter enable
                if global_filter_enable:
                    sub = f"{p.subreddit}"
                    # check the individual subreddit filter enable
                    if keyword_filter[sub]['enabled']:
                        # check if the post contains any of the keywords
                        if any(x in p.title.lower() for x in keyword_filter[sub]['filter']):
                            print(
                                f"{datetime.datetime.now()}: Match found in r/{sub}: {p.title}")
                            await webhook_coroutine(p)
                        elif any(x in p.selftext.lower() for x in keyword_filter[sub]['filter']):
                            print(
                                f"{datetime.datetime.now()}: Match found in r/{sub}: {p.title}")
                            await webhook_coroutine(p)

                    else:
                        await webhook_coroutine(p)

                else:
                    await webhook_coroutine(p)
            else:
                print(F"{datetime.datetime.now()}: No new posts found")
    except Exception as e:
        print(e)


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


async def database_multiple_post_check(posts):
    ''' Checks if the multiple posts are in the database and returns a true/false value for each post
        If false insert the post id into the database and remove any posts older than 1 day'''

    # Dictionary to hold the post id and a boolean value if it exists in the database
    post_ids_exist = {post.id: True for post in posts}

    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    # Creating a cursor (a DB cursor is an abstraction, meant for data set traversal)
    cur = conn.cursor()

    # values constructor
    string2 = ", ".join(f"('{x}')" for x in post_ids_exist)

    # Query that returns missing ids in database
    select_query = f"(WITH v(id) as (VALUES{string2}) select v.id from v left join redditpostalerts i on i.post_id = v.id where i.post_id is null);"

    cur.execute(select_query)
    missing_ids = cur.fetchall()

    # update the database with missing ids
    if missing_ids:
        # unwrap the tuples in list
        missing_ids = [x[0] for x in missing_ids]
        # values constructor
        string = ", ".join(f"('{x}')" for x in missing_ids)

        # insert missing ids into database
        insert_query = f"INSERT INTO redditpostalerts (post_id) VALUES {string};"
        cur.execute(insert_query)

        # set the missings id values to false
        for id in missing_ids:
            post_ids_exist[id] = False

    # remove posts older than 1 day
    delete_older_than_1_day_query = "DELETE FROM redditpostalerts WHERE timestamp < NOW() - INTERVAL '1 DAY';"
    cur.execute(delete_older_than_1_day_query)

    # In order to make the changes to the database permanent, we now commit our changes
    conn.commit()

    # We have committed the necessary changes and can now close out our connection
    cur.close()
    conn.close()

    return post_ids_exist


async def ScrapePosts(subreddits, reddit, num_posts_toLoad=len(subs) * 1):
    posts = []
    # print(await reddit.user.me())
    try:

        reddits = await reddit.subreddit(subreddits)
        print(reddits)

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
