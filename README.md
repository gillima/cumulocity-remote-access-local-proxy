# Local Proxy for Cumulocity Cloud Remote Access

This is a proxy implementation for the Cloud Remote Access feature of Cumulocity which allows to connect to devices using native TCP-based clients like ssh, vnc, rdp etc.

Main purpose of this proxy is to bridge all TCP packets via WebSocket. The local proxy is designed to run on clients where the native client software is installed.

![architecture](img/Remote_access_architecture.png)

The proxy is written in Python3.

# Installation

> ### Migration Notes
>
> If your are upgrade from <=1.x please see the [MIGRATION to V2 NOTES](docs/MIGRATION_V2.md) as there are some breaking changes. Please forgive us, but you can be sure it is worth it! Version 2.x brings a lot of great features like interactive ssh sessions and plugins to make c8ylp even more useful!
>

The Local Proxy can be installed via pip, or manually installed from the repository by clone it.

Additionally a Debian package (.deb) can be created by building the project yourself and hosting the package in your own Debian repository. See the [DEVELOPER Notes](docs/DEVELOPER.md) for details.


## Installation via pip (hosted in pypi)

```console
pip install c8ylp
```

>
> Note: Depending on your python setup, you may need to use `pip3` instead of `pip`.
>

### Installing a specific version

You can install specific version by specifying the version number when using pip.

```console
pip install c8ylp==1.5.0
```

Or if you want to install the latest v1.x version and do not want to upgrade to v2.x until you are ready, then use:

```console
pip install "c8ylp<2.0.0"
```

## Installation from Source Code

Clone the project, then navigate to the root folder of the project and run:

```console
pip install .
```

# Usage

>The Local Proxy needs to be executed for each device tunnel you want to establish. 
>Multiple device tunnels per single Local Proxy Instance is currently not supported due to the limitation of the SSH Protocol.
>
>This also includes that the provided TCP Port should be not in use by other Proxies or Services.

In a terminal session execute:

c8ylp supports different commands depending on your use case. The commands are organized in a multi-level command structure. The list of available commands and subcommands can be shown by using the `--help/-h` option.

The command can be launched by either using the `c8ylp` binary or my calling the `c8ylp` module by python.

```sh
c8ylp

# or calling via python (or use python3)
python -m c8ylp
```

The available commands can be shown using:

```console
% c8ylp --help
Usage: c8ylp [OPTIONS] COMMAND [ARGS]...

Options:
  --help  Show this message and exit.

Commands:
  connect  Connect to a device via different protocols
  login    Login and save token to an environment file
  plugin   Run a custom plugin (installed under ~/.c8ylp/plugins/)
  server   Start local proxy in server mode
  version  Show the c8ylp version number
```

### Launching as local proxy server

```sh
c8ylp server <device> --env-file .env
```

### Launching as local proxy server then launching an interactive ssh session

```sh
c8ylp connect ssh <device> --ssh-user <device_username> --env-file .env
```

### Command documentation

The command usage and all options can be viewed on the following pages:

* [c8ylp](docs/cli/C8YLP.md)
* [c8ylp login](docs/cli/C8YLP_LOGIN.md)
* [c8ylp server](docs/cli/C8YLP_SERVER.md)
* [c8ylp connect](docs/cli/C8YLP_CONNECT.md)
* [c8ylp connect ssh](docs/cli/C8YLP_CONNECT_SSH.md)
* [c8ylp plugin](docs/cli/C8YLP_PLUGIN.md)
* [c8ylp plugin command](docs/cli/C8YLP_PLUGIN_COMMAND.md)

### Configuration

c8ylp can be configured via either options or environment variables. The environment variables can either be set via shell, or by using a dotenv file (i.e. `.env`). When using a dotenv file then it needs to be provide to the `--env-file <file>` option.

Example Usage:

If you create a file called `.env` and add the following contents:

```sh
# Cumulocity settings
C8Y_HOST=<cumulocity_host>
C8Y_USER=<your_cumulocity_username>

# c8ylp settings
C8YLP_VERBOSE=true
```

Then reference the file from the command line:

```console
c8ylp server test-device --env-file .env
```

The environment variables corresponding to the option can be viewed by using the in-built help.

```console
c8ylp --help
```

> Please note that the Local Proxy will block the current terminal session. If you want to use it in background just use "&" and/or "nohup". As the relevant information will be stored in a log file as well you can forward the output to dev/null or to syslog if you want to do so.
>```
>c8ylp server [options] > /dev/null 2>&1
>```

If no TCP Client is connected but Web Socket Connection is open it might get be terminated by a server timeout. The Local Proxy will automatically reestablish the connection in this case.

If a TCP Client has been connected and the Web Socket Connection gets terminated, the TCP Client Connection will be terminated which results in that the Local Proxy terminates and needs to be restarted manually.

## Tab completion

c8ylp (version >= 2.0.0) supports tab completion for bash, zsh and fish shells.

To add the completion, you will need to add the corresponding line to your shell profile, and reload your shell afterwards.

**Note**

Completion is not currently supported in Cygwin.

```sh
# bash (profile: ~/.bashrc)
eval "$(_C8YLP_COMPLETE=bash_source c8ylp)"

# zsh (profile: ~/.zshrc)
eval "$(_C8YLP_COMPLETE=zsh_source c8ylp)"

# fish (profile: ~/.config/fish/config.fish)
_C8YLP_COMPLETE=fish_source c8ylp | source
```

# Plugins

`c8ylp` can be extended by the use of plugins (either via python or bash script). Checkout the [plugins](docs/PLUGINS.md) documentation for more information about how to create your own plugin, but it is intended for advanced users only. For simple one liners have a look at using the in-built generic plugin [c8ylp plugin command](docs/cli/C8YLP_PLUGIN_COMMAND.md) instead.

Plugins are loaded at runtime and can be listed by running the following command:

```console
c8ylp plugin
```


# Log

The log file can be found in the following directory. 

```console
~/.c8ylp/*.log
```

Where `~` is your user folder.

To increase the detail of log use the option `--verbose or -v`. If set, the log will be written on debug level.

All relevant information will be sent to the console AND to the log file. So when running in background you can just ignore the console output: 

```
c8ylp [OPTIONS] > /dev/null 2>&1
```

And for fancy setups, you can also forward the log output to any log server / file of your choice using standard linux mechanisms.

## Dependencies

The Local Proxy depends on the following components packages. The dependencies will be automatically installed when installing via pip or if you are installing c8ylp via a manually built Debian package (.deb).

* [certifi](https://pypi.org/project/certifi/)
* [click](https://pypi.org/project/click/)
* [requests](https://pypi.org/project/requests/)
* [setuptools](https://pypi.org/project/setuptools/)
* [websocket_client](https://pypi.org/project/websocket_client/)

# Contributing

Checkout the [DEVELOPER Notes](docs/DEVELOPER.md) to see how to contribute to the project.

_____________________
These tools are provided as-is and without warranty or support. They do not constitute part of the Software AG product suite. Users are free to use, fork and modify them, subject to the license agreement. While Software AG welcomes contributions, we cannot guarantee to include every contribution in the master project.

For more information you can Ask a Question in the [Tech Community Forums](https://tech.forums.softwareag.com/tag/Cumulocity-IoT).
