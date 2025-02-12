from lollms.helpers import ASCIIColors
from lollms.config import TypedConfig, BaseConfig, ConfigTemplate
from lollms.personality import APScript, AIPersonality
from lollms.types import MSG_TYPE
from typing import Callable

from safe_store.text_vectorizer import TextVectorizer, VectorizationMethod
import subprocess

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
        # Example entry
        #       {"name":"make_scripted","type":"bool","value":False, "help":"Makes a scriptred AI that can perform operations using python script"},
        # Supported types:
        # str, int, float, bool, list
        # options can be added using : "options":["option1","option2"...]        
        personality_config_template = ConfigTemplate(
            [
                {"name":"project_folder_path","type":"str","value":"", "help":"A path to a folder where "},
                {"name":"max_coding_attempts","type":"int","value":10, "help":"The maximum number of iteration over the code before give up"},
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
                                    "default": None
                                },                           
                            ],
                            callback=callback
                        )
        self.data_base = TextVectorizer(VectorizationMethod.BERT, self.personality.model)

        
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

        if self.personality_config.project_folder_path=="":
            self.full("Before starting to talk to me, please define a project folder path in my configuration settings then we can start building the app.")
            return
        
        self.output=""
        self.callback = callback
        operation = self.multichoice_question(
                                    "Classify the last prompt from the user.",
                                    [
                                        "Not explanation of code, not asking to start building code, not giving update information",
                                        "Explanation about the code",
                                        "Asking to start building code",
                                        "New updates to the previous code"
                                    ],
                                    previous_discussion_text)
        ASCIIColors.yellow(operation)
        if operation == 0: #Generic stuff
            ASCIIColors.info("Generating")
            self.step("Detected a generic communication")
            out = self.fast_gen(previous_discussion_text)
            self.full(out)
            self.step("Detected a generic communication")
        elif operation == 1: # Giving information about the software to build
            ASCIIColors.info("Generating")
            self.step("Detected a software information")
            self.step_start("Saving the information to long term memory")
            title = self.make_title(prompt)
            self.data_base.add_document(title,prompt, add_to_index=True)
            self.step_end("Saving the information to long term memory")
            self.step_start(f"Assimilating the Data")
            out = self.fast_gen(previous_discussion_text+"Here is a reformulation of your request:\n")
            self.step_end(f"Assimilating the Data")
            self.full(out+"\nReady to start building, please say Start building when you think that you have input all data required.")
        elif operation == 2: #build the software
            ASCIIColors.info("Generating")
            self.step("Detected a software build request")
            self.step_start("Saving the information to long term memory")
            title = self.make_title(prompt)
            self.data_base.add_document(title,prompt, add_to_index=True)
            self.step_end("Saving the information to long term memory")
            self.callback = callback

            attempt =0
            while attempt<self.personality_config.max_coding_attempts:
                self.step_start(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}")
                code = self.build_python_code(previous_discussion_text)
                if code!="":
                    self.step_end(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}")
                    previous_discussion_text += code
                    try:
                        self.execute_python(code, self.personality_config.project_folder_path, "main.py")
                        break
                    except Exception as ex:
                        self.step_end(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}", False)
                        previous_discussion_text += f"!@> Exception detected:\n{ex}\n!@>request:Fix the bug.\n"
                        attempt +=1 
                        self.output += "```exception\n"+str(ex)+"\n```"
                else:
                    self.step_end(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}", False)
                    attempt +=1 
                self.full(self.output)
            self.full(self.output)
            ASCIIColors.yellow(code)
        elif operation == 3: # updates to the software
            ASCIIColors.info("Generating")
            self.step("Detected a software update request")
            self.step_start("Saving the information to long term memory")
            title = self.make_title(prompt)
            self.data_base.add_document(title,prompt, add_to_index=True)
            self.step_end("Saving the information to long term memory")
            self.step_start(f"Assimilating the Data")
            out = self.fast_gen(previous_discussion_text+"Here is a reformulation of your request:\n")
            self.step_end(f"Assimilating the Data")
            self.full(out)
            attempt =0
            while attempt<self.personality_config.max_coding_attempts:
                self.step_start(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}")
                code = self.build_python_code(previous_discussion_text)
                if code!="":
                    self.step_end(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}")
                    previous_discussion_text += code
                    try:
                        self.execute_python(code, self.personality_config.project_folder_path, "main.py")
                        break
                    except Exception as ex:
                        self.step_end(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}", False)
                        previous_discussion_text += str(ex)
                        attempt +=1 
                        self.output += "```exception\n"+str(ex)+"\n```"
                else:
                    self.step_end(f"Building the code. Attempt {attempt+1}/{self.personality_config.max_coding_attempts}", False)
                    attempt +=1 
                self.full(self.output)
            self.full(self.output)            
        return ""

