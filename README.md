# maubot-webhook
A [maubot](https://github.com/maubot/maubot) plugin to send messages using webhooks.


## Installation
**TODO: insert release assets link**  
Either download an `.mbp` file from the [release assets](#TODO) or [build one yourself](#building).
Then, [upload](https://docs.mau.fi/maubot/usage/basic.html#uploading-plugins) it to your maubot instance.


## Usage
Create a new instance in the maubot management interface and select `me.jkhsjdhjs.maubot.webhook` as `Type`.
The client selected as `Primary user` will be used to send the messages.

Each instance of this plugin provides a single webhook.
To create multiple webhooks, just instantiate this plugin as often as you like.


## Configuration
This plugin has the following settings you can configure:


### `path`
The path the webhook will be available at.
It must start with a `/` or be empty.
It is relative to the webapp base URL of the instance:

```
http://your.maubot.instance/_matrix/maubot/plugin/<instance ID>/<path>
```

The URL under which the webhook is made available is logged on instance startup, so if you're unsure, you can check the logs.

The path supports variable resources, which can be used to extract information from the request URL and format the [`room`](#room) and the [`message`](#message).
Further information on this can be found in [the formatting section](#formatting).

*If you change this setting while the respective instance is running you have to restart the instance for the change to take effect:
Click the `Running` switch to disable it, then save. Click the `Running` switch to enable it again, then save again.*


### `method`
Specifies the HTTP method that can be used on the given path.
Should be one of `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD`, `OPTIONS` or `*` for any methods.
This setting is case-insensitive.

See also: https://docs.aiohttp.org/en/stable/web_reference.html?highlight=add_route#aiohttp.web.UrlDispatcher.add_route

*If you change this setting while the respective instance is running you have to restart the instance for the change to take effect:
Click the `Running` switch to disable it, then save. Click the `Running` switch to enable it again, then save again.*


### `room`
The room the message shall be sent to when the webhook is triggered.
Supports formatting [as defined below](#formatting).


### `message`
The message that is sent when the webhook is triggered.
Supports formatting [as defined below](#formatting).


### `auth_token`
This can be used to protect a webhook against unauthorized access.
By default, anyone can send messages using the webhook.
If specified, the client is authorized via bearer token authorization, meaning that only requests, that carry an `Authorization: Bearer <token>` header with the token specified in this setting, will be processed.

For example, if this is set to `foobar`, a client would have to send the `Authorization: Bearer foobar` header.
But please don't use such insecure tokens on your instance.


### `markdown`
This setting takes a boolean and specifies if the message should be sent as Markdown or as plaintext.
If `false` (the default), the message will be sent as plaintext.
Otherwise it will be sent as Markdown.


## Formatting
The `room` and `message` options can be formatted using values from the path, the query string and the request body.
Values extracted from the path are available under the same name but with a `$path_` prefix.
Parameters given in the query string are also available under the same name but with a `$query_` prefix.
The request body in plain text is available as `$body`.
To print a single `$` in the string you can use `$$`, as a single `$` will result in an error.

For example, if the `path` is specified as `/{foo}` and the message is set to `$query_bar $path_foo$body`, a request to `/wor?bar=Hello` with request body `ld!` would result in the message `Hello world!`.

See also:  
https://docs.aiohttp.org/en/stable/web_quickstart.html#variable-resources  
https://docs.python.org/3/library/string.html#template-strings


## Building
Use the `mbc` tool to build this plugin:
```
mbc build
```
Optionally use the `-u` switch to upload it to your maubot instance, if configured:
```
mbc build -u
```

Since `.mbp` files are just zip archives with a different name, you can also just zip the files of this repository:
```
zip -9r plugin.mbp *
```


## License
<img align="right" src="https://www.gnu.org/graphics/agplv3-155x51.png"/>

This project is licensed under the GNU Affero General Public License v3.0, see [LICENSE](LICENSE).
