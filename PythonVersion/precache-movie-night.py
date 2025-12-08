import os
from sys import exit
from pathlib import Path, PurePath
from http.client import HTTPSConnection
from configparser import ConfigParser
from argparse import ArgumentParser
from urllib.parse import urlparse, urljoin
from urllib.request import urlopen
from json import load


SERVER_CONFIG_DEFAULT_FILE_NAME: str = "precache-remote-settings.ini"
LOCAL_CONFIG_DEFAULT_FILE_NAME: str = "precache-local-settings.ini"
DEFAULT_LOCAL_CACHE_DIRECTORY: str = "./MovieNight"


class Util:
    @staticmethod
    def exitFatal(message):
        print("Error: Failed to precache items")
        print(f"{Util.error_colored("Error")}: {message}")
        input("Press enter to exit.")
        exit(1)

    WELL_DEFINED_ENCODING = [
        {
            "encoding": "utf-8-sig",
            "bom": b"\xef\xbb\xbf",
        },
        {
            "encoding": "utf-16-le",
            "bom": b"\xff\xfe",
        },
        {
            "encoding": "utf-16-be",
            "bom": b"\xfe\xff",
        },
        {
            "encoding": "utf-32-le",
            "bom": b"\xff\xfe\x00\x00",
        },
        {
            "encoding": "utf-32-be",
            "bom": b"\x00\x00\xfe\xff",
        },
    ]

    @staticmethod
    def detectKnownEncoding(file_path: str):
        with open(file_path, "rb") as f:
            raw_bytes = f.read(4)
        for encoding_def in Util.WELL_DEFINED_ENCODING:
            if raw_bytes.startswith(encoding_def.get("bom")):
                return encoding_def.get("encoding")
        return ""

    @staticmethod
    def tryReadConfig(config: ConfigParser, file: str):
        file_hint = Util.detectKnownEncoding(file)
        # utf-8 covers the ANSII encoding space. These do not contain a BOM
        possible_encodings = ["utf-8", "utf-16", "cp1252"]
        if file_hint:
            possible_encodings.insert(0, file_hint)
        for encoding in possible_encodings:
            try:
                config.read(file, encoding=encoding)
                return
            except UnicodeError:
                pass
        raise RuntimeError("Unable to read config file.")

    @staticmethod
    def maybe_str_lit(stringLike: str|None):
        if not isinstance(stringLike, str): return None
        if stringLike.startswith("'"): return stringLike.strip("'")
        if stringLike.startswith('"'): return stringLike.strip('"')
        return stringLike
    

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


parser = ArgumentParser(description="Precache Remote Source Tool Verson 1.1.0.0")
parser.add_argument(
    "server_config",
    help=f"The server source configuration.",
    nargs="?",
    default=SERVER_CONFIG_DEFAULT_FILE_NAME,
)
parser_result = parser.parse_args()
server_config_path = Path(parser_result.server_config)
if not server_config_path.exists():
    Util.exitFatal(
        f'The server source configuration is required. Default file is "{SERVER_CONFIG_DEFAULT_FILE_NAME}"'
    )

server_config = ConfigParser()
Util.tryReadConfig(server_config, parser_result.server_config)

if not Path(LOCAL_CONFIG_DEFAULT_FILE_NAME).exists():
    print(
        f'{Util.info_colored("Info:")}Cannot find {LOCAL_CONFIG_DEFAULT_FILE_NAME}, Generating file. Using Default path "{DEFAULT_LOCAL_CACHE_DIRECTORY}"'
    )
    local_config = ConfigParser()
    local_config["Application"] = {"DownloadDirectory": DEFAULT_LOCAL_CACHE_DIRECTORY}
    download_directory = local_config["Application"]["DownloadDirectory"]
    with open(
        LOCAL_CONFIG_DEFAULT_FILE_NAME, "w", encoding="utf-8"
    ) as local_config_file:
        local_config.write(local_config_file)
else:
    local_config = ConfigParser()
    Util.tryReadConfig(local_config, LOCAL_CONFIG_DEFAULT_FILE_NAME)

download_directory = str(PurePath(local_config.get(
    "Application", "DownloadDirectory", fallback=DEFAULT_LOCAL_CACHE_DIRECTORY
)))

download_directory_path = Path(download_directory).resolve()

if not download_directory_path.exists():
    Util.exitFatal(
        f'The directory "{download_directory_path.name}" does not exist. Ensure your plugin is installed and running from the Application Installation Directory or the directory is created.'
    )

playlist_config = Util.maybe_str_lit(server_config.get("Application", "Playlist", fallback=None))

if not playlist_config:
    Util.exitFatal("Playlist is not optional in a Server Configuration .ini!")

parsed_playlist_path = urlparse(playlist_config)
download_server_config = Util.maybe_str_lit(server_config.get(
    "Application", "DownloadServer", fallback=None
))

parsed_download_server = urlparse(download_server_config)

if not parsed_download_server.netloc and not parsed_playlist_path.netloc:
    Util.exitFatal(
        "A fully qualified url is required when DownloadServer is empty for Playlist"
    )

download_server_uri = download_server_config + "/" if download_server_config else ""
playlist_uri = urljoin(download_server_uri, playlist_config)

with urlopen(playlist_uri) as response:
    if response.getcode() != 200:
        Util.exitFatal(
            f'Unable to find the file at "{playlist_uri}". Unable to continue.'
        )

    playlist_json = load(response)

if not playlist_json or not (
    isinstance(playlist_json, list) and all(isinstance(f, str) for f in playlist_json)
):
    Util.exitFatal(
        "Unexpected Server response after retrieving json! Expected array of strings"
    )

count = 0
for filename in playlist_json:
    file_uri = urljoin(download_server_uri, filename)
    basename = os.path.basename(urlparse(file_uri).path)
    file_path = download_directory_path / basename

    print(f'Downloading "{basename}"')
    with urlopen(file_uri) as response:
        if response.getcode() != 200:
            print(f" {Util.error_colored("Error:")} Failed to download file")
            if file_path.exists():
                print(f' {Util.ok_colored("Notice:")} Deleting previous pre-cached file "{basename}"')
                file_path.unlink()
            continue

        with open(file_path, "wb") as f:
            while chunk := response.read(4096):
                f.write(chunk)

    print(Util.ok_colored("Complete."))
    count += 1

print(Util.ok_colored(f"Successfully download {count} of {len(playlist_json)} into cache."))
input("Press enter to exit.")
