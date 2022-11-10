# maubot-webhook - A maubot plugin to send messages using webhooks
# Copyright (C) 2022 maubot-webhook Contributors
#
# This file is part of maubot-webhook.
#
# maubot-webhook is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# maubot-webhook is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with maubot-webhook. If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import string
from typing import Dict, Type, Union

from maubot import Plugin
from aiohttp import hdrs
from aiohttp.web import Request, Response
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("path")
        helper.copy("method")
        helper.copy("room")
        helper.copy("message")
        helper.copy("auth_token")
        helper.copy("markdown")


class WebhookPlugin(Plugin):

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config

    async def start(self) -> None:
        self.config.load_and_update()
        path = self.config["path"]
        self.webapp.add_route(self.config["method"], path, self.handle_request)
        self.log.info(f"Webhook available at: {self.webapp_url}{path}")

    def substitute_config_template(self, config_key: str, formatting: Dict[str, str]) -> Union[str, Response]:
        try:
            return string.Template(self.config[config_key]).substitute(formatting)
        except ValueError as e:
            error_message = f"Error substituting config value '{config_key}': {e}"
            self.log.error(error_message)
            return Response(status=500, text=error_message)
        except KeyError as e:
            key = e.args[0]
            if key.startswith("query_"):
                return Response(status=400, text=f"Missing query parameter: {key[6:]}")
            error_message = "Missing {} parameter '{}' for config value '{}'! This is a configuration error.".format(
                    *(("path", key[5:]) if key.startswith("path_") else ("formatting", key)), config_key)
            self.log.error(error_message)
            return Response(status=500, text=error_message)

    async def handle_request(self, req: Request) -> Response:
        self.log.debug(f"Got request {req}")
        if self.config["auth_token"] is not None:
            if hdrs.AUTHORIZATION not in req.headers:
                return Response(status=401, text="Missing authorization header")
            auth_type, auth_token = req.headers.get(hdrs.AUTHORIZATION).split(' ', 1)
            if auth_type != "Bearer":
                return Response(status=401, text=f"Unsupported authorization type: {auth_type}")
            if auth_token != self.config["auth_token"]:
                return Response(status=401, text="Invalid authorization token")
            self.log.debug(f"Auth token is valid")

        formatting = {"path_" + k: v for k, v in req.match_info.items()}
        formatting.update({"query_" + k: v for k, v in req.rel_url.query.items()})
        formatting["body"] = await req.text()

        room = self.substitute_config_template("room", formatting)
        message = self.substitute_config_template("message", formatting)
        if isinstance(room, Response):
            return room
        if isinstance(message, Response):
            return message

        self.log.info(f"Sending message to room {room}: {message}")
        try:
            await (self.client.send_markdown if self.config["markdown"] else self.client.send_text)(room, message)
        except Exception as e:
            error_message = f"Failed to send message '{message}' to room {room}: {e}"
            self.log.error(error_message)
            return Response(status=500, text=error_message)
        return Response()
