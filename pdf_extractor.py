from llama_parse import LlamaParse
from llama_index.core.schema import ImageDocument
from typing import List
from prompts import ins
import json
import nest_asyncio
import os
from dotenv import load_dotenv
load_dotenv()
nest_asyncio.apply()

class llama_document_parser(object):
    def __init__(self):  # Remove the parsing_ins parameter
        self.api_keys = [
            os.getenv("LLAMA_CLOUD_API_KEY_1"),
            os.getenv("LLAMA_CLOUD_API_KEY_2"),
            os.getenv("LLAMA_CLOUD_API_KEY_3")
        ]
        self.current_key_index = 0
        self.initialize_parser()

    def initialize_parser(self):
        self.parser = LlamaParse(
            api_key=self.api_keys[self.current_key_index],
            verbose=True,
            ignore_errors=False,
            invalidate_cache=True,
            do_not_cache=True,
            parsing_instruction=ins
        )

    def switch_api_key(self):
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self.initialize_parser()
        print(f"Switched to API key {self.current_key_index + 1}")

    def get_image_text_nodes(self, download_path: str, json_objs: List[dict]):
        """Extract out text from images using a multimodal model."""
        image_dicts = self.parser.get_images(json_objs, download_path=download_path)
        image_documents = []
        img_text_nodes = []
        for image_dict in image_dicts:
            image_doc = ImageDocument(image_path=image_dict["path"])
            img_text_nodes.append(image_doc)
        return img_text_nodes

    def document_processing_llamaparse(self, file_name: str, image_output_folder: str):
        """Parse document using llamaparse and return extracted elements in json format"""
        for _ in range(len(self.api_keys)):
            try:
                json_objs = self.parser.get_json_result(file_name)
                json_list = json_objs[0]["pages"]
                print(json_list)
                if not os.path.exists(image_output_folder):
                    os.mkdir(image_output_folder)

                image_text_nodes = self.get_image_text_nodes(image_output_folder, json_objs)
                return json_list
            except Exception as e:
                print(f"Error with current API key: {str(e)}")
                self.switch_api_key()
        
        raise Exception("All API keys failed. Unable to process document.")

    def process_and_save(self, pdf_path: str, output_folder: str):
        """Process the PDF and save the output"""
        # Create output folder if it doesn't exist
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        # Get the base name of the PDF file
        pdf_name = os.path.basename(pdf_path).split('.')[0]

        # Process the document
        json_list = self.document_processing_llamaparse(
            file_name=pdf_path,
            image_output_folder=os.path.join(output_folder, f"{pdf_name}_images")
        )

        # Save the output as JSON
        output_path = os.path.join(output_folder, f"{pdf_name}_output.json")
        with open(output_path, 'w') as f:
            json.dump(json_list, f, indent=2)

        print(f"Output saved to: {output_path}")
        return json_list