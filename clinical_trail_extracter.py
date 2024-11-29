import os
import json
import logging
from pymongo import MongoClient
from pdf_extractor import llama_document_parser
from section_matcher import match_sections
from dotenv import load_dotenv
import re
import csv
import requests
from urllib.parse import urlparse

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Load the template
with open('template.json', 'r') as f:
    template = json.load(f)

# MongoDB connection setup
mongo_uri = f"mongodb://{os.getenv('MONGO_USERNAME')}:{os.getenv('MONGO_PASSWORD')}@{os.getenv('MONGO_HOST')}:{os.getenv('MONGO_PORT')}/{os.getenv('MONGO_DB')}?authSource=admin"
client = MongoClient(mongo_uri)
db = client[os.getenv('MONGO_DB')]
collection = db[os.getenv('MONGO_COLLECTION')]

def get_drug_name(file_path):
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    return base_name.split('_')[0]

def get_protocol_number(content):
    pattern = r"(?i)protocol\s*number:?\s*([\w-]+)"
    for page in content:
        match = re.search(pattern, page['text'])
        if match:
            return match.group(1)
    return "Protocol Number Not Found"

def process_document(file_path):
    output_folder = "protocol_images"
    json_file_path = os.path.join(output_folder, f"{os.path.splitext(os.path.basename(file_path))[0]}_output.json")
    
    try:
        if os.path.exists(json_file_path):
            with open(json_file_path, 'r') as f:
                content = json.load(f)
            logger.info(f"Loaded existing JSON for {file_path}")
        else:
            llama_parser = llama_document_parser()  # Remove the argument here
            content = llama_parser.process_and_save(file_path, output_folder)
            logger.info(f"Processed new document: {file_path}")
        
        matched_sections = match_sections(content, file_path)  # Pass file_path here
        
        document = {
            "drug_name": get_drug_name(file_path),
            "protocol_source": file_path,
            "protocol_number": get_protocol_number(content),
        }
        document.update(matched_sections)
        
        return document
    except Exception as e:
        logger.error(f"Error processing document {file_path}: {e}")
        return None

def save_to_mongodb(document):
    try:
        result = collection.insert_one(document)
        logger.info(f"Document saved to MongoDB with ID: {result.inserted_id}")
    except Exception as e:
        logger.error(f"Error saving document to MongoDB: {e}")

def download_pdf(url, output_folder):
    response = requests.get(url)
    if response.status_code == 200:
        file_name = os.path.basename(urlparse(url).path)
        file_path = os.path.join(output_folder, file_name)
        with open(file_path, 'wb') as f:
            f.write(response.content)
        return file_path
    else:
        logger.error(f"Failed to download PDF from {url}")
        return None

def main():
    root_folder = "test"
    for root, dirs, files in os.walk(root_folder):
        for file in files:
            if file.endswith('.pdf'):
                file_path = os.path.join(root, file)
                logger.info(f"Processing file: {file_path}")
                document = process_document(file_path)
                if document:
                    save_to_mongodb(document)
                else:
                    logger.warning(f"Skipping file due to processing error: {file_path}")

def extract_pdf_url(study_documents):
    # Split the study_documents string by '|' to separate multiple URLs
    url_parts = study_documents.split('|')
    
    # Define the pattern for matching PDF URLs
    pattern = r'(https?://\S+?(?:Prot_(?:SAP_)?\d+\.pdf))'
    
    for part in url_parts:
        match = re.search(pattern, part.strip(), re.IGNORECASE)
        if match:
            return match.group(1)
    
    return None

def main_csv(csv_file_path):
    output_folder = "downloaded_pdfs"
    os.makedirs(output_folder, exist_ok=True)

    with open(csv_file_path, 'r', encoding='utf-8') as csvfile:
        csv_reader = csv.DictReader(csvfile)
        for row in csv_reader:
            logger.info(f"Processing row: {row['NCT Number']}")
            # Extract PDF URL
            study_documents = row.get('Study Documents', '')
            pdf_url = extract_pdf_url(study_documents)
            
            if not pdf_url:
                logger.warning(f"No valid PDF URL found for {row['NCT Number']}")
                continue

            # Download PDF
            pdf_path = download_pdf(pdf_url, output_folder)
            if not pdf_path:
                continue

            # Process PDF
            document = process_document(pdf_path)
            if not document:
                logger.warning(f"Skipping row due to processing error: {row['NCT Number']}")
                continue

            # Add CSV data to document
            for key, value in row.items():
                if key != 'Study Documents':  # Skip this column as we've already processed it
                    document[key] = value

            # Save to MongoDB
            save_to_mongodb(document)

            # Clean up downloaded PDF
            os.remove(pdf_path)

if __name__ == "__main__":
    #main()
    main_csv("ctg-studies2.csv")
