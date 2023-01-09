import json
import logging
import os
import sys
import time
from pathlib import Path
import shutil

import pytest
from src.py_selenium_ext.chrome import CreateChrome, ReusableChrome

BASE_DIR = Path(__file__).parent.resolve()
WEBDRIVER_PATH = BASE_DIR / "webdriver"
ID_PATH = BASE_DIR / "id.json"

def teardown():
    ReusableChrome.end_all_driver_processes()
    if ID_PATH.exists():
        ID_PATH.unlink()
        
    if WEBDRIVER_PATH.exists():
        shutil.rmtree(str(WEBDRIVER_PATH))
        
    

logging.getLogger("selenium").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

if sys.platform == "win32":
    # without this tox couldn't find chrome binary
    os.environ.update({"PROGRAMW6432": "C:\\Program Files",})


class TestDisposable:
    
    def test_basic_create(self):
        teardown()
        chrome = CreateChrome(WEBDRIVER_PATH)
        chrome.begin()
        chrome.open_url("https://www.google.com/")
        assert chrome.current_url == "https://www.google.com/"
        chrome.quit()


class TestReusable:
    
    def test_create_wo_patch(self):
        teardown()
        chrome = ReusableChrome(WEBDRIVER_PATH, ID_PATH, apply_patch=False)
        ret = chrome.begin()
        assert ret is True
        assert chrome.open_url("https://www.google.com/") is True
        chrome.quit()
        assert chrome.end_all_driver_processes() is True
        
    def test_end_all_chrome_processes_wo_chrome(self):
        assert ReusableChrome.end_all_driver_processes() is True
        
    def test_end_all_chrome_processes_w_chrome(self):
        chrome = ReusableChrome(str(WEBDRIVER_PATH), ID_PATH)
        ret = chrome.begin()
        assert ret is True
        assert chrome.end_all_driver_processes() is True
        
    def test_create(self):
        teardown()
        chrome = ReusableChrome(WEBDRIVER_PATH, ID_PATH)
        ret = chrome.begin()
        assert ret is True
        assert chrome.open_url("https://www.google.com/") is True
        chrome.quit()
        assert chrome.end_all_driver_processes() is True
        
    def test_reuse(self):
        """uses the same session from the last test, with same id.json, this does not run teardown"""
        chrome = ReusableChrome(WEBDRIVER_PATH, ID_PATH)
        ret = chrome.begin()
        assert ret is True
        assert chrome.open_url("https://www.google.com/") is True
        chrome.quit()
        assert chrome.end_all_driver_processes() is True
        
        
    def test_broken_id_json(self):
        """uses the same session from the last test, with same id.json, this does not run teardown"""
        with ID_PATH.open('w') as f:
            f.write("")
            
        chrome = ReusableChrome(WEBDRIVER_PATH, ID_PATH)
        ret = chrome.begin()
        assert ret is True
        
    