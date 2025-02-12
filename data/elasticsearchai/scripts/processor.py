from lollms.helpers import ASCIIColors
from lollms.config import TypedConfig, BaseConfig, ConfigTemplate
from lollms.personality import APScript, AIPersonality
from lollms.utilities import PackageManager
from lollms.types import MSG_TYPE
from typing import Callable

import subprocess
import ssl

if not PackageManager.check_package_installed("elasticsearch"):
    PackageManager.install_package("elasticsearch")

from elasticsearch import Elasticsearch

import json
# Helper functions
class Processor(APScript):
    """
    A class that processes model inputs and outputs.

    Inherits from APScript.
    """
    def __init__(
                 self, 
                 personality: AIPersonality,
                 callback = None,
                ) -> None:
        
        self.callback = None
        self.es = None
        # Example entry
        #       {"name":"make_scripted","type":"bool","value":False, "help":"Makes a scriptred AI that can perform operations using python script"},
        # Supported types:
        # str, int, float, bool, list
        # options can be added using : "options":["option1","option2"...]        
        personality_config_template = ConfigTemplate(
            [
                {"name":"servers","type":"str","value":"https://localhost:9200", "help":"List of addresses of the server in form of ip or host name: port"},
                {"name":"index_name","type":"str","value":"", "help":"The index to be used for querying"},
                {"name":"user","type":"str","value":"", "help":"The user name to connect to the database"},
                {"name":"password","type":"str","value":"", "help":"The password to connect to the elastic search database"},
                
                # Specify the host and port of the Elasticsearch server
            ]
            )
        personality_config_vals = BaseConfig.from_template(personality_config_template)

        personality_config = TypedConfig(
            personality_config_template,
            personality_config_vals
        )
        super().__init__(
                            personality,
                            personality_config,
                            [
                                {
                                    "name": "idle",
                                    "commands": { # list of commands
                                        "help":self.help,
                                    },
                                    "default": self.idle
                                },                      
                                {
                                    "name": "waiting_for_index_name",
                                    "commands": { # list of commands
                                    },
                                    "default": self.get_index_name
                                },                            
                                {
                                    "name": "waiting_for_mapping",
                                    "commands": { # list of commands
                                    },
                                    "default": self.get_mapping
                                },                  
                                     
                            ],
                            callback=callback
                        )
        
    def install(self):
        super().install()
        
        # requirements_file = self.personality.personality_package_path / "requirements.txt"
        # Install dependencies using pip from requirements.txt
        # subprocess.run(["pip", "install", "--upgrade", "-r", str(requirements_file)])      
        ASCIIColors.success("Installed successfully")        

    def help(self, prompt="", full_context=""):
        self.full(self.personality.help)
    
    def add_file(self, path, callback=None):
        """
        Here we implement the file reception handling
        """
        super().add_file(path, callback)

    # ============================ Elasticsearch stuff
    def ping(self):
        # Ping the Elasticsearch server
        response = self.es.ping()

        # Check if the server is reachable
        if response:
            print("Elasticsearch server is reachable")
            return True
        else:
            print("Elasticsearch server is not reachable")
            return False
        
    def create_index(self, index_name):
        try:
            self.es.indices.create(index=index_name)
            self.personality_config.index_name = index_name
            self.personality_config.save()
            return True
        except Exception as ex:
            self.personality.error(str(ex))
            return False

    def set_index(self, index_name):
        self.personality_config.index_name = index_name
        self.personality_config.save()

    def create_mapping(self, mapping):
        try:
            self.es.indices.put_mapping(index=self.personality_config.index_name, body=mapping)
            return True
        except Exception as ex:
            self.personality.error(str(ex))
            return False
    
    def read_mapping(self):
        try:
            mapping = self.es.indices.get_mapping(index=self.personality_config.index_name)
            return mapping

        except Exception as ex:
            self.personality.error(str(ex))
            return None
    
    def perform_query(self, query):
        results = self.es.search(index=self.personality_config.index_name, body=query)
        return results        

    def prepare(self):
        if self.personality_config.servers=="":
            self.error("Please set a server")
        if self.es is None:
            # Create a default SSL context
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            self.es = Elasticsearch(
                self.personality_config.servers.replace(" ", "").replace(".","").split(","), 
                http_auth=(self.personality_config.user, self.personality_config.password),
                verify_certs=False)

    def get_index_name(self, prompt, previous_discussion_text=""):
        self.goto_state("idle")
        index_name=self.fast_gen(f"!@>instruction: extract the index name from the prompt?\n!@>user prompt: {prompt}\n!@>answer: The requested index name is ").split("\n")[0].strip()
        self.operation(index_name.replace("\"","").replace(".",""))
        self.full("Index created successfully")

    def get_mapping(self, prompt, previous_discussion_text=""):
        self.goto_state("idle")
        output="```json\n{\n    \"properties\": {"+self.fast_gen(f"!@>instruction: what is the requested mapping in json format?\n!@>user prompt: {prompt}\n!@>answer: The requested index name is :\n```json\n"+"{\n    \"properties\": {")
        output=self.remove_backticks(output.strip())
        self.create_mapping(json.loads(output))
        self.full("Mapping created successfully")

    def idle(self, prompt, previous_discussion_text=""):
        index = self.multichoice_question("classify this prompt",
                                                [
                                                    "The prompt is asking for creating a new index", 
                                                    "The prompt is asking for changing index",
                                                    "creating a mapping",
                                                    "reading a mapping",
                                                    "asking a question about an entry"
                                                ],
                                                prompt)
        if index==0:# "The prompt is asking for creating a new index"
            if self.yes_no("does the prompt contain the index name?",prompt):
                index_name=self.fast_gen(f"!@>instruction: what is the requested index name?\n!@>user prompt: {prompt}\n!@>answer: The requested index name is ").split("\n")[0].strip()
                if self.create_index(index_name.replace("\"","").replace(".","")):
                    self.full("Index created successfully")
                else:
                    self.full("Unfortunately an error occured and I couldn't build the index. please check the connection to the database as well as the certificate")

            else:
                self.full("Please provide the index name")
                self.operation = self.create_index
                self.goto_state("waiting_for_index_name")
                return
        elif index==1:# "The prompt is asking for changing index"
            if self.yes_no("does the prompt contain the index name?",prompt):
                index_name=self.fast_gen(f"!@>instruction: what is the requested index name?\n!@>user prompt: {prompt}\n!@>answer: The requested index name is ").split("\n")[0].strip()
                self.set_index(index_name)
                self.full("Index set successfully")
            else:
                self.full("Please provide the index name")
                self.operation = self.set_index
                self.goto_state("waiting_for_index_name")
                return
        elif index==2:# "creating a mapping"
            if self.yes_no("does the prompt contain the mapping information required to build a mapping json out of it?",prompt):
                output="```json\n{\n    \"properties\": {"+self.fast_gen(f"!@>instruction: what is the requested mapping in json format?\n!@>user prompt: {prompt}\n!@>answer: The requested index name is :\n```json\n"+"{\n    \"properties\": {")
                output=self.remove_backticks(output.strip())
                self.create_mapping(json.loads(output))
                self.full("Mapping created successfully")
            else:
                self.full("Please provide the mapping")
                self.operation = self.set_index
                self.goto_state("waiting_for_mapping")
                return
        elif index==3:# "reading a mapping"
            mapping = self.read_mapping()
            self.full("```json\n"+json.dumps(mapping.body,indent=4)+"\n```\n")
        else:
            query = "```python\ndef query(es:ElasticSearch):\n"+self.fast_gen("!@>context!:\n"+previous_discussion_text+"\n!@>instructions: Make a python function that takes an ElasticSearch object es and perform the right operations to query the database in order to answer the question of the user. The output should be in form of a dictionary.\nelasticsearch_ai:Here is the query function that you are asking for:\n```python\ndef query(es:ElasticSearch):\n")
            query=self.remove_backticks(query)

            # Perform the search query
            res = self.es.search(index=self.personality_config.index_name, body=eval(query))

            # Process the search results
            docs= "!@>Documentation:\n"
            for hit in res['hits']['hits']:
                docs.append(hit)
                print(hit['_source'])

                self.chunk(hit['_source'])
            self.personality.info("Generating")
            out = self.fast_gen(previous_discussion_text)
            self.full(out)
    def run_workflow(self, prompt:str, previous_discussion_text:str="", callback: Callable[[str, MSG_TYPE, dict, list], bool]=None, context_details:dict=None):
        """
        This function generates code based on the given parameters.

        Args:
            full_prompt (str): The full prompt for code generation.
            prompt (str): The prompt for code generation.
            context_details (dict): A dictionary containing the following context details for code generation:
                - conditionning (str): The conditioning information.
                - documentation (str): The documentation information.
                - knowledge (str): The knowledge information.
                - user_description (str): The user description information.
                - discussion_messages (str): The discussion messages information.
                - positive_boost (str): The positive boost information.
                - negative_boost (str): The negative boost information.
                - force_language (str): The force language information.
                - fun_mode (str): The fun mode conditionning text
                - ai_prefix (str): The AI prefix information.
            n_predict (int): The number of predictions to generate.
            client_id: The client ID for code generation.
            callback (function, optional): The callback function for code generation.

        Returns:
            None
        """

        self.callback = callback
        if self.personality_config.user=="" or self.personality_config.servers=="":
            self.full("Sorry, but before talking, I need to get access to your elasticsearch server.\nTo do this:\n- Got to my settings and set the server(s) names in hte format https://server name or ip address:port number. You can give multiple servers separated by coma.\n- Set your user name and password.\n- come back here and we can start to talk.")
        else:
            self.prepare()
            if self.ping():
                self.process_state(prompt, previous_discussion_text)
            else:
                self.full("I couldn't connect to the server. Please make sure it is on and reachable and that your user name and password are correct")

        return ""

