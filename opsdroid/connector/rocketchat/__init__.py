"""A connector for Rocket.Chat."""
import asyncio
import logging
import datetime
import aiohttp

from opsdroid.connector import Connector
from opsdroid.message import Message

_LOGGER = logging.getLogger(__name__)
API_PATH = '/api/v1/'


class RocketChat(Connector):
    """A connector for the chat service Rocket.Chat."""

    def __init__(self, config, opsdroid=None):
        """Create the connector.

        Sets up logic for the Connector class, gets data from
            the config.yaml or adds default values.

        Args:
            opsdroid (OpsDroid): An instance of opsdroid.core.
            config (dict): configuration settings from the
                file config.yaml.

        """
        super().__init__(config, opsdroid=opsdroid)
        self.name = "rocket.chat"
        self.config = config
        self.default_room = config.get("default-room", "general")
        self.group = config.get("group", None)
        self.url = config.get("channel-url", "https://open.rocket.chat")
        self.update_interval = config.get("update-interval", 1)
        self.bot_name = config.get("bot-name", "opsdroid")
        self.listening = True
        self.latest_update = datetime.datetime.utcnow().isoformat()

        try:
            self.user_id = config['user-id']
            self.token = config['token']
            self.headers = {
                'X-User-Id': self.user_id,
                "X-Auth-Token": self.token,
            }
        except (KeyError, AttributeError):
            _LOGGER.error("Unable to login: Access token is missing. "
                          "Rocket.Chat connector will not be available.")

    def build_url(self, method):
        """Build the url to connect with api.

        Helper function to build the url to interact with the
        Rocket.Chat REST API. Uses the global variable API_PATH
        that points to current api version. (example: /api/v1/)

        Args:
            method (string): Api call endpoint.

        Return:
            String that represents full API url.

        """
        return "{}{}{}".format(self.url, API_PATH, method)

    async def connect(self):
        """Connect to the chat service.

        This method is used to text if the connection to the chat
        service is successful. If the connection is successful
        the response is a JSON format containing information
        about the user. Other than the user username, the
        information is not used.

        """
        _LOGGER.info("Connecting to Rocket.Chat")

        async with aiohttp.ClientSession() as session:
            resp = await session.get(self.build_url('me'),
                                     headers=self.headers)
            if resp.status != 200:
                _LOGGER.error("Unable to connect.")
                _LOGGER.error("Rocket.Chat error %s, %s",
                              resp.status, resp.text)
            else:
                json = await resp.json()
                _LOGGER.debug("Connected to Rocket.Chat as %s",
                              json["username"])

    async def _parse_message(self, response):
        """Parse the message received.

        Args:
            response (dict): Response returned by aiohttp.Client.

        """
        if response['messages']:
            message = Message(
                response['messages'][0]['msg'],
                response['messages'][0]['u']['username'],
                response['messages'][0]['rid'],
                self)
            _LOGGER.debug("Received message from Rocket.Chat %s",
                          response['messages'][0]['msg'])

            await self.opsdroid.parse(message)
            self.latest_update = response['messages'][0]['ts']

    async def _get_message(self):
        """Connect to the API and get messages.

        This method will only listen to either a channel or a
        private room called groups by Rocket.Chat. If a group
        is specified in the config then it takes priority
        over a channel.

        """
        if self.group:
            url = self.build_url('groups.history?roomName={}'.format(
                self.group))
            self.default_room = self.group
        else:
            url = self.build_url('channels.history?roomName={}'.format(
                self.default_room))

        if self.latest_update:
            url += '&oldest={}'.format(self.latest_update)

        async with aiohttp.ClientSession() as session:
            resp = await session.get(url,
                                     headers=self.headers)

            if resp.status != 200:
                _LOGGER.error("Rocket.Chat error %s, %s",
                              resp.status, resp.text)
                self.listening = False
            else:
                json = await resp.json()
                await self._parse_message(json)

    async def listen(self):
        """Listen for and parse new messages.

        The method will sleep asynchronously at the end of
        every loop. The time can either be specified in the
        config.yaml with the param update-interval - this
        defaults to 1 second.

        If the channel didn't get any new messages opsdroid
        will still call the REST API, but won't do anything.

        """
        while self.listening:
            await self._get_message()
            await asyncio.sleep(self.update_interval)

    async def respond(self, message, room=None):
        """Respond with a message.

        The message argument carries both the text to reply with but
        also which room to reply with depending of the roomId(rid) got
        from the _parse_message method.

        Args:
            message (object): An instance of Message
            room (string, optional): Name of the room to respond to.

        """
        _LOGGER.debug("Responding with: %s", message.text)
        async with aiohttp.ClientSession() as session:
            data = {}
            data['channel'] = message.room
            data['alias'] = self.bot_name
            data['text'] = message.text
            data['avatar'] = ''
            resp = await session.post(
                self.build_url('chat.postMessage'),
                headers=self.headers,
                data=data)

            if resp.status == 200:
                _LOGGER.debug('Successfully responded')
            else:
                _LOGGER.debug("Error - %s: Unable to respond", resp.status)
