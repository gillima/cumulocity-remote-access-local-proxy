#!/usr/bin/env python
"""Main cli interface to c8ylp"""
# -*- coding: utf-8 -*-

#  Copyright (c) 2021 Software AG, Darmstadt, Germany and/or its licensors
#
#  SPDX-License-Identifier: Apache-2.0
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#

import dataclasses
import logging
import os
import pathlib
import platform
import signal
import shutil
import subprocess
import sys
import threading
import time
from datetime import timedelta
from enum import IntEnum
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, NoReturn

import click

from c8ylp.helper import wait_for_port

from . import options, __version__
from .banner import BANNER1
from .env import save_env
from .rest_client.c8yclient import CumulocityClient
from .tcp_socket.tcp_server import TCPProxyServer
from .websocket_client.ws_client import WebsocketClient
from .plugin import PluginCLI


PASSTHROUGH = "PASSTHROUGH"
REMOTE_ACCESS_FRAGMENT = "c8y_RemoteAccessList"


class ExitCodes(IntEnum):
    """Exit codes"""

    OK = 0
    NO_SESSION = 2
    NOT_AUTHORIZED = 3
    PID_FILE_ERROR = 4

    DEVICE_MISSING_REMOTE_ACCESS_FRAGMENT = 5
    DEVICE_NO_PASSTHROUGH_CONFIG = 6
    DEVICE_NO_MATCHING_PASSTHROUGH_CONFIG = 7
    MISSING_ROLE_REMOTE_ACCESS_ADMIN = 8

    UNKNOWN = 9

    SSH_NOT_FOUND = 10


class ExitCommand(Exception):
    """ExitCommand error"""


def signal_handler(_signal, _frame):
    """Signal handler"""
    raise ExitCommand()


def print_version(ctx: click.Context, _param: click.Parameter, _value: Any) -> Any:
    """Print command version

    Args:
        ctx (click.Context): Click context
        _param (click.Parameter): Click param
        value (Any): Parameter value

    Returns:
        Any: Parameter value
    """
    click.echo(f"Version {__version__}")
    ctx.exit(ExitCodes.OK)


@click.group(
    invoke_without_command=True,
    no_args_is_help=True,
    context_settings=dict(
        help_option_names=["-h", "--help"],
    ),
    help="Cumulocity Remote Access Local Proxy",
)
@click.pass_context
def cli_core(ctx: click.Context):
    """Main cli entry point"""
    ctx.ensure_object(dict)


@cli_core.command()
@options.HOSTNAME_PROMPT
@options.C8Y_TENANT
@options.C8Y_USER
@options.C8Y_TOKEN
@options.C8Y_PASSWORD
@options.C8Y_TFA_CODE
@options.LOGGING_VERBOSE
@options.ENV_FILE_OPTIONAL_EXISTS
@options.STORE_TOKEN
@options.DISABLE_PROMPT
@click.pass_context
def login(
    ctx: click.Context,
    *_args,
    **kwargs,
):
    """Login and save credentials to an environment file

    You will be prompted for all of the relevant information,
    i.e. host, username, password and TFA code (if required)

    Example: Create/update an env-file by trying to login into Cumulocity
    \b
        c8ylp login --env-file mytenant.env

    """
    opts = ProxyOptions().fromdict(kwargs)

    try:
        create_client(ctx, opts)
    except Exception:
        ctx.fail("Could not login")


@cli_core.command(help="Show version number")
@click.pass_context
def version(ctx):
    print_version(ctx, None, None)


@cli_core.command()
@options.ARG_DEVICE
# @options.DEVICE
@options.HOSTNAME
@options.EXTERNAL_IDENTITY_TYPE
@options.REMOTE_ACCESS_TYPE
@options.C8Y_TENANT
@options.C8Y_USER
@options.C8Y_TOKEN
@options.C8Y_PASSWORD
@options.C8Y_TFA_CODE
@options.PORT
@options.PING_INTERVAL
@options.KILL_EXISTING
@options.TCP_SIZE
@options.TCP_TIMEOUT
@options.LOGGING_VERBOSE
@options.MODE_SCRIPT
@options.SSL_IGNORE_VERIFY
@options.PID_USE
@options.PID_FILE
@options.SERVER_RECONNECT_LIMIT
@options.ENV_FILE
@options.DISABLE_PROMPT
@options.STORE_TOKEN
@click.pass_context
def server(
    ctx,
    *_args,
    **kwargs,
):
    """Start local proxy in server mode

    \b
        DEVICE is the device's external identity

    Once the local proxy has started, clients such as ssh and scp can be used
    to establish a connection to the device.

    \b
    Example 1: Start the local proxy, prompt for credentials (if not set via env variables)

        \b
        c8ylp start --host https://example.c8y.io device01

    Example 2: Start the local proxy using environment file

        \b
        c8ylp start --env-file .env device01

    Example 3: Start the local proxy with randomized port

        \b
        c8ylp start --env-file .env device01 --port 0
    """
    opts = ProxyOptions().fromdict(kwargs)
    start_proxy(ctx, opts)


@cli_core.command()
@options.ARG_DEVICE
@options.HOSTNAME
@options.EXTERNAL_IDENTITY_TYPE
@options.REMOTE_ACCESS_TYPE
@options.C8Y_TENANT
@options.C8Y_USER
@options.C8Y_TOKEN
@options.C8Y_PASSWORD
@options.C8Y_TFA_CODE
@options.PORT_DEFAULT_RANDOM
@options.PING_INTERVAL
@options.TCP_SIZE
@options.TCP_TIMEOUT
@options.LOGGING_VERBOSE
@options.SSL_IGNORE_VERIFY
@options.SSH_USER
@options.ENV_FILE
@options.STORE_TOKEN
@options.DISABLE_PROMPT
@click.argument(
    "additional_args", metavar="[REMOTE_COMMANDS]...", nargs=-1, type=click.UNPROCESSED
)
@click.pass_context
def connect_ssh(
    ctx,
    *_args,
    **kwargs,
):
    """Start once-off proxy and connect via ssh

    An interactive ssh is opened if a remote command is not provided.

    Once the ssh session is closed, then the local proxy will be shutdown.

    Use "--" before the remote commands to prevent the arguments
    from being interpreted by c8ylp (i.e. to avoid clashes with c8ylp).

    \b
        DEVICE is the device's external identity

    Example 1: Start an interactive SSH connection

    \b
        c8ylp connect-ssh --env-file .env device01 --ssh-user admin

    Example 2: Execute a command via SSH

    \b
        c8ylp connect-ssh --env-file .env device01 --ssh-user admin -- systemctl status ssh

    Example 3: Execute a complex command via SSH (use quotes to ensure command is sent to the device)

    \b
        c8ylp connect-ssh --env-file .env device01 --ssh-user admin -- "systemctl status ssh; dpkg --list | grep ssh"

    """
    opts = ProxyOptions().fromdict(kwargs)
    opts.script_mode = True
    start_proxy(ctx, opts)


@click.group()
def cli_plugin():
    pass


@cli_plugin.command(
    "plugin",
    cls=PluginCLI,
    hidden=True,  # Hide for now ;)
    context_settings=dict(
        ignore_unknown_options=True,
    ),
)
@options.ARG_DEVICE
@options.HOSTNAME
@options.EXTERNAL_IDENTITY_TYPE
@options.REMOTE_ACCESS_TYPE
@options.C8Y_TENANT
@options.C8Y_USER
@options.C8Y_TOKEN
@options.C8Y_PASSWORD
@options.C8Y_TFA_CODE
@options.PORT_DEFAULT_RANDOM
@options.PING_INTERVAL
@options.TCP_SIZE
@options.TCP_TIMEOUT
@options.LOGGING_VERBOSE
@options.SSL_IGNORE_VERIFY
@options.ENV_FILE
@options.STORE_TOKEN
@options.DISABLE_PROMPT
@click.pass_context
def cli_plugin_custom(ctx: click.Context, *_args, **kwargs):
    """
    Run a custom plugin (installed under ~/.c8ylp/plugins/)

    Example 1:
    \b
        c8ylp plugin device01 copyto <src> <dst>
    """

    click.echo("Running pre-install phase")
    opts = ProxyOptions().fromdict(kwargs)
    opts.script_mode = True

    # Skip starting server if the user just want to see the help
    if "--help" in sys.argv or "-h" in sys.argv:
        return

    stop_signal = threading.Event()
    opts.skip_exit = True

    # Inject custom env variables for use within the script
    os.environ["DEVICE"] = str(opts.device)
    os.environ["PORT"] = str(opts.port)

    # register signals as the proxy will be starting in a background thread
    # to enable the proxy to run as a subcommand
    register_signals()

    # Start the proxy in a background thread so the user can
    background = threading.Thread(
        target=start_proxy, args=(ctx, opts, stop_signal), daemon=True
    )
    background.start()

    # Shutdown the server once the plugin has been run
    @ctx.call_on_close
    def _shutdown_server_thread():
        stop_signal.set()
        background.join()

    # Block until the port is actually open
    wait_for_port(opts.port)

    # The subcommand is called after this


@cli_core.command(
    "execute",
    context_settings=dict(
        ignore_unknown_options=True,
    ),
)
@options.ARG_DEVICE
@options.ARG_SCRIPT
@options.HOSTNAME
@options.EXTERNAL_IDENTITY_TYPE
@options.REMOTE_ACCESS_TYPE
@options.C8Y_TENANT
@options.C8Y_USER
@options.C8Y_TOKEN
@options.C8Y_PASSWORD
@options.C8Y_TFA_CODE
@options.PORT_DEFAULT_RANDOM
@options.PING_INTERVAL
@options.TCP_SIZE
@options.TCP_TIMEOUT
@options.LOGGING_VERBOSE
@options.SSL_IGNORE_VERIFY
@options.ENV_FILE
@options.STORE_TOKEN
@options.DISABLE_PROMPT
@click.argument(
    "additional_args", metavar="[SCRIPT_ARGS]...", nargs=-1, type=click.UNPROCESSED
)
@click.pass_context
def cli_execute(
    ctx,
    *_args,
    **kwargs,
):
    """
    Start once-off proxy and execute a (local) script/command

        \b
        DEVICE is the device's external identity
        SCRIPT is the script or command to run after the proxy has been started

        All additional arguments will be passed to the script/command. Use "--" before
        the additional arguments to prevent the arguments from being interpreted by
        c8ylp (i.e. to avoid clashes with c8ylp).

    \b
    Available ENV variables (use single quotes to prevent expansion):

      \b
      DEVICE - external device identity
      PORT   - port number of the local proxy

    \b
    Example 1: Use scp to copy a file to a device

        \b
        c8ylp execute device01 --env-file .env \\
            -- /usr/bin/scp -P '$PORT' myfile.tar.gz admin@localhost:/tmp

    Example 2: Run a custom script (not included) to copy a file from the device to
    the current folder

        \b
        c8ylp execute device01 --env-file .env -v ./copyfrom.sh /var/log/dpkg.log ./
    """
    opts = ProxyOptions().fromdict(kwargs)
    opts.script_mode = True
    logging.info(
        "Collected additional args which will be passed to script later: %s",
        opts.additional_args,
    )
    start_proxy(ctx, opts)


@dataclasses.dataclass
class ProxyOptions:
    """Local proxy options"""

    host = ""
    device = ""
    external_type = ""
    config = ""
    tenant = ""
    user = ""
    token = ""
    password = ""
    tfa_code = ""
    port = 0
    ping_interval = ""
    kill = False
    tcp_size = 0
    tcp_timeout = 0
    verbose = False
    script_mode = False
    ignore_ssl_validate = False
    use_pid = False
    pid_file = ""
    reconnects = 0
    ssh_user = ""
    script = ""
    additional_args = None
    disable_prompts = False
    env_file = None
    store_token = False
    skip_exit = None

    def fromdict(self, src_dict: Dict[str, Any]) -> "ProxyOptions":
        """Load proxy settings from a dictionary

        Args:
            src_dict (Dict[str, Any]): [description]

        Returns:
            ProxyOptions: Proxy options after the values have been set
                via the dictionary
        """
        logging.info("Loading from dictionary")
        assert isinstance(src_dict, dict)
        for key, value in src_dict.items():
            logging.info("reading key: %s=%s", key, value)
            if hasattr(self, key):
                setattr(self, key, value)
        return self


def configure_logger(path: str = None, verbose: bool = False) -> logging.Logger:
    """Configure logger

    Args:
        path (str, optional): Path where the persistent logger should write to. Defaults to None.
        verbose (bool, optional): Use verbose logging. Defaults to False.

    Returns:
        logging.Logger: Created logger
    """
    if not path:
        path = pathlib.Path.home() / ".c8ylp"
        path.mkdir(parents=True, exist_ok=True)

    loglevel = logging.INFO if verbose else logging.WARNING
    logger = logging.getLogger()
    logger.setLevel(loglevel)
    log_file_formatter = logging.Formatter(
        "%(asctime)s %(threadName)s %(levelname)s %(name)s %(message)s"
    )
    log_console_formatter = logging.Formatter("[c8ylp]  %(levelname)-5s %(message)s")

    # Set default log format
    if len(logger.handlers) == 0:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_console_formatter)
        console_handler.setLevel(loglevel)
        logger.addHandler(console_handler)
    else:
        handler = logger.handlers[0]
        handler.setFormatter(log_console_formatter)

    # Max 5 log files each 10 MB.
    rotate_handler = RotatingFileHandler(
        filename=path / "localproxy.log", maxBytes=10000000, backupCount=5
    )
    rotate_handler.setFormatter(log_file_formatter)
    rotate_handler.setLevel(loglevel)
    # Log to Rotating File
    logger.addHandler(rotate_handler)
    return logger


def store_credentials(opts: ProxyOptions, client: CumulocityClient):
    """Store credentials to the environment file. It creates
    the file if it does not already exist.

    The file will only be written to if it has changed.

    Args:
        opts (ProxyOptions): Proxy options
        client (CumulocityClient): Cumulocity client containing valid
            credentials
    """
    changed = save_env(
        opts.env_file,
        {
            # Note: Don't save password!
            "C8Y_HOST": client.url,
            "C8Y_USER": client.user,
            "C8Y_TENANT": client.tenant,
            "C8Y_TOKEN": client.token,
        },
    )

    if changed:
        click.echo(f"Env file {opts.env_file} was updated")
    else:
        logging.info("Env file %s is already up to date", opts.env_file)


def create_client(ctx: click.Context, opts: ProxyOptions) -> CumulocityClient:
    """Create Cumulocity client and prompt for missing credentials
    if necessary.

    Args:
        ctx (click.Context): Click context
        opts (ProxyOptions): Proxy options

    Returns:
        CumulocityClient: Configured Cumulocity client
    """
    client = CumulocityClient(
        hostname=opts.host,
        tenant=opts.tenant,
        user=opts.user,
        password=opts.password,
        tfacode=opts.tfa_code,
        token=opts.token,
        ignore_ssl_validate=opts.ignore_ssl_validate,
    )
    logging.info("Checking tenant id")
    client.validate_tenant_id()
    # logging.info("Got tenant id")

    retries = 2
    success = False
    while retries:
        try:
            if client.token:
                client.validate_credentials()
            else:
                client.login_oauth()

            if opts.env_file and opts.store_token:
                store_credentials(opts, client)

            success = True
            break
        except Exception as ex:
            logging.info("unknown exception: %s", ex)

            if not opts.disable_prompts:
                if not client.user:
                    client.user = click.prompt(
                        text="Enter your Cumulocity Username",
                    )

                if not client.password:
                    client.password = click.prompt(
                        text="Enter your Cumulocity Password [input hidden]",
                        hide_input=True,
                    )

                if not client.tfacode:
                    client.tfacode = click.prompt(
                        text="Enter your Cumulocity TFA-Token", hide_input=False
                    )
        retries -= 1

    if not success:
        logging.info("Could not create client")
        ctx.exit(ExitCodes.NO_SESSION)

    return client


def get_config_id(ctx: click.Context, mor: Dict[str, Any], config: str) -> str:
    """Get the remote access configuration id matching a specific type
    from a device managed object

    Args:
        mor (Dict[str, Any]): Device managed object
        config (str): Expected configuration type

    Returns:
        str: Remote access configuration id
    """
    device_name = mor.get("name", "<<empty_name>>")
    if REMOTE_ACCESS_FRAGMENT not in mor:
        logging.error(
            'No Remote Access Configuration has been found for device "%s"', device_name
        )
        ctx.exit(ExitCodes.DEVICE_MISSING_REMOTE_ACCESS_FRAGMENT)

    valid_configs = [
        item
        for item in mor.get(REMOTE_ACCESS_FRAGMENT, [])
        if item.get("protocol") == PASSTHROUGH
    ]

    if not valid_configs:
        logging.error(
            'No config with protocol set to "%s" has been found for device "%s"',
            PASSTHROUGH,
            device_name,
        )
        ctx.exit(ExitCodes.DEVICE_NO_PASSTHROUGH_CONFIG)

    def extract_config_id(matching_config):
        logging.info(
            'Using Configuration with Name "%s" and Remote Port %s',
            matching_config.get("name"),
            matching_config.get("port"),
        )
        return matching_config.get("id")

    if not config:
        # use first config
        return extract_config_id(valid_configs[0])

    # find config matching name
    matches = [
        item
        for item in valid_configs
        if item.get("name", "").casefold() == config.casefold()
    ]

    if not matches:
        logging.error(
            'Provided config name "%s" for "%s" was not found or none with protocal set to "%s"',
            config,
            device_name,
            PASSTHROUGH,
        )
        ctx.exit(ExitCodes.DEVICE_NO_MATCHING_PASSTHROUGH_CONFIG)

    return extract_config_id(matches[0])


def register_signals():
    if platform.system() in ("Linux", "Darwin"):
        signal.signal(signal.SIGUSR1, signal_handler)
    else:
        signal.signal(signal.SIGINT, signal_handler)


def start_proxy(
    ctx: click.Context, opts: ProxyOptions, stop_signal: threading.Event = None
) -> NoReturn:
    """Start the local proxy

    Args:
        ctx (click.Context): Click context
        opts (ProxyOptions): Proxy options
    """
    # pylint: disable=too-many-branches,too-many-statements
    is_main_thread = threading.current_thread() is threading.main_thread()
    if is_main_thread:
        register_signals()

    configure_logger(verbose=opts.verbose)

    if opts.use_pid:
        try:
            upsert_pid_file(
                opts.pid_file, opts.device, opts.host, opts.config, opts.user
            )
        except PermissionError:
            ctx.exit(ExitCodes.PID_FILE_ERROR)
    if opts.kill:
        if opts.use_pid:
            kill_existing_instances(opts.pid_file)
        else:
            logging.warning(
                'Killing existing instances is only supported when "--use-pid" is used.'
            )

    try:
        client = create_client(ctx, opts)
        mor = client.get_managed_object(opts.device, opts.external_type)
        config_id = get_config_id(ctx, mor, opts.config)
        device_id = mor.get("id")

        is_authorized = client.validate_remote_access_role()
        if not is_authorized:
            logging.error(
                "User %s is not authorized to use Cloud Remote Access. Contact your Cumulocity Admin!",
                opts.user,
            )
            ctx.exit(ExitCodes.MISSING_ROLE_REMOTE_ACCESS_ADMIN)
    except Exception as ex:
        if isinstance(ex, click.exceptions.Exit):
            logging.error("Could not retrieve device information. reason=%s", ex)
            # re-raise existing exit
            raise
        ctx.exit(ExitCodes.NOT_AUTHORIZED)

    client_opts = {
        "host": opts.host,
        "config_id": config_id,
        "device_id": device_id,
        "session": client.session,
        "token": opts.token,
        "ignore_ssl_validate": opts.ignore_ssl_validate,
        "ping_interval": opts.ping_interval,
    }

    try:
        tcp_server = TCPProxyServer(
            opts.port,
            WebsocketClient(**client_opts),
            opts.tcp_size,
            opts.tcp_timeout,
            opts.script_mode,
            max_reconnects=opts.reconnects,
        )

        exit_code = ExitCodes.OK

        click.secho(BANNER1)
        logging.info("Starting tcp server")

        background = threading.Thread(target=tcp_server.serve_forever, daemon=True)
        background.start()

        if not tcp_server.wait_for_running(30.0):
            logging.warning(
                "Server did not start up in time, but trying to proceed anyway"
            )

        if opts.script:
            with CommandTimer("Duration"):
                exit_code = run_script(ctx, opts)
            raise ExitCommand()

        if opts.ssh_user:
            with CommandTimer("SSH Session duration"):
                exit_code = start_ssh(ctx, opts)
            raise ExitCommand()

        click.secho(
            f"\nc8ylp is listening for device (ext_id) {opts.device} ({opts.host}) on localhost:{opts.port}",
            fg="green",
        )
        ssh_username = opts.ssh_user or "<device_username>"
        click.secho(
            f"\nConnect to {opts.device} by executing the following in a new tab/console:\n\n"
            f"\tssh -p {opts.port} {ssh_username}@localhost",
            color=True,
        )

        # loop, waiting for server to stop
        while background.is_alive() and (stop_signal and not stop_signal.is_set()):
            time.sleep(1)
            logging.debug(
                "Waiting in background: alive=%s",
                background.is_alive(),
            )
    except ExitCommand:
        pass
    except Exception as ex:
        if isinstance(ex, click.exceptions.Exit):
            # propagate exit code
            exit_code = getattr(ex, "exit_code")
            raise

        if str(ex):
            logging.error("Error on TCP-Server. %s", ex)
            exit_code = ExitCodes.UNKNOWN
    finally:
        if opts.use_pid:
            clean_pid_file(opts.pid_file, os.getpid())

        tcp_server.shutdown()
        background.join()
        logging.info("Exit code: %s", exit_code)
        click.echo("Exiting")

        if is_main_thread:
            ctx.exit(exit_code)


def upsert_pid_file(pidfile: str, device: str, url: str, config: str, user: str):
    """Create/update pid file

    Args:
        pidfile (str): PID file path
        device (str): Device external identity
        url (str): Cumulocity URL
        config (str): Remote access configuration type
        user (str): Cumulocity user
    """
    try:
        clean_pid_file(pidfile, os.getpid())
        pid_file_text = get_pid_file_text(device, url, config, user)
        logging.debug("Adding %s to PID-File %s", pid_file_text, pidfile)

        if not os.path.exists(pidfile):
            if not os.path.exists(os.path.dirname(pidfile)):
                os.makedirs(os.path.dirname(pidfile))

        with open(pid_file_text, "a+") as file:
            file.seek(0)
            file.write(pid_file_text)
            file.write("\n")

    except PermissionError:
        logging.error(
            "Could not write PID-File %s. Please create the folder manually and assign the correct permissions.",
            pidfile,
        )
        raise


def run_script(_ctx: click.Context, opts: ProxyOptions) -> int:
    """Execute a script with environment variables set with information
    about the local proxy, i.e. device, port etc.

    Args:
        ctx (click.Context): Click context
        opts (ProxyOptions): Proxy options

    Returns:
        int: Exit code of script
    """

    cmd_args = [
        opts.script,
    ]

    # add env variables which can be used in the extra arguments
    os.environ["PORT"] = str(opts.port)
    os.environ["DEVICE"] = str(opts.device)

    if opts.additional_args:
        for value in opts.additional_args:
            logging.info("Expanding script arguments: %s", value)
            cmd_args.append(os.path.expandvars(value))

    logging.info("Executing extension: %s", " ".join(cmd_args))
    exit_code = subprocess.call(cmd_args, env=os.environ, shell=False)
    if exit_code != 0:
        logging.warning("Script exited with a non-zero exit code. code=%s", exit_code)
    return exit_code


def start_ssh(ctx: click.Context, opts: ProxyOptions) -> int:
    """Start interactive ssh session

    Args:
        ctx (click.Context): Click context
        opts (ProxyOptions): Proxy options

    Returns:
        int: Exit code of ssh command
    """
    if not shutil.which("ssh"):
        logging.error(
            "ssh client not found. Please make sure the 'ssh' client is included in your PATH variable"
        )

        ctx.exit(ExitCodes.SSH_NOT_FOUND)

    ssh_args = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-p",
        str(opts.port),
        f"{opts.ssh_user}@localhost",
    ]

    if opts.additional_args:
        logging.info("Executing a once-off command then exiting")
        ssh_args.extend(opts.additional_args)
        click.secho(
            f"Executing command via ssh on {opts.device} ({opts.host})", fg="green"
        )
    else:
        click.secho(
            f"Starting interactive ssh session with {opts.device} ({opts.host})",
            fg="green",
        )

    logging.info("Starting ssh session using: %s", " ".join(ssh_args))
    exit_code = subprocess.call(ssh_args, env=os.environ)
    if exit_code != 0:
        logging.warning("SSH exited with a non-zero exit code. code=%s", exit_code)
    return exit_code


class CommandTimer:
    """Command Timer which shows how long a command takes to run
    and prints out a message to the user

    Example

    >>>
    with CommandTimer():
        print("Doing someting")
        time.sleep(100)
    >>>

    """

    def __init__(self, message: str) -> None:
        self.message = message
        self.start_time = 0
        self.last_duration = 0

    def start(self):
        """Start the timer"""
        self.start_time = time.monotonic()

    def stop(self) -> float:
        """Stop the timer and return the duration in seconds

        Returns:
            float: Duration in seconds
        """
        if not self.start_time:
            return 0
        self.last_duration = time.monotonic() - self.start_time
        return self.last_duration

    def __enter__(self) -> None:
        self.start()

    def __exit__(self, _type, _value, _traceback) -> None:
        duration = timedelta(seconds=(int(self.stop())))
        msg = f"{self.message}: {duration}"
        logging.info(msg)
        click.echo(msg)


def get_pid_file_text(device: str, url: str, config: str, user: str) -> str:
    """Format pid file text contents

    Args:
        device (str): Device external identity
        url (str): Cumulocity url
        config (str): Remote access type
        user (str): User

    Returns:
        str: Text contents that should be written to a pid file
    """
    pid = str(os.getpid())
    return f"{pid},{url},{device},{config},{user}"


def get_pid_from_line(line: str) -> int:
    """Get the process id from the contents of a pid file

    Args:
        line (str): Encoded PID information

    Returns:
        int: Porcess id
    """
    return int(str.split(line, ",")[0])


def pid_is_active(pid: int) -> bool:
    """Check if a PID is active

    Args:
        pid (int): Process ID

    Returns:
        bool: True if the process is still running
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def clean_pid_file(pidfile: str, pid: int):
    """Clean up pid file

    Args:
        pidfile (str): PID file path
        pid (int): current process id
    """
    if os.path.exists(pidfile):
        logging.debug("Cleaning Up PID %s in PID-File %s", pid, pidfile)
        pid = pid if pid is not None else os.getpid()
        with open(pidfile, "w+") as file:
            lines = file.readlines()
            file.seek(0)
            for line in lines:
                if get_pid_from_line(line) != pid:
                    file.write(line)
            file.truncate()

        if os.path.getsize(pidfile) == 0:
            os.remove(pidfile)


def kill_existing_instances(pidfile: str):
    """Kill existing instances of c8ylp

    Args:
        pidfile (str): PID file path
    """
    if os.path.exists(pidfile):
        with open(pidfile) as file:
            pid = int(os.getpid())
            for line in file:
                other_pid = get_pid_from_line(line)
                if pid != other_pid and pid_is_active(other_pid):
                    logging.info("Killing other running Process with PID %s", other_pid)
                    os.kill(get_pid_from_line(line), 9)
                clean_pid_file(pidfile, other_pid)


cli = click.CommandCollection("cli", sources=[cli_core, cli_plugin])
