from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
import os
import time
from pydantic import BaseModel
from threading import Lock
import yaml
from typing import Optional
import json
from pkg.utils.dir_listener import DirListener
from const.const import ROOT_DIR

config_dir = os.path.dirname(os.path.abspath(__file__))
config_file_path = os.path.join(ROOT_DIR, "config", "config.yaml")
lock = Lock()


class App(BaseModel):
    port: Optional[int] = 8080


class Logger(BaseModel):
    level: Optional[str] = "INFO"


class Model(BaseModel):
    base_url: str
    api_key: str
    model_name: str


class Sherpa(BaseModel):
    base_dir: str
    keyword_threshold: Optional[float] = 0.3
    keyword_score: Optional[float] = 0.3
    keywords: list


class NaviConfig(BaseModel):
    base_url: str  # http://x.x.x.x/xx


class AngleSerial(BaseModel):
    serial_port: Optional[str] = "/dev/ttyUSB0"
    baud_rate: Optional[int] = 1000000


class Google(BaseModel):
    api_key: Optional[str] = ""
    model: Optional[str] = "gemini-2.5-flash-native-audio-preview-12-2025"


class Tencent(BaseModel):
    appid: Optional[str] = ""
    secret_id: Optional[str] = ""
    secret_key: Optional[str] = ""


class Config(BaseModel):
    app: Optional[App] = App()
    logger: Optional[Logger] = Logger()
    model: Optional[Model]
    navi: Optional[NaviConfig]
    sherpa: Optional[Sherpa] = None
    serial: Optional[AngleSerial] = AngleSerial()
    google: Optional[Google] = Google()
    tencent: Optional[Tencent] = Tencent()


default_config: Config = None


def config_listen_handler(event):
    if event.src_path.endswith("config.yaml"):
        load_config(reload=True)


def load_config(reload=False):
    global default_config
    global updated_time

    if reload:
        with lock:
            if not os.path.exists(config_file_path):
                raise RuntimeError(f"Config file {config_file_path} not exist")
            with open(config_file_path, "r", encoding="utf-8") as f:
                data = yaml.load(f, Loader=yaml.Loader)
            default_config = Config(**data)
            updated_time = time.time()
        return default_config

    if default_config is not None:
        return default_config
    with lock:
        if default_config is not None:
            return default_config
        if not os.path.exists(config_file_path):
            raise RuntimeError(f"Config file {config_file_path} not exist")
        with open(config_file_path, "r", encoding="utf-8") as f:
            data = yaml.load(f, Loader=yaml.Loader)
        updated_time = time.time()
        _ = DirListener(config_dir, config_listen_handler)
        default_config = Config(**data)
    return default_config


load_config()
