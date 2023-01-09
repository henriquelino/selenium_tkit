import json
import logging
import os
import re
from pathlib import Path
from subprocess import CREATE_NEW_CONSOLE, CREATE_NO_WINDOW, Popen
from typing import Optional, Union

import psutil
from selenium.common.exceptions import (InvalidSessionIdException,
                                        SessionNotCreatedException,
                                        WebDriverException)
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.remote.webdriver import WebDriver
from undetected_chromedriver.patcher import Patcher
from urllib3.exceptions import MaxRetryError
from webdriver_manager.chrome import ChromeDriverManager

from .custom_webdriver import CustomWebDriver

# --------------------------------------------------

logger = logging.getLogger(__name__)

# --------------------------------------------------

class ReusableChrome(CustomWebDriver):

    def __init__(
        self,
        driver_path: Union[Path, str],
        id_path: Union[Path, str],
        implicity_wait: int = 0,
        port: int = 65000,
        options: Optional[ChromeOptions] = None,
        attach_retries: int = 2,
        new_console: bool = True,
        apply_patch: bool = True
    ) -> None:  # yapf: disable
        """Cria um chromedriver que pode ser reutilizado após encerramento do Python

        ---
        Parameters
        ------
        `driver_path` : Path, str
            Caminho até o .exe do chromedriver
        `id_path` : Path, str
            Caminho até o arquivo .json que será salvo o id + command_executor
        `implicity_wait` : int
            Quando executar os scripts, esperar implicitamente por N segundos
        `port` : int
            Porta em que o chromedriver será aberta
        `options` : Options, None
            Opcional, parâmetros adicionais do webdriver
        `attach_retries` : int
            Quantas vezes tentar criar o driver
        `new_console` : bool
            ao criar novo chromedriver, abrir em um novo console ou não
        ---
        ### Exemplos:

        ```
        from PythonUtils.utils import BASE_DIR

        chrome_configs={
            "driver_path": f"{BASE_DIR}\\chromedriver\\chromedriver.exe",
            "id_path": f"{BASE_DIR}\\chromedriver\\chrome_id.json"
        }

        driver = CustomChrome(**chrome_configs)
        if not driver.begin():
            logger.critical(f"Falha ao criar chromedriver")
            exit()

        driver.open_url("https://www.google.com")
        ```
        """

        if isinstance(driver_path, Path):
            driver_path = str(driver_path)
        self.driver_path = ChromeDriverManager(path=driver_path).install()

        if apply_patch:
            patcher = Patcher(executable_path=self.driver_path, force=False)
            patcher.auto()

            self.driver_path = patcher.executable_path

        self.id_path = id_path
        self.implicity_wait = implicity_wait
        self.port = port
        self.options = options
        self.attach_retries = attach_retries
        self.new_console = new_console

        return

    @property
    def any_chrome_process_exists(self):
        for p in psutil.process_iter():
            if "chromedriver.exe" in p.name():
                return True
        else:
            return False

    @classmethod
    def end_all_driver_processes(self):
        for p in psutil.process_iter():
            if "chrome" in p.name():
                logger.critical(f"Encerrando processo: '{p.name()}'")
                os.system(f"taskkill /f /t /im {p.name()}")

        for p in psutil.process_iter():
            if "chrome" in p.name():
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
        `True` : bool
            Sucesso criando chrome
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
                attached = self.__attach()

            # se não tiver um dos três pra dar attach, então precisa reabrir o chrome
            if not attached:
                self.end_all_driver_processes()  # encerra os chromes em execução
                self.__create_new_chrome()  # cria um novo chrome com Popen
                attached = self.__attach()  # tenta utilizar o chrome criado

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

    def __create_new_chrome(self):
        """Cria um novo chrome, porém o método é um pouco diferente do convencional\n

        O chromedriver.exe é executado como uma nova janela (geralmente)\n
        Assim após o Python terminar a execução, o processo do chromedriver continuará ativo
        para podermos reutilizarmos posteriormente
        """
        logger.debug("Executando um novo Chrome")

        if self.new_console:
            flag = CREATE_NEW_CONSOLE
        else:
            flag = CREATE_NO_WINDOW

        full_launch = f'"{self.driver_path}" --port={self.port}'
        logger.debug(f"Executando chrome: '{full_launch}'")
        self.chrome_process = Popen(full_launch, creationflags=flag)

        self.last_command_executor = f"http://127.0.0.1:{self.port}"
        self.last_session_id = (
            None  # reseta o session ID, assim não utiliza o do arquivo
        )
        return

    def __attach(self):
        logger.debug("Tentando attachear a um Chrome já existente...")

        # pra dar o attach, tem que existir algum chrome aberto
        # então procura um processo do chrome
        if not self.any_chrome_process_exists:
            logger.debug("Nenhum processo com nome de chrome encontrado, não vou tentar dar attach...")
            return False

        # --------------------  --------------------

        if self.options is not None:
            # se a primeira vez que foi instanciado foi com user-data-dir,
            # na reutilização será necessário retirar esse parâmetro
            for opt in self.options.to_capabilities()["goog:chromeOptions"]["args"]:
                if "user-data-dir" in opt:
                    data_dir = opt.split("=")[1]

                    # se a pasta data-dir estiver em uso, remove o argumento para não dar erro
                    if os.path.exists(data_dir):  # se a pasta existe
                        # tenta renomear pro mesmo nome, valida se está em uso
                        # se der erro, significa que ela está em uso e o parâmetro precisa ser removido
                        try:
                            os.rename(data_dir, data_dir)
                        except OSError:
                            # retira a opção de data-dir do self.options
                            self.options.to_capabilities()["goog:chromeOptions"]["args"].remove(opt)
                    break

        # --------------------  --------------------

        try:
            # antigo pra referencia:
            # driver = webdriver.Remote(self.last_command_executor, options=self.options)

            # o super desta classe é o Remote
            super().__init__(command_executor=self.last_command_executor, options=self.options)

        except SessionNotCreatedException as e:
            logger.exception(f"Geralmente o chrome está desatualizado:")
            # tira a versão que o chrome está para baixar o chromedriver dela
            version = re.findall("version is (.*) with binary", str(e))
            if version:
                self.driver_path = ChromeDriverManager(path=self.driver_path).install()
            return False
        except (MaxRetryError, WebDriverException):
            logger.exception(f"Exceção ao conectar no chrome usando Remote:")
            self.end_all_driver_processes()
            return False

        # --------------------  --------------------

        # se não tem session ID então o chrome que foi aberto é novo
        # se já tinha session ID precisa fechar o driver (ele sempre abre um novo, mesmo usando remote, ele que será fechado) e mudar o ID
        if self.last_session_id is not None:
            self.close()
            self.session_id = self.last_session_id

        # --------------------  --------------------
        # validações pra verificar se o driver que foi aberto está responsivo
        try:
            for handle in self.window_handles:
                self.switch_to.window(handle)
                break
        except InvalidSessionIdException:
            logger.critical(f"Session ID '{self.last_session_id}' gravada não serve para o chrome atual")
            return False
        except WebDriverException:
            logger.critical("Geralmente chrome not reachable")
            return False

        # --------------------  --------------------
        # muda o implicity_wait do driver
        self.implicitly_wait(self.implicity_wait)
        # se ele falhar no Remote ou no swith_to, retorna False
        # pois não conseguiu de fato assumir o controle de um chrome
        # return False

        # --------------------  --------------------
        logger.critical("Attach com sucesso!")
        return True


class CreateChrome(CustomWebDriver, Chrome):

    def __init__(
        self,
        driver_path: Union[Path,
                           str],
        implicity_wait: int = 0,
        port: int = 64900,
        options: Optional[ChromeOptions] = None,
        **kwargs,
    ) -> None:

        if isinstance(driver_path, Path):
            driver_path = str(driver_path)
        self.driver_path = ChromeDriverManager(path=driver_path).install()

        self.implicity_wait = implicity_wait
        self.port = port
        self.options = options
        return

    def begin(self):

        serv = ChromeService(executable_path=self.driver_path, port=self.port)

        super().__init__(service=serv, options=self.options)

        self.implicitly_wait(self.implicity_wait)

        return True

# --------------------------------------------------

def create_chrome():
    """This is an example function that you can copy and customize for each project"""
    BASE_DIR = Path(__file__).parent.resolve()
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    chrome_configs = {
        "driver_path": BASE_DIR / "/chromedriver",
        "id_path": BASE_DIR / "chromedriver/id.json",
        "port": 65000,
        "implicity_wait": 0,
        "attach_retries": 2,
        "new_console": True,
    }

    chrome_options = {
        "arguments": [
            "log-level=3",
            "no-first-run",
            # "incognito",
            "no-default-browser-check",
            "disable-infobars",
            "disable-blink-features",
            "disable-blink-features=AutomationControlled",
            rf"user-data-dir={BASE_DIR}\chromedriver\data-dir",
        ],
        "experimental": {
            "prefs": {
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "plugins.always_open_pdf_externally": True,
                "download.default_directory": BASE_DIR / "chromedriver/downloads",
            },
            "excludeSwitches": ["enable-automation", "ignore-certificate-errors"],
            "useAutomationExtension": False,
        },
        "extensions": [  
            # r"path_to\extensions" # --> a folder will use all .crx of folder
            # r"path_to\extensions\uBlock-Origin.crx", # --> only a single extension
        ],
    } # yapf: disable

    options = ChromeOptions()
    
    # --------------------------------------------------
    # add arguments
    for arg in chrome_options["arguments"]:
        options.add_argument(arg)

    # --------------------------------------------------
    # add experimental options
    for k, v in chrome_options["experimental"].items():
        options.add_experimental_option(k, v)

    # --------------------------------------------------
    # if extension isn't a list or a tuple, fixes to a list
    if chrome_options["extensions"] and not isinstance(chrome_options["extensions"], (list, tuple)):
        chrome_options["extensions"] = list(chrome_options["extensions"])

    # add extensions
    all_extensions = list()
    for ext in chrome_options["extensions"]:
        ext = Path(ext)
        if ext.is_dir():
            for e in ext.glob("*.*"):
                all_extensions.append(str(e))
        else:
            all_extensions.append(str(ext))

    for ext in all_extensions:
        options.add_extension(ext)

    # --------------------------------------------------

    # CustomChrome.end_all_chrome_processes()
    driver = CreateChrome(**chrome_configs, options=options) # creates a chrome that closes after program ends
    # driver = ReusableChrome(**chrome_configs, options=options) # creates a chrome session that can be reused over runs
    if not driver.begin():
        logger.critical(f"Something went wrong creating a chrome instance. Check logs for details.")
        return False

    # --------------------------------------------------

    driver.rotate_user_agent()

    driver.set_navigator_to_undefined()

    # driver.refresh()

    # corrects the exception: "unknown command: session/_____/se/file"
    driver._is_remote = False

    return driver
