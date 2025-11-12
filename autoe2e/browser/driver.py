import os
import stat
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webdriver import WebDriver
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.firefox import GeckoDriverManager

from autoe2e.utils import AbstractSingleton
from autoe2e.crawler.config import Config


# TODO: if the connection is closed create a new driver
class DriverContainer(AbstractSingleton):
    def __init__(self, config: Config):
        driver_path = ChromeDriverManager().install()
        options = _chrome_options()
        driver = webdriver.Chrome(
            service=Service(_ensure_chromedriver_binary(driver_path)),
            options=options,
        )
        # driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()))
        # wait for elements to load on page if necessary
        # driver.implicitly_wait(10)
        self.driver = driver
    
    
    def get_driver(self) -> WebDriver:
        return self.driver

def get_driver_container(config: Config) -> DriverContainer:
    driver_container = DriverContainer(config)
    return driver_container


def _ensure_chromedriver_binary(driver_path: str) -> str:
    """ webdriver_manager 4.x may return the notice file instead of the binary. """
    path = Path(driver_path)
    if path.name.startswith("THIRD_PARTY_NOTICES"):
        candidate = path.with_name("chromedriver")
        if candidate.exists():
            path = candidate
    str_path = str(path)
    if not os.access(str_path, os.X_OK):
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str_path


def _chrome_options() -> ChromeOptions:
    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    return options
