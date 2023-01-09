import logging
import re
from pathlib import Path
from typing import Optional, Union

from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager

from .custom_webdriver import CustomWebDriver

logger = logging.getLogger(__name__)


class CreateEdge(CustomWebDriver):

    def __init__(
        self,
        driver_path: Union[Path, str],  # yapf: disable
        implicity_wait: int = 0,
        port: int = 64900,
        options: Optional[EdgeOptions] = None,
        **kwargs,
    ) -> None:

        if isinstance(driver_path, Path):
            driver_path = str(driver_path)
        self.driver_path = EdgeChromiumDriverManager(path=driver_path).install()

        self.implicity_wait = implicity_wait
        self.port = port
        self.options = options
        return

    def begin(self):
        # TODO: quando o data-dir já está em execução, dá erro, precisa corrigr
        # ? testar se o data-dir está em uso, se sim, criar um novo?
        # ? ou qual ação tomar?

        serv = EdgeService(executable_path=self.driver_path, port=self.port)

        super().__init__(service=serv, options=self.options)

        self.implicitly_wait(self.implicity_wait)

        return True


def create_edge():
    """Este é apenas uma função exemplo!"""
    # import PythonUtils.log as log

    # log.create_logger(level=10)
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # CustomChrome.end_all_chrome_processes()
    edge_configs = {
        "driver_path": "{APP_PATH}\chromedriver",
        "id_path": "{APP_PATH}\chromedriver\chrome_id.json",
        "port": 65000,
        "implicity_wait": 0,
        "attach_retries": 2,
        "new_console": True,
    }

    edge_options = {}

    # --------------------------------------------------

    options = EdgeOptions()

    if edge_options:
        for arg in edge_options["arguments"]:
            options.add_argument(arg)

        # --------------------------------------------------

        for k, v in edge_options["preferences"].items():
            if isinstance(v, str):
                v = v.replace("\n", "")
                v = re.sub(" +", " ", v)
            options.add_experimental_option(k, v)

    logger.critical(f"{options.arguments = }")
    logger.critical(f"{options.capabilities = }")

    # --------------------------------------------------

    driver = CreateEdge(**edge_configs, options=options)  # ok
    if not driver.begin():
        logger.critical(f"Falha ao criar edge driver")
        return False

    # --------------------------------------------------

    driver.rotate_user_agent()

    driver.set_navigator_to_undefined()

    # driver.refresh()

    # corrige a exception
    # unknown command: session/51ac9879f26bdb921197203660769456/se/file
    driver._is_remote = False

    return driver
