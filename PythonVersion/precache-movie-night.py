import os
import re
import sys
import typing
import platform
from sys import exit
from pathlib import Path
from datetime import datetime
from configparser import ConfigParser
from argparse import ArgumentParser
from urllib.parse import urlparse, urljoin
from urllib.request import urlopen, urlretrieve
from json import load


APP = "Application"
IS_WINDOWS = platform.system() == "Windows"
SERVER_CONFIG_DEFAULT_FILE_NAME: str = "precache-remote-settings.ini"
LOCAL_CONFIG_DEFAULT_FILE_NAME: str = "precache-local-settings.ini"
DEFAULT_LOCAL_CACHE_DIRECTORY: str = "./MovieNight"
STRIP_QUOTES = re.compile('^["\'](.*?)["\']$', re.IGNORECASE)

def main(args):
    parser_result = parse_args(args)
    server_config_path = Path(parser_result.server_config)
    if not server_config_path.exists():
        fatal(f'The server source configuration is required. Default file is "{SERVER_CONFIG_DEFAULT_FILE_NAME}".')

    config = Config()
    config.read(parser_result.server_config)
    create_local_config_if_not_exists(LOCAL_CONFIG_DEFAULT_FILE_NAME)
    config.read(LOCAL_CONFIG_DEFAULT_FILE_NAME)

    path_candidate = config.get(APP, "DownloadDirectory", fallback=DEFAULT_LOCAL_CACHE_DIRECTORY)
    if not IS_WINDOWS and '\\' in path_candidate:
        path_candidate.replace('\\', '/') # blind guess, who would want \\ in Linux?
    download_dir = Path(path_candidate).expanduser().resolve()
    if not download_dir.exists():
        fatal(f'The directory "{download_dir.name}" does not exist. '
              f'Ensure your plugin is installed and running from the Application Installation Directory '
              f'or the directory is created.')

    playlist_config = config.get(APP, "Playlist")
    if not playlist_config:
        fatal("Playlist is not optional in a Server Configuration .ini!")

    download_server = config.get(APP, "DownloadServer")
    parsed_playlist_path, parsed_download_server = urlparse(playlist_config), urlparse(download_server)
    if not parsed_download_server.netloc and not parsed_playlist_path.netloc:
        fatal("A fully qualified url is required when DownloadServer is empty for playlist.")

    download_server_uri = download_server + "/" if download_server else ""
    playlist_uri = urljoin(download_server_uri, playlist_config)
    with urlopen(playlist_uri) as response:
        if response.getcode() != 200:
            fatal(f'Unable to find the file at "{playlist_uri}". Unable to continue.')
        playlist_json = load(response)

    if not is_str_list(playlist_json):
        fatal("Unexpected server response after retrieving json! Expected array of strings.")

    count = 0
    for filename in playlist_json:
        # urljoin will replace the original URI with filename if it is a full URI
        file_uri = urljoin(download_server_uri, filename)
        basename = os.path.basename(urlparse(file_uri).path)
        file_path = download_dir / basename

        print(f'Downloading "{basename}"...', end="", flush=True)
        try:
            urlretrieve(file_uri, file_path, reporthook=with_name(basename))
        except Exception as ex:
            try_unlink(file_path)
            Logger.error(f" Failed to download file. {str(ex)}")

        print(Logger.ok_colored(" Complete."))
        count += 1

    print(Logger.ok_colored(f"Successfully download {count} of {len(playlist_json)} into cache."))
    input("Press enter to exit.")

def parse_args(args: 'list[str]'):
    parser = ArgumentParser(description="Precache Remote Source Tool Version 1.1.0.0")
    parser.add_argument(
        "server_config",
        help=f"The server source configuration.",
        nargs="?",
        default=SERVER_CONFIG_DEFAULT_FILE_NAME,
    )
    return parser.parse_args(args)

def create_local_config_if_not_exists(file_name: str, default_download_dir = DEFAULT_LOCAL_CACHE_DIRECTORY):
    local_config_path = Path(file_name)
    if not local_config_path.exists():
        Logger.info(
            f'Cannot find {file_name}. Generating file using default path "{default_download_dir}".')
        local_config = Config()
        local_config[APP] = {"DownloadDirectory": default_download_dir}
        local_config.write(file_name)

def is_str_list(value: 'typing.Any') -> 'bool':
    return isinstance(value, list) and all(isinstance(f, str) for f in value)

def save_buffer_to(buffer: 'typing.IO[bytes]', file_path: 'Path'):
    with open(file_path, "wb") as f:
        while chunk := buffer.read(40960):
            f.write(chunk)

def try_unlink(file_path: 'str|bytes|os.PathLike[str]|os.PathLike[bytes]'):
    try:
        os.unlink(file_path)
    except IOError:
        pass

def xxx(file_uri: str, file_path: 'Path', basename: str):
    with urlopen(file_uri) as response:
        if response.getcode() != 200:
            print(f" {Logger.error_colored("Error:")} Failed to download file")
            if file_path.exists():
                print(f' {Logger.ok_colored("Notice:")} Deleting previous pre-cached file "{basename}"')
                try_unlink(file_path)
            return False
        save_buffer_to(response, file_path)
        return True

def with_name(name):
    def download_hook(count: int, block_size: int, total_size: int):
        print(f"\rDownloading \"{name}\"... {round(count * block_size / total_size * 100.0, 2):.2f}%", end="", flush=True)
    return download_hook

def fatal(message, ex: Exception|None = None):
    Logger.error(f"Failed to precache items. {message}")
    if ex:
        Logger.error(f"{Logger.error_colored(str(ex))}")
    input("Press enter to exit.")
    exit(1)

class Config:
    _WELL_DEFINED_ENCODING = [
        ("utf-8-sig", b"\xef\xbb\xbf"),
        ("utf-16-le", b"\xff\xfe"),
        ("utf-16-be", b"\xfe\xff"),
        ("utf-32-le", b"\xff\xfe\x00\x00"),
        ("utf-32-be", b"\x00\x00\xfe\xff"),
    ]

    def _detect_known_encoding(self, file_path: str):
        with open(file_path, "rb") as f:
            raw_bytes = f.read(4)
        for encoding, bom in self._WELL_DEFINED_ENCODING:
            if raw_bytes.startswith(bom):
                return encoding
        return ""

    def _try_read(self, *files: str):
        for file in files:
            success = False
            file_hint = self._detect_known_encoding(file)
            # utf-8 covers the ASCII encoding space. These do not contain a BOM
            possible_encodings = ["utf-8", "utf-16", "cp1252"]
            if file_hint:
                possible_encodings.insert(0, file_hint)
            for encoding in possible_encodings:
                try:
                    self.config.read(file, encoding=encoding)
                    success=True
                    break
                except UnicodeError:
                    pass
            if not success:
                raise RuntimeError("Unable to read config file.")

    @staticmethod
    def _maybe_str_lit(value: str | None):
        if value is None:
            return None
        value = str(value)
        if m := STRIP_QUOTES.match(value) is not None:
            return m.group(1)
        return value

    def __init__(self, config = None):
        self.config = ConfigParser() if config is None else config

    def __setitem__(self, section: str, options: dict):
        self.config[section] = options

    def read(self, *files: str):
        self._try_read(*files)

    def get(self, section: str, option: str, fallback: str | None = None):
        value = self.config.get(section, option, fallback=fallback)
        return self._maybe_str_lit(value)

    def __index__(self, section: str):
        return Config(self.config[section])

    def write(self, file: str):
        with open(file, "w", encoding="utf-8") as f:
            self.config.write(f)

class Logger:
    @staticmethod
    def info(message):
        print(str.format("{0} {1}", Logger.info_colored("[INFO]"), message))

    @staticmethod
    def error(message):
        print(str.format("{0} {1}", Logger.error_colored("[ERROR]"), message))

    @staticmethod
    def warning(message):
        print(str.format("{0} {1}", Logger.warn_colored("[WARN]"), message))

    @staticmethod
    def success(message):
        print(str.format("{0} {1}", Logger.ok_colored("[OK]"), message))

    @staticmethod
    def error_colored(string: str):
        return f"\033[31m{string}\033[0m"

    @staticmethod
    def warn_colored(string: str):
        return f"\033[33m{string}\033[0m"

    @staticmethod
    def info_colored(string: str):
        return f"\033[34m{string}\033[0m"

    @staticmethod
    def ok_colored(string: str):
        return f"\033[32m{string}\033[0m"


if __name__ == "__main__":
    main(sys.argv[1:])
