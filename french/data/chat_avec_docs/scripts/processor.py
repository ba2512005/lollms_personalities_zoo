from lollms.config import TypedConfig, BaseConfig, ConfigTemplate, InstallOption
from lollms.types import MSG_TYPE
from lollms.personality import APScript, AIPersonality
from lollms.paths import LollmsPaths
from lollms.helpers import ASCIIColors, trace_exception
from lollms.utilities import TextVectorizer, GenericDataLoader

import numpy as np
import json
from pathlib import Path
import numpy as np
import json
import subprocess
from urllib.parse import quote

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
        
        self.word_callback = None    

        personality_config_template = ConfigTemplate(
            [
                {"name":"build_keywords","type":"bool","value":True, "help":"Si vrai, le modèle générera d'abord des mots-clés avant de rechercher."},
                {"name":"save_db","type":"bool","value":False, "help":"Si vrai, la base de données vectorisée sera sauvegardée pour une utilisation future."},
                {"name":"vectorization_method","type":"str","value":"model_embedding", "options":["model_embedding", "ftidf_vectorizer"], "help":"Méthode de vectorisation à utiliser (modifier cela réinitialisera la base de données)."},

                {"name":"nb_chunks","type":"int","value":2, "min":1, "max":50,"help":"Nombre de morceaux de données à utiliser pour sa vectorisation (au plus nb_chunks*max_chunk_size ne doit pas dépasser deux tiers de la taille du contexte)."},
                {"name":"database_path","type":"str","value":"nom_de_la_personnalite_db.json", "help":"Chemin vers la base de données."},
                {"name":"max_chunk_size","type":"int","value":512, "min":10, "max":personality.config["ctx_size"],"help":"Taille maximale des morceaux de texte à vectoriser."},
                {"name":"chunk_overlap_sentences","type":"int","value":1, "min":0, "max":personality.config["ctx_size"],"help":"Chevauchement entre les morceaux."},

                {"name":"max_answer_size","type":"int","value":512, "min":10, "max":personality.config["ctx_size"],"help":"Nombre maximal de jetons autorisés pour que le générateur génère une réponse à votre question."},

                {"name":"data_visualization_method","type":"str","value":"PCA", "options":["PCA", "TSNE"], "help":"La méthode à utiliser pour afficher les données."},
                {"name":"interactive_mode_visualization","type":"bool","value":False, "help":"Si vrai, vous pouvez obtenir une visualisation interactive où vous pouvez pointer sur les données pour obtenir le texte."},
                {"name":"visualize_data_at_startup","type":"bool","value":False, "help":"Si vrai, la base de données sera visualisée au démarrage."},
                {"name":"visualize_data_at_add_file","type":"bool","value":False, "help":"Si vrai, la base de données sera visualisée lorsqu'un nouveau fichier est ajouté."},
                {"name":"visualize_data_at_generate","type":"bool","value":False, "help":"Si vrai, la base de données sera visualisée lors de la génération."}

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
                                        "show_database": self.show_database,
                                        "set_database": self.set_database,
                                        "clear_database": self.clear_database
                                    },
                                    "default": self.chat_with_doc
                                },                           
                            ],
                            callback=callback
                        )
        self.state = 0
        self.ready = False
        self.personality = personality
        self.callback = None
        self.vector_store = None


    def install(self):
        super().install()
        # Get the current directory
        root_dir = self.personality.lollms_paths.personal_path
        # We put this in the shared folder in order as this can be used by other personalities.
        shared_folder = root_dir/"shared"
        sd_folder = shared_folder / "sd"

        requirements_file = self.personality.personality_package_path / "requirements.txt"
        # Step 2: Install dependencies using pip from requirements.txt
        subprocess.run(["pip", "install", "--upgrade", "-r", str(requirements_file)])            
        try:
            print("Checking pytorch")
            import torch
            import torchvision
            if torch.cuda.is_available():
                print("CUDA is supported.")
            else:
                print("CUDA is not supported. Reinstalling PyTorch with CUDA support.")
                self.reinstall_pytorch_with_cuda()
        except Exception as ex:
            self.reinstall_pytorch_with_cuda()

        # Step 1: Clone repository
        if not sd_folder.exists():
            subprocess.run(["git", "clone", "https://github.com/CompVis/stable-diffusion.git", str(sd_folder)])

        # Step 2: Install the Python package inside sd folder
        subprocess.run(["pip", "install", "--upgrade", str(sd_folder)])

        # Step 3: Create models/Stable-diffusion folder if it doesn't exist
        models_folder = shared_folder / "sd_models"
        models_folder.mkdir(parents=True, exist_ok=True)

        ASCIIColors.success("Installed successfully")

    

    def help(self, prompt, full_context):
        self.full(self.personality.help, callback=self.callback)

    def show_database(self, prompt, full_context):
        if self.ready:
            self.vector_store.show_document()
            out_path = f"/uploads/{self.personality.personality_folder_name}/db.png"
            if self.personality_config.data_visualization_method=="PCA":
                self.full(f"Database representation (PCA):\n![{out_path}]({out_path})", callback=self.callback)
            else:
                self.full(f"Database representation (TSNE):\n![{out_path}]({out_path})", callback=self.callback)

    def set_database(self, prompt, full_context):
        self.goto_state("waiting_for_file")

    def clear_database(self,prompt, full_context):
        self.vector_store.clear_database()

    def chat_with_doc(self, prompt, full_context):
        self.step_start("Recovering data")
        if self.vector_store.ready:
            self.step_start("Analyzing request", callback=self.callback)
            if self.personality_config.build_keywords:
                full_text =f"""!@>instructor:Extraire des mots-clés de cette indication pour la recherche dans une base de données vectorisée.
!@>prompt: {prompt}
keywords:"""
                preprocessed_prompt = self.generate(full_text, self.personality_config["max_answer_size"]).strip()
            else:
                preprocessed_prompt = prompt
            self.step_end("Analyzing request", callback=self.callback)

            docs, sorted_similarities = self.vector_store.recover_text(self.vector_store.embed_query(preprocessed_prompt), top_k=self.personality_config.nb_chunks)
            # for doc in docs:
            #     tk = self.personality.model.tokenize(doc)
            #     print(len(tk))
            docs = '\n'.join([f"chunk number {i}:\n{v}" for i,v in enumerate(docs)])
            full_text =f"""{full_context}
!@>document chunks:
{docs}
!@>instructor:Using the information from the document chunks, answer this question.
!@>question: {prompt}
Be precise and give details in your answer.
Answer in French.
answer:"""

            tk = self.personality.model.tokenize(full_text)
            # print(f"total: {len(tk)}")           
            ASCIIColors.blue("-------------- Documentation -----------------------")
            ASCIIColors.blue(full_text)
            ASCIIColors.blue("----------------------------------------------------")
            ASCIIColors.blue("Thinking")
            self.step_end("Recovering data")
            self.step_start("Thinking", callback=self.callback)
            tk = self.personality.model.tokenize(full_text)
            ASCIIColors.info(f"Documentation size in tokens : {len(tk)}")
            if self.personality.config.debug:
                ASCIIColors.yellow(full_text)
            output = self.generate(full_text, self.personality_config["max_answer_size"]).strip()
            docs_sources=[]
            for entry in sorted_similarities:
                e = "_".join(entry[0].replace("\\","/").split("/")[-1].split('_')[:-2])
                ci = "_".join(entry[0].replace("\\","/").split("/")[-1].split('_')[-2:])
                name = "/uploads/" + self.personality.personality_folder_name + "/" + e
                path = e + f" chunk id : {ci}"
                docs_sources.append([path, name])

            output += "\n## Used References:\n" + "\n".join([f'[{v[0]}]({quote(v[1])})\n' for v in docs_sources])

            ASCIIColors.yellow(output)

            self.step_end("Thinking", callback=self.callback)
            self.full(output, callback=self.callback)
        else:
            self.full("Vector store is not ready. Please send me a document to use. Use Send file command form your chatbox menu to trigger this.", callback=self.callback)

    def build_db(self):
        if self.vector_store is None:
            self.vector_store = TextVectorizer(
                                        self
                                    )        
        if len(self.vector_store.embeddings)>0:
            self.ready = True

        ASCIIColors.info("-> Vectorizing the database"+ASCIIColors.color_orange)
        if self.callback is not None:
            self.callback("Vectorizing the database", MSG_TYPE.MSG_TYPE_STEP)
        for file in self.files:
            try:
                if Path(file).suffix==".pdf":
                    text =  GenericDataLoader.read_pdf_file(file)
                elif Path(file).suffix==".docx":
                    text =  GenericDataLoader.read_docx_file(file)
                elif Path(file).suffix==".docx":
                    text =  GenericDataLoader.read_pptx_file(file)
                elif Path(file).suffix==".json":
                    text =  GenericDataLoader.read_json_file(file)
                elif Path(file).suffix==".csv":
                    text =  GenericDataLoader.read_csv_file(file)
                elif Path(file).suffix==".html":
                    text =  GenericDataLoader.read_html_file(file)
                else:
                    text =  GenericDataLoader.read_text_file(file)
                try:
                    chunk_size=int(self.personality_config["max_chunk_size"])
                except:
                    ASCIIColors.warning(f"Couldn't read chunk size. Verify your configuration file")
                    chunk_size=512
                try:
                    overlap_size=int(self.personality_config["chunk_overlap_sentences"])
                except:
                    ASCIIColors.warning(f"Couldn't read chunk size. Verify your configuration file")
                    overlap_size=50

                self.vector_store.index_document(file, text, chunk_size=chunk_size, overlap_size=overlap_size)
                
                print(ASCIIColors.color_reset)
                ASCIIColors.success(f"File {file} vectorized successfully")
                self.ready = True
            except Exception as ex:
                ASCIIColors.error(f"Couldn't vectorize {file}: The vectorizer threw this exception:{ex}")
                trace_exception(ex)

    def add_file(self, path):
        super().add_file(path)
        self.prepare()
        try:
            self.step_start("Vectorizing database", callback=self.callback)
            self.build_db()
            self.step_end("Vectorizing database", callback=self.callback)
            self.ready = True
            return True
        except Exception as ex:
            ASCIIColors.error(f"Couldn't vectorize the database: The vectgorizer threw this exception: {ex}")
            trace_exception(ex)
            return False        

    def prepare(self):
        if self.vector_store is None:
            self.vector_store = TextVectorizer(
                                        self
                                    )    

        if self.vector_store and self.personality_config.vectorization_method=="ftidf_vectorizer":
            from sklearn.feature_extraction.text import TfidfVectorizer
            data = list(self.vector_store.texts.values())
            if len(data)>0:
                self.vectorizer = TfidfVectorizer()
                self.vectorizer.fit(data)

        if len(self.vector_store.embeddings)>0:
            self.ready = True

    def run_workflow(self, prompt, full_context="", callback=None):
        """
        Runs the workflow for processing the model input and output.

        This method should be called to execute the processing workflow.

        Args:
            generate_fn (function): A function that generates model output based on the input prompt.
                The function should take a single argument (prompt) and return the generated text.
            prompt (str): The input prompt for the model.
            previous_discussion_text (str, optional): The text of the previous discussion. Default is an empty string.

        Returns:
            None
        """
        # State machine
        self.callback = callback
        self.prepare()

        self.process_state(prompt, full_context, callback)

        return ""


