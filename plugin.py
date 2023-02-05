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
from aiohttp import hdrs, BasicAuth
from aiohttp.web import Request, Response
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        if "auth_type" not in self and "auth_token" in self:
            helper.base["auth_type"] = "Bearer"

        valid_auth_types = {"Basic", "Bearer"}
        auth_type = self["auth_type"]
        if auth_type is not None:
            auth_type = auth_type.capitalize()
            if auth_type not in valid_auth_types:
                raise ValueError(f"Invalid auth_type '{auth_type}' specified! Only {' and '.join(valid_auth_types)} "
                                 "are supported.")
            auth_token = self["auth_token"]
            if auth_token is None:
                raise ValueError(f"No auth_token specified!")
            if auth_type == "Basic" and ":" not in auth_token:
                raise ValueError(f"Invalid auth_token '{auth_token}' specified! For HTTP basic auth, it must contain "
                                 "a username and a password, separated by a colon (<username>:<password>).")

        helper.copy("path")
        helper.copy("method")
        helper.copy("room")
        helper.copy("message")
        helper.copy("auth_type")
        helper.copy("auth_token")
        helper.copy("markdown")
        helper.copy("force_json")


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
            if key.startswith(("query_", "json_")):
                param_type = key.split('_', 1)[0]
                return Response(status=400, text=f"Missing {param_type} parameter: {key[len(param_type) + 1:]}")
            error_message = "Missing {} parameter '{}' for config value '{}'! This is a configuration error.".format(
                    *(("path", key[5:]) if key.startswith("path_") else ("formatting", key)), config_key)
            self.log.error(error_message)
            return Response(status=500, text=error_message)

    async def handle_request(self, req: Request) -> Response:
        self.log.debug(f"Got request {req}")
        config_auth_type = self.config["auth_type"]

        def unauthorized(text):
            return Response(status=401, headers={hdrs.WWW_AUTHENTICATE: config_auth_type}, text=text)

        if config_auth_type is not None:
            config_auth_type = config_auth_type.capitalize()
            if hdrs.AUTHORIZATION not in req.headers:
                return unauthorized("Missing authorization header")
            auth_header = req.headers.get(hdrs.AUTHORIZATION)
            auth_header_split = auth_header.split(' ', 1)
            if len(auth_header_split) < 2:
                return unauthorized("Invalid authorization header format")
            auth_type, auth_token = auth_header_split
            auth_type = auth_type.capitalize()
            config_auth_token = self.config["auth_token"]
            if auth_type != config_auth_type:
                return unauthorized(f"Unsupported authorization type: {auth_type}")
            if auth_type == "Basic":
                try:
                    basic_auth_header = BasicAuth.decode(auth_header)
                except ValueError as e:
                    return unauthorized(f"Invalid authorization header format: {e}")
                if BasicAuth(*config_auth_token.split(":", 1)) != basic_auth_header:
                    return unauthorized("Invalid username or password")
            elif auth_type == "Bearer" and auth_token != config_auth_token:
                return unauthorized("Invalid authorization token")
            self.log.debug(f"Auth token is valid")

        formatting = {"path_" + k: v for k, v in req.match_info.items()}
        formatting.update({"query_" + k: v for k, v in req.rel_url.query.items()})
        formatting["body"] = await req.text()

        if req.content_type == "application/json" or self.config["force_json"]:
            try:
                json = await req.json()
            except ValueError as e:
                error_message = f"Failed to parse JSON: {e}"
                return Response(status=401, text=error_message)
            for k, v in json.items():
                if not isinstance(v, (int, float, str)):
                    self.log.warning(f"Skipping JSON value with key '{k}', since it's not an int, float or string: {v}")
                    continue
                formatting.update({"json_" + k: v})

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
