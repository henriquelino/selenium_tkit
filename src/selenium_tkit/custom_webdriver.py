import json
import logging
import time
from typing import Literal, Optional, Union

from fake_useragent import FakeUserAgent
from retimer import Timer
from selenium.common.exceptions import (JavascriptException,
                                        StaleElementReferenceException,
                                        TimeoutException,
                                        UnexpectedAlertPresentException,
                                        WebDriverException)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# --------------------------------------------------

logger = logging.getLogger(__name__)

# --------------------------------------------------

class CustomWebDriver(WebDriver):

    def execute_cdp_cmd(self, cmd, params={}):
        url = f"{self.command_executor._url}/session/{self.session_id}/chromium/send_command_and_get_result"
        body = json.dumps({"cmd": cmd, "params": params})
        response = self.command_executor._request("POST", url, body)
        return response.get("value")

    def rotate_user_agent(self, ua: Optional[str] = None) -> bool:
        """Rotates the agent using FakeUserAgent[1]

        [1]: https://pypi.org/project/fake-useragent/
        ---
        Parameters
        ------
        `ua` : UserAgent
            Optional, use `None` for a random agent
        """
        if ua is None:
            ua = FakeUserAgent().random
        
        try:
            logger.debug(f"User agent atual: '{self.execute_script('return navigator.userAgent')}'")
            
            self.execute_cdp_cmd("Network.setUserAgentOverride", {"userAgent": ua})
            
            logger.debug(f"User agent novo: '{self.execute_script('return navigator.userAgent')}'")
        except WebDriverException:
            logger.exception("Exception occured while changing browser user agent")
            return False
        
        return True


    def set_navigator_to_undefined(self) -> None:
        """https://w3c.github.io/webdriver/#interface"""
        
        self.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                    })
                """
            },
        ) # yapf: disable
        
        return

    def scroll_down(
        self, *,
        scroll_sleep: Union[int, float] = 5,
        timeout: Union[int, float] = 30
        ) -> bool:  # yapf: disable
        """Scroll page down

        ---
        Parameters
        ------
        `scroll_sleep` : int, float
            Time between each scroll
        `timeout` : int, float
            Time limit to reach the botton of the page

        Returns
        ------
        `True` : bool
            Reached page ends
        `False` : bool
            Timeout
        """

        last_height = self.execute_script("return document.body.scrollHeight")

        timer = Timer(timeout)
        while timer.not_expired:
            try:
                # scrolls to the page height (botton of the page)
                self.execute_script("window.scrollTo(0, document.body.scrollHeight);")

                # wait to page loads/scrolls
                time.sleep(scroll_sleep)

                # double check for page state becomes complete
                self.wait_page_state(timeout=scroll_sleep)

                # gets the new height of the page
                new_height = self.execute_script("return document.body.scrollHeight")
            except WebDriverException:
                logger.exception(f"Exception ao scrollar a página:")
                continue

            # if the height now is the same as the height before
            # we consider that the page is not fully scrolled
            if new_height == last_height:
                logger.debug(f"Page height hasn't changed since last scroll. Assuming it's fully scrolled.")
                return True

            last_height = new_height
            continue

        if timer.expired:
            logger.info(f"Timeout scrolling page after '{timer.duration}' seconds")
            return False

    def open_url(
        self,
        url: str,
        *,
        state: Literal["complete", "loading", "interactive"] = "complete",
        timeout: Union[float, int] = 30,
    ) -> bool:  # yapf: disable
        """Opens an URL and waits for the website state to be equals `state`

        Encapsulates ``driver.get(url)`` and ``driver.wait_ready_state(state, timeout)``\n
        ---
        Parameters
        ------
        `url` : str
            URL to load
        `state` : str
            One of the following: ['complete', 'loading', 'interactive']
        `timeout` : int, float
            Time for URL to load

        Returns
        ------
        `True` : bool
            Website loaded
        `False` : bool
            Timeout
        """
        self.set_page_load_timeout(timeout)
        try:
            self.get(url)
        except (WebDriverException, TimeoutException):
            logger.exception(f"Exception loading url: '{url}'")
            return False

        loaded = self.wait_page_state(state, timeout)
        if not loaded:
            logger.debug(f"Timeout waiting page reach state '{state}'")
            return False

        logger.info(f"URL '{url}' loaded, title: '{self.title}'")
        return True

    def wait_page_state(
        self,
        state: Literal["complete", "loading", "interactive"] = "complete",
        timeout: Union[float, int] = 30,
    ) -> bool:  # yapf: disable
        """Waits the current page to reach desired `state`

        ---
        Parameters
        ------
        `state` : str
            Expected state
        `timeout` : int, float
            Timeout to reach the state

        Returns
        ------
        `True` : bool
            State reached
        `False` : bool
            Timeout
        """

        timer = Timer(timeout)

        while timer.not_expired:
            try:
                page_state = self.wait_execute_script("document.readyState", timeout=1)
            except WebDriverException:
                logger.exception("")
                time.sleep(1)
                continue
            
            logger.debug(f"Page state now: '{page_state}'. Desired state: '{state}'")
            if state == state:
                return True
            
            time.sleep(1)
            continue

        if timer.expired:
            logger.debug(f"Timeout after {timer.duration} seconds")
            return False

    def wait_execute_script(
        self,
        script: str,
        *,
        timeout: Union[float, int] = 30,
        force_wait_webelement: bool = False,
    ) -> Union[bool, WebElement, list[WebElement], str]:  # yapf: disable
        """Executes a javascript script on browser with a timeout

        ---
        Parameters
        ------
        `script` : str
            JS script to execute
        `timeout` : int, float
            Time for script to execute successfully

        Returns
        ------
        `r` : bool, WebElement
            Script result
        `False` : bool
            Couldn't execute script
        """
        
        timer = Timer(timeout)
        while timer.not_expired:

            try:
                r = self.execute_script(script)
            except (
                JavascriptException,
                StaleElementReferenceException,
                UnexpectedAlertPresentException,
            ):
                # These exceptions can be retried and works for most of cases
                logger.exception("")
                time.sleep(1)
                continue
            
            except Exception:
                logger.exception(f"Unknow exception!")
                raise

            if force_wait_webelement:
                # if the return must be a web element, forces the loop to continue
                if isinstance(r, WebElement):
                    return r
                elif isinstance(r, list): # if it's a list, check if any item is a WebElement
                    if any([isinstance(i, WebElement) for i in r]):
                        return r
                
                time.sleep(1)
                continue

            # Some actions dont return anything, if thats the case, returns True
            # so we can at least evaluate the result
            r = True if r is None else r
            return r

        if timer.expired:
            logger.debug(f"Timeout after {timer.duration} seconds")
            return False

    def wait_find_element(
        self,
        by: Union[By,Literal["id", "xpath", "link text", "partial link text",
                             "name", "tag name", "class name", "css selector"]],
        selector: str,
        timeout: Union[float, int] = 30,
    ) -> Union[bool, WebElement]:  # yapf: disable
        """Searches an webelement using `WebDriverWait` and any of these expected conditions: `element_to_be_clickable`, `visibility_of`, `presence_of_element_located`

        ---
        Parameters
        ------
        `by` : By, str
            um dos seguintes tipos: ["id", "xpath", "link text", "partial link text", "name", "tag name", "class name", "css selector"]
        `selector` : str
            qual seletor usar
        `timeout` : int, float
            esperar por quanto tempo para encontrar o elemento

        Returns
        ------
        `r` : WebElement
            Elemento web
        `False` : bool
            Exception ao encontrar o elemento web
        """

        timer = Timer(timeout)
        while timer.not_expired:
            try:
                try:
                    clickable = WebDriverWait(self, 0.01).until(EC.element_to_be_clickable((by, selector)))
                except (TimeoutException, WebDriverException, AttributeError):
                    clickable = None

                try:
                    visibility = WebDriverWait(self, 0.01).until(EC.visibility_of((by, selector)))
                except (TimeoutException, WebDriverException, AttributeError):
                    visibility = None

                try:
                    presence = WebDriverWait(self, 0.01).until(EC.presence_of_element_located((by, selector)))
                except (TimeoutException, WebDriverException, AttributeError):
                    presence = None
            
            except Exception:
                logger.exception(f"Unknow exception occured")
                raise
            
            if visibility:
                logger.critical(f"Found element with condition: 'visibility_of'")
                r = visibility
            elif clickable:
                logger.critical(f"Found element with condition: 'element_to_be_clickable'")
                r = clickable
            elif presence:
                logger.critical(f"Found element with condition: 'presence_of_element_located'")
                r = presence
            else:
                continue

            return r

        if timer.expired:
            logger.info(f"Timeout após {timer.duration} segundos")
            return False

    def wait_find_elements(
        self,
        by: Union[By, Literal["id", "xpath", "link text", "partial link text",
                              "name", "tag name", "class name", "css selector"]],
        selector: str,
        timeout: Union[float, int] = 30,
    ) -> Union[bool, list[WebElement]]:  # yapf: disable
        """Procura um elemento usando `WebDriverWait` e `EC.element_to_be_clickable`

        ---
        Parameters
        ------
        `by` : By, str
            um dos seguintes tipos: ["id", "xpath", "link text", "partial link text", "name", "tag name", "class name", "css selector"]
        `selector` : str
            qual seletor usar
        `timeout` : int, float
            esperar por quanto tempo para encontrar o elemento

        Returns
        ------
        `r` : list[WebElement]
            Lista de WebElements
        `False` : bool
            Ocorreu uma exception ao encontrar o elemento web
        """

        timer = Timer(timeout)
        while timer.not_expired:
            try:
                try:
                    r = WebDriverWait(self, 1).until(EC.presence_of_all_elements_located((by, selector)))
                except (TimeoutException, WebDriverException, AttributeError):
                    presence = None
                    
                try:
                    r = WebDriverWait(self, 1).until(EC.visibility_of_all_elements_located((by, selector)))
                except (TimeoutException, WebDriverException, AttributeError):
                    visibility = None
            
            except Exception:
                logger.exception(f"Unknow exception occured")
                raise
                
            
            if visibility:
                logger.critical(f"Found element with condition: 'visibility_of_all_elements_located'")
                r = visibility
            elif presence:
                logger.critical(f"Found element with condition: 'presence_of_all_elements_located'")
                r = presence
            else:
                continue

            return r

        if timer.expired:
            logger.critical(f"Timeout após {timer.duration} segundos")
            return False

    def click_element(
        self,
        element: WebElement,
        *,
        js_click: bool = True
        ) -> bool:  # yapf: disable
        """Clicks on `element`, by default js_click is True, it uses `execute_script`, this seens to be the overall best method,\n
        if it didn't work use js_click = False to use ActionChains instead
        
        ---
        Parameters
        ------
        `element` : WebElement
            The webelement to be clicked
        `js_click` : bool
            True uses execute_script, False uses ActionChains
        
        Returns
        ------
        `True` : bool
            Clicked on WebElement
        `False` : bool
            Couldn't click on WebElement
        """

        try:
            if js_click is True:
                # clicks using execute_script, overall seens to be the best way to reliably click
                self.execute_script("arguments[0].click();", element)
            else:
                # clicks using ActionChains, use this if js_click didn't works
                action = ActionChains(self)
                action.move_to_element(element)
                action.click(element)
                action.perform()        
            return True
        
        except Exception:
            logger.exception(f"Unknow exception occured")
            return False

    def find_and_click_element(
        self,
        timeout: Union[float, int] = 30,
        **kwargs
        ) -> bool:  # yapf: disable
        """* If provided `by` and `selector` uses `wait_find_element`
        * If provided `script` then uses `wait_execute_script`
        ---
        Parameters
        ------
        * To use ``wait_find_element`` use the parameters:
            * ``by``
            * ``selector``
        * To use ``wait_execute_script`` use the parameter:
            * ``script``
        `timeout` : int
            Timeout to find and click the element
        `js_click` : bool
            Optional, uses True for execute_script click and False for ActionChains click

        Returns
        ------
        `r` : bool
            Return of the `click_element` function
        `False` : bool
            Element hasn't been found
        """

        if kwargs.get("by") and kwargs.get("selector"):
            element = self.wait_find_element(by=kwargs["by"], selector=kwargs["selector"], timeout=timeout)

        elif kwargs.get("script"):

            if ".click()" in kwargs["script"]:
                # tira o .click do script, queremos o WebElement aqui
                kwargs["script"] = kwargs["script"].replace(".click()", "")
                logger.critical("Script had '.click()', removed it!")

            element = self.wait_execute_script(script=kwargs["script"], timeout=timeout, force_wait_webelement=True)

        else:
            raise KeyError("Use 'by' e 'selector' para wait_find_element, ou 'script' para execute_script")

        # --------------------------------------------------
        
        if not element:
            logger.debug("Element wasn't found to be clicked")
            return False

        # --------------------------------------------------

        logger.debug("Element found, clicking...")
        # By default clicks using javascript, if js_click is False then uses ActionChains
        r = self.click_element(element, js_click=kwargs.get("js_click", True))
        return r

    def fill_element(
        self,
        element: WebElement,
        text: str,
        *,
        timeout: Union[float, int] = 30,
        clear_before_fill: bool = True,
        tab_after_fill: bool = True,
    ) -> bool:  # yapf: disable
        """Preferably uses `find_and_fill_element` for the extra validation!

        Fills a WebElement with desired text\n
        ---
        Parameters
        ------
        `element` : WebElement
            Element where the text will be put
        `text` : str
            Text to be filled
        `timeout` : int
            Timeout to fill
        `clear_before_fill` : bool
            Clear the field before putting the text?
        `tab_after_fill` : bool
            Press tab after filling the text?

        Returns
        ------
        `True` : bool
            Element was filled with the text
        `False` : bool
            Couldn't fill the element
        """
        timer = Timer(timeout)
        while timer.not_expired:
            logger.debug("Waits element to not be read-only")
            try:
                if element.get_attribute("readonly") is True:
                    logger.debug(f"Element was readonly, waiting")
                    time.sleep(1)
                    continue
            except StaleElementReferenceException:
                logger.debug("Element becomes stale")
                return False
            except Exception:
                logger.exception(f"Unknow exception waiting element to not be readonly")
                time.sleep(1)
                continue

            # Fills the element
            try:
                logger.debug(f"Filling element with: '{text}'")
                element.send_keys(Keys.NULL) # to get focus
                if clear_before_fill:
                    element.clear() # clear with selenium functions
                    self.execute_script("arguments[0].value = '';", element) # clear with javascript
                    for _ in range(len(text) * 2):
                        # press delete and backspace 2 times the size of text to be filled
                        element.send_keys(Keys.BACKSPACE)
                        element.send_keys(Keys.DELETE)

                element.send_keys(text) # send keys to the webelement
                
                if tab_after_fill:
                    element.send_keys(Keys.TAB)
                    
                return True

            except Exception:
                logger.exception(f"")
                time.sleep(1)
                continue

        if timer.expired:
            logger.critical(f"Timeout after {timer.duration} seconds")
            return False

    def find_and_fill_element(
        self,
        texto: str,
        timeout: Union[float, int] = 30,
        clear_before_fill: bool = True,
        tab_after_fill: bool = True,
        **kwargs,
        ) -> bool:  # yapf: disable
        """Dê preferência a utilizar esta função ao invés da função `fill_element` pela validação extra de preenchimento!

        * Se receber as variaveis `by` e `selector`, então usa a função `wait_find_element`
        * Se receber `script` usa a função `wait_execute_script`\n

        ---
        Parameters
        ------
        Para usar `wait_find_element` use:
            * `by` : (str)
                Um dos seguintes tipos: ["id", "xpath", "link text", "partial link text", "name", "tag name", "class name", "css selector"]
            * `selector` : (str)
                Qual o seletor para encontrar o elemento
        Para usar `wait_execute_script` use:
            * `script` : (str)
                O script em javascript que será executado
        `texto` : str
            Texto a ser inserido no elemento
        `timeout` : int
            Tempo para procurar e preencher o elemento
        `show_exception` : bool
            logger.exception caso ocorra

        Returns
        ------
        `True` : bool
            Elemento preenchido
        `False` : bool
            Falha ao preencher (ver log)
        """

        timer = Timer(timeout)
        while timer.not_expired:
            
            if kwargs.get("by") and kwargs.get("selector"):
                element = self.wait_find_element(by=kwargs["by"], selector=kwargs["selector"], timeout=0.05)

            
            elif kwargs.get("script"):
                element = self.wait_execute_script(script=kwargs["script"], timeout=0.05, force_wait_webelement=True)

            
            else:
                raise KeyError("Use 'by' and 'selector' for 'wait_find_element', or 'script' for 'execute_script'")

            if not isinstance(element, WebElement):
                logger.debug(f"Couldn't find any element, trying again. '{element = }'")
                time.sleep(0.05)
                continue

            # --------------------------------------------------

            # validate text filled
            if (element.get_attribute("value") == texto) or (element.text == texto):
                logger.debug(f"Element successfully filled with '{texto}'")
                return True
            
            logger.critical(f"Element have the value: attribute='{element.get_attribute('value')}'/text='{element.text}'")

            # fills the element
            self.fill_element(
                element,
                texto,
                timeout= 0.05, # even if timeout occurs, it will loop until successfully fills or the outer timeout happens
                clear_before_fill=clear_before_fill,
                tab_after_fill=tab_after_fill,
            )

            logger.debug("Validating...")
            continue

        if timer.expired:
            logger.critical(f"Timeout after {timer.duration} seconds")
            return False

    def get_download_all_progress(
        self,
        *,
        timeout: Union[float, int] = 10
        ) -> Union[bool, list]:  # yapf: disable
        """Retorna o estado de todos os downloads em formato de lista

        Caso já esteja concluido, retorna None para o item
        Ex: `[None, None, None, 64, None]` significa que há 5 downloads, 4 acabaram e um está em 64%
        ---
        Parameters
        ------
        `timeout` : int, float
            Tempo para o site chrome://downloads/ carregar

        Returns
        ------
        `progress` : list
            lista com o estado de cada download, None = acabou, int = porcentagem concluida
        `False` : bool
            Timeout após 10s
        """

        r = self.open_url("chrome://downloads/", timeout=timeout)
        if r is False:
            logger.critical(f"Não carregou a página de downloads a tempo")
            return False

        progress = self.execute_script(
            """
        var tag = document.querySelector('downloads-manager').shadowRoot;
        var item_tags = tag.querySelectorAll('downloads-item');
        var item_tags_length = item_tags.length;
        var progress_lst = [];
        for(var i=0; i<item_tags_length; i++) {
            var intag = item_tags[i].shadowRoot;
            var progress_tag = intag.getElementById('progress');
            var progress = null;
            if(progress_tag) {
                var progress = progress_tag.value;
            }
            progress_lst.push(progress);
        }
        return progress_lst
        """
        )

        return progress

    def wait_all_downloads_end(
        self,
        *, timeout: Union[int, float] = 30
        ) -> Union[bool, list]:  # yapf: disable
        """Espera todos os downloads terminarem

        ---
        Parameters
        ------
        `timeout` : int, float
            Tempo para o site chrome://downloads/ carregar

        Returns
        ------
        `True` : bool
            Todos os downloads terminaram
        `False` : bool
            Timeout aguardando downloads terminarem
        """
        url_before = self.current_url
        timer = Timer(timeout)
        while timer.not_expired:

            progress = self.get_download_all_progress()

            # espera todos os items serem None
            all_downloads_done = all(item is None for item in progress)
            if all_downloads_done is False:  # aguarda mais 1s, downloads não terminaram
                time.sleep(1)
                continue
            else:  # se todos forem None, retorna True
                self.open_url(url_before)
                return True

        if timer.expired:
            logger.critical(f"Timeout após {timer.duration} segundos")
            self.open_url(url_before)
            return False

    def drag_and_drop_file(
        self,
        target: WebElement,
        path: str):  # yapf: disable
        """
        A idéia é criar um box invisivel na página,
        que vai aceitar o arquivo pelo send_keys e
        então irá copiar pro elemento destino

        [SELENIUM SEND_KEYS] -> [JS_DROP_FILE] -> [TARGET]
        """

        js_drop_file = """
            var target = arguments[0],
                offsetX = arguments[1],
                offsetY = arguments[2],
                document = target.ownerDocument || document,
                window = document.defaultView || window;

            var input = document.createElement('INPUT');
            input.type = 'file';
            input.onchange = function () {
            var rect = target.getBoundingClientRect(),
                x = rect.left + (offsetX || (rect.width >> 1)),
                y = rect.top + (offsetY || (rect.height >> 1)),
                dataTransfer = { files: this.files };

            ['dragenter', 'dragover', 'drop'].forEach(function (name) {
                var evt = document.createEvent('MouseEvent');
                evt.initMouseEvent(name, !0, !0, window, 0, 0, 0, x, y, !1, !1, !1, !1, 0, null);
                evt.dataTransfer = dataTransfer;
                target.dispatchEvent(evt);
            });

            setTimeout(function () { document.body.removeChild(input); }, 25);
            };
            document.body.appendChild(input);
            return input;
        """

        driver: CustomWebDriver = target.parent
        file_input: WebElement = driver.execute_script(js_drop_file, target, 0, 0)
        file_input.send_keys(path)
        return
