import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, Union

import psutil
from selenium.webdriver import Firefox
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from selenium.webdriver.remote.webdriver import WebDriver
from webdriver_manager.firefox import GeckoDriverManager

from .custom_webdriver import CustomWebDriver

logger = logging.getLogger(__name__)


class ReusableFirefox(CustomWebDriver):

    def __init__(
        self,
        driver_path: Union[Path,
                           str],
        id_path: Union[Path,
                       str],
        implicity_wait: int = 0,
        port: int = 65000,
        options: Optional[FirefoxOptions] = None,
        attach_retries: int = 2,
        new_console: bool = True,
    ):

        if isinstance(driver_path, Path):
            driver_path = str(driver_path)
        self.driver_path = GeckoDriverManager(path=driver_path).install()

        self.id_path = id_path
        self.implicity_wait = implicity_wait
        self.port = port
        self.options = options
        self.attach_retries = attach_retries
        self.new_console = new_console
        return

    @classmethod
    def end_all_driver_processes(self):
        for p in psutil.process_iter():
            if "firefox" in p.name():
                logger.critical(f"Encerrando processo: '{p.name()}'")
                os.system(f"taskkill /f /t /im {p.name()}")

        for p in psutil.process_iter():
            if "firefox" in p.name():
                return False
        else:
            return True

    def begin(self) -> Union[WebDriver, bool]:
        """Realiza o fluxo de criação de um driver usável
        1. Cria os arquivos necessários (chromedriver.exe e id.json)
        2. Tenta utilizar um chrome já aberto
        2.1. Caso não consiga, encerra os processos do chrome abertos
        2.2. Re-abre os chromes, caso seja necessário, atualiza a versão
        3. Após obter um driver utilizável, salva as informações (command executor e ID) para ser reutilizado

        Returns
        ------
        `driver` : WebDriver
            instância do chromedriver
        `False` : bool
            Falha ao criar o chrome
        """

        # se o ID não existir...
        if not os.path.exists(self.id_path):
            logger.critical(f"Arquivo {self.id_path} não existe, criando um novo...")
            with open(self.id_path, "w", encoding="utf-8") as json_file:
                # cria um arquivo json com um dict vazio
                json.dump(dict(), json_file, indent=4)
            logger.critical(f"Arquivo '{self.id_path}' foi criado")

        # -----------------------------------
        # carrega o command executor e o session ID do arquivo id.json
        with open(self.id_path, "r") as json_file:
            try:
                chrome_ids = json.load(json_file)
            except json.decoder.JSONDecodeError:
                chrome_ids = dict()

        logger.debug(f"Arquivo de ID trouxe: '{chrome_ids}'")

        self.last_session_id = chrome_ids.get("session_id", None)
        self.last_command_executor = chrome_ids.get("command_executor", None)

        # -----------------------------------

        for tentativa_atual in range(self.attach_retries):
            logger.critical(f"Tentando criar driver {tentativa_atual+1}/{self.attach_retries}")
            attached = False

            # se tiver command_executor, session_id e um chrome existir, tenta usar uma sessão já aberta
            if (self.last_command_executor and self.last_session_id and self.any_chrome_process_exists):
                attached = self._attach()

            # se não tiver um dos três pra dar attach, então precisa reabrir o chrome
            if not attached:
                self.end_all_driver_processes()  # encerra os chromes em execução

            if attached:
                # se conseguiu dar attach em qualquer momento, sai do loop, se não continua
                break
        else:
            logger.critical(f"Não consegui criar um driver após '{self.attach_retries}' tentativas")
            return False

        # -----------------------------------
        # salva as informações da nova sessão do chromedriver
        chrome_configs = {
            "command_executor": self.command_executor._url,
            "session_id": self.session_id,
        }

        with open(self.id_path, "w", encoding="utf-8") as json_file:
            json.dump(chrome_configs, json_file, indent=4)

        logger.debug(f"Arquivo ID foi atualizado com: {chrome_configs}")

        return True


class CreateFirefox(CustomWebDriver, Firefox):

    def __init__(
        self,
        driver_path: Union[Path,
                           str],
        implicity_wait: int = 0,
        port: int = 64900,
        options: Optional[FirefoxOptions] = None,
        **kwargs,
    ) -> None:

        if isinstance(driver_path, Path):
            driver_path = str(driver_path)
        self.driver_path = GeckoDriverManager(path=driver_path).install()

        self.implicity_wait = implicity_wait
        self.port = port
        self.options = options
        return

    def begin(self):
        # TODO: quando o data-dir já está em execução, dá erro, precisa corrigr
        # ? testar se o data-dir está em uso, se sim, criar um novo?
        # ? ou qual ação tomar?

        #  options=self.options

        Firefox.__init__(self, service=FirefoxService(self.driver_path), options=self.options)

        # super().__init__()
        self.implicitly_wait(self.implicity_wait)

        return True


def create_firefox():
    """Este é apenas uma função exemplo!"""
    # import log

    # log.create_logger(level=10)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # CustomChrome.end_all_chrome_processes()
    firefox_configs = {
        "driver_path": "{APP_PATH}\chromedriver",
        "id_path": "{APP_PATH}\chromedriver\chrome_id.json",
        "port": 65000,
        "implicity_wait": 0,
        "attach_retries": 2,
        "new_console": True,
    }

    firefox_options = {
        "arguments": [
            # "--headless"
        ],
        # http://kb.mozillazine.org/Category:Preferences
        "preferences": {
            "browser.helperApps.neverAsk.saveToDisk": """application/csv,
                                                       application/excel,
                                                       application/vnd.ms-excel,
                                                       application/vnd.msexcel,,
                                                       application/xml,
                                                       application/octet-stream,
                                                       text/anytext,
                                                       text/comma-separated-values,
                                                       text/csv,
                                                       text/plain,
                                                       text/x-csv,,
                                                       text/xml
                                                       application/x-csv,
                                                       text/x-comma-separated-values,
                                                       text/tab-separated-values,
                                                       image/jpeg,
                                                       data:text/csv""",
            "browser.helperApps.neverAsk.openFile": """application/csv,
                                                     application/excel,
                                                     application/vnd.ms-excel,
                                                     application/vnd.msexcel,
                                                     text/anytext,
                                                     text/comma-separated-values,
                                                     text/csv,
                                                     text/plain,
                                                     text/x-csv,
                                                     application/x-csv,
                                                     text/x-comma-separated-values,
                                                     text/tab-separated-values,
                                                     data:text/csv,
                                                     application/xml,
                                                     text/plain,
                                                     text/xml,
                                                     image/jpeg,
                                                     application/octet-stream,
                                                     data:text/csv""",
            "browser.download.manager.showWhenStarting": False,
            "browser.helperApps.alwaysAsk.force": False,
            "browser.download.useDownloadDir": True,
            "dom.file.createInChild": True,
        },
        "extensions": [  # uma pasta com arquivos ou cada arquivo separado
            # r"D:\git\ITGreen\pythonutils\PythonUtils\chromedriver\extensions"
            # r"D:\git\ITGreen\pythonutils\PythonUtils\chromedriver\extensions\CRX-Extractor-Downloader.crx",
            # r"D:\git\ITGreen\pythonutils\PythonUtils\chromedriver\extensions\uBlock-Origin.crx",
        ],
    }

    # --------------------------------------------------

    options = FirefoxOptions()

    for arg in firefox_options["arguments"]:
        options.add_argument(arg)

    # --------------------------------------------------

    for k, v in firefox_options["preferences"].items():
        if isinstance(v, str):
            v = v.replace("\n", "")
            v = re.sub(" +", " ", v)
        options.set_preference(k, v)

    # --------------------------------------------------

    driver = CreateFirefox(**firefox_configs, options=options)  # ok
    if not driver.begin():
        logger.critical(f"Falha ao criar chromedriver")
        return False

    # --------------------------------------------------

    driver.rotate_user_agent()

    driver.set_navigator_to_undefined()

    # driver.refresh()

    # corrige a exception
    # unknown command: session/51ac9879f26bdb921197203660769456/se/file
    driver._is_remote = False

    return driver
