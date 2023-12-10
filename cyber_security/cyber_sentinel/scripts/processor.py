from lollms.helpers import ASCIIColors
from lollms.config import TypedConfig, BaseConfig, ConfigTemplate
from lollms.personality import APScript, AIPersonality
from safe_store.generic_data_loader import GenericDataLoader
from safe_store.document_decomposer import DocumentDecomposer
import subprocess
from pathlib import Path
import json
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Helper functions
class Processor(APScript, FileSystemEventHandler):
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
                {"name":"logs_path","type":"str","value":"", "help":"The path to a folder containing the logs"},
                {"name":"output_file_path","type":"str","value":"", "help":"The path to a text file that will contain the final report of the AI"},
                {"name":"file_types","type":"str","value":"nips,xml,pcap,json", "help":"The extensions of files to read"},
                {"name":"chunk_size","type":"int","value":3072, "help":"The size of the chunk to read each time"},
                {"name":"chunk_overlap","type":"int","value":256, "help":"The overlap between blocs"},
                {"name":"save_each_n_chunks","type":"int","value":0, "help":"The number of chunks to process before saving the file. If 0, then the report is built at the end and a soingle report will be built for all logs."},
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
                                        "read_all_logs":self.read_all_logs,
                                        "start_logs_monitoring":self.start_logs_monitoring,
                                        "stop_logs_monitoring":self.stop_logs_monitoring,
                                    },
                                    "default": None
                                },                           
                            ],
                            callback=callback
                        )
        
    def install(self):
        super().install()
        
        # requirements_file = self.personality.personality_package_path / "requirements.txt"
        # Install dependencies using pip from requirements.txt
        subprocess.run(["pip", "install", "--upgrade", "watchdog"])      
        subprocess.run(["pip", "install", "--upgrade", "dpkt"])      
        
        ASCIIColors.success("Installed successfully")        

    def help(self, prompt="", full_context=""):
        self.full(self.personality.help)


    def on_modified(self, event):
        if not event.is_directory:
            file_path = Path(event.src_path)
            self.step(f"Detected modification in log file {file_path}")
            self.process_file(file_path)
    
    
    def process_file(self, file):
                self.step_start(f"Processing {file.name}")
                data = GenericDataLoader.read_file(file)
                dd = DocumentDecomposer()
                chunks = dd.decompose_document(
                                            data,
                                            self.personality_config.chunk_size,
                                            self.personality_config.chunk_overlap,
                                            self.personality.model.tokenize,
                                            self.personality.model.detokenize,
                                            return_detokenized=True
                                    )
                n_chunks = len(chunks)
                for i, chunk in enumerate(chunks):
                    self.step_start(f"Processing {file.name} chunk {i+1}/{n_chunks}")
                    str_json = "[" + self.fast_gen(
                        f"""!@>log chunk:
{chunk}
"""+"""
!@>instructions:
Act as cyber_sentinel_AI an AI that analyzes logs and detect security breaches from the content of the log chunk.
- Analyze the provided chunk of data and extract all potential security breach attempts from the chunk.
- Identify any suspicious patterns or anomalies that may indicate a security breach.
- Provide details about the breach attempt.
- If applicable mention the timestamp or ID of the log entry that triggers the detection and explain it.
- Be specific and provide explanations.
- If no breach detected, return an empty list [].
- Your analysis should be detailed and provide clear evidence to support your conclusion. Remember to consider both known and unknown security threats.
- Be attentive to the content of the logs and do not miss important information.
- Answer in valid json format.
- Only report breaches and suspecious activities.
- Only report breaches. Do not report legitimed access to the network.


!@>JSON format:
[
    A list of entries.
    Each entry represents a suspicious breach that should only be reported if you understand the problem and can qualify it with arguments
    {
        "severity": "high","medium" or "low",
        "breach_timestamp": the timestamp of the suspicious entry if exists in the log chunk else leave blank,
        "breach_description": a detailed and argued description of the breach,
        "breach_detection_arguments": explain why do you think the breach exists using arguments from the log,
        "proposed_fix": If you know a counter measure to avoid this, report it here or just say, I have no idea.
    }
]
!@>cyber_sentinel_AI:
Here is my report as a valid json:
["""
                    )
                    try:
                        str_json = str_json.replace('\n', '').replace('\r', '').strip()
                        if not str_json.endswith(']'):
                              str_json +="]"
                        json_output = json.loads(str_json)
                        for entry in json_output:
                            breach_timestamp = entry.get('breach_timestamp','')
                            breach_description = entry.get('breach_description','')
                            breach_detection_arguments = entry.get('breach_detection_arguments','')
                            proposed_fix = entry.get('proposed_fix','')

                            self.output_file.write(f"## A {entry['severity']} breach detected chunk {i+1} of file {file}\n")
                            self.output += f"## A {entry['severity']} breach detected chunk {i+1} of file {file}\n"
                            if breach_timestamp:
                                self.output_file.write(f"### breach_timestamp:\n")
                                self.output_file.write(f"{breach_timestamp}\n")
                                self.output += f"### breach_timestamp:\n"
                                self.output += f"{entry.get('breach_timestamp','')}\n"
                            if breach_description:
                                self.output_file.write(f"### description:\n")
                                self.output_file.write(f"{breach_description}\n")
                                self.output += f"### description:\n"
                                self.output += f"{breach_description}\n"
                            if breach_detection_arguments:
                                self.output_file.write(f"### arguments:\n")
                                self.output_file.write(f"{breach_detection_arguments}\n")
                                self.output += f"### arguments:\n"
                                self.output += f"{entry.get('breach_detection_arguments','')}\n"
                            if proposed_fix:
                                self.output_file.write(f"### proposed fix:\n")
                                self.output_file.write(f"{proposed_fix}\n")
                                self.output += f"### proposed fix:\n"
                                self.output += f"{entry.get('proposed_fix','')}\n"
                            

                            self.output_file.flush()


                        if self.personality_config.save_each_n_chunks>0 and i%self.personality_config.save_each_n_chunks==0:
                            self.output_file.close()
                            self.output_file = open(self.output_file_path.parent/(self.output_file_path.stem+f"_{i}"+self.output_file_path.suffix),"w")

                    except Exception as ex:
                        ASCIIColors.error(ex)
                    self.step_end(f"Processing {file.name} chunk {i+1}/{n_chunks}")
                    self.full(self.output)

                self.step_end(f"Processing {file.name}")

    def read_all_logs(self, prompt="", full_context=""):
        if self.personality_config.output_file_path=="":
            self.personality.info("Please setup output file path first")
            return
        if self.personality_config.logs_path=="":
            self.personality.info("Please setup logs folder path first")
            return
        self.output = ""
        self.new_message("")
        self.process_logs(
                            self.personality_config.logs_path, 
                            self.personality_config.file_types
                        )

    def stop_logs_monitoring(self, prompt="", full_context=""):
        self.observer.stop()

    def start_logs_monitoring(self, prompt="", full_context=""):
        if self.personality_config.output_file_path=="":
            self.personality.info("Please setup output file path first")
            return
        if self.personality_config.logs_path=="":
            self.personality.info("Please setup logs folder path first")
            return
        self.new_message("Starting continuous logs process...")
        self.observer = Observer()
        self.observer.schedule(self, self.personality_config.logs_path, recursive=True)
        self.observer.start()
    
    def process_logs(self, folder_path, extensions):
        folder = Path(folder_path)
        files = folder.glob('*')
        extension_list = [v.strip() for v in extensions.split(',')]

        self.output_file_path = Path(self.personality_config.output_file_path)
        self.output_file = open(self.output_file_path,"w")
        
        self.output = ""

        for file in files:
            if file.is_file() and file.suffix[1:] in extension_list:
                self.process_file(file)

    
    def add_file(self, path, callback=None):
        """
        Here we implement the file reception handling
        """
        super().add_file(path, callback)

    def run_workflow(self, prompt, previous_discussion_text="", callback=None):
        """
        Runs the workflow for processing the model input and output.

        This method should be called to execute the processing workflow.

        Args:
            prompt (str): The input prompt for the model.
            previous_discussion_text (str, optional): The text of the previous discussion. Default is an empty string.
            callback a callback function that gets called each time a new token is received
        Returns:
            None
        """
        ASCIIColors.info("Generating")
        self.callback = callback
        if self.personality_config.output_file_path=="":
            out = self.fast_gen(previous_discussion_text + "Please set the output file path in my settings page.")
            self.full(out)
            return
        if self.personality_config.logs_path=="":
            out = self.fast_gen(previous_discussion_text + "Please set the logs folder path in my settings page.")
            self.full(out)
            return

        self.process_logs(
                            self.personality_config.logs_path, 
                            self.personality_config.file_types
                        )


        return ""

