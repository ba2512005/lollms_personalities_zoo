import subprocess
from pathlib import Path
from lollms.helpers import ASCIIColors
from lollms.config import TypedConfig, BaseConfig, ConfigTemplate, InstallOption
from lollms.types import MSG_TYPE
from lollms.personality import APScript, AIPersonality
import re
import importlib
import requests
from tqdm import tqdm


class Processor(APScript):
    """
    A class that processes model inputs and outputs.

    Inherits from APScript.
    """


    def __init__(
                 self, 
                 personality: AIPersonality
                ) -> None:
        
        self.word_callback = None
        personality_config_template = ConfigTemplate(
            [
                {"name":"model_name","type":"str","value":"DreamShaper_5_beta2_noVae_half_pruned.ckpt", "help":"Name of the model to be loaded for stable diffusion generation"},
                {"name":"sampler_name","type":"str","value":"ddim", "options":["ddim","dpms","plms"], "help":"Select the sampler to be used for the diffusion operation. Supported samplers ddim, dpms, plms"},                
                {"name":"ddim_steps","type":"int","value":50, "min":10, "max":1024},
                {"name":"scale","type":"float","value":7.5, "min":0.1, "max":100.0},
                {"name":"W","type":"int","value":512, "min":10, "max":2048},
                {"name":"H","type":"int","value":512, "min":10, "max":2048},
                {"name":"skip_grid","type":"bool","value":True,"help":"Skip building a grid of generated images"},
                {"name":"batch_size","type":"int","value":1, "min":1, "max":100,"help":"Number of images per batch (requires more memory)"},
                {"name":"num_images","type":"int","value":1, "min":1, "max":100,"help":"Number of batch of images to generate (to speed up put a batch of n and a single num images, to save vram, put a batch of 1 and num_img of n)"},
                {"name":"seed","type":"int","value":-1},
                {"name":"max_generation_prompt_size","type":"int","value":512, "min":10, "max":personality.config["ctx_size"]},
                
            ]
            )
        personality_config_vals = BaseConfig.from_template(personality_config_template)

        personality_config = TypedConfig(
            personality_config_template,
            personality_config_vals
        )
        super().__init__(
                            personality,
                            personality_config
                        )
        self.sd = self.get_sd().SD(self.personality.lollms_paths, self.personality_config)
        
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

        # Step 4: Download model file
        model_url = "https://huggingface.co/Lykon/DreamShaper/resolve/main/DreamShaper_5_beta2_noVae_half_pruned.ckpt"
        model_file = models_folder / "DreamShaper_5_beta2_noVae_half_pruned.ckpt"
        
        # Download with progress using tqdm
        if not model_file.exists():
            response = requests.get(model_url, stream=True)
            total_size = int(response.headers.get("content-length", 0))
            block_size = 1024  # 1KB
            progress_bar = tqdm(total=total_size, unit="B", unit_scale=True)

            with open(model_file, "wb") as file:
                for data in response.iter_content(block_size):
                    progress_bar.update(len(data))
                    file.write(data)
            
            progress_bar.close()
        ASCIIColors.success("Installed successfully")


    def get_sd(self):
        sd_script_path = Path(__file__).parent / "sd.py"
        if sd_script_path.exists():
            module_name = sd_script_path.stem  # Remove the ".py" extension
            # use importlib to load the module from the file path
            loader = importlib.machinery.SourceFileLoader(module_name, str(sd_script_path))
            sd_module = loader.load_module()
            return sd_module

    def remove_image_links(self, markdown_text):
        # Regular expression pattern to match image links in Markdown
        image_link_pattern = r"!\[.*?\]\((.*?)\)"

        # Remove image links from the Markdown text
        text_without_image_links = re.sub(image_link_pattern, "", markdown_text)

        return text_without_image_links


    

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
        output_path = self.personality.lollms_paths.personal_outputs_path
        # First we create the yaml file
        # ----------------------------------------------------------------
        self.step_start("Coming up with the personality name...", callback)
        name = self.generate(f"""!!>request:{prompt}
!!>task: Give a name to the personality requested by the user.
name:""",128,0.1,10,0.98).strip()
        self.step_end("Coming up with the personality name...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("Coming up with the author name...", callback)
        author = self.generate(f"""!!>request:{prompt}
!!>task: Write the name of the author infered from the request?
If no author mensioned then respond with ParisNeo
author name:""",128,0.1,10,0.98).strip()
        self.step_end("Coming up with the author name...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("Coming up with the version ...", callback)
        version = self.generate(f"""!!>request:{prompt}
!!>task: Write the version of the personality infered from the request?
If no version mensioned then respond with 1.0
author name:""",128,0.1,10,0.98).strip()
        self.step_end("Coming up with the version ...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("Coming up with the category ...", callback)
        category = self.generate(f"""!!>request:{prompt}
!!>task: Write the category of the personality infered from the request?
category:""",128,0.1,10,0.98).strip()
        self.step_end("Coming up with the category ...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("Coming up with the language ...", callback)
        language = self.generate(f"""!!>request:{prompt}
!!>task: Write the language of the personality infered from the request?
language:""",128,0.1,10,0.98).strip() 
        self.step_end("Coming up with the language ...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("Coming up with the description ...", callback)
        description = self.generate(f"""!!>request:{prompt}
!!>task: Write a description of the personality infered from the request?
description:""",128,0.1,10,0.98).strip() 
        self.step_end("Coming up with the description ...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("Coming up with the disclaimer ...", callback)
        disclaimer = self.generate(f"""!!>request:{prompt}
!!>task: Write a disclaimer about the ai personality infered from the request?
disclaimer:""",128,0.1,10,0.98).strip()  
        self.step_end("Coming up with the disclaimer ...", callback)
        # ----------------------------------------------------------------

        # ----------------------------------------------------------------
        self.step_start("Coming up with the conditionning ...", callback)
        conditioning = self.generate(f"""!!>request:{prompt}
!!>task: Write a conditioning text to condition a text ai to simulate the personality infered from the request?
conditioning:""",128,0.1,10,0.98).strip()
        self.step_end("Coming up with the conditionning ...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("Coming up with the welcome message ...", callback)
        welcome_message = self.generate(f"""!!>request:{prompt}
!!>task: Write a welcome message text that the ai personality should say to start the discussion infered from the request?
welcome_message:""",128,0.1,10,0.98).strip()          
        self.step_end("Coming up with the welcome message ...", callback)
        # ----------------------------------------------------------------
                         
        # ----------------------------------------------------------------
        self.step_start("Building the yaml file ...", callback)
        yaml_data=f"""## {name} Chatbot conditionning file
  ## Author: {author}
  ## Version: {version}
  ## Description:
  ## {description}
  ## talking to.

  # Credits
  author: {author}
  version:{version}
  category: {category}
  language:{language}
  name: {name}
  personality_description: |
    {description}
  disclaimer: |
    {disclaimer}

  # Actual useful stuff
  personality_conditioning: |
    !!>Instructions: 
    {conditioning}  
  user_message_prefix: '!!>User:'
  ai_message_prefix: '!!>{name.lower().strip.replace(' ','_')}:'
  # A text to put between user and chatbot messages
  link_text: '\n'
  welcome_message: |
    {welcome_message}
  # Here are default model parameters
  model_temperature: 0.6 # higher: more creative, lower: more deterministic
  model_n_predicts: 2048 # higher: generates more words, lower: generates fewer words
  model_top_k: 50
  model_top_p: 0.90
  model_repeat_penalty: 1.0
  model_repeat_last_n: 40

  # Recommendations
  recommended_binding: ''
  recommended_model: ''

  # Here is the list of extensions this personality requires
  dependencies: []

  # A list of texts to be used to detect that the model is hallucinating and stop the generation if any one of these is output by the model
  anti_prompts: ['!!>'"<|end|>","<|user|>","<|system|>"]
        """
        personality_path:Path = output_path/(name.lower().strip().replace(" ","_"))
        personality_path.mkdir(parents=True, exist_ok=True)
        with open(personality_path/"config.yaml","w", encoding="utf8") as f:
            f.write(yaml_data)

        self.step_end("Building the yaml file ...", callback)
        # ----------------------------------------------------------------
        
        # Now we generate icon        
        personality_assets_path = personality_path/"assets"
        personality_assets_path.mkdir(parents=True, exist_ok=True)
        
        self.word_callback = callback
        
        # ----------------------------------------------------------------
        self.step_start("# Imagining  ![](/personalities/english/art/artbot/assets/imagine_animation.gif) ...", callback)
        # 1 first ask the model to formulate a query
        sd_prompt = self.generate(f"""!!>request:{prompt}
!!>task: Write a prompt to build an icon to the personality being built. The prompt should be descriptive and include stylistic information
prompt:""",self.personality_config.max_generation_prompt_size,0.1,10,0.98).strip()
        self.step_end("# Imagining  ![](/personalities/english/art/artbot/assets/imagine_animation.gif) ...", callback)
        # ----------------------------------------------------------------
        
        # ----------------------------------------------------------------
        self.step_start("# Painting  ![](/personalities/english/art/artbot/assets/painting_animation.gif)", callback)
        files = self.sd.generate(sd_prompt.strip(), self.personality_config.num_images, self.personality_config.seed)
        output = f"```yaml\n{yaml_data}\n```# Icon:\n" + sd_prompt.strip()+"\n"
        for i in range(len(files)):
            files[i] = str(files[i]).replace("\\","/")
            pth = files[i].split('/')
            idx = pth.index("outputs")
            pth = "/".join(pth[idx:])
            file_path = f"![](/{pth})\n"
            output += file_path
            print(f"Generated file in here : {files[i]}")

        # ----------------------------------------------------------------
        self.step_end("# Painting  ![](/personalities/english/art/artbot/assets/painting_animation.gif)", callback)
        
        self.full(output, callback)
        
        return output

