# maubot-webhook - A maubot plugin to send messages using webhooks
# Copyright (C) 2024 maubot-webhook Contributors
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

from typing import Dict, Optional, Type, Union

from maubot import Plugin, PluginWebApp
from aiohttp import hdrs, BasicAuth
from aiohttp.web import Request, Response
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper
import mautrix.types
import jinja2


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        # migrate in source config as it allows us to "decouple"
        # the copy-part from the migration

        # 0.1.0 -> 0.2.0 migration: auth_type added
        # set auth_type as 'Bearer' if auth_token is set in source config
        if "auth_type" not in self and "auth_token" in self:
            self["auth_type"] = "Bearer"

        # 0.2.0 -> 0.3.0 migration: markdown option replaced by message_format
        # set message_format as 'markdown' if markdown is true in source config
        if "message_format" not in self and self["markdown"]:
            self["message_format"] = "markdown"

        # copy values to base config
        helper.copy("path")
        helper.copy("method")
        helper.copy("room")
        helper.copy("message")
        helper.copy("message_format")
        helper.copy("auth_type")
        helper.copy("auth_token")
        helper.copy("force_json")
        helper.copy("ignore_empty_messages")

        # validate base config as it also contains default values
        # for options not present in the source config.

        # validate message_format
        valid_message_formats = {"markdown", "plaintext", "html"}
        message_format = helper.base["message_format"]
        if message_format not in valid_message_formats:
            raise ValueError(f"Invalid message_format '{message_format}' specified! "
                             f"Must be one of: {', '.join(valid_message_formats)}")

        # validate auth_type and auth_token
        valid_auth_types = {"Basic", "Bearer"}
        auth_type = helper.base["auth_type"]
        if auth_type is not None:
            auth_type = auth_type.capitalize()
            if auth_type not in valid_auth_types:
                raise ValueError(f"Invalid auth_type '{auth_type}' specified! "
                                 f"Must be one of: {', '.join(valid_auth_types)}")
            auth_token = helper.base["auth_token"]
            if auth_token is None:
                raise ValueError("No auth_token specified!")
            if auth_type == "Basic" and ":" not in auth_token:
                raise ValueError(f"Invalid auth_token '{auth_token}' specified! For HTTP basic auth, it must contain "
                                 "a username and a password, separated by a colon (<username>:<password>).")


class WebhookPlugin(Plugin):
    # config and webapp are declared as Optional in the superclass,
    # as not every plugin is configurable and offers a webapp.
    # Re-declare these variables here for the typecheckers sake.
    config: BaseProxyConfig
    webapp: PluginWebApp

    @classmethod
    def get_config_class(cls) -> Type[BaseProxyConfig]:
        return Config

    def on_external_config_update(self) -> None:
        old_path, old_method = self.config["path"], self.config["method"]
        old_room, old_message = self.config["room"], self.config["message"]
        super().on_external_config_update()
        new_path, new_method = self.config["path"], self.config["method"]
        new_room, new_message = self.config["room"], self.config["message"]
        if old_path != new_path or old_method != new_method:
            self.log.debug("Path or method changed, restarting webhook...")
            self.webapp.clear()
            self.register_webhook()
        if old_room != new_room:
            self.reload_template("room")
        if old_message != new_message:
            self.reload_template("message")

    def reload_template(self, key: str) -> None:
        self.log.debug(f"{key.capitalize()} changed, reloading template...")
        self.load_template(key)
        self.log.info(f"Successfully reloaded {key} template")

    def load_template(self, key: str) -> None:
        try:
            self.templates[key] = jinja2.Template(self.config[key])
        except jinja2.TemplateSyntaxError as e:
            # avoid 'During handling of the above exception, another exception occurred'
            # to keep the error message in the log as short as possible.
            raise ValueError(f"Error in {key} template: {e}") from None

    def render_template(self, key: str, variables: Dict) -> Union[str, Response]:
        try:
            # self.templates[key] is always defined:
            # If an error occurs when reloading the template,
            #  the old template is not replaced.
            # If an error occurs when initially loading the template,
            #  the webhook will not be registered and render_template() is not called.
            return self.templates[key].render(variables)
        except jinja2.UndefinedError as e:
            error_message = f"Undefined variables in {key} template: {e}"
            self.log.error(error_message)
            return Response(status=500, text=error_message)

    def register_webhook(self) -> None:
        path, method = self.config["path"], self.config["method"]
        self.webapp.add_route(method, path, self.handle_request)
        self.log.info(f"Webhook available at: {method} {self.webapp_url}{path}")

    async def start(self) -> None:
        self.templates: Dict[str, jinja2.Template] = {}
        self.config.load_and_update()
        self.load_template("room")
        self.load_template("message")
        self.register_webhook()

    async def handle_request(self, req: Request) -> Response:
        self.log.debug(f"Got request {req}")
        config_auth_type: Optional[str] = self.config["auth_type"]

        def unauthorized(text: str) -> Response:
            # config_auth_type can be None, but the function is not called in this case.
            # Thus, we can ignore the type here.
            return Response(status=401, headers={hdrs.WWW_AUTHENTICATE: config_auth_type},  # type: ignore[arg-type]
                            text=text)

        if config_auth_type is not None:
            config_auth_type = config_auth_type.capitalize()
            auth_header: Optional[str] = req.headers.get(hdrs.AUTHORIZATION)
            if auth_header is None:
                return unauthorized("Missing authorization header")
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
            self.log.debug("Auth token is valid")

        template_variables = {
            "path": dict(req.match_info),
            "query": dict(req.rel_url.query),
            "body": await req.text()
        }

        if req.content_type == "application/json" or self.config["force_json"]:
            try:
                json = await req.json()
            except ValueError as e:
                error_message = f"Failed to parse JSON: {e}"
                return Response(status=400, text=error_message)
            template_variables["json"] = json

        room: Union[str, Response] = self.render_template("room", template_variables)
        if isinstance(room, Response):
            return room
        # RoomID is a str, wrap this here for the typechecker,
        # since send_markdown() and send_text() expect a RoomID
        room = mautrix.types.RoomID(room)

        message: Union[str, Response] = self.render_template("message", template_variables)
        if isinstance(message, Response):
            return message

        if self.config["ignore_empty_messages"] and not message:
            self.log.info(f"Not Sending message to room. {req} was successfully processed, "
                          "but the template generated an empty message.")
            return Response()

        self.log.info(f"Sending message to room {room}: {message}")
        try:
            if self.config["message_format"] == 'markdown':
                await self.client.send_markdown(room, message)
            elif self.config["message_format"] == 'html':
                await self.client.send_text(room, None, html=message)
            else:
                await self.client.send_text(room, message)
        except Exception as e:
            error_message = f"Failed to send message '{message}' to room {room}: {e}"
            self.log.error(error_message)
            return Response(status=500, text=error_message)
        return Response()
